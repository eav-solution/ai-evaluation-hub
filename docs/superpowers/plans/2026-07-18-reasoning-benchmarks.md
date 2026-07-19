# Reasoning Benchmarks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Reasoning Benchmark" workspace area (nav item below Model Benchmarks) serving a hand-curated, growing catalog of model-reasoning tests across harness layers, seeded with the 2026-07-18 five-model test-planning comparison.

**Architecture:** Mirror the existing `app/model_benchmarks` static-catalog pattern: frozen pydantic types, import-time cross-reference validation, one authenticated GET endpoint, client component fetching once and rendering a criteria × entries matrix. One Python module per test under `reasoning_benchmarks/tests/`; shared harness/model registries; `catalog.py` assembles.

**Tech Stack:** FastAPI + pydantic v2 (backend), Next.js app router + React client components (frontend), pytest + TestClient, vitest + testing-library.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-18-reasoning-benchmarks-design.md` (user-approved).
- Catalog records: `model_config = ConfigDict(frozen=True, extra="forbid")` (match `app/model_benchmarks/types.py:11-12`).
- Validation failures raise `ValueError` at import listing every violation with ids (match `model_benchmarks` fail-fast contract).
- Nav label exactly `Reasoning Benchmark`, route segment `reasoning-benchmarks`.
- Catalog content English. No secrets. Do not commit to git (user has not requested commits).
- Dev deployment hot-reloads both containers (`docker-compose.yml` bind mounts); no rebuild.

---

### Task 1: Backend types + registries

**Files:**
- Create: `backend/app/reasoning_benchmarks/__init__.py` (empty)
- Create: `backend/app/reasoning_benchmarks/types.py`
- Create: `backend/app/reasoning_benchmarks/registry.py`
- Test: `backend/tests/test_reasoning_benchmark_types.py`

**Interfaces:**
- Produces: `HarnessRecord(id, display_name, description)`, `ReasoningModelRecord(id, display_name, developer)`, `CriterionDefinition(id, display_name, description, minimum, maximum, direction: ScoreDirection)`, `CriterionScore(criterion_id, value, evidence: str | None = None)`, `TestEntry(model_id, harness_id, summary, scores: tuple[CriterionScore, ...])`, `ReasoningTest(id, display_name, category, series_id: str | None, conducted_at: date, task_summary, methodology, source_reference, criteria, entries, findings: tuple[str, ...], limitations: tuple[str, ...])`, `ReasoningBenchmarkCatalog(catalog_version, last_updated_at: date, harnesses, models, tests)`; `ScoreDirection` reused from `app.model_benchmarks.types`.
- `registry.py` exports `HARNESSES: tuple[HarnessRecord, ...]` (claude-code, codex-cli) and `MODELS: tuple[ReasoningModelRecord, ...]` (claude-opus-4-8, claude-fable-5, qwen-27b, qwen-35b-a3b, codex-5-6-sol).

- [ ] **Step 1: Write failing test** — `test_reasoning_benchmark_types.py`:

```python
from datetime import date

import pytest
from pydantic import ValidationError


def test_records_are_frozen_and_reject_unknown_fields():
    from app.reasoning_benchmarks.types import HarnessRecord

    record = HarnessRecord(id="claude-code", display_name="Claude Code", description="CLI agent harness.")
    with pytest.raises(ValidationError):
        record.id = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        HarnessRecord(id="x", display_name="X", description="d", extra_field="nope")


def test_registries_expose_seed_harnesses_and_models():
    from app.reasoning_benchmarks.registry import HARNESSES, MODELS

    assert {h.id for h in HARNESSES} == {"claude-code", "codex-cli"}
    assert {m.id for m in MODELS} == {
        "claude-opus-4-8", "claude-fable-5", "qwen-27b", "qwen-35b-a3b", "codex-5-6-sol",
    }


def test_score_value_and_criterion_bounds_are_validated():
    from app.reasoning_benchmarks.types import CriterionDefinition, CriterionScore
    from app.model_benchmarks.types import ScoreDirection

    criterion = CriterionDefinition(
        id="c", display_name="C", description="d",
        minimum=0, maximum=10, direction=ScoreDirection.HIGHER_IS_BETTER,
    )
    assert criterion.maximum == 10
    score = CriterionScore(criterion_id="c", value=9.5)
    assert score.evidence is None
```

- [ ] **Step 2: Run** `pytest tests/test_reasoning_benchmark_types.py -v` → FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implement** `types.py` (all classes above inheriting a local `CatalogRecord` with frozen+forbid; `ReasoningTest.criteria/entries/findings/limitations` are tuples with `Field(min_length=1)` where the spec requires non-empty) and `registry.py` (two tuples, descriptions one sentence each).
- [ ] **Step 4: Run same command** → PASS.

### Task 2: Seeded first test module

**Files:**
- Create: `backend/app/reasoning_benchmarks/tests/__init__.py` (empty)
- Create: `backend/app/reasoning_benchmarks/tests/t2026_07_test_planning.py`

**Interfaces:**
- Produces: module attribute `TEST: ReasoningTest` with `id="test-planning-2026-07"`, `category="planning"`, `conducted_at=date(2026, 7, 18)`, 11 criteria (ids below, all 0–10 higher_is_better), 5 entries (model × harness) each with 11 scores, 4 findings, 4 limitations, `source_reference` pointing at the analysis report path.

Criterion ids in order: `goal-understanding`, `active-investigation`, `factual-accuracy`, `self-consistency`, `oracle-design`, `risk-reasoning`, `constraint-planning`, `safety-reasoning`, `orchestration-design`, `epistemic-honesty`, `instructional-clarity`.

Score rows (same criterion order):

| entry (model @ harness) | scores |
| --- | --- |
| claude-opus-4-8 @ claude-code | 10, 10, 10, 10, 10, 10, 10, 9.5, 9.5, 10, 10 |
| claude-fable-5 @ claude-code | 10, 9, 8, 9, 10, 9, 8.5, 10, 10, 9.5, 9.5 |
| codex-5-6-sol @ codex-cli | 10, 9, 10, 10, 9, 9.5, 9.5, 9.5, 9, 9.5, 6.5 |
| qwen-27b @ claude-code | 3, 6.5, 4, 6, 1, 4, 2, 4, 6, 5, 5 |
| qwen-35b-a3b @ claude-code | 4, 3, 4.5, 3, 1, 5, 2, 5, 5, 6, 5 |

Entry summaries: Opus "The empiricist — measured the live environment before asserting anything."; Fable "The gatekeeper — protected pre-existing data and resisted false positives."; Codex "The auditor — exact inventories, hidden-API discovery, cost governance."; Qwen 27B "Read the frontend source well but missed the point of the oracle datasets."; Qwen 35B "Surface-level exploration; fabricated workflows where it could not see."
Selected `evidence` strings (2–3 per entry) taken from the report, e.g. Opus/active-investigation: "Probed the judge endpoint before planning: embeddings 501, vision OK, ~100 s latency."; Qwen 27B/oracle-design: "References 4 of 25 sample files; no expected-score assertions anywhere."

- [ ] **Step 1: Write module** (no dedicated test; Task 3's validation + API tests assert its shape and counts).
- [ ] **Step 2:** `python -c "from app.reasoning_benchmarks.tests.t2026_07_test_planning import TEST; print(len(TEST.criteria), len(TEST.entries))"` inside the api container or with backend venv → prints `11 5`.

### Task 3: Validation + catalog assembly

**Files:**
- Create: `backend/app/reasoning_benchmarks/validation.py`
- Create: `backend/app/reasoning_benchmarks/catalog.py`
- Test: `backend/tests/test_reasoning_benchmark_validation.py`

**Interfaces:**
- Consumes: Task 1 types/registries, Task 2 `TEST`.
- Produces: `validate_catalog(catalog: ReasoningBenchmarkCatalog) -> None` (raises `ValueError` whose message contains every violation, each naming the offending id); `catalog.py` exports `CATALOG: ReasoningBenchmarkCatalog` (version `"2026.07.18"`, `last_updated_at=date(2026, 7, 18)`) and its docstring documents the 3-step add-a-test workflow.

Violation classes (each one test): duplicate harness/model/test/criterion ids; entry referencing unknown model or harness; duplicate (model, harness) entry in one test; score referencing unknown criterion; missing (entry, criterion) pair; duplicate score for a pair; value outside [minimum, maximum]; empty criteria or entries.

- [ ] **Step 1: Write failing tests** — build a minimal valid catalog helper in the test file, then mutate per violation:

```python
def test_valid_seeded_catalog_passes():
    from app.reasoning_benchmarks.catalog import CATALOG
    from app.reasoning_benchmarks.validation import validate_catalog

    validate_catalog(CATALOG)  # must not raise


def test_score_outside_bounds_is_named():
    catalog = _catalog_with(score_value=11.0)
    with pytest.raises(ValueError, match="outside"):
        validate_catalog(catalog)
```

(plus one test per violation class listed above, each asserting the offending id appears in the message)

- [ ] **Step 2: Run** `pytest tests/test_reasoning_benchmark_validation.py -v` → FAIL.
- [ ] **Step 3: Implement** `validation.py` (collect `errors: list[str]`, raise once with `"; ".join`), `catalog.py` (assemble + `validate_catalog(CATALOG)` at import bottom, mirroring `model_benchmarks/catalog.py`).
- [ ] **Step 4: Run** → PASS.

### Task 4: Router + registration

**Files:**
- Create: `backend/app/routers/reasoning_benchmarks.py`
- Modify: `backend/app/main.py` (import + `app.include_router(reasoning_benchmarks.router)` next to `model_benchmarks`)
- Test: `backend/tests/test_reasoning_benchmarks_api.py`

**Interfaces:**
- Produces: `GET /api/reasoning-benchmarks` → `ReasoningBenchmarkCatalog`, 401 without bearer token.

- [ ] **Step 1: Write failing test** (mirror `tests/test_model_benchmarks_api.py`):

```python
def test_reasoning_benchmarks_requires_login(client):
    assert client.get("/api/reasoning-benchmarks").status_code == 401


def test_reasoning_benchmarks_returns_seeded_catalog(client, auth_headers):
    response = client.get("/api/reasoning-benchmarks", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_version"]
    assert len(payload["harnesses"]) == 2
    assert len(payload["models"]) == 5
    assert len(payload["tests"]) == 1
    test = payload["tests"][0]
    assert len(test["criteria"]) == 11
    assert len(test["entries"]) == 5
    assert all(len(entry["scores"]) == 11 for entry in test["entries"])
    assert test["findings"] and test["limitations"]
```

- [ ] **Step 2: Run** `pytest tests/test_reasoning_benchmarks_api.py -v` → FAIL (404).
- [ ] **Step 3: Implement router** (copy `routers/model_benchmarks.py` shape: prefix `/api/reasoning-benchmarks`, `dependencies=[Depends(get_current_user)]`) and register in `main.py`.
- [ ] **Step 4: Run** → PASS. Also run the full new-backend set: `pytest tests/test_reasoning_benchmark_types.py tests/test_reasoning_benchmark_validation.py tests/test_reasoning_benchmarks_api.py -v`.

### Task 5: Frontend lib + component + page + nav + CSS

**Files:**
- Create: `frontend/lib/reasoning-benchmarks.ts`
- Create: `frontend/components/ReasoningBenchmarkCatalog.tsx`
- Create: `frontend/app/w/[workspace]/reasoning-benchmarks/page.tsx`
- Modify: `frontend/components/WorkspaceNav.tsx:8-13` (insert `["Reasoning Benchmark", "reasoning-benchmarks"]` after Model Benchmarks)
- Modify: `frontend/app/globals.css` (append `.reasoning-benchmark-*` block)
- Test: `frontend/tests/reasoning-benchmark-fixture.ts`, `frontend/tests/reasoning-benchmark-catalog.test.tsx`

**Interfaces:**
- Consumes: `api<T>(path)` from `lib/api.ts`; payload shape from Task 4.
- Produces (lib): types mirroring the payload plus
  `entryAverage(entry: TestEntry): number` (mean of its scores),
  `rankEntries(test: ReasoningTest): RankedEntry[]` (`{entry, average, rank}` sorted average desc, then model display name asc — resolved via a `modelsById` argument),
  `bestValueByCriterion(test: ReasoningTest): Map<string, number>` (max for higher_is_better, min for lower_is_better),
  `formatScore(value: number): string` (trim trailing zeros, e.g. `9.5`, `10`).
- Component renders: meta line (`conducted`, category, catalog version), test `<select aria-label="Reasoning test">` (optgroups when >1 category), matrix `<table class="reasoning-benchmark-matrix">` — header cells = model display name + `<span class="reasoning-harness-badge">` harness name; body rows = criterion display name + scale hint (`0–10`), cells with `reasoning-score-best` class on best-per-criterion; `<tfoot>` rows `Average` and `Rank`; sections `Findings`, `Limitations`, `Methodology` (+ source reference line).

- [ ] **Step 1: Write fixture** — hand-build a 2-test payload (the seeded planning test trimmed to 3 entries × 3 criteria + a second tiny test with a different category) so the selector and optgroup logic are testable.
- [ ] **Step 2: Write failing component test** (same harness as `tests/model-benchmark-catalog.test.tsx`: `vi.mock("@/lib/api")`):

```tsx
it("renders the matrix with harness badges, best-cell highlight, averages and rank", async () => {
  render(<ReasoningBenchmarkCatalog />);
  expect(await screen.findByRole("table")).toBeInTheDocument();
  expect(screen.getByText("Claude Opus 4.8")).toBeInTheDocument();
  expect(screen.getAllByText("Claude Code").length).toBeGreaterThan(0);
  const bestCells = document.querySelectorAll("td.reasoning-score-best");
  expect(bestCells.length).toBeGreaterThan(0);
  expect(screen.getByText("Average")).toBeInTheDocument();
  expect(screen.getByText("Rank")).toBeInTheDocument();
});

it("switches tests via the selector", async () => { /* select second test, assert its criterion appears */ });
it("shows the error notice with retry when the request fails", async () => { /* mock reject, click Retry, assert reload */ });
```

- [ ] **Step 3: Run** `npm test -- reasoning-benchmark-catalog` → FAIL (module missing).
- [ ] **Step 4: Implement** lib, component (fetch/loading/error/retry skeleton as `ModelBenchmarkCatalog.tsx:34-73`, `useMemo` for ranking/best maps), page (header copy: eyebrow `Harness-level evidence`, h1 `Reasoning benchmarks`, muted `Hand-scored comparisons of model reasoning across harnesses, one test at a time.`), nav insert, CSS block (matrix: `max-width: 100%; overflow-x: auto`, sticky `thead th` top 0, sticky first column left 0, badge pill, `.reasoning-score-best` accent background, tfoot emphasis).
- [ ] **Step 5: Run** `npm test -- reasoning-benchmark-catalog` → PASS; `npm test -- workspace-nav` → adjust nav test only if it enumerates items exhaustively.

### Task 6: Full suites + live verification

- [ ] **Step 1:** Backend: `pytest` (full) — expect all green (new + existing).
- [ ] **Step 2:** Frontend: `npm test` (full vitest) — all green.
- [ ] **Step 3:** Live: open `http://192.168.1.37:3000`, register `qa-rb-<timestamp>@example.com`, open Reasoning Benchmark nav item, confirm: nav item below Model Benchmarks, matrix 5 columns × 11 rows, Opus leads every best-cell count, averages 9.9/9.3/9.2/4.2/4.0, rank row 1–5, findings/limitations render. Screenshot for the report.
- [ ] **Step 4:** Confirm API contract: `curl -H "Authorization: Bearer <token>" http://192.168.1.37:8000/api/reasoning-benchmarks | jq '.tests[0].entries | length'` → `5`.

## Self-Review

- Spec coverage: types/registry (T1), seed (T2), validation+catalog (T3), router (T4), UI+nav+CSS+tests (T5), verification (T6) — all spec sections mapped; out-of-scope items absent. ✓
- No placeholders; commands and expected outcomes stated. ✓ (Commit steps intentionally omitted — user has not requested git commits; Global Constraints notes this.)
- Type names consistent across tasks (`ReasoningTest`, `TestEntry`, `CriterionScore`, `rankEntries`, `bestValueByCriterion`). ✓
