# Phase 1 Metric Core Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade DeepEval to 4.1.0 and add the typed sample, adapter metadata/configuration, reproducible snapshot, and additive result contracts required before adding curated metrics.

**Architecture:** Keep the ten existing adapter keys and execution paths, but make each adapter the authoritative source for category, family, sample kind, configuration schema, dynamic data requirements, and provider resources. Normalize current rows into a Pydantic `single_turn` sample while defining the four-kind discriminated union used by later phases. Extend run snapshots and result rows additively so old runs remain readable.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, PostgreSQL JSONB, Alembic, Ragas 0.4.3, DeepEval 4.1.0, React 19, TypeScript 6, Vitest.

## Global Constraints

- Keep `ragas==0.4.3` and pin `deepeval==4.1.0`.
- Keep exactly the ten current adapter keys; Phase 1 adds no metric card or scorer.
- Keep current static and endpoint request shapes. Accept new nested `config`, but preserve legacy top-level `threshold` and `rubric`.
- Adapter metadata is authoritative. Frontend must not keep a separate embedding-metric key set.
- Use four sample kinds only: `single_turn`, `agent_trace`, `conversation`, and `multimodal`.
- MCP data belongs to `agent_trace` or `conversation`; do not create an MCP sample kind.
- Store raw scalar scores and reject non-finite or out-of-range values.
- New `details`, `usage`, and `estimated_cost` result fields are nullable and additive; old rows return `null`.
- Snapshot configuration contains no API keys, decrypted headers, or other provider secrets.
- Existing runs without expanded snapshot fields continue to use the Phase 0 fallback behavior.
- Use TDD for every production behavior.

---

### Task 1: Pin and verify supported upstream contracts

**Files:**

- Modify: `backend/requirements.txt`
- Modify: `backend/tests/test_documents_api.py`
- Create: `backend/tests/test_metric_upstream_contract.py`

**Interfaces:**

- Produces: installed versions `ragas==0.4.3`, `deepeval==4.1.0`.
- Produces: an executable compatibility check for every upstream class named by the curated design.

- [ ] **Step 1: Write the failing dependency test**

```python
from importlib.metadata import version
from pathlib import Path


def test_metric_dependencies_are_pinned_to_supported_versions():
    requirements = (
        Path(__file__).parents[1] / "requirements.txt"
    ).read_text(encoding="utf-8")
    assert "ragas==0.4.3" in requirements
    assert "deepeval==4.1.0" in requirements
    assert version("ragas") == "0.4.3"
    assert version("deepeval") == "4.1.0"
```

- [ ] **Step 2: Add the upstream import test**

```python
def test_curated_upstream_metric_classes_are_importable():
    from deepeval import metrics as deepeval_metrics
    from ragas.metrics import collections as ragas_metrics

    ragas_names = {
        "Faithfulness",
        "AnswerRelevancy",
        "ContextRelevance",
        "ContextPrecisionWithReference",
        "ContextRecall",
    }
    deepeval_names = {
        "AnswerRelevancyMetric",
        "FaithfulnessMetric",
        "ContextualRelevancyMetric",
        "TaskCompletionMetric",
        "AgentLoopDetectionMetric",
        "ToolCorrectnessMetric",
        "MCPTaskCompletionMetric",
        "MCPUseMetric",
        "GEval",
        "HallucinationMetric",
        "PromptAlignmentMetric",
        "JsonCorrectnessMetric",
        "ToxicityMetric",
        "PIILeakageMetric",
        "BiasMetric",
        "ConversationCompletenessMetric",
        "TurnRelevancyMetric",
        "RoleAdherenceMetric",
        "ImageCoherenceMetric",
        "ImageHelpfulnessMetric",
    }
    assert all(getattr(ragas_metrics, name, None) for name in ragas_names)
    assert all(getattr(deepeval_metrics, name, None) for name in deepeval_names)
```

- [ ] **Step 3: Run RED**

Run:

```bash
cd backend && .venv/bin/python -m pytest tests/test_metric_upstream_contract.py -q
```

Expected: dependency pin test fails because `requirements.txt` still contains `deepeval==4.0.7`.

- [ ] **Step 4: Update the pin and remove the verified unused import**

Change `deepeval==4.0.7` to `deepeval==4.1.0`. Keep the already verified `GenerationJob` removal in `test_documents_api.py`; no runtime code changes are needed.

- [ ] **Step 5: Sync the worktree environment and run GREEN**

```bash
uv pip install --python backend/.venv/bin/python -r backend/requirements.txt
cd backend && .venv/bin/python -m pytest tests/test_metric_upstream_contract.py tests/test_metric_adapters.py -q
/opt/homebrew/bin/ruff check app tests alembic/versions
```

Expected: all tests and Ruff pass.

- [ ] **Step 6: Commit the dependency slice**

```bash
git add backend/requirements.txt backend/tests/test_documents_api.py backend/tests/test_metric_upstream_contract.py
git commit -m "build(metrics): upgrade DeepEval to 4.1.0"
```

---

### Task 2: Add the four-kind typed sample union

**Files:**

- Create: `backend/app/evals/samples.py`
- Modify: `backend/app/evals/base.py`
- Modify: `backend/app/tasks.py`
- Modify: `backend/app/routers/endpoint_test.py`
- Modify: `backend/tests/test_endpoints.py`
- Modify: `backend/tests/test_metric_adapters.py`
- Modify: `backend/tests/test_metrics.py`
- Create: `backend/tests/test_samples.py`

**Interfaces:**

- Produces: `EvaluationSample`, a Pydantic discriminated union.
- Produces: `SingleTurnSample`, `AgentTraceSample`, `ConversationSample`, `MultimodalSample`.
- Produces: compatibility alias `EvalRow = SingleTurnSample`.
- Produces: `NORMALIZER_REVISION = "1"`.

- [ ] **Step 1: Write RED tests for valid and invalid sample kinds**

```python
import pytest
from pydantic import TypeAdapter, ValidationError

from app.evals.samples import EvaluationSample


adapter = TypeAdapter(EvaluationSample)


def test_typed_sample_union_parses_all_four_kinds():
    samples = [
        {"kind": "single_turn", "input": "q", "actual_output": "a"},
        {
            "kind": "agent_trace",
            "input": "q",
            "actual_output": "a",
            "agent_trace": [{"type": "tool", "name": "search"}],
        },
        {
            "kind": "conversation",
            "turns": [{"role": "user", "content": "hello"}],
            "chatbot_role": "support",
        },
        {
            "kind": "multimodal",
            "input": [{"type": "text", "text": "describe"}],
            "actual_output": [{"type": "image", "asset_id": "asset-1"}],
        },
    ]
    assert [adapter.validate_python(item).kind for item in samples] == [
        "single_turn",
        "agent_trace",
        "conversation",
        "multimodal",
    ]


def test_typed_sample_union_rejects_unknown_kind_and_unresolved_image():
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "mcp"})
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "kind": "multimodal",
                "input": [{"type": "image", "asset_id": ""}],
                "actual_output": [{"type": "text", "text": "answer"}],
            }
        )
```

- [ ] **Step 2: Run RED**

```bash
cd backend && .venv/bin/python -m pytest tests/test_samples.py -q
```

Expected: collection fails because `app.evals.samples` does not exist.

- [ ] **Step 3: Implement the sample models**

Create `samples.py` with strict Pydantic models:

```python
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NORMALIZER_REVISION = "1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SampleSource(StrictModel):
    row_index: int | None = Field(default=None, ge=0)
    event_id: str | None = None
    external_id: str | None = None


class SampleMetadata(StrictModel):
    source: SampleSource | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    normalizer_revision: str = NORMALIZER_REVISION


class ToolCall(StrictModel):
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: str | None = None


class AgentTraceEvent(StrictModel):
    type: str = Field(min_length=1)
    name: str | None = None
    input: Any = None
    output: Any = None
    details: dict[str, Any] = Field(default_factory=dict)


class ConversationTurn(StrictModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MCPEvent(StrictModel):
    type: str = Field(min_length=1)
    name: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TextBlock(StrictModel):
    type: Literal["text"] = "text"
    text: str


class ImageBlock(StrictModel):
    type: Literal["image"] = "image"
    asset_id: str = Field(min_length=1)


ContentBlock = Annotated[TextBlock | ImageBlock, Field(discriminator="type")]


class SingleTurnSample(SampleMetadata):
    kind: Literal["single_turn"] = "single_turn"
    input: str
    actual_output: str
    expected_output: str | None = None
    context: list[str] | None = None
    retrieval_contexts: list[str] | None = None

    @property
    def contexts(self) -> list[str] | None:
        return self.retrieval_contexts


class AgentTraceSample(SampleMetadata):
    kind: Literal["agent_trace"] = "agent_trace"
    input: str
    actual_output: str
    agent_trace: list[AgentTraceEvent]
    tools_called: list[ToolCall] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)


class ConversationSample(SampleMetadata):
    kind: Literal["conversation"] = "conversation"
    turns: list[ConversationTurn] = Field(min_length=1)
    chatbot_role: str = Field(min_length=1)
    conversation_context: list[str] = Field(default_factory=list)
    mcp_metadata: dict[str, Any] = Field(default_factory=dict)
    mcp_events: list[MCPEvent] = Field(default_factory=list)


class MultimodalSample(SampleMetadata):
    kind: Literal["multimodal"] = "multimodal"
    input: list[ContentBlock] = Field(min_length=1)
    actual_output: list[ContentBlock] = Field(min_length=1)
    expected_output: list[ContentBlock] | None = None


EvaluationSample = Annotated[
    SingleTurnSample | AgentTraceSample | ConversationSample | MultimodalSample,
    Field(discriminator="kind"),
]
```

- [ ] **Step 4: Move current execution onto `SingleTurnSample`**

In `base.py`, import `SingleTurnSample` and set `EvalRow = SingleTurnSample`. Update every `EvalRow(...)` construction to keyword arguments and replace `contexts=` with `retrieval_contexts=`. In DeepEval conversion, preserve legacy Hallucination behavior with:

```python
context=row.context or row.retrieval_contexts,
retrieval_context=row.retrieval_contexts,
```

- [ ] **Step 5: Run GREEN and compatibility tests**

```bash
cd backend && .venv/bin/python -m pytest tests/test_samples.py tests/test_endpoints.py tests/test_metric_adapters.py tests/test_worker.py tests/test_worker_endpoint.py -q
```

Expected: all pass and current endpoint/static behavior remains unchanged.

- [ ] **Step 6: Commit typed samples**

```bash
git add backend/app/evals/samples.py backend/app/evals/base.py backend/app/evals/deepeval.py backend/app/tasks.py backend/app/routers/endpoint_test.py backend/tests/test_samples.py backend/tests/test_endpoints.py backend/tests/test_metric_adapters.py backend/tests/test_metrics.py
git commit -m "feat(metrics): add typed sample contract"
```

---

### Task 3: Make adapters own metadata, config, requirements, and resources

**Files:**

- Modify: `backend/app/evals/base.py`
- Modify: `backend/app/evals/registry.py`
- Modify: `backend/app/routers/metrics.py`
- Modify: `backend/tests/test_metrics.py`
- Create: `backend/tests/test_metric_contract.py`

**Interfaces:**

- Produces: `MetricConfig`, `DeepEvalMetricConfig`, `GEvalConfig`.
- Produces: `CallableAdapter.validate_config()`, `.requirements()`, `.resources()`, `.catalog_entry()`.
- Produces: catalog fields `revision`, `category`, `family`, `sample_kind`, `config_schema`, `default_config`, `resources`, and `recommended`.

- [ ] **Step 1: Write RED adapter-contract tests**

```python
import pytest
from pydantic import ValidationError

from app.evals.registry import METRICS


def test_adapter_exposes_generated_config_and_dynamic_resources():
    adapter = METRICS["ragas.answer_relevancy"]
    assert adapter.revision == "1"
    assert adapter.category == "rag"
    assert adapter.family == "generation"
    assert adapter.sample_kind == "single_turn"
    assert adapter.default_config() == {"threshold": None}
    assert adapter.resources(adapter.default_config()) == frozenset(
        {"judge", "embedding"}
    )
    assert adapter.config_schema()["additionalProperties"] is False


def test_adapter_rejects_unknown_or_invalid_config():
    adapter = METRICS["deepeval.geval"]
    with pytest.raises(ValidationError):
        adapter.validate_config({"threshold": 2})
    with pytest.raises(ValidationError):
        adapter.validate_config({"unknown": True})
```

- [ ] **Step 2: Run RED**

```bash
cd backend && .venv/bin/python -m pytest tests/test_metric_contract.py -q
```

Expected: adapter metadata and methods do not exist.

- [ ] **Step 3: Add configuration models and adapter methods**

Use strict Pydantic models in `base.py`:

```python
class MetricConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    threshold: float | None = Field(default=None, ge=0, le=1)


class DeepEvalMetricConfig(MetricConfig):
    threshold: float = Field(default=0.5, ge=0, le=1)


class GEvalConfig(DeepEvalMetricConfig):
    rubric: str = Field(
        default="Evaluate the quality of the response.",
        min_length=1,
        max_length=10_000,
    )
```

Extend `CallableAdapter` with exact metadata fields, a `config_model`, `requirement_fn`, and `resource_fn`. Implement methods using `model_validate`, `model_dump(mode="json")`, and `model_json_schema()`. Keep `.requires` as the default-config compatibility property.

- [ ] **Step 4: Declare metadata with each current registry entry**

Use categories/families:

```text
ragas.faithfulness                 rag / generation
ragas.answer_relevancy             rag / generation
ragas.context_precision            rag / retrieval
ragas.context_recall               rag / retrieval
deepeval.answer_relevancy          rag / generation
deepeval.faithfulness              rag / generation
deepeval.hallucination             general / text_safety
deepeval.toxicity                  general / text_safety
deepeval.bias                      general / text_safety
deepeval.geval                     general / text_safety
```

All use `sample_kind="single_turn"`, revision `"1"`, and resource `judge`; only `ragas.answer_relevancy` also requires `embedding`. Attach `METRIC_INFO[key]` to the adapter so the route no longer joins a second map.

- [ ] **Step 5: Return generated metadata from `/api/metrics`**

Replace the hand-built route object with:

```python
return [adapter.catalog_entry() for adapter in METRICS.values()]
```

Keep `requires` in the response for current clients.

- [ ] **Step 6: Run GREEN**

```bash
cd backend && .venv/bin/python -m pytest tests/test_metric_contract.py tests/test_metrics.py tests/test_runs.py -q
```

- [ ] **Step 7: Commit adapter metadata**

```bash
git add backend/app/evals/base.py backend/app/evals/registry.py backend/app/routers/metrics.py backend/tests/test_metric_contract.py backend/tests/test_metrics.py
git commit -m "feat(metrics): expose adapter metadata"
```

---

### Task 4: Validate configuration and expand reproducible run snapshots

**Files:**

- Create: `backend/app/evals/snapshots.py`
- Modify: `backend/app/routers/runs.py`
- Modify: `backend/app/tasks.py`
- Modify: `backend/tests/test_runs.py`
- Modify: `backend/tests/test_worker.py`

**Interfaces:**

- Consumes: adapter metadata/config contract from Task 3.
- Produces: normalized persisted metric config with defaults applied.
- Produces: `build_definition_snapshot()` with library, adapter, sample, resource, schema, and endpoint metadata.

- [ ] **Step 1: Write RED route tests**

Add tests proving:

```python
response = client.post(
    run_url,
    json={
        **valid_body,
        "metrics": [
            {"key": "deepeval.geval", "config": {"rubric": "Be concise"}}
        ],
    },
    headers=auth_headers,
)
assert response.status_code == 201
stored = db.get(Run, response.json()["id"])
assert stored.metric_config["metrics"] == [
    {"key": "deepeval.geval", "threshold": 0.5, "rubric": "Be concise"}
]
assert stored.definition_snapshot["libraries"] == {
    "ragas": "0.4.3",
    "deepeval": "4.1.0",
}
assert stored.definition_snapshot["metrics"][0]["revision"] == "1"
assert stored.definition_snapshot["sample"] == {
    "kind": "single_turn",
    "normalizer_revision": "1",
}
assert "api_key" not in str(stored.definition_snapshot).lower()
assert "authorization" not in str(stored.definition_snapshot).lower()
```

Also assert unknown config keys return `422`, and legacy `threshold`/`rubric` still work. A nested config value conflicting with its legacy field returns `422`.

- [ ] **Step 2: Run RED**

```bash
cd backend && .venv/bin/python -m pytest tests/test_runs.py -q
```

- [ ] **Step 3: Accept nested and legacy config safely**

Extend `MetricIn` with `config: dict = Field(default_factory=dict)` and a model validator that merges non-null legacy `threshold`/`rubric`. Reject different values supplied in both locations.

At create time, call `adapter.validate_config()`, convert validation failures to `422` with metric key and Pydantic error locations, and persist:

```python
{"key": adapter.key, **validated_config}
```

Use `adapter.requirements(validated_config)` and `adapter.resources(validated_config)` for preflight checks. Remove backend `EMBEDDING_METRICS`.

- [ ] **Step 4: Build the safe snapshot**

`snapshots.py` returns:

```python
{
    "schema_map": dict(dataset.schema_map),
    "libraries": {"ragas": version("ragas"), "deepeval": version("deepeval")},
    "sample": {"kind": "single_turn", "normalizer_revision": NORMALIZER_REVISION},
    "metrics": [
        {"key": adapter.key, "revision": adapter.revision, "config": config}
        for adapter, config in selected
    ],
    "resources": safe_resource_snapshot,
    "endpoint": (
        {
            "method": endpoint_config.method,
            "response_jsonpath": endpoint_config.response_jsonpath,
        }
        if endpoint_config is not None
        else None
    ),
}
```

Resource snapshots contain connection IDs, names, types, and model names only.

- [ ] **Step 5: Keep worker compatibility**

Worker receives normalized flat config for new runs. Existing runs with flat legacy config continue unchanged. No result deletion or replay behavior changes.

- [ ] **Step 6: Run GREEN**

```bash
cd backend && .venv/bin/python -m pytest tests/test_runs.py tests/test_worker.py tests/test_worker_endpoint.py -q
```

- [ ] **Step 7: Commit run configuration and snapshots**

```bash
git add backend/app/evals/snapshots.py backend/app/routers/runs.py backend/app/tasks.py backend/tests/test_runs.py backend/tests/test_worker.py
git commit -m "feat(evals): snapshot metric contracts"
```

---

### Task 5: Add nullable result extensions and compatibility migration

**Files:**

- Create: `backend/alembic/versions/0002_run_result_extensions.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/routers/runs.py`
- Modify: `backend/app/reports.py`
- Modify: `backend/tests/test_models.py`
- Modify: `backend/tests/test_exports.py`
- Modify: `frontend/lib/types.ts`

**Interfaces:**

- Produces: `RunResult.details`, `RunResult.usage`, `RunResult.estimated_cost`.
- Produces: API/export fields with `null` for old rows.

- [ ] **Step 1: Write RED model and serializer tests**

Persist one result with:

```python
details={"trace": [{"type": "tool", "name": "search"}]},
usage={"input_tokens": 12, "output_tokens": 4},
estimated_cost=0.0012,
```

Assert round-trip equality. Persist a second legacy-shaped result without these fields and assert all three are `None`. Assert `/results` and JSON export expose the fields, and CSV serializes JSON using `json.dumps(..., ensure_ascii=False)`.

- [ ] **Step 2: Run RED**

```bash
cd backend && .venv/bin/python -m pytest tests/test_models.py tests/test_exports.py tests/test_runs.py -q
```

- [ ] **Step 3: Add model fields and migration**

Model fields:

```python
details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
```

Migration revision `0002`, down revision `0001`, adds the three nullable columns and drops them in reverse order on downgrade.

- [ ] **Step 4: Extend API and exports**

Add the fields to run-result JSON, report payload, CSV base fields, and frontend `RunResult`. Do not add report widgets in Phase 1.

- [ ] **Step 5: Run GREEN and migration cycle**

```bash
cd backend && .venv/bin/python -m pytest tests/test_models.py tests/test_exports.py tests/test_runs.py -q
.venv/bin/python -m alembic heads
```

Expected: tests pass and Alembic reports `0002 (head)`.

- [ ] **Step 6: Commit result extensions**

```bash
git add backend/alembic/versions/0002_run_result_extensions.py backend/app/models.py backend/app/routers/runs.py backend/app/reports.py backend/tests/test_models.py backend/tests/test_exports.py frontend/lib/types.ts
git commit -m "feat(evals): extend result metadata"
```

---

### Task 6: Make frontend resource selection metadata-driven

**Files:**

- Modify: `frontend/lib/types.ts`
- Modify: `frontend/components/RunWizard.tsx`
- Modify: `frontend/tests/run-wizard.test.tsx`
- Modify: `frontend/tests/run-report.test.tsx`
- Modify: `frontend/tests/metric-info-modal.test.tsx`

**Interfaces:**

- Consumes: catalog metadata from Task 3.
- Produces: frontend `Metric` contract with category/family/config/resources.
- Removes: hard-coded frontend `EMBEDDING_METRICS` key set.

- [ ] **Step 1: Write RED resource-driven wizard test**

Provide a test-only metric with key `test.embedding` and `resources: ["judge", "embedding"]`. Select it and assert the embedding connection/model controls appear. This must fail while the wizard still checks the hard-coded key set.

- [ ] **Step 2: Run RED**

```bash
cd frontend && npm test -- --run tests/run-wizard.test.tsx
```

- [ ] **Step 3: Extend the frontend metric type**

Add required fields:

```typescript
revision: string;
category: "rag" | "agentic" | "general";
family: string;
sample_kind: "single_turn" | "agent_trace" | "conversation" | "multimodal";
config_schema: Record<string, unknown>;
default_config: Record<string, unknown>;
resources: ("judge" | "embedding" | "multimodal")[];
recommended: boolean;
```

Update metric fixtures accordingly.

- [ ] **Step 4: Remove the hard-coded key set**

Compute:

```typescript
const needsEmbedding = selected.some((key) =>
  metrics.find((metric) => metric.key === key)?.resources.includes("embedding"),
);
```

Keep framework grouping unchanged; capability tabs and generated forms belong to Phase 2.

- [ ] **Step 5: Run GREEN and build**

```bash
cd frontend
npm test -- --run tests/run-wizard.test.tsx tests/run-report.test.tsx tests/metric-info-modal.test.tsx
npm run build
```

- [ ] **Step 6: Commit frontend resource metadata**

```bash
git add frontend/lib/types.ts frontend/components/RunWizard.tsx frontend/tests/run-wizard.test.tsx frontend/tests/run-report.test.tsx frontend/tests/metric-info-modal.test.tsx
git commit -m "refactor(metrics): drive resources from catalog"
```

---

### Task 7: Full verification and Phase 1 closeout

**Files:**

- Verify: all Phase 1 files
- Modify only when verification proves a mismatch: `docs/superpowers/specs/2026-07-14-curated-ragas-deepeval-metric-support-design.md`

- [ ] **Step 1: Run backend quality and tests**

```bash
/opt/homebrew/bin/ruff check backend/app backend/tests backend/alembic/versions
cd backend && .venv/bin/python -m pytest -q
```

- [ ] **Step 2: Run frontend tests and production build**

```bash
cd frontend
npm test -- --run
npm run build
```

- [ ] **Step 3: Verify Compose and migration graph**

```bash
docker compose config >/dev/null
cd backend && .venv/bin/python -m alembic heads
```

Expected: Compose exits `0`; Alembic reports exactly `0002 (head)`.

- [ ] **Step 4: Test migration on a disposable database**

Create `evalhub_phase1_migration_test`, then run upgrade `head`, downgrade `0001`, and upgrade `head`. Drop the disposable database afterward. Do not run downgrade against the application database.

- [ ] **Step 5: Confirm scope and clean diff**

```bash
git diff --check
git status --short
git diff main...HEAD --stat
```

Confirm:

- installed versions are exactly Ragas 0.4.3 and DeepEval 4.1.0;
- registry still contains exactly ten keys;
- no Phase 2 metric key or card was added;
- old run results remain readable with nullable extension fields;
- no provider secret appears in a run snapshot.
