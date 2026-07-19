# Reasoning Benchmarks — Design

**Date:** 2026-07-18 · **Status:** Approved by user (chat, 2026-07-18)

## Purpose

A new workspace area, "Reasoning Benchmark", below Model Benchmarks in the sidebar. It hosts a growing collection of hand-curated evaluations ("tests") that compare AI model capability across different harness layers (Claude Code, Codex CLI, raw API, …). The owner updates tests over time by editing Python catalog files; the app serves and renders them.

First seeded test: the 2026-07-18 test-planning comparison — 5 models × 11 reasoning criteria, sourced from `DANH-GIA-CHI-TIET-REASONING.md` (external analysis).

## Decisions (user-approved)

1. **Storage: static Python catalog** mirroring the existing `app/model_benchmarks` pattern (typed, frozen pydantic records, validation at import). Not JSON files, not DB. Dev-mode bind mounts + `--reload` make edits live without rebuilds.
2. **Seed the first test** with the 5-model planning comparison.
3. **Structure for many tests** (approved in chat):
   - One Python module per test under `app/reasoning_benchmarks/tests/`; `catalog.py` only assembles.
   - Three data tiers: shared registries (harnesses, models) in `registry.py`; per-test `ReasoningTest` with its own criteria; per-test `TestEntry` = model × harness with scores.
   - `category` on each test for future grouping; optional `series_id` to link re-runs of the same protocol over time (no trend UI yet — YAGNI).

## Backend

Package `backend/app/reasoning_benchmarks/`:

- `types.py` — frozen pydantic models (`extra="forbid"`), mirroring `model_benchmarks/types.py` style:
  - `HarnessRecord(id, display_name, description)`
  - `ReasoningModelRecord(id, display_name, developer)`
  - `CriterionDefinition(id, display_name, description, minimum, maximum, direction)` — direction reuses higher/lower-is-better semantics; scales are per-criterion so future tests can use %, pass-rates, or 0–5.
  - `CriterionScore(criterion_id, value, evidence: str | None)`
  - `TestEntry(model_id, harness_id, summary, scores)`
  - `ReasoningTest(id, display_name, category, series_id | None, conducted_at, task_summary, methodology, source_reference, criteria, entries, findings, limitations)`
  - `ReasoningBenchmarkCatalog(catalog_version, last_updated_at, harnesses, models, tests)`
- `registry.py` — `HARNESSES`, `MODELS` tuples shared by all tests.
- `tests/t2026_07_test_planning.py` — exports `TEST: ReasoningTest` (the seeded comparison; 5 entries × 11 criteria = 55 scores).
- `catalog.py` — module docstring documenting the 3-step "add a test" workflow; assembles `CATALOG` from registry + test modules; calls `validate_catalog(CATALOG)` at import (fail-fast like model benchmarks).
- `validation.py` — raises `ValueError` listing every violation: duplicate ids; entry referencing unknown model/harness; unknown criterion in a score; missing or duplicate (entry, criterion) score; value outside [minimum, maximum]; empty tests/criteria/entries; duplicate (model, harness) entry inside one test.
- Router `backend/app/routers/reasoning_benchmarks.py`: `GET /api/reasoning-benchmarks` behind `get_current_user`, `response_model=ReasoningBenchmarkCatalog`; registered in `main.py`.

## Frontend

- `WorkspaceNav.tsx`: add `["Reasoning Benchmark", "reasoning-benchmarks"]` after Model Benchmarks.
- Page `app/w/[workspace]/reasoning-benchmarks/page.tsx`: standard `page-header` (eyebrow "Harness-level evidence", h1 "Reasoning benchmarks") + `<ReasoningBenchmarkCatalog />`.
- `lib/reasoning-benchmarks.ts`: payload types mirroring backend + pure helpers: `entryAverages`, `rankEntries` (average desc, name asc tiebreak), `bestValueByCriterion` (respects direction), `formatScore`.
- `components/ReasoningBenchmarkCatalog.tsx` (client): fetch once via `api()`, loading/error/retry mirroring `ModelBenchmarkCatalog`; test `<select>` (grouped by category via `<optgroup>` when categories > 1); meta line (conducted date, category, catalog version); matrix table — rows = criteria (name + scale hint), columns = entries (model name + harness badge), best cell per row highlighted, footer rows for average and rank; sections below the table: Findings, Limitations, Methodology + source reference.
- CSS: `.reasoning-benchmark-*` block in `globals.css`; matrix follows the model-benchmark matrix constraints (horizontal scroll inside the table wrapper, sticky header and first column).
- Tests: `tests/reasoning-benchmark-fixture.ts` + `tests/reasoning-benchmark-catalog.test.tsx` (loading → render, matrix content, leader highlight, average/rank, error + retry), same `vi.mock("@/lib/api")` pattern as the model benchmark tests.

## Seeded data (test 1)

- Harnesses: `claude-code` (Claude Code), `codex-cli` (Codex CLI).
- Models: `claude-opus-4-8`, `claude-fable-5`, `qwen-27b`, `qwen-35b-a3b`, `codex-5-6-sol`.
- Criteria (0–10, higher is better): goal understanding, active investigation, factual accuracy, self-consistency, oracle design, risk & causal reasoning, constraint-aware planning, safety reasoning, orchestration design, epistemic honesty, instructional clarity.
- Scores exactly as published in the analysis report (averages 9.9 / 9.3 / 9.2 / 4.2 / 4.0).
- Findings (4) and limitations (4) copied from the report's conclusions; catalog content in English to match the product UI.

## Error handling

- Catalog mistakes fail at import with a message naming the offending test/entry/criterion — the API process refuses to start, which is the intended editing feedback loop (same contract as model benchmarks).
- Frontend: request failure renders the standard `notice error` with Retry; empty catalog is prevented by validation.

## Testing

- Backend: `test_reasoning_benchmark_validation.py` (valid catalog passes; each violation class raises with a naming message), `test_reasoning_benchmarks_api.py` (401 unauthenticated; 200 shape + seeded counts: 2 harnesses, 5 models, 1 test, 11 criteria, 5 entries, 55 scores).
- Frontend: component test as above; no changes to existing tests except the nav test if it asserts the item list (`workspace-nav.test.tsx` — extend, don't break).

## Out of scope (deliberate)

- Cross-test "By model" view, trend charts over `series_id`, DB storage, upload UI, workspace-scoped catalogs.
