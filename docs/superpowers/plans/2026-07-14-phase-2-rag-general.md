# Phase 2 RAG and General Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver all eight curated RAG adapters and all seven curated General text/safety adapters through offline datasets and live endpoints, with capability-based dataset/picker UI and adapter-generated configuration.

**Architecture:** Extend the Phase 1 adapter contract instead of adding framework-specific catalog maps. Normalize legacy and canonical RAG mappings into `SingleTurnSample`, validate config twice (submission and worker), and keep one shared scorer per framework. The frontend consumes catalog JSON Schema, requirements, resources, presets, and category/family metadata without hard-coded metric keys.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Ragas 0.4.3, DeepEval 4.1.0, React 19, TypeScript 6, Vitest.

## Global Constraints

- Keep all ten existing adapter keys stable and add exactly five Phase 2 keys.
- Phase 2 registry contains exactly 15 runnable keys: eight RAG and seven General text/safety.
- Do not add Agentic, Conversational/MCP, or Multimodal cards in this phase.
- Keep `contexts` as a legacy alias of `retrieval_contexts`; new mappings expose both `context` and `retrieval_contexts`.
- Support static datasets and endpoint responses through the same `SingleTurnSample` normalizer.
- Keep legacy `response_jsonpath`, `threshold`, and `rubric` requests readable.
- Use the existing resource identifiers `judge`, `embedding`, and `multimodal` for API compatibility; Phase 2 uses only `judge` and `embedding`.
- Adapter metadata remains the only source for category, family, requirements, resources, configuration, and score direction.
- JSON Correctness supports only object schemas composed of properties, required fields, nested objects, arrays, and string/integer/number/boolean values.
- Tests mock upstream scorers; no live paid model calls run in CI.
- A catalog card is visible only after validation, execution, persistence, report, and export paths are runnable.

---

### Task 1: Add strict Phase 2 configuration contracts

**Files:**

- Create: `backend/app/evals/json_schema.py`
- Modify: `backend/app/evals/base.py`
- Modify: `backend/app/evals/registry.py`
- Create: `backend/tests/test_metric_config.py`

**Interfaces:**

- Produces: `model_from_object_schema(schema: dict) -> type[BaseModel]`.
- Produces: `DeepEvalMetricConfig`, `GEvalConfig`, `PromptAlignmentConfig`, and `JsonCorrectnessConfig`.
- Produces: config-dependent `CallableAdapter.requirements(config)`.

- [ ] **Step 1: Write failing schema/config tests**

```python
def test_object_schema_builds_nested_pydantic_model():
    model = model_from_object_schema({
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "items": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["name"],
    })
    assert model.model_validate({"name": "x", "items": [1]}).name == "x"
    with pytest.raises(ValidationError):
        model.model_validate({"items": ["bad"]})


def test_object_schema_rejects_composition_and_unknown_keywords():
    with pytest.raises(ValueError, match="oneOf"):
        model_from_object_schema({"type": "object", "oneOf": []})


def test_metric_specific_config_defaults_and_requirements():
    prompt = METRICS["deepeval.prompt_alignment"]
    assert prompt.default_config()["prompt_instructions"]
    geval = METRICS["deepeval.geval"]
    config = geval.validate_config({"evaluation_fields": ["expected_output"]})
    assert geval.requirements(config) == frozenset({"expected_output"})
```

- [ ] **Step 2: Run RED**

Run: `cd backend && .venv/bin/pytest tests/test_metric_config.py -q`

Expected: imports or the new registry keys fail because the schema converter and config models do not exist.

- [ ] **Step 3: Implement the supported object-schema subset**

`json_schema.py` recursively accepts these exact keywords:

```python
COMMON_KEYS = {"type", "title", "description"}
OBJECT_KEYS = COMMON_KEYS | {"properties", "required"}
ARRAY_KEYS = COMMON_KEYS | {"items"}
PRIMITIVES = {"string": str, "integer": int, "number": float, "boolean": bool}
```

Reject every unrecognized keyword with its dotted path. Build nested models with `create_model`, `ConfigDict(extra="forbid")`, required fields using `...`, and optional fields using `annotation | None` with a `None` default.

- [ ] **Step 4: Add exact configuration models**

```python
class DeepEvalMetricConfig(MetricConfig):
    threshold: float = Field(default=0.5, ge=0, le=1)
    include_reason: bool = True
    strict_mode: bool = False


class GEvalConfig(MetricConfig):
    threshold: float = Field(default=0.5, ge=0, le=1)
    strict_mode: bool = False
    rubric: str = Field(default="Evaluate the quality of the response.", min_length=1, max_length=10_000)
    evaluation_fields: list[Literal["input", "actual_output", "expected_output", "context", "retrieval_contexts"]] = Field(default_factory=lambda: ["input", "actual_output"], min_length=1)


class PromptAlignmentConfig(DeepEvalMetricConfig):
    prompt_instructions: list[str] = Field(default_factory=lambda: ["Follow the instructions in the user input."], min_length=1)


class JsonCorrectnessConfig(DeepEvalMetricConfig):
    strict_mode: bool = True
    expected_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}, "required": []})
```

Validate trimmed, non-empty instruction strings; validate `expected_schema` by calling `model_from_object_schema`.

- [ ] **Step 5: Let the registry declare config and dynamic requirements**

Extend `_adapter()` with explicit `config_model` and `requirement_fn` overrides. G-Eval maps configured fields to canonical dataset requirements, excluding `input` and `actual_output`, which the run contract already requires.

- [ ] **Step 6: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest tests/test_metric_config.py tests/test_metric_contract.py -q`

```bash
git add backend/app/evals/json_schema.py backend/app/evals/base.py backend/app/evals/registry.py backend/tests/test_metric_config.py
git commit -m "feat(metrics): add Phase 2 config contracts"
```

---

### Task 2: Add the five new scorers and complete the 15-card catalog

**Files:**

- Modify: `backend/app/evals/ragas.py`
- Modify: `backend/app/evals/deepeval.py`
- Modify: `backend/app/evals/registry.py`
- Modify: `backend/app/evals/metric_info.py`
- Modify: `backend/tests/test_metric_adapters.py`
- Modify: `backend/tests/test_metric_contract.py`
- Modify: `backend/tests/test_metrics.py`

**Interfaces:**

- Produces: `ragas.context_relevance`.
- Produces: `deepeval.contextual_relevancy`, `deepeval.prompt_alignment`, `deepeval.json_correctness`, and `deepeval.pii_leakage`.
- Produces: exactly 15 Phase 2 catalog entries with complete `MetricInfo`.

- [ ] **Step 1: Write RED registry and field-conversion tests**

```python
PHASE_2_KEYS = {
    "ragas.faithfulness", "ragas.answer_relevancy", "ragas.context_relevance",
    "ragas.context_precision", "ragas.context_recall",
    "deepeval.answer_relevancy", "deepeval.faithfulness",
    "deepeval.contextual_relevancy", "deepeval.geval",
    "deepeval.hallucination", "deepeval.prompt_alignment",
    "deepeval.json_correctness", "deepeval.toxicity",
    "deepeval.pii_leakage", "deepeval.bias",
}
assert set(METRICS) == PHASE_2_KEYS
```

Mock `_make_metric` and prove Ragas Context Relevance receives `user_input` plus `retrieved_contexts`. Mock DeepEval constructors and prove Prompt Alignment receives `prompt_instructions`, JSON Correctness receives a generated Pydantic model, and all new metrics receive a `LLMTestCase` with canonical context fields.

- [ ] **Step 2: Run RED**

Run: `cd backend && .venv/bin/pytest tests/test_metric_adapters.py tests/test_metrics.py -q`

Expected: missing keys and missing `MetricInfo` entries fail.

- [ ] **Step 3: Extend the shared Ragas scorer**

Import `ContextRelevance`, instantiate it with the existing Ragas LLM, and score:

```python
"context_relevance": {
    "user_input": row.input,
    "retrieved_contexts": row.retrieval_contexts,
}
```

- [ ] **Step 4: Extend the shared DeepEval scorer**

Add `ContextualRelevancyMetric`, `PromptAlignmentMetric`, `JsonCorrectnessMetric`, and `PIILeakageMetric`. Pass `include_reason` and `strict_mode` only to constructors that accept them. Map G-Eval `evaluation_fields` to `SingleTurnParams`. Build JSON Correctness `expected_schema` with `model_from_object_schema`.

- [ ] **Step 5: Register exact metadata**

```text
ragas.context_relevance          rag / retrieval / retrieval_contexts
deepeval.contextual_relevancy   rag / retrieval / retrieval_contexts
deepeval.prompt_alignment       general / text_safety
deepeval.json_correctness       general / text_safety
deepeval.pii_leakage            general / text_safety
```

Only Ragas Answer Relevancy declares `embedding`; all 15 declare `judge`.

- [ ] **Step 6: Add complete metric information**

Each of the five entries supplies meaning, direction, two-to-four calculation steps, formula, exactly two examples, improvement tips, and required data. Directions are higher-is-better except PII Leakage, which is lower-is-better.

- [ ] **Step 7: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest tests/test_metric_adapters.py tests/test_metric_contract.py tests/test_metrics.py -q`

```bash
git add backend/app/evals/ragas.py backend/app/evals/deepeval.py backend/app/evals/registry.py backend/app/evals/metric_info.py backend/tests/test_metric_adapters.py backend/tests/test_metric_contract.py backend/tests/test_metrics.py
git commit -m "feat(metrics): add curated RAG and General metrics"
```

---

### Task 3: Normalize canonical RAG mappings and named endpoint responses

**Files:**

- Modify: `backend/app/routers/datasets.py`
- Modify: `backend/app/endpoints.py`
- Modify: `backend/app/routers/runs.py`
- Modify: `backend/app/evals/snapshots.py`
- Modify: `backend/app/tasks.py`
- Modify: `backend/tests/test_datasets.py`
- Modify: `backend/tests/test_endpoints.py`
- Modify: `backend/tests/test_runs.py`
- Modify: `backend/tests/test_worker.py`
- Modify: `backend/tests/test_worker_endpoint.py`

**Interfaces:**

- Produces: schema keys `context` and `retrieval_contexts`, with `contexts` retained as an alias.
- Produces: `EndpointConfig.response_mappings` for `actual_output`, `context`, and `retrieval_contexts`.
- Produces: `extract_response_fields(payload, config) -> dict[str, Any]`.

- [ ] **Step 1: Write RED mapping tests**

Prove dataset schema-map accepts `context` and `retrieval_contexts`, rejects unknown keys, and still accepts `contexts`. Prove `_eval_row()` creates distinct trusted and retrieval context lists while a legacy `contexts` mapping still fills retrieval contexts.

- [ ] **Step 2: Write RED endpoint tests**

```python
config = EndpointConfig(
    url="https://example.test/chat",
    response_mappings={
        "actual_output": "$.answer",
        "context": "$.facts",
        "retrieval_contexts": "$.documents",
    },
)
assert extract_response_fields(payload, config.model_dump()) == {
    "actual_output": "answer",
    "context": ["fact"],
    "retrieval_contexts": ["doc"],
}
```

Also prove legacy `response_jsonpath` becomes the `actual_output` mapping and conflicting/unknown named mappings return `422`.

- [ ] **Step 3: Run RED**

Run: `cd backend && .venv/bin/pytest tests/test_datasets.py tests/test_endpoints.py tests/test_worker_endpoint.py -q`

- [ ] **Step 4: Add canonical mapping normalization**

Allow `input`, `actual_output`, `expected_output`, `context`, `retrieval_contexts`, and legacy `contexts`. `_eval_row()` reads trusted context separately and resolves retrieval contexts as `retrieval_contexts` first, then `contexts`.

- [ ] **Step 5: Add named endpoint response mappings**

`EndpointConfig` keeps nullable `response_jsonpath` and adds `response_mappings`. Its validator requires an actual-output path from one form, rejects keys outside the three Phase 2 fields, validates every JSONPath, and rejects different legacy/named actual-output paths.

- [ ] **Step 6: Use named fields in run preflight and worker execution**

For endpoint runs, adapter requirements may be satisfied by dataset mappings or response mappings. After the endpoint call, normalize returned actual output, trusted context, and retrieval contexts into a new `SingleTurnSample`; persist trusted context under `RunResult.details.sample.context` so recovery reconstructs the same sample.

- [ ] **Step 7: Snapshot safe response mappings**

Store method plus named JSONPaths, never headers or response payload secrets, in `definition_snapshot.endpoint`.

- [ ] **Step 8: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest tests/test_datasets.py tests/test_endpoints.py tests/test_runs.py tests/test_worker.py tests/test_worker_endpoint.py -q`

```bash
git add backend/app/routers/datasets.py backend/app/endpoints.py backend/app/routers/runs.py backend/app/evals/snapshots.py backend/app/tasks.py backend/tests/test_datasets.py backend/tests/test_endpoints.py backend/tests/test_runs.py backend/tests/test_worker.py backend/tests/test_worker_endpoint.py
git commit -m "feat(evals): normalize RAG endpoint mappings"
```

---

### Task 4: Revalidate worker config and publish recommended presets

**Files:**

- Create: `backend/app/evals/presets.py`
- Modify: `backend/app/routers/metrics.py`
- Modify: `backend/app/tasks.py`
- Modify: `backend/tests/test_metrics.py`
- Modify: `backend/tests/test_worker.py`

**Interfaces:**

- Produces: `GET /api/metrics/presets`.
- Produces: `validated_metric_configs(run) -> list[dict]` with legacy-null compatibility.

- [ ] **Step 1: Write RED preset and worker-validation tests**

```python
assert presets["rag_live"]["metric_keys"] == [
    "deepeval.answer_relevancy",
    "deepeval.faithfulness",
    "deepeval.contextual_relevancy",
]
assert presets["rag_offline_references"]["metric_keys"] == [
    "deepeval.answer_relevancy",
    "deepeval.faithfulness",
    "deepeval.contextual_relevancy",
    "ragas.context_precision",
    "ragas.context_recall",
]
```

Prove worker defaults are reapplied, unknown immutable config fails before a paid call, and legacy `None` values are treated as omitted.

- [ ] **Step 2: Run RED**

Run: `cd backend && .venv/bin/pytest tests/test_metrics.py tests/test_worker.py -q`

- [ ] **Step 3: Add the two approved RAG presets**

Return id, display name, description, category, mode hint, and ordered metric keys. Validate at import that every key exists and no preset selects duplicate framework implementations of one concept.

- [ ] **Step 4: Revalidate immutable worker config**

Strip `key` and legacy null values, call `adapter.validate_config`, and pass the normalized flat config to the scorer. Existing completed scores are never replayed.

- [ ] **Step 5: Run GREEN and commit**

Run: `cd backend && .venv/bin/pytest tests/test_metrics.py tests/test_worker.py tests/test_worker_endpoint.py -q`

```bash
git add backend/app/evals/presets.py backend/app/routers/metrics.py backend/app/tasks.py backend/tests/test_metrics.py backend/tests/test_worker.py
git commit -m "feat(metrics): add RAG presets and revalidation"
```

---

### Task 5: Upgrade the dataset page for capability navigation

**Files:**

- Modify: `frontend/components/DatasetUpload.tsx`
- Modify: `frontend/app/w/[workspace]/datasets/page.tsx`
- Modify: `frontend/app/globals.css`
- Modify: `frontend/tests/column-mapper.test.tsx`
- Create: `frontend/tests/datasets-page.test.tsx`

**Interfaces:**

- Produces: compact Common/RAG mapping group.
- Produces: dataset tabs `All`, `RAG`, `Agentic`, and `General` inferred only from schema mappings.
- Produces: upgraded rows with capability badges and compatible metric count.

- [ ] **Step 1: Write RED mapper and page tests**

Assert the mapper displays Input, Actual output, Expected output, Retrieval contexts, and Trusted context under `Common / RAG`, while a legacy `contexts` mapping remains selected. Assert dataset tab selection filters rows without losing data and rows show capability badges plus compatible count.

- [ ] **Step 2: Run RED**

Run: `cd frontend && npm test -- --run tests/column-mapper.test.tsx tests/datasets-page.test.tsx`

- [ ] **Step 3: Implement capability inference**

Use pure helpers:

```typescript
datasetCapabilities(dataset): ("rag" | "agentic" | "general")[]
compatibleMetricCount(dataset, metrics): number
```

RAG requires a retrieval mapping (`retrieval_contexts` or `contexts`); General requires input plus actual output; Agentic remains empty in Phase 2 because no Agentic mapping fields are exposed yet.

- [ ] **Step 4: Keep mapping vertically compact**

Render one Common/RAG group using the existing responsive grid. Do not add Phase 3 mapping controls.

- [ ] **Step 5: Run GREEN and commit**

Run: `cd frontend && npm test -- --run tests/column-mapper.test.tsx tests/datasets-page.test.tsx`

```bash
git add frontend/components/DatasetUpload.tsx frontend/app/w/[workspace]/datasets/page.tsx frontend/app/globals.css frontend/tests/column-mapper.test.tsx frontend/tests/datasets-page.test.tsx
git commit -m "feat(datasets): add capability tabs and RAG mappings"
```

---

### Task 6: Build the capability metric picker and generated config form

**Files:**

- Create: `frontend/components/MetricConfigForm.tsx`
- Modify: `frontend/components/RunWizard.tsx`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/app/globals.css`
- Modify: `frontend/tests/run-wizard.test.tsx`
- Create: `frontend/tests/metric-config-form.test.tsx`

**Interfaces:**

- Produces: tabs `RAG`, `Agentic`, `General`, family filters, framework groups, and search.
- Produces: `MetricConfigForm` for booleans, numbers, strings, enum lists, string lists, and object JSON.
- Consumes: `GET /api/metrics/presets` and adapter `config_schema/default_config`.

- [ ] **Step 1: Write RED picker tests**

Assert category tabs and family filters show the correct cards, search matches display name/key/description, framework groups remain inside each family, disabled cards show exact missing fields, and selections persist across filters.

- [ ] **Step 2: Write RED preset and endpoint mapping tests**

Assert RAG Live selects exactly its three DeepEval keys, never selects framework duplicates, and is disabled when required mappings are absent. In endpoint mode, configuring a retrieval-context JSONPath makes retrieval metrics compatible.

- [ ] **Step 3: Write RED generated-form tests**

Assert threshold renders as a number, booleans as checkboxes, G-Eval fields as a multi-select, prompt instructions as newline-separated text, and JSON Correctness schema as Advanced JSON. Invalid JSON stays client-side and prevents launch.

- [ ] **Step 4: Run RED**

Run: `cd frontend && npm test -- --run tests/run-wizard.test.tsx tests/metric-config-form.test.tsx`

- [ ] **Step 5: Implement the picker without a parallel catalog map**

Filter and group the fetched `Metric[]`; derive labels only from category/family/framework fields. Agentic shows an empty Phase 2 state, not placeholder cards. Preserve the selected-key array when tabs, filters, or search change.

- [ ] **Step 6: Implement generated configuration**

Initialize config from `metric.default_config` at selection. Render schema properties directly; object fields use a JSON textarea labeled Advanced JSON. Submit:

```typescript
metrics: selected.map((key) => ({key, config: metricConfig[key]}))
```

- [ ] **Step 7: Add named endpoint response controls**

Render required Actual output JSONPath and optional Trusted context and Retrieval contexts JSONPaths. Send them under `endpoint_config.response_mappings` while omitting legacy `response_jsonpath` for new runs.

- [ ] **Step 8: Run GREEN, build, and commit**

Run:

```bash
cd frontend
npm test -- --run tests/run-wizard.test.tsx tests/metric-config-form.test.tsx tests/metric-info-modal.test.tsx
npm run build
```

```bash
git add frontend/components/MetricConfigForm.tsx frontend/components/RunWizard.tsx frontend/lib/types.ts frontend/app/globals.css frontend/tests/run-wizard.test.tsx frontend/tests/metric-config-form.test.tsx
git commit -m "feat(metrics): add capability picker and config forms"
```

---

### Task 7: Surface General metric and result details consistently

**Files:**

- Modify: `frontend/components/MetricInfoModal.tsx`
- Modify: `frontend/components/RunReport.tsx`
- Modify: `backend/app/templates/report.html`
- Modify: `frontend/tests/metric-info-modal.test.tsx`
- Modify: `frontend/tests/run-report.test.tsx`
- Modify: `backend/tests/test_exports.py`

**Interfaces:**

- Produces: category-neutral improvement copy.
- Produces: trusted-context/sample details, usage, and estimated cost drill-down in web and HTML reports.

- [ ] **Step 1: Write RED report tests**

Assert RAG uses `How to improve your RAG`, General uses `How to improve`, and a result with `details`, `usage`, or `estimated_cost` exposes a row drill-down in both React and self-contained HTML.

- [ ] **Step 2: Run RED**

Run: `cd frontend && npm test -- --run tests/metric-info-modal.test.tsx tests/run-report.test.tsx`

- [ ] **Step 3: Implement minimal conditional copy and drill-down**

Use `metric.category` for the heading. Render optional result metadata only when non-null; keep current contexts and metric-reason displays unchanged.

- [ ] **Step 4: Run GREEN and commit**

Run:

```bash
cd frontend && npm test -- --run tests/metric-info-modal.test.tsx tests/run-report.test.tsx
cd ../backend && .venv/bin/pytest tests/test_exports.py -q
```

```bash
git add frontend/components/MetricInfoModal.tsx frontend/components/RunReport.tsx backend/app/templates/report.html frontend/tests/metric-info-modal.test.tsx frontend/tests/run-report.test.tsx backend/tests/test_exports.py
git commit -m "feat(reports): show Phase 2 result details"
```

---

### Task 8: Full Phase 2 verification and closeout

**Files:**

- Verify: all Phase 2 files
- Modify only if verification proves a mismatch: `docs/superpowers/specs/2026-07-14-curated-ragas-deepeval-metric-support-design.md`

- [ ] **Step 1: Run backend quality and full tests**

```bash
ruff check backend/app backend/tests backend/alembic/versions
cd backend && .venv/bin/pytest -q -p no:deepeval tests
```

Expected: Ruff clean and every backend test passes.

- [ ] **Step 2: Run frontend full tests and build**

```bash
cd frontend
npm test -- --run
npm run build
```

Expected: every Vitest test and the Next.js production build pass.

- [ ] **Step 3: Verify exact scope and compatibility**

```bash
git diff --check codex/phase-1-metric-contract...HEAD
git status --short
```

Confirm:

- exactly 15 Phase 2 keys exist;
- the five new keys have runnable scorer tests;
- no Agentic, Conversational/MCP, or Multimodal card was added;
- legacy contexts, response JSONPath, threshold, rubric, old results, and old snapshots remain readable;
- static and named-response endpoint runs share `SingleTurnSample`;
- frontend contains no metric-key category/resource/config map;
- no provider or endpoint secret appears in snapshots or exports.

- [ ] **Step 4: Commit any verification-only correction**

Use a focused Conventional Commit only when Step 1–3 proves a mismatch. Leave the branch clean.
