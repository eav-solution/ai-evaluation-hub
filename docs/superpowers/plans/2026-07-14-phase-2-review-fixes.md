# Phase 2 Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the Phase 2 endpoint, schema, compatibility, reporting, telemetry, and UI inconsistencies found in post-implementation review.

**Architecture:** Keep adapters authoritative for requirements and aliases, and expose the same declarative metadata to the frontend. Normalize and validate at shared boundaries, preserve only documented legacy behavior, and collect provider telemetry without inventing cost for unsupported models.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy, Ragas 0.4.3, DeepEval 4.1.0, Next.js, React, TypeScript, pytest, Vitest.

## Global Constraints

- Keep exactly 15 Phase 2 metric keys.
- `contexts` aliases `retrieval_contexts`; only Hallucination may use it as a legacy trusted-context fallback.
- Unknown current metric configuration remains invalid; only the known legacy non-G-Eval `rubric` field is ignored.
- JSON Schema validation returns a controlled validation error, never a server error.
- Usage and cost are additive per row; cost remains `null` when the pinned provider catalog cannot price the selected model.
- Every production change follows RED, GREEN, then focused regression verification.

---

### Task 1: Preserve all endpoint context matches

**Files:**
- Modify: `backend/app/endpoints.py`
- Test: `backend/tests/test_endpoints.py`

**Interfaces:**
- Consumes: `extract_response_fields(payload: object, config: dict)`.
- Produces: list-valued `context` and `retrieval_contexts` for wildcard JSONPath matches while keeping first-match behavior for `actual_output`.

- [x] **Step 1: Write failing wildcard tests**

Add tests proving `$.documents[*].text` returns both strings for retrieval contexts and `$.answers[*]` keeps the first answer for actual output.

- [x] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/pytest -q -p no:deepeval tests/test_endpoints.py`

Expected: the context wildcard test receives only the first match.

- [x] **Step 3: Implement field-aware extraction**

Use all match values for `context` and `retrieval_contexts`; use the first match for `actual_output`. Preserve a directly matched list as-is.

- [x] **Step 4: Run the endpoint tests and verify GREEN**

Run: `.venv/bin/pytest -q -p no:deepeval tests/test_endpoints.py`

Expected: all endpoint tests pass.

### Task 2: Bound and harden generated JSON Schema models

**Files:**
- Modify: `backend/app/evals/json_schema.py`
- Test: `backend/tests/test_metric_config.py`
- Test: `backend/tests/test_runs.py`

**Interfaces:**
- Consumes: `model_from_object_schema(schema: dict, name: str)`.
- Produces: deterministic `ValueError` for reserved names, depth over 20, or more than 1,000 schema nodes.

- [x] **Step 1: Write failing reserved-name and complexity tests**

Cover `model_dump`, `model_config`, `__base__`, a depth-21 schema, and a run request using one reserved name. Assert adapter validation becomes `ValidationError` and the API returns `422`.

- [x] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/pytest -q -p no:deepeval tests/test_metric_config.py tests/test_runs.py`

Expected: raw `NameError`, `TypeError`, swallowed fields, or `RecursionError` exposes the missing boundary checks.

- [x] **Step 3: Implement explicit schema guards**

Reject dunder names, `model_config`, and names present on `BaseModel`. Carry depth and a shared node counter through recursive annotation construction and raise `ValueError` before `create_model` exceeds the limits.

- [x] **Step 4: Run the tests and verify GREEN**

Run: `.venv/bin/pytest -q -p no:deepeval tests/test_metric_config.py tests/test_runs.py`

Expected: all schema/config tests pass and bad requests return `422`.

### Task 3: Make adapter requirements authoritative in backend and UI

**Files:**
- Modify: `backend/app/evals/base.py`
- Modify: `backend/app/evals/registry.py`
- Modify: `backend/app/routers/runs.py`
- Modify: `backend/app/evals/deepeval.py`
- Modify: `frontend/lib/types.ts`
- Create: `frontend/lib/metric-requirements.ts`
- Modify: `frontend/lib/dataset-capabilities.ts`
- Modify: `frontend/components/RunWizard.tsx`
- Test: `backend/tests/test_metric_contract.py`
- Test: `backend/tests/test_metric_adapters.py`
- Test: `backend/tests/test_runs.py`
- Test: `frontend/tests/run-wizard.test.tsx`
- Test: `frontend/tests/datasets-page.test.tsx`

**Interfaces:**
- Produces: catalog `requirement_rule` and `requirement_aliases` metadata.
- Produces: `MetricAdapter.missing_requirements(config, available_fields)`.
- Produces: frontend `metricRequirements()` and `missingMetricRequirements()` helpers.

- [x] **Step 1: Write failing contract and behavior tests**

Prove Hallucination accepts legacy `contexts`, G-Eval configured with `context` does not, DeepEval only applies the retrieval fallback to Hallucination, live G-Eval config disables launch when its selected field is absent, and compatible counts use requirements instead of category.

- [x] **Step 2: Run focused backend and frontend tests and verify RED**

Run backend: `.venv/bin/pytest -q -p no:deepeval tests/test_metric_contract.py tests/test_metric_adapters.py tests/test_runs.py`

Run frontend: `npm test -- run-wizard.test.tsx datasets-page.test.tsx`

Expected: current global alias widening and static UI requirements fail the new assertions.

- [x] **Step 3: Implement declarative requirement metadata**

Replace the opaque G-Eval requirement lambda with a catalog-visible config-field rule. Add Hallucination's `context <- contexts` alias to adapter metadata. Remove global `contexts -> context` widening and use the shared missing-requirement predicate in backend and frontend.

- [x] **Step 4: Run focused tests and verify GREEN**

Run the commands from Step 2.

Expected: all focused requirement tests pass.

### Task 4: Reuse normalized config for scoring and summaries

**Files:**
- Modify: `backend/app/tasks.py`
- Test: `backend/tests/test_worker.py`

**Interfaces:**
- Consumes: `_validated_metric_configs(run)` once per claimed run.
- Produces: `_summarize(db, run, results, metric_configs)` using the same normalized thresholds used by scorers.

- [x] **Step 1: Write failing summary and legacy-rubric tests**

Prove stored `threshold: null` produces summary threshold `0.5`, a legacy non-G-Eval rubric is ignored, and a truly unknown config key still fails before a paid call.

- [x] **Step 2: Run the worker tests and verify RED**

Run: `.venv/bin/pytest -q -p no:deepeval tests/test_worker.py`

Expected: summary threshold remains `None` and legacy rubric validation fails.

- [x] **Step 3: Implement targeted compatibility and summary reuse**

Strip only `key`, null values, and legacy `rubric` when the selected adapter config model does not define it. Pass the already validated list into `_summarize`.

- [x] **Step 4: Run worker tests and verify GREEN**

Run the command from Step 2.

Expected: all worker tests pass.

### Task 5: Persist meaningful result metadata and provider telemetry

**Files:**
- Modify: `backend/app/evals/base.py`
- Modify: `backend/app/evals/judges.py`
- Modify: `backend/app/evals/deepeval.py`
- Modify: `backend/app/evals/ragas.py`
- Modify: `backend/app/tasks.py`
- Test: `backend/tests/test_metric_adapters.py`
- Test: `backend/tests/test_openai_compatible.py`
- Test: `backend/tests/test_worker.py`

**Interfaces:**
- Produces: `UsageTracker.record_response()`, `usage_snapshot(model)`.
- Produces: optional `MetricScore.usage` and `MetricScore.estimated_cost`.
- Produces: row-level additive usage and cost persistence.

- [x] **Step 1: Write failing telemetry and empty-details tests**

Prove OpenAI-style and Anthropic-style usage are counted, known direct-provider prices produce estimated cost, unsupported/custom pricing stays `None`, multiple metric results add usage/cost, and a row without trusted context stores `details=None`.

- [x] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest -q -p no:deepeval tests/test_metric_adapters.py tests/test_openai_compatible.py tests/test_worker.py`

Expected: no current scorer telemetry reaches `RunResult`, and details is always non-null.

- [x] **Step 3: Implement minimal telemetry collection**

Attach one tracker to each DeepEval and Ragas judge wrapper. Read standard response usage fields, price only official direct-provider models known to the pinned DeepEval catalog, expose telemetry through `MetricScore`, and add it to the row during the same terminal score write. Store trusted-context details only when context exists.

- [x] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2.

Expected: all telemetry and worker tests pass.

### Task 6: Canonicalize Ragas retrieval access and close out

**Files:**
- Modify: `backend/app/evals/ragas.py`
- Verify: all Phase 2 files

**Interfaces:**
- Produces: one canonical `row.retrieval_contexts` access path for every Ragas retrieval metric.

- [x] **Step 1: Replace legacy property reads**

Use `row.retrieval_contexts` for Faithfulness, Context Precision, and Context Recall.

- [x] **Step 2: Run complete backend verification**

Run: `.venv/bin/pytest -q -p no:deepeval tests && ruff check app tests`

Expected: all backend tests pass and Ruff reports no findings.

- [x] **Step 3: Run complete frontend verification**

Run: `npm test && npx tsc --noEmit && npm run build`

Expected: all frontend tests, TypeScript validation, and production build pass.

- [x] **Step 4: Inspect the final diff**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only the reviewed fix scope is modified.
