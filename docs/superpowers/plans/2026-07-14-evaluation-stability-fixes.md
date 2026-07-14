# Evaluation Stability Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five current evaluation correctness bugs before adding new Ragas and DeepEval adapters.

**Architecture:** Persist an immutable mapping snapshot when a run is created, claim each Celery delivery atomically, and checkpoint endpoint and metric work so stale-run recovery resumes instead of repeating paid calls. Keep scalar scores unchanged in storage while making report ordering and comparison charts respect metric direction. Keep dataset mapping inline and derive preview columns from every preview row.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, PostgreSQL JSONB, Alembic, Celery/Redis, pytest, Next.js 16, React 19, TypeScript 6, Vitest, Testing Library, Recharts.

## Global Constraints

- Execute in an isolated worktree because the main checkout contains untracked `.superpowers/brainstorm/` artifacts.
- This plan fixes existing behavior only. Do not add metric cards, typed sample kinds, ingestion, multimodal assets, generated adapter forms, or DeepEval `4.1.0` here.
- Preserve all ten current metric keys and the existing static and endpoint request shapes.
- Existing runs with no snapshot remain readable and may fall back to the current dataset mapping; every newly created run must use its immutable snapshot.
- Never automatically repeat a persisted paid metric result, including a persisted metric error.
- Do not replay an endpoint request across worker recovery when completion is unknown. Endpoint mode supports non-idempotent methods and may call a paid model. Existing bounded retries inside one `call_endpoint()` invocation remain unchanged.
- An interrupted metric pair is terminal for that run. The current manual recovery path is creating a new run; Phase 0 does not add targeted pair retry.
- Store raw metric scores. Direction-aware UI may derive a comparison value but must not rewrite stored scores.
- Reuse the existing outbox, attempt, heartbeat, and stale-job patterns used by dataset generation. Add no queue or state-machine dependency.
- Use TDD for every task and commit after each independently passing slice.

---

### Task 1: Add run snapshot and lease fields

**Files:**

- Create: `backend/alembic/versions/f2b3c4d5e6f7_run_snapshot_and_lease.py`
- Modify: `backend/app/models.py:108-128`
- Modify: `backend/app/config.py:7-38`
- Test: `backend/tests/test_models.py`

**Interfaces:**

- Produces: `Run.definition_snapshot: dict`, `Run.attempt: int`, `Run.heartbeat_at: datetime | None`.
- Produces: `settings.evaluation_lease_seconds: int`, default `900`.
- Consumes: existing `runs`, `run_results`, and `outbox_events` tables.

- [ ] **Step 1: Write the failing model test**

Add this dedicated round-trip test to `backend/tests/test_models.py`:

```python
def test_run_snapshot_and_lease_roundtrip(db):
    from app.models import Dataset, Run, User, Workspace

    user = User(email="run-lease@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Run lease", owner_id=user.id)
    db.add(workspace)
    db.flush()
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Rows",
        format="json",
        row_count=1,
        storage_path=f"datasets/{workspace.id}/rows.json",
        schema_map={"input": "prompt", "actual_output": "answer"},
    )
    db.add(dataset)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        name="Snapshot",
        mode="static",
        metric_config={"metrics": []},
        judge_config={},
        definition_snapshot={"schema_map": {"input": "prompt"}},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    assert run.definition_snapshot == {"schema_map": {"input": "prompt"}}
    assert run.attempt == 0
    assert run.heartbeat_at is None
```

- [ ] **Step 2: Run the model test and verify it fails**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_models.py -q
```

Expected: FAIL because `Run` has no `definition_snapshot`, `attempt`, or `heartbeat_at` fields.

- [ ] **Step 3: Add the SQLAlchemy fields and lease setting**

Add to `Run` after `judge_config`:

```python
definition_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
attempt: Mapped[int] = mapped_column(Integer, default=0)
heartbeat_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True
)
```

Add to `Settings` beside `eval_batch_size`:

```python
evaluation_lease_seconds: int = 900
```

- [ ] **Step 4: Add the additive migration**

Create `f2b3c4d5e6f7_run_snapshot_and_lease.py` with `down_revision = "e1a2b3c4d5e6"` and:

```python
def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "definition_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "runs",
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "runs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    connection = op.get_bind()
    running = connection.execute(
        sa.text("SELECT count(*) FROM runs WHERE status = 'running'")
    ).scalar_one()
    if running:
        raise RuntimeError("Cannot downgrade while evaluation runs are running")
    op.drop_column("runs", "heartbeat_at")
    op.drop_column("runs", "attempt")
    op.drop_column("runs", "definition_snapshot")
```

- [ ] **Step 5: Run model and migration checks**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_models.py -q
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade e1a2b3c4d5e6
.venv/bin/alembic upgrade head
```

Expected: model tests pass; upgrade, downgrade, and re-upgrade exit `0` on a database with no running evaluation.

- [ ] **Step 6: Commit the schema slice**

```bash
git add backend/app/models.py backend/app/config.py backend/alembic/versions/f2b3c4d5e6f7_run_snapshot_and_lease.py backend/tests/test_models.py
git commit -m "fix(evals): add run snapshot and lease state"
```

---

### Task 2: Snapshot dataset mapping when creating a run

**Files:**

- Modify: `backend/app/routers/runs.py:108-217`
- Test: `backend/tests/test_runs.py`
- Test: `backend/tests/test_worker.py`

**Interfaces:**

- Consumes: `Run.definition_snapshot` from Task 1.
- Produces: new-run snapshot shape `{"schema_map": dict}`.
- Produces: `_run_schema_map(run: Run, dataset: Dataset) -> dict[str, str]` for worker compatibility.

- [ ] **Step 1: Write failing API and worker snapshot tests**

After creating a run in `test_create_run_validates_and_enqueues`, load it and assert:

```python
stored = db.get(Run, response.json()["id"])
assert stored.definition_snapshot == {
    "schema_map": dataset.schema_map,
}
```

Add a worker regression test that creates a run with:

```python
definition_snapshot={
    "schema_map": {"input": "original_prompt", "actual_output": "original_answer"},
}
```

Then change `dataset.schema_map` to different columns before calling `evaluate_run.run(run.id)`. Return source data containing both old and new columns. Assert stored `RunResult.input` and `actual` use `original_prompt` and `original_answer`.

- [ ] **Step 2: Run focused tests and verify current mapping leaks into the run**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_runs.py::test_create_run_validates_and_enqueues tests/test_worker.py -q
```

Expected: FAIL because no snapshot is written and worker reads `dataset.schema_map`.

- [ ] **Step 3: Store the immutable mapping snapshot**

Pass this field when constructing `Run`:

```python
definition_snapshot={
    "schema_map": dict(dataset.schema_map),
},
```

Do not include provider secrets or decrypted endpoint headers.

- [ ] **Step 4: Read the snapshot with backward-compatible fallback**

Add in `backend/app/tasks.py`:

```python
def _run_schema_map(run: Run, dataset: Dataset) -> dict[str, str]:
    snapshot = run.definition_snapshot or {}
    mapping = snapshot.get("schema_map")
    return dict(mapping) if isinstance(mapping, dict) else dict(dataset.schema_map)
```

Resolve it once after loading the dataset and replace both worker reads of `dataset.schema_map` with the local `schema_map`.

- [ ] **Step 5: Run focused backend tests**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_runs.py tests/test_worker.py tests/test_worker_endpoint.py -q
```

Expected: all tests pass; new runs remain bound to original mappings; legacy run fixtures still work with `{}` snapshots.

- [ ] **Step 6: Commit the snapshot behavior**

```bash
git add backend/app/routers/runs.py backend/app/tasks.py backend/tests/test_runs.py backend/tests/test_worker.py
git commit -m "fix(evals): freeze run schema mapping"
```

---

### Task 3: Atomically claim and durably enqueue evaluations

**Files:**

- Modify: `backend/app/routers/runs.py:90-217`
- Modify: `backend/app/tasks.py:21-67,161-173,499-553`
- Modify: `backend/app/celery_app.py:13-27`
- Test: `backend/tests/test_runs.py`
- Test: `backend/tests/test_worker.py`
- Test: `backend/tests/test_worker_generation.py`

**Interfaces:**

- Produces: outbox kind `evaluate_run`, payload `{"run_id": str}`, dedupe key `evaluation:{run_id}`.
- Produces: `_claim_run(db: Session, run_id: str) -> tuple[Run, int] | None`.
- Produces: Celery task `recover_stale_evaluation_runs()`.
- Consumes: Task 1 lease fields and existing `dispatch_outbox_event()`.

- [ ] **Step 1: Write failing claim and durable-enqueue tests**

Add tests proving:

```python
tasks.evaluate_run.run(run.id)
tasks.evaluate_run.run(run.id)
assert scorer_calls == ["one", "two"]
assert db.get(Run, run.id).attempt == 1
```

Add a route test that monkeypatches `dispatch_outbox_event` to raise, creates a run, asserts `caplog` contains `Immediate evaluation dispatch failed`, and asserts one `OutboxEvent` remains with:

```python
assert event.kind == "evaluate_run"
assert event.dedupe_key == f"evaluation:{run.id}"
assert event.payload == {"run_id": run.id}
```

Add a dispatch test asserting `evaluate_run.apply_async` receives `args=[run.id]` and `task_id=f"evaluation-{event.id}"`.

- [ ] **Step 2: Run focused tests and verify duplicate delivery repeats work**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_runs.py tests/test_worker.py -q
```

Expected: FAIL because runs are directly enqueued and any non-cancelled status is re-executed.

- [ ] **Step 3: Create run and outbox event in one transaction**

Replace direct `_enqueue(row.id)` with:

```python
db.add(row)
db.flush()
event = OutboxEvent(
    kind="evaluate_run",
    dedupe_key=f"evaluation:{row.id}",
    payload={"run_id": row.id},
)
db.add(event)
db.commit()
try:
    dispatch_outbox_event(event.id)
except Exception:
    logger.exception(
        "Immediate evaluation dispatch failed for run %s; outbox will retry",
        row.id,
    )
```

Add `import logging` and `logger = logging.getLogger(__name__)` in the router. Import `OutboxEvent` and lazily import `dispatch_outbox_event` inside `create_run` to avoid router/task import cycles. Delete `_enqueue`; update route tests to patch `dispatch_outbox_event` instead.

- [ ] **Step 4: Teach the outbox dispatcher about evaluation runs**

Add before `delete_object` handling:

```python
elif event.kind == "evaluate_run":
    evaluate_run.apply_async(
        args=[event.payload["run_id"]],
        task_id=f"evaluation-{event.id}",
    )
```

- [ ] **Step 5: Add atomic claim**

Add:

```python
def _claim_run(db, run_id: str) -> tuple[Run, int] | None:
    now = datetime.now(timezone.utc)
    claimed = (
        db.query(Run)
        .filter_by(id=run_id, status="pending")
        .update(
            {
                Run.status: "running",
                Run.error: None,
                Run.attempt: Run.attempt + 1,
                Run.heartbeat_at: now,
                Run.finished_at: None,
            },
            synchronize_session=False,
        )
    )
    if claimed != 1:
        db.rollback()
        return None
    db.commit()
    run = db.get(Run, run_id)
    return run, run.attempt
```

At worker entry, call `_claim_run`. Return when it yields `None`. Remove unconditional status assignment and result deletion.

- [ ] **Step 6: Guard terminal writes by attempt**

Replace unguarded success/failure writes with `UPDATE ... WHERE id=:id AND status='running' AND attempt=:attempt`. A stale worker that lost its lease must not overwrite the current attempt:

```python
updated = (
    db.query(Run)
    .filter_by(id=run_id, status="running", attempt=attempt)
    .update(values, synchronize_session=False)
)
db.commit()
if updated != 1:
    return
```

- [ ] **Step 7: Run claim and outbox tests**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_runs.py tests/test_worker.py tests/test_worker_endpoint.py tests/test_worker_generation.py -q
```

Expected: all tests pass; duplicate delivery is a no-op and generation outbox behavior is unchanged.

- [ ] **Step 8: Commit atomic delivery**

```bash
git add backend/app/routers/runs.py backend/app/tasks.py backend/tests/test_runs.py backend/tests/test_worker.py backend/tests/test_worker_endpoint.py backend/tests/test_worker_generation.py
git commit -m "fix(evals): claim evaluation jobs atomically"
```

---

### Task 4: Checkpoint rows and metrics before stale-run recovery

**Files:**

- Modify: `backend/app/tasks.py:161-315,499-553`
- Modify: `backend/app/celery_app.py:17-28`
- Test: `backend/tests/test_worker.py`
- Test: `backend/tests/test_worker_endpoint.py`

**Interfaces:**

- Consumes: Task 3 atomic claim and `RunResult(run_id, row_index)` uniqueness.
- Produces: resumable `RunResult` checkpoints keyed by `(run_id, row_index)`.
- Produces: `recover_stale_evaluation_runs()` using `evaluation_lease_seconds`.

- [ ] **Step 1: Write failing resume tests**

Create a pending run with an existing row checkpoint:

```python
RunResult(
    workspace_id=workspace.id,
    run_id=run.id,
    row_index=0,
    input="one",
    actual="answer one",
    scores={
        "test.good": {
            "score": 0.8,
            "reason": "ok",
            "passed": True,
            "error": None,
        }
    },
)
```

Run the worker and assert `test.good` is not called for row `0`, while missing metrics and later rows are evaluated. Add the endpoint variant and assert `call_endpoint` is not invoked for a row with persisted `actual`.

Add a stale-run test: set `status="running"`, old `heartbeat_at`, and `attempt=1`; call recovery; assert status becomes `pending`, heartbeat clears, and an `evaluate_run` outbox event is dispatched.

- [ ] **Step 2: Run resume tests and verify current worker deletes checkpoints**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_worker.py tests/test_worker_endpoint.py -q
```

Expected: FAIL because worker deletes prior results and repeats endpoint/metric calls.

- [ ] **Step 3: Load checkpoints instead of deleting them**

At worker start:

```python
stored_results = {
    result.row_index: result
    for result in db.query(RunResult).filter_by(run_id=run.id).all()
}
```

For each row:

- reuse a stored result whose normalized fields already exist;
- otherwise normalize static data and insert the `RunResult` with `scores={}`;
- before an endpoint call, insert a row checkpoint with
  `error="Endpoint request interrupted before its result was persisted"` and
  commit; after a successful call, fill `actual` and clear `error`; after a
  normal caught exception, replace the marker with the actual endpoint error;
- treat a persisted row-level `error` as complete and do not replay it across
  worker recovery. This is required because endpoint mode supports `POST`,
  `PUT`, `PATCH`, and `DELETE`, and the worker cannot know whether an
  interrupted request completed remotely.

Add a crash/recovery test for a `POST` endpoint whose fake call raises
`SystemExit` after incrementing a counter. Recover and redeliver the run, then
assert the counter remains `1` and the interruption error is retained. Existing
bounded retries inside `call_endpoint()` remain covered by endpoint unit tests.

- [ ] **Step 4: Checkpoint every metric pair**

Before invoking a scorer, skip any metric key already present in `result.scores`.
Persist an invocation marker before the paid call, then replace it with the
terminal result. The marker makes a worker crash at-most-once rather than
silently repeating a call:

```python
scores = dict(result.scores or {})
if metric_key not in scores:
    scores[metric_key] = {
        "score": None,
        "reason": None,
        "passed": None,
        "error": "Evaluation interrupted before its result was persisted",
        "in_progress": True,
    }
    result.scores = scores
    run.heartbeat_at = datetime.now(timezone.utc)
    db.commit()
    try:
        score = METRICS[metric_key].score(row, judge, config)
        scores[metric_key] = {
            "score": score.score,
            "reason": score.reason,
            "passed": score.passed,
            "error": None,
            "in_progress": False,
        }
    except Exception as exc:
        scores[metric_key] = {
            "score": None,
            "reason": None,
            "passed": None,
            "error": str(exc),
            "in_progress": False,
        }
    result.scores = scores
    run.heartbeat_at = datetime.now(timezone.utc)
    db.commit()
```

Check cancellation and matching `attempt` before each metric group. Paid errors remain persisted and are not automatically retried.

When a recovered worker encounters `in_progress=True`, change only that marker
to `in_progress=False`; retain the interruption error and do not invoke the
adapter. Add a crash test whose scorer raises `SystemExit` after incrementing a
counter, recover the run, execute the new delivery, and assert the counter is
still `1`. The result report must expose the terminal interruption message. A
user may create a new run to retry; targeted retry of one metric pair remains
outside Phase 0.

- [ ] **Step 5: Rebuild progress and summaries from persisted rows**

Set progress to the count of rows that have either a row error or every selected metric key persisted. Before summarizing:

```python
db.query(RunSummary).filter_by(run_id=run.id).delete()
results = db.query(RunResult).filter_by(run_id=run.id).all()
_summarize(db, run, results)
```

This makes recovery deterministic and avoids duplicate summary rows.

- [ ] **Step 6: Add stale evaluation recovery**

Implement the generation recovery pattern with:

```python
cutoff = datetime.now(timezone.utc) - timedelta(
    seconds=settings.evaluation_lease_seconds
)
```

Lock each stale `Run`, recheck heartbeat, set `status="pending"`, clear heartbeat, create/reuse outbox event `evaluation:{run.id}`, commit, then dispatch. Add to Celery beat:

```python
"recover-stale-evaluation-runs": {
    "task": "app.tasks.recover_stale_evaluation_runs",
    "schedule": 60.0,
},
```

- [ ] **Step 7: Run worker lifecycle tests**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_worker.py tests/test_worker_endpoint.py tests/test_worker_generation.py tests/test_compose.py -q
```

Expected: all tests pass; completed row/metric pairs and endpoint answers are not repeated after recovery.

- [ ] **Step 8: Commit resumable execution**

```bash
git add backend/app/tasks.py backend/app/celery_app.py backend/tests/test_worker.py backend/tests/test_worker_endpoint.py backend/tests/test_worker_generation.py backend/tests/test_compose.py
git commit -m "fix(evals): resume persisted evaluation work"
```

---

### Task 5: Reject invalid adapter scores

**Files:**

- Modify: `backend/app/evals/base.py:59-73`
- Test: `backend/tests/test_metric_adapters.py`

**Interfaces:**

- Produces: `CallableAdapter.score()` accepts only finite scores in inclusive range `0.0..1.0`.
- Consumes: unchanged `MetricScore` scalar result.

- [ ] **Step 1: Write failing boundary tests**

Parameterize `-0.01`, `1.01`, `float("nan")`, and `float("inf")` and assert:

```python
with pytest.raises(ValueError, match="score in the range 0..1"):
    adapter.score(row, judge)
```

Keep exact-boundary assertions for `0.0` and `1.0`.

- [ ] **Step 2: Run the focused test and verify clamping hides the error**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_metric_adapters.py -q
```

Expected: finite out-of-range cases fail because current code returns `0.0` or `1.0`.

- [ ] **Step 3: Replace clamping with validation**

Use:

```python
value = float(result.score)
if not isfinite(value) or not 0.0 <= value <= 1.0:
    raise ValueError(f"{self.key} must return a finite score in the range 0..1")
return MetricScore(
    metric=self.key,
    score=value,
    reason=result.reason,
    passed=result.passed,
)
```

- [ ] **Step 4: Run adapter and worker tests**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_metric_adapters.py tests/test_worker.py -q
```

Expected: all tests pass; invalid scores become per-metric errors rather than altered values.

- [ ] **Step 5: Commit strict score validation**

```bash
git add backend/app/evals/base.py backend/tests/test_metric_adapters.py
git commit -m "fix(metrics): reject invalid normalized scores"
```

---

### Task 6: Make report interpretation direction-aware

**Files:**

- Modify: `frontend/components/RunReport.tsx:1-200`
- Test: `frontend/tests/run-report.test.tsx`

**Interfaces:**

- Produces: `directionFor(key: string) -> "higher_is_better" | "lower_is_better" | null`.
- Produces: `comparisonScore(key: string, score: number) -> number | null` used only for cross-metric charts.
- Consumes: `Metric.info.score_direction` from `GET /api/metrics`. The existing backend catalog test asserts direction for all ten current keys.

- [ ] **Step 1: Write failing lower-is-better report tests**

Add a `deepeval.toxicity` fixture with `score_direction: "lower_is_better"`. Assert:

- selecting Toxicity sorts `0.1` before `0.8`;
- missing Toxicity scores remain after every numeric score;
- its summary card says `Lower is better`;
- comparison chart data uses `0.9` for raw score `0.1`;
- raw table cells still show `0.1`.

Also cover a historical metric absent from the catalog. Assert its raw score
remains visible, its summary says `Direction unavailable`, and it is omitted
from direction-normalized comparison charts.

- [ ] **Step 2: Run the report test and verify current descending sort**

Run:

```bash
cd frontend && npm test -- --run tests/run-report.test.tsx
```

Expected: FAIL because the report always sorts descending and charts raw means without direction labels.

- [ ] **Step 3: Add direction helpers and direction-aware sorting**

Inside `RunReport`:

```typescript
const directionFor = (key: string) =>
  metricsByKey.get(key)?.info.score_direction ?? null;

const comparisonScore = (key: string, value: number) => {
  const direction = directionFor(key);
  if (direction === null) return null;
  return direction === "lower_is_better" ? 1 - value : value;
};
```

Change selected metric sorting:

```typescript
const direction = directionFor(sortMetric);
return [...filtered].sort((a, b) => {
  const left = a.scores[sortMetric]?.score;
  const right = b.scores[sortMetric]?.score;
  if (left == null && right == null) return a.row_index - b.row_index;
  if (left == null) return 1;
  if (right == null) return -1;
  if (direction === "lower_is_better") return left - right;
  if (direction === "higher_is_better") return right - left;
  return a.row_index - b.row_index;
});
```

Add `metricsByKey` to this `useMemo` dependency list so rows re-sort after the
asynchronously loaded catalog supplies direction metadata.

- [ ] **Step 4: Use comparison values only where metrics share one chart**

Build chart rows:

```typescript
const comparisonSummaries = run.summaries.flatMap((summary) => {
  const comparison = comparisonScore(summary.metric_key, summary.mean);
  return comparison === null
    ? []
    : [{...summary, comparison_score: comparison, raw_mean: summary.mean}];
});
```

Use `comparison_score` for the multi-metric bar and radar charts; label those charts `Comparable quality`. Tooltip must show both `raw_mean` and whether higher/lower is better. Keep score distribution and result table raw. Metrics without catalog direction remain in summaries and tables but are omitted from comparison charts.

Add direction text to each summary card:

```tsx
<span>
  {directionFor(summary.metric_key) === "lower_is_better"
    ? "Lower is better"
    : directionFor(summary.metric_key) === "higher_is_better"
      ? "Higher is better"
      : "Direction unavailable"}
</span>
```

- [ ] **Step 5: Run focused frontend tests**

Run:

```bash
cd frontend && npm test -- --run tests/run-report.test.tsx tests/metric-info-modal.test.tsx
```

Expected: all tests pass; raw values remain unchanged and comparison visuals are direction-aware.

- [ ] **Step 6: Commit report correction**

```bash
git add frontend/components/RunReport.tsx frontend/tests/run-report.test.tsx
git commit -m "fix(reports): respect metric score direction"
```

---

### Task 7: Discover dataset columns from the complete preview

**Files:**

- Modify: `frontend/components/DatasetUpload.tsx:15-25`
- Test: `frontend/tests/column-mapper.test.tsx`

**Interfaces:**

- Produces: column choices equal the ordered union of keys across all preview rows.
- Consumes: unchanged `Dataset.preview: Record<string, unknown>[]`.

- [ ] **Step 1: Write a failing sparse-preview test**

Render `ColumnMapper` with:

```typescript
preview: [
  {prompt: "one"},
  {prompt: "two", answer: "late column", contexts: ["doc"]},
]
```

Assert `answer` and `contexts` appear as mapping options.

- [ ] **Step 2: Run the focused test and verify late columns are absent**

Run:

```bash
cd frontend && npm test -- --run tests/column-mapper.test.tsx
```

Expected: FAIL because only `preview[0]` is inspected.

- [ ] **Step 3: Compute a stable union**

Replace the current memo with:

```typescript
const columns = useMemo(
  () => Array.from(
    new Set((dataset.preview ?? []).flatMap((row) => Object.keys(row))),
  ),
  [dataset.preview],
);
```

This preserves first-seen order and matches backend validation, which already unions all dataset rows.

- [ ] **Step 4: Run mapper and upload tests**

Run:

```bash
cd frontend && npm test -- --run tests/column-mapper.test.tsx tests/run-wizard.test.tsx
```

Expected: all tests pass.

- [ ] **Step 5: Commit mapper correction**

```bash
git add frontend/components/DatasetUpload.tsx frontend/tests/column-mapper.test.tsx
git commit -m "fix(datasets): map sparse preview columns"
```

---

### Task 8: Full verification and documentation sync

**Files:**

- Modify only if required by verified behavior: `README.md`
- Verify: backend and frontend suites

**Interfaces:**

- Consumes: all previous tasks.
- Produces: verified Phase 0 baseline for the curated metric feature plans.

- [ ] **Step 1: Run backend formatting and full tests**

Run:

```bash
cd backend
.venv/bin/ruff check app tests
.venv/bin/pytest -q
```

Expected: zero Ruff errors and all backend tests pass.

- [ ] **Step 2: Run frontend tests, lint, and production build**

Run:

```bash
cd frontend
npm test -- --run
npm run lint
npm run build
```

Expected: all Vitest tests pass; lint and production build exit `0`.

- [ ] **Step 3: Verify Compose and migration configuration**

Run:

```bash
docker compose config >/dev/null
cd backend && .venv/bin/alembic heads
```

Expected: Compose config exits `0`; Alembic reports exactly `f2b3c4d5e6f7 (head)`.

- [ ] **Step 4: Confirm the scope diff**

Run:

```bash
git diff --check
git status --short
git log --oneline --max-count=8
```

Expected: no whitespace errors; only Phase 0 files changed; no metric catalog expansion or dependency upgrade appears.

- [ ] **Step 5: Commit any verified documentation correction**

Only when README behavior changed:

```bash
git add README.md
git commit -m "docs: describe resilient evaluation runs"
```

Otherwise make no empty commit.
