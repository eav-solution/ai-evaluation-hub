# Phase 3 Agentic Trace Implementation Plan

> **Execution:** Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add runnable offline, endpoint, and ingestion support for Task Completion, Tool Correctness, and Agent Loop Detection using the existing typed-sample and scalar-result contracts.

**Architecture:** Extend the current sample union with production-grade agent-trace normalization, then let the existing adapter registry and worker operate on either `single_turn` or `agent_trace` samples. Dataset and endpoint runs keep their current lifecycle; authenticated ingestion stores an immutable raw artifact and creates a normal run through the same validation, scoring, persistence, and reporting path. Deterministic agent metrics do not require a provider connection.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy, Alembic, Celery, PostgreSQL JSONB, DeepEval 4.1.0, Next.js 16, React 19, TypeScript, pytest, Vitest.

## Global Constraints

- Keep all 15 Phase 2 metric keys and add exactly three Phase 3 keys: `deepeval.task_completion`, `deepeval.tool_correctness`, and `deepeval.agent_loop_detection`.
- Do not add Conversational, MCP, or Multimodal cards in this phase.
- Use only the existing four sample kinds; every new adapter uses `agent_trace`.
- Support agent-trace evaluation from static datasets, named endpoint response mappings, and workspace-authenticated ingestion.
- `Task Completion` requires `judge`; `Tool Correctness` and `Agent Loop Detection` make no provider call and require no judge.
- A run may contain multiple adapters only when every selected adapter has the same `sample_kind`.
- CSV structured values are JSON strings; JSON and JSONL retain native arrays and objects.
- Ingestion requires `Idempotency-Key`; the same key and request returns the original `artifact_id` and `run_id`, while a changed request returns `409`.
- Raw ingestion payloads are snapshotted in object storage before worker normalization. Provider secrets never enter artifacts or definition snapshots.
- Missing trace, tools, or expected tools is a row incompatibility, never an automatic score of zero.
- Preserve atomic claim, resumable persisted progress, attempt-guarded terminal writes, cancellation, and no automatic retry of paid judge calls.
- Keep scalar scores in `0..1`; trace and tool data belongs in nullable result `details` and existing exports.
- Use no new dependency.

---

### Task 1: Normalize typed agent-trace samples

**Files:**

- Modify: `backend/app/evals/samples.py`
- Create: `backend/app/evals/normalizers.py`
- Modify: `backend/tests/test_samples.py`
- Create: `backend/tests/test_agent_normalizers.py`

**Interfaces:**

- Produces: recursive `AgentTraceEvent.children` and canonical `AgentTraceSample.expected_tools: list[ToolCall]`.
- Produces: `normalize_sample(sample_kind, source, schema_map, overrides=None, source_ref=None) -> EvaluationSample`.
- Produces: field-specific `ValueError` messages for malformed CSV JSON.

- [ ] **Step 1: Write RED sample-contract tests**

Add tests proving nested trace children validate, expected tool-name shorthand becomes `ToolCall(name=...)`, empty traces fail validation, and unknown fields remain forbidden.

```python
sample = AgentTraceSample.model_validate({
    "kind": "agent_trace",
    "input": "Book a flight",
    "actual_output": "Booked",
    "agent_trace": [{
        "type": "agent",
        "name": "planner",
        "children": [{"type": "tool", "name": "search"}],
    }],
    "expected_tools": ["search"],
})
assert sample.agent_trace[0].children[0].name == "search"
assert sample.expected_tools[0].name == "search"
```

- [ ] **Step 2: Write RED normalizer tests**

Cover native JSON/JSONL objects, CSV JSON strings, legacy string expected-tool names, endpoint overrides, missing mapped values, and invalid structured JSON naming the canonical field and source column.

```python
sample = normalize_sample(
    "agent_trace",
    {
        "prompt": "Find weather",
        "answer": "Sunny",
        "trace_json": '[{"type":"tool","name":"weather"}]',
        "called_json": '[{"name":"weather","arguments":{"city":"Paris"}}]',
        "expected_json": '["weather"]',
    },
    {
        "input": "prompt",
        "actual_output": "answer",
        "agent_trace": "trace_json",
        "tools_called": "called_json",
        "expected_tools": "expected_json",
    },
)
assert sample.kind == "agent_trace"
assert sample.tools_called[0].arguments == {"city": "Paris"}
```

- [ ] **Step 3: Run RED**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_samples.py tests/test_agent_normalizers.py`

Expected: failures for absent recursive children, string tool coercion, minimum trace length, and the missing normalizer module.

- [ ] **Step 4: Implement strict agent models and one normalizer boundary**

Use a before-validator for expected-tool shorthand and a single structured-value decoder.

```python
class AgentTraceEvent(StrictModel):
    type: str = Field(min_length=1)
    name: str | None = None
    input: Any = None
    output: Any = None
    details: dict[str, Any] = Field(default_factory=dict)
    children: list["AgentTraceEvent"] = Field(default_factory=list)


class AgentTraceSample(SampleMetadata):
    kind: Literal["agent_trace"] = "agent_trace"
    input: str
    actual_output: str
    agent_trace: list[AgentTraceEvent] = Field(min_length=1)
    tools_called: list[ToolCall] = Field(default_factory=list)
    expected_tools: list[ToolCall] = Field(default_factory=list)

    @field_validator("expected_tools", mode="before")
    @classmethod
    def tool_name_shorthand(cls, value):
        return [{"name": item} if isinstance(item, str) else item for item in value or []]
```

`normalize_sample` must use canonical names as the only output shape and must merge endpoint `overrides` after dataset values so response mappings win.

- [ ] **Step 5: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_samples.py tests/test_agent_normalizers.py`

```bash
git add backend/app/evals/samples.py backend/app/evals/normalizers.py backend/tests/test_samples.py backend/tests/test_agent_normalizers.py
git commit -m "feat(evals): normalize agent trace samples"
```

---

### Task 2: Register and score the three Agentic adapters

**Files:**

- Modify: `backend/app/evals/base.py`
- Modify: `backend/app/evals/judges.py`
- Modify: `backend/app/evals/deepeval.py`
- Modify: `backend/app/evals/registry.py`
- Modify: `backend/app/evals/metric_info.py`
- Modify: `backend/app/evals/presets.py`
- Modify: `backend/tests/test_metric_contract.py`
- Modify: `backend/tests/test_metric_adapters.py`
- Modify: `backend/tests/test_metric_upstream_contract.py`
- Modify: `backend/tests/test_metrics.py`

**Interfaces:**

- Produces: `TaskCompletionConfig`, `ToolCorrectnessConfig`, and `AgentLoopDetectionConfig` JSON Schemas.
- Produces: `MetricAdapter.score(sample: EvaluationSample, judge: JudgeConfig | None, config=None)`.
- Produces: `agentic` recommended preset with Task Completion and Agent Loop Detection.

- [ ] **Step 1: Write RED registry and resource tests**

Assert exactly 18 keys, categories/families/sample kinds, generated defaults, higher-is-better directions, and resource roles.

```python
assert METRICS["deepeval.task_completion"].resources({}) == frozenset({"judge"})
assert METRICS["deepeval.tool_correctness"].resources({}) == frozenset()
assert METRICS["deepeval.agent_loop_detection"].resources({}) == frozenset()
assert all(
    METRICS[key].sample_kind == "agent_trace"
    for key in (
        "deepeval.task_completion",
        "deepeval.tool_correctness",
        "deepeval.agent_loop_detection",
    )
)
```

Prove the upstream contract imports all three classes from DeepEval 4.1.0 and the `agentic` preset contains only Task Completion and Agent Loop Detection.

- [ ] **Step 2: Write RED constructor and conversion tests**

Mock each upstream metric and prove:

- Task Completion receives the configured task and judge;
- Tool Correctness receives deterministic options and converted DeepEval tool calls;
- Agent Loop Detection receives repetition/similarity/check toggles;
- the generated `LLMTestCase._trace_dict` contains a synthetic root plus nested children; and
- deterministic adapters score with `judge=None`.

```python
assert test_case.tools_called[0].input_parameters == {"city": "Paris"}
assert test_case.expected_tools[0].name == "weather"
assert test_case._trace_dict["children"][0]["type"] == "tool"
```

- [ ] **Step 3: Run RED**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_metric_contract.py tests/test_metric_adapters.py tests/test_metric_upstream_contract.py tests/test_metrics.py`

- [ ] **Step 4: Add validated adapter configs**

```python
class TaskCompletionConfig(DeepEvalMetricConfig):
    task: str | None = Field(default=None, min_length=1, max_length=10_000)


class ToolCorrectnessConfig(DeepEvalMetricConfig):
    evaluation_params: list[Literal["input_parameters", "output"]] = Field(default_factory=list)
    should_exact_match: bool = False
    should_consider_ordering: bool = False


class AgentLoopDetectionConfig(DeepEvalMetricConfig):
    repetition_threshold: int = Field(default=3, ge=2, le=100)
    similarity_threshold: float = Field(default=0.85, ge=0, le=1)
    check_tool_repetition: bool = True
    check_reasoning_stagnation: bool = True
    check_call_graph_cycles: bool = True
```

Add a model validator rejecting an Agent Loop config with all three checks disabled. Fix registry resource resolution so `resources=set()` remains empty instead of falling back to `judge`.

- [ ] **Step 5: Add deterministic DeepEval conversion and scoring**

Add one local `DeepEvalBaseLLM` implementation whose generate methods raise if called, and pass it only to Tool Correctness so DeepEval does not demand an API key for a deterministic run. Convert EvalHub `ToolCall.arguments` to DeepEval `ToolCall.input_parameters` and assign the trace dictionary to the test case private trace field.

```python
def _trace_dict(sample: AgentTraceSample) -> dict[str, Any]:
    return {
        "type": "agent",
        "name": "evalhub-agent-trace",
        "input": sample.input,
        "output": sample.actual_output,
        "children": [event.model_dump(mode="json") for event in sample.agent_trace],
    }
```

Single-turn scoring must continue to assert a non-null judge before constructing any judge-backed metric.

- [ ] **Step 6: Publish metadata, info, and preset**

Register:

```python
("deepeval.task_completion", "agentic", "trace", {"agent_trace"}, {"judge"})
("deepeval.agent_loop_detection", "agentic", "trace", {"agent_trace"}, set())
(
    "deepeval.tool_correctness",
    "agentic",
    "tools",
    {"tools_called", "expected_tools"},
    set(),
)
```

Add complete `MetricInfo` entries with `higher_is_better`, trace/tool examples, improvement tips, and exact required fields. Add preset id `agentic` with Task Completion followed by Agent Loop Detection.

- [ ] **Step 7: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_metric_contract.py tests/test_metric_adapters.py tests/test_metric_upstream_contract.py tests/test_metrics.py`

```bash
git add backend/app/evals backend/tests/test_metric_contract.py backend/tests/test_metric_adapters.py backend/tests/test_metric_upstream_contract.py backend/tests/test_metrics.py
git commit -m "feat(metrics): add agentic trace adapters"
```

---

### Task 3: Validate agent runs and named endpoint mappings

**Files:**

- Modify: `backend/app/endpoints.py`
- Modify: `backend/app/evals/snapshots.py`
- Modify: `backend/app/routers/runs.py`
- Modify: `backend/app/routers/datasets.py`
- Modify: `backend/tests/test_endpoints.py`
- Modify: `backend/tests/test_runs.py`
- Modify: `backend/tests/test_datasets.py`

**Interfaces:**

- Produces: endpoint mappings for `agent_trace`, `tools_called`, and `expected_tools`.
- Produces: `_validate_metric_selection(...)` shared by dataset runs and ingestion.
- Produces: optional `RunIn.judge`; it is required only when selected resources include `judge` or `embedding`.

- [ ] **Step 1: Write RED run-preflight tests**

Cover static Agentic success, missing trace/tools rejection, endpoint mappings satisfying requirements, mixed sample-kind rejection, Task Completion requiring a judge, and Agent Loop-only or Tool Correctness-only runs accepting `judge=null`.

```python
response = client.post(
    f"/api/workspaces/{workspace.id}/runs",
    json={
        "dataset_id": dataset.id,
        "name": "Loop check",
        "mode": "static",
        "metrics": [{"key": "deepeval.agent_loop_detection"}],
        "judge": None,
    },
    headers=auth_headers,
)
assert response.status_code == 201
assert response.json()["judge_config"] == {}
```

- [ ] **Step 2: Write RED endpoint tests**

Assert `EndpointConfig` accepts only the six current response fields, preserves native trace/tool arrays, and still requires `actual_output`.

```python
assert extract_response_fields(payload, config)["agent_trace"] == [
    {"type": "tool", "name": "search"}
]
```

- [ ] **Step 3: Run RED**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_endpoints.py tests/test_runs.py`

- [ ] **Step 4: Generalize preflight without weakening compatibility**

Extract the current metric loop into a helper that validates config, rejects multiple sample kinds, checks requirements against dataset plus active endpoint fields, and returns `(selected, resource_roles, sample_kind)`. Continue converting Pydantic config errors to the current indexed `422` shape.

Judge resolution must follow:

```python
needs_judge = "judge" in resource_roles
if needs_judge and body.judge is None:
    raise HTTPException(status_code=422, detail="A judge connection is required for the selected metrics")
if not needs_judge and body.judge is None:
    judge_config = {}
```

Keep embedding validation unchanged and reachable only when `embedding` is selected.

- [ ] **Step 5: Extend endpoint and snapshot fields**

Allow `agent_trace`, `tools_called`, and `expected_tools` in `response_mappings`. Snapshot the selected `agent_trace` kind and named mappings while keeping headers, keys, and URLs out of the definition snapshot. Allow the same canonical structured fields in dataset schema mappings so JSON, JSONL, and CSV agent datasets can pass preflight.

- [ ] **Step 6: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_endpoints.py tests/test_runs.py tests/test_metric_contract.py`

```bash
git add backend/app/endpoints.py backend/app/evals/snapshots.py backend/app/routers/runs.py backend/app/routers/datasets.py backend/tests/test_endpoints.py backend/tests/test_runs.py backend/tests/test_datasets.py
git commit -m "feat(runs): validate agentic input mappings"
```

---

### Task 4: Persist immutable ingestion artifacts

**Files:**

- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/0003_evaluation_artifacts.py`
- Create: `backend/app/routers/ingestions.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/routers/runs.py`
- Modify: `backend/tests/test_models.py`
- Create: `backend/tests/test_ingestions.py`

**Interfaces:**

- Produces: `EvaluationArtifact(id, workspace_id, sample_kind, idempotency_key, request_hash, storage_path)`.
- Produces: `POST /api/workspaces/{workspace_id}/ingestions/agent-traces`.
- Produces: `Run.dataset_id: str | None`, `Run.artifact_id: str | None`, and run mode `ingestion`.

- [ ] **Step 1: Write RED model and migration tests**

Assert a run can reference an artifact without a dataset, artifact idempotency is unique per workspace, and Alembic has one head after revision `0003`.

- [ ] **Step 2: Write RED ingestion API tests**

Cover workspace authentication, missing idempotency key, first acceptance, same-request replay, changed-request conflict, exact validation pointer, immutable object payload, no secret leakage, outbox creation, and storage cleanup on a database failure.

```python
first = client.post(url, json=body, headers={**auth_headers, "Idempotency-Key": "trace-1"})
replay = client.post(url, json=body, headers={**auth_headers, "Idempotency-Key": "trace-1"})
assert first.status_code == 202
assert replay.status_code == 200
assert replay.json() == first.json()
```

- [ ] **Step 3: Run RED**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_models.py tests/test_ingestions.py tests/test_runs.py`

- [ ] **Step 4: Add the additive artifact migration**

Create `evaluation_artifacts`, make `runs.dataset_id` nullable, add nullable indexed `runs.artifact_id`, and add a check constraint requiring exactly one source.

```python
sa.CheckConstraint(
    "(dataset_id IS NOT NULL AND artifact_id IS NULL) OR "
    "(dataset_id IS NULL AND artifact_id IS NOT NULL)",
    name="ck_runs_exactly_one_source",
)
```

The downgrade must refuse while artifact-backed runs exist, then remove the constraint, FK/index/column, restore dataset non-nullability, and drop the artifact table.

- [ ] **Step 5: Implement authenticated idempotent acceptance**

The request body contains `name`, raw `sample`, `metrics`, and optional `judge`. Validate `sample` as `AgentTraceSample`, validate selection through the Task 3 helper, hash a canonical JSON encoding of the full request, and store the original `sample` object bytes under `evaluation-artifacts/{workspace_id}/{artifact_id}.json`.

The first request creates artifact, run, and `evaluate_run` outbox event in one DB transaction and returns `202`. A replay with the same hash returns the stored association with `200`; a different hash returns `409`. Catch the unique-key race, roll back, delete only the losing upload, and resolve the winning row.

- [ ] **Step 6: Expose nullable source identifiers safely**

Return `dataset_id` and `artifact_id` from run endpoints and exports. Do not expose artifact storage paths or endpoint/provider secrets.

- [ ] **Step 7: Run GREEN, verify migration, and commit**

Run:

```bash
cd backend
.venv/bin/pytest -q -p no:deepeval tests/test_models.py tests/test_ingestions.py tests/test_runs.py
.venv/bin/alembic heads
```

Expected: API/model tests pass and Alembic prints one `0003` head.

```bash
git add backend/app/models.py backend/alembic/versions/0003_evaluation_artifacts.py backend/app/routers/ingestions.py backend/app/main.py backend/app/routers/runs.py backend/tests/test_models.py backend/tests/test_ingestions.py
git commit -m "feat(ingestion): persist idempotent trace artifacts"
```

---

### Task 5: Execute agent samples through the resumable worker

**Files:**

- Modify: `backend/app/tasks.py`
- Modify: `backend/tests/test_worker.py`
- Modify: `backend/tests/test_worker_endpoint.py`
- Create: `backend/tests/test_worker_agentic.py`

**Interfaces:**

- Produces: `_load_run_source(run) -> tuple[list[dict], dict[str, str] | None]` for dataset or artifact sources.
- Produces: `_stored_sample(result, sample_kind) -> EvaluationSample` for recovery without paid-call replay.
- Consumes: Task 1 `normalize_sample` and Task 2 polymorphic adapters.

- [ ] **Step 1: Write RED static and deterministic worker tests**

Prove a JSON/JSONL agent row reaches all three scorers as `AgentTraceSample`, tool details persist, partial metric failure stays row-scoped, and an Agent Loop-only run resolves no provider connection.

- [ ] **Step 2: Write RED endpoint and ingestion worker tests**

Prove named endpoint fields override dataset values, malformed response trace fails only that row, artifact payload is loaded from its immutable storage path, and persisted agent details rebuild the same sample during recovery without replaying completed metrics.

- [ ] **Step 3: Run RED**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_worker.py tests/test_worker_endpoint.py tests/test_worker_agentic.py`

- [ ] **Step 4: Generalize source and judge loading**

Load dataset bytes from the existing definition snapshot. For ingestion, load the `EvaluationArtifact` by the run FK and read its snapshotted JSON bytes. Resolve a judge only when `run.judge_config.connection_id` exists; pass `None` to deterministic adapters.

- [ ] **Step 5: Normalize before checkpoint creation**

For static and ingestion runs, normalize the final sample once. For endpoint runs, render the request from mapped dataset fields, extract all named response fields, then normalize with response fields as overrides.

Persist common columns plus typed details:

```python
details = {
    "sample": {
        "kind": "agent_trace",
        "agent_trace": sample.agent_trace,
        "tools_called": sample.tools_called,
        "expected_tools": sample.expected_tools,
        "metadata": sample.metadata,
        "tags": sample.tags,
    }
}
```

Keep single-turn details nullable when no trusted context exists.

- [ ] **Step 6: Preserve lifecycle invariants**

Retain the endpoint checkpoint before the network call, metric `in_progress` checkpoint before scoring, attempt guards after external calls, no automatic replay of interrupted metrics, per-row errors, result-derived summaries, and status `failed` only when every row fails.

- [ ] **Step 7: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest -q -p no:deepeval tests/test_worker.py tests/test_worker_endpoint.py tests/test_worker_agentic.py tests/test_ingestions.py`

```bash
git add backend/app/tasks.py backend/tests/test_worker.py backend/tests/test_worker_endpoint.py backend/tests/test_worker_agentic.py
git commit -m "feat(worker): evaluate agent trace sources"
```

---

### Task 6: Add Agentic dataset and run UI

**Files:**

- Modify: `frontend/components/DatasetUpload.tsx`
- Modify: `frontend/lib/dataset-capabilities.ts`
- Modify: `frontend/components/RunWizard.tsx`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/app/globals.css`
- Modify: `frontend/tests/column-mapper.test.tsx`
- Modify: `frontend/tests/datasets-page.test.tsx`
- Modify: `frontend/tests/run-wizard.test.tsx`
- Modify: `frontend/tests/metric-config-form.test.tsx`

**Interfaces:**

- Produces: compact Agentic mapping group for `agent_trace`, `tools_called`, and `expected_tools`.
- Produces: Agentic families `Trace` and `Tools` with framework sub-labels.
- Produces: conditional endpoint mappings and judge controls driven by selected adapter metadata.

- [ ] **Step 1: Write RED dataset UI tests**

Assert the mapper adds one compact `Agentic` group, dataset capability inference uses schema mappings only, and compatible counts use metric requirements for agent-trace adapters.

```typescript
expect(screen.getByRole("group", {name: "Agentic"})).toBeInTheDocument();
expect(screen.getByLabelText("Agent trace")).toBeInTheDocument();
expect(screen.getByLabelText("Tools called")).toBeInTheDocument();
expect(screen.getByLabelText("Expected tools")).toBeInTheDocument();
```

- [ ] **Step 2: Write RED Run Wizard tests**

Assert the three cards appear under Trace/Tools, the Agentic preset selects exactly Task Completion and Agent Loop Detection, different sample kinds cannot be mixed in one run, endpoint mode renders only needed Agentic JSONPaths, deterministic selections hide judge controls, Task Completion requires judge controls, and launch sends `judge: null` for deterministic runs.

- [ ] **Step 3: Write RED hierarchy and config tests**

Assert Family headings use `metric-family-heading`, framework legends use `metric-framework-label`, neither includes counts, and generated controls render all Task Completion, Tool Correctness, and Agent Loop config fields from adapter JSON Schema.

- [ ] **Step 4: Run RED**

Run: `cd frontend && npm test -- --run tests/column-mapper.test.tsx tests/datasets-page.test.tsx tests/run-wizard.test.tsx tests/metric-config-form.test.tsx`

- [ ] **Step 5: Extend mapping and capability inference**

Keep Input and Actual output in `Common / RAG`; add only the three structured fields to `Agentic`. Infer Agentic when `input`, `actual_output`, and `agent_trace` are mapped. Count compatible metrics solely through `missingMetricRequirements` and each metric's sample kind.

- [ ] **Step 6: Make the picker sample-kind and resource aware**

Use the selected metrics to derive one active sample kind and resource union. Disable a card from another sample kind with `Choose in a separate run`. Render Agentic endpoint mapping controls when the active sample kind is `agent_trace`. Hide LLM controls and omit the judge payload when `judge` is absent from the selected resource union.

- [ ] **Step 7: Apply the approved visual hierarchy**

Family is a 16px section header with a light violet background and left accent. Framework is a 10.5px muted uppercase label. Family filter selection uses a soft violet state while primary capability tabs retain solid purple. Do not display Family or Framework counts.

- [ ] **Step 8: Run GREEN, build, and commit**

Run:

```bash
cd frontend
npm test -- --run tests/column-mapper.test.tsx tests/datasets-page.test.tsx tests/run-wizard.test.tsx tests/metric-config-form.test.tsx
npm run build
```

```bash
git add frontend/components/DatasetUpload.tsx frontend/lib/dataset-capabilities.ts frontend/components/RunWizard.tsx frontend/lib/types.ts frontend/app/globals.css frontend/tests/column-mapper.test.tsx frontend/tests/datasets-page.test.tsx frontend/tests/run-wizard.test.tsx frontend/tests/metric-config-form.test.tsx
git commit -m "feat(ui): expose agentic datasets and metrics"
```

---

### Task 7: Verify trace reports, exports, and Phase 3 scope

**Files:**

- Modify: `frontend/components/RunReport.tsx`
- Modify: `backend/app/templates/report.html`
- Modify: `backend/app/reports.py`
- Modify: `frontend/tests/run-report.test.tsx`
- Modify: `backend/tests/test_exports.py`
- Verify: all Phase 3 files

**Interfaces:**

- Produces: readable Agent trace, Tools called, and Expected tools drill-down sections.
- Produces: JSON/CSV/HTML exports containing agent details without changing scalar score columns.

- [ ] **Step 1: Write RED report/export tests**

Create one agent result with trace/tool details and assert React, HTML, JSON, and CSV exports expose the same data. Confirm absent details remain absent on historical single-turn rows.

- [ ] **Step 2: Run RED**

Run:

```bash
cd frontend && npm test -- --run tests/run-report.test.tsx
cd ../backend && .venv/bin/pytest -q -p no:deepeval tests/test_exports.py
```

- [ ] **Step 3: Add readable typed-detail labels**

Use the existing `details.sample.kind` discriminator. Render dedicated sections for `agent_trace`, `tools_called`, and `expected_tools`, then keep the existing generic Details section for other metadata. Do not create a new result kind or new database column.

- [ ] **Step 4: Run focused GREEN**

Run the commands from Step 2 and expect all focused tests to pass.

- [ ] **Step 5: Run complete backend verification**

```bash
cd backend
.venv/bin/pytest -q -p no:deepeval tests
ruff check app tests alembic/versions
.venv/bin/alembic heads
```

Expected: all backend tests pass, Ruff is clean, and Alembic reports exactly one `0003` head.

- [ ] **Step 6: Run complete frontend verification**

```bash
cd frontend
npm test
npx tsc --noEmit
npm run build
```

Expected: all Vitest tests, TypeScript validation, and the Next.js production build pass.

- [ ] **Step 7: Verify exact Phase 3 acceptance**

Confirm:

- exactly 18 registry keys and exactly three Agentic cards;
- all three named DeepEval 4.1.0 classes import;
- static, endpoint, and ingestion agent paths persist scalar results and trace details;
- deterministic runs do not resolve a provider;
- mixed sample-kind runs fail before enqueueing;
- ingestion replay cannot duplicate artifacts, runs, results, or outbox work;
- no Conversational, MCP, or Multimodal adapter is registered;
- no endpoint/provider secret appears in artifacts, API responses, snapshots, or exports; and
- existing Phase 2 tests and historical result rendering remain green.

- [ ] **Step 8: Commit report changes and inspect branch**

```bash
git add frontend/components/RunReport.tsx backend/app/templates/report.html backend/app/reports.py frontend/tests/run-report.test.tsx backend/tests/test_exports.py
git commit -m "feat(reports): show agent trace details"
git diff --check main...HEAD
git status --short
```

Expected: no whitespace errors and a clean Phase 3 branch.
