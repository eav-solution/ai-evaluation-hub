# Curated Ragas and DeepEval Metric Support — Design

**Date:** 2026-07-14
**Status:** Approved design; awaiting written-spec review

## Supersession and retained decisions

This document supersedes:

- `2026-07-13-full-ragas-deepeval-metric-support-design.md`;
- `2026-07-13-metric-categories-and-dataset-capabilities-design.md`; and
- `../plans/2026-07-13-metric-categories-and-dataset-capabilities.md`.

The previous master design targeted every runnable upstream export. This design
replaces that scope with the metrics most broadly useful to EvalHub users: 22
evaluation concepts represented by 25 framework-specific adapter cards.

The following earlier decisions remain in force:

- primary metric tabs are `RAG`, `Agentic`, and `General`;
- framework groups appear inside family filters;
- the metric grid remains fixed at five columns;
- dataset capabilities are inferred from schema mappings;
- upload and mapping remain inline; and
- both offline and live evaluation are supported.

## Purpose

Upgrade DeepEval from `4.0.7` to `4.1.0` and expand the current ten adapters to
a curated catalog that covers common RAG, agent, general text, conversational,
MCP, and multimodal evaluation needs without exposing the full upstream metric
surface.

Every catalog card must be runnable end to end: discoverable, configurable,
validated, executable, persisted, reported, and exportable for its supported
offline or live input modes. Catalog-only cards are not allowed.

## Goals

- Preserve all ten existing adapter keys and behavior-compatible inputs.
- Add Context Relevancy to the core RAG evaluation set.
- Add the smallest useful Agentic, General, Conversational/MCP, and Multimodal
  sets.
- Use adapter metadata as the source of truth for UI placement, configuration,
  requirements, and provider resources.
- Normalize offline datasets, endpoint responses, and ingested events into four
  typed sample kinds.
- Keep results compatible with the current scalar report model.
- Snapshot inputs and validated configuration for reproducible runs.

## Non-goals

- EvalHub does not expose all Ragas or DeepEval public exports.
- Upstream aliases, helpers, and newly released metrics do not automatically
  become catalog cards.
- Pairwise/Arena, SQL/DataCompy, ranking, BLEU/ROUGE/CHRF, advanced graph/DAG,
  and arbitrary uploaded Python metrics are excluded.
- PDF multimodal evaluation and video/audio evaluation are excluded.
- Image generation/editing quality metrics are excluded; this release evaluates
  images used alongside text.
- Testset generation, prompt optimization, and observability integrations are
  outside this feature.

## Curated catalog

The catalog contains exactly 25 adapter keys representing 22 concepts. Answer
Relevancy, Faithfulness, and Context Relevancy each have both Ragas and DeepEval
implementations.

### RAG — eight adapters

| Family | Adapter key | Upstream metric | Status |
|---|---|---|---|
| Generation | `ragas.faithfulness` | `Faithfulness` | Existing |
| Generation | `ragas.answer_relevancy` | `AnswerRelevancy` | Existing |
| Retrieval | `ragas.context_relevance` | `ContextRelevance` | New |
| Retrieval | `ragas.context_precision` | `ContextPrecisionWithReference` | Existing |
| Retrieval | `ragas.context_recall` | `ContextRecall` | Existing |
| Generation | `deepeval.answer_relevancy` | `AnswerRelevancyMetric` | Existing |
| Generation | `deepeval.faithfulness` | `FaithfulnessMetric` | Existing |
| Retrieval | `deepeval.contextual_relevancy` | `ContextualRelevancyMetric` | New |

Context Precision and Context Recall remain Ragas-only. DeepEval duplicates are
not added unless user demand later establishes a need for framework parity.

### Agentic — five adapters

| Family | Adapter key | Upstream metric | Status |
|---|---|---|---|
| Trace | `deepeval.task_completion` | `TaskCompletionMetric` | New |
| Trace | `deepeval.agent_loop_detection` | `AgentLoopDetectionMetric` | New |
| Tools | `deepeval.tool_correctness` | `ToolCorrectnessMetric` | New |
| MCP | `deepeval.mcp_task_completion` | `MCPTaskCompletionMetric` | New |
| MCP | `deepeval.mcp_use` | `MCPUseMetric` | New |

### General — twelve adapters

| Family | Adapter key | Upstream metric | Status |
|---|---|---|---|
| Text & Safety | `deepeval.geval` | `GEval` | Existing |
| Text & Safety | `deepeval.hallucination` | `HallucinationMetric` | Existing, moved from RAG |
| Text & Safety | `deepeval.prompt_alignment` | `PromptAlignmentMetric` | New |
| Text & Safety | `deepeval.json_correctness` | `JsonCorrectnessMetric` | New |
| Text & Safety | `deepeval.toxicity` | `ToxicityMetric` | Existing |
| Text & Safety | `deepeval.pii_leakage` | `PIILeakageMetric` | New |
| Text & Safety | `deepeval.bias` | `BiasMetric` | Existing |
| Conversational | `deepeval.conversation_completeness` | `ConversationCompletenessMetric` | New |
| Conversational | `deepeval.turn_relevancy` | `TurnRelevancyMetric` | New |
| Conversational | `deepeval.role_adherence` | `RoleAdherenceMetric` | New |
| Multimodal | `deepeval.image_coherence` | `ImageCoherenceMetric` | New |
| Multimodal | `deepeval.image_helpfulness` | `ImageHelpfulnessMetric` | New |

Ragas framework groups appear only under RAG in this release. Empty framework
groups are not rendered.

## Adapter contract

Each adapter declares:

```text
key and adapter revision
framework, category, family, display name, description
accepted sample kind
requirements(config)
resources(config)
Pydantic configuration model
upstream converter and scorer
recommended status
```

`requirements(config)` and `resources(config)` are dynamic. A selected metric
may require extra data or a provider only after a configuration option is
enabled.

`GET /api/metrics` returns this metadata plus configuration JSON Schema and
defaults. The frontend must not maintain separate category, requirement, or
configuration maps.

Shared scorers and converters are preferred. Adapters with the same upstream
test-case shape reuse the same conversion path; no class-per-metric hierarchy
is required.

## Dependency policy

- Pin `ragas==0.4.3`.
- Upgrade and pin `deepeval==4.1.0`.
- Do not compare the registry against every upstream `__all__` export.
- Tests assert that exactly the 25 curated keys are registered and their named
  upstream classes remain importable.
- A future upstream release does not expand scope automatically. New metrics
  require an explicit product decision.

## Typed samples

Use a Pydantic discriminated union with four sample kinds.

| Sample kind | Purpose | Core fields |
|---|---|---|
| `single_turn` | RAG and General text/safety | input, actual_output, expected_output, context, retrieval_contexts |
| `agent_trace` | Agent trace and tool evaluation | input, actual_output, agent_trace, tools_called, expected_tools |
| `conversation` | Conversational and MCP evaluation | turns, chatbot_role, conversation_context, MCP metadata/events |
| `multimodal` | Text plus image evaluation | ordered text/image content blocks with asset references |

MCP uses `agent_trace` or `conversation`; it is not a separate sample type.
There is no Pairwise or SQL sample type in this release.

Every normalized sample also records source row/event, metadata, tags, and
normalizer revision.

## Canonical field semantics

- `input`: user request or source input.
- `actual_output`: response being evaluated.
- `expected_output`: ground-truth answer used by reference-based metrics.
- `retrieval_contexts`: documents returned by a retriever.
- `context`: trusted facts or broader context used by Hallucination.
- `agent_trace`: ordered spans/steps required by trace metrics.
- `tools_called`: observed tool calls.
- `expected_tools`: ground-truth calls required by Tool Correctness.
- `turns`: ordered user/assistant conversation turns.
- `chatbot_role`: declared role required by Role Adherence.
- MCP metadata: available servers and observed tool/resource/prompt events.

Existing `contexts` mappings remain a backward-compatible alias for
`retrieval_contexts`. Hallucination first uses an explicit `context`; existing
datasets and runs may fall back to legacy `contexts` so current behavior does
not break. New mappings keep `context` and `retrieval_contexts` distinct.

## Metric data requirements

| Metric concept | Required data |
|---|---|
| Answer Relevancy | input, actual_output |
| Faithfulness | input, actual_output, retrieval_contexts |
| Context Relevancy | input, retrieval_contexts |
| Context Precision/Recall | input, retrieval_contexts, expected_output |
| G-Eval | fields selected in its criteria/configuration |
| Hallucination | input, actual_output, context or legacy contexts |
| Prompt Alignment | input, actual_output, prompt constraints from config |
| JSON Correctness | input, actual_output, supported object schema from config |
| Toxicity, PII Leakage, Bias | actual_output |
| Task Completion, Agent Loop Detection | agent_trace |
| Tool Correctness | tools_called, expected_tools |
| Conversation Completeness, Turn Relevancy | turns |
| Role Adherence | turns, chatbot_role |
| MCP Task Completion, MCP Use | trace/conversation plus MCP metadata/events |
| Image Coherence, Image Helpfulness | text and at least one image asset |

Adapters remain authoritative when an upstream metric requires a stricter
shape than this summary.

## Dataset library and mapping

The unified dataset page keeps:

```text
All | RAG | Agentic | General
             ↓
       family filters
```

Capabilities are inferred from schema mappings; users do not choose a dataset
type. One dataset may appear under multiple tabs. Each list row shows derived
capabilities and the number of compatible curated metrics instead of claiming
that every metric in a category is ready.

Upload and mapping remain inline and vertically compact. Mapper groups are:

- Common/RAG;
- Agentic;
- Conversational/MCP; and
- Multimodal.

CSV structured values use serialized JSON. JSON and JSONL preserve arrays and
objects. Mapping failures identify the source column and first invalid row
without discarding the uploaded dataset.

Pairwise candidate fields, SQL/Data fields, PDF blocks, and deferred metric
fields are not added.

## Offline and live execution

All input modes use the same normalizer and adapter pipeline:

```text
static dataset | endpoint response | ingestion API
                         ↓
              schema/response mapping
                         ↓
                   typed sample
                         ↓
                  metric adapter
                         ↓
                standardized result
```

### Static dataset

Mapped rows already contain the outputs, traces, conversations, MCP events, or
image references required by selected metrics.

### Endpoint evaluation

Replace the single response path with named response mappings. One response may
populate actual output, context, retrieval contexts, trace, tool calls, turns,
MCP events, or image references.

### Ingestion API

A workspace-authenticated API accepts trace, conversation, MCP, and image event
payloads. Requests require an idempotency key; replaying a key returns the same
accepted artifact/run association instead of duplicating evaluation work.

Live payloads are snapshotted before normalization. Run definitions reference
immutable snapshots so evaluated input can be audited later.

## Multimodal assets

Multimodal inputs accept uploaded images and remote HTTPS image URLs. Remote
images are fetched and snapshotted by the backend before scoring.

Required controls:

- allow-listed image MIME types and bounded size;
- request timeout and bounded redirects;
- DNS and resolved-address checks blocking loopback, link-local, private, and
  other non-public targets;
- workspace-scoped authorization;
- no local filesystem paths; and
- object-storage `asset_id` references instead of relational-table base64.

Only text and image content blocks are supported in this release.

## Metric picker UI

The fixed five-column card grid is organized as:

```text
RAG
  Generation | Retrieval
Agentic
  Trace | Tools | MCP
General
  Text & Safety | Conversational | Multimodal
```

Each family contains framework groups. Cards display framework, required data,
provider resources, recommended/configured status, and exact missing-data
reasons. Search matches name, key, and description. Selections persist while
moving between tabs, filters, and search results.

Incompatible cards remain visible but disabled. Metrics with the same concept
remain separate framework cards and cannot be accidentally treated as one key.

## Recommended presets

Presets are one-click suggestions and are never applied automatically.

- **RAG live:** DeepEval Answer Relevancy, Faithfulness, and Contextual
  Relevancy. This avoids selecting duplicate frameworks and does not require a
  separate embedding resource.
- **RAG offline with references:** the live set plus Ragas Context Precision
  and Context Recall.
- **Agentic:** Task Completion and Agent Loop Detection; add Tool Correctness
  when `expected_tools` exists.
- **Conversational:** Conversation Completeness, Turn Relevancy, and Role
  Adherence.
- **MCP:** MCP Task Completion and MCP Use.
- **Multimodal:** Image Coherence and Image Helpfulness.

Users may replace a recommended RAG implementation with its Ragas equivalent.
The picker does not select two implementations of one concept by default.

## Adapter-generated configuration

Every adapter owns a Pydantic configuration model. The API publishes JSON
Schema and defaults; the Run Wizard renders supported fields for booleans,
numbers, text, enums, lists, JSON Schema values, and simple nested objects.

Common and metric-specific examples include:

- threshold and supported strict/include-reason options;
- G-Eval criteria/rubric and evaluated fields;
- supported object schema for JSON Correctness; and
- prompt constraints for Prompt Alignment.

JSON Correctness accepts the common object-schema subset needed to construct
the Pydantic model required by DeepEval: `type: object`, `properties`,
`required`, nested objects, arrays, and primitive value types. The adapter
rejects unsupported composition or reference keywords with a field-level
message. It does not claim arbitrary JSON Schema compatibility.

Advanced JSON is available only when the same configuration cannot be expressed
compactly by generated controls. Visual and JSON forms pass through the same
Pydantic validation. Backend run creation and the worker revalidate the
immutable configuration snapshot.

## Provider resources

Adapters declare only provider resources they actually consume:

- `judge_llm`;
- `embedding`; and
- `multimodal_judge`.

Trace, conversation, and MCP are input data, not provider resources. Ragas
Answer Relevancy requires the embedding role. Agent Loop Detection is
deterministic and requires no judge. The UI requests only the union of resources
required by selected adapters. A run whose selected adapters do not need a
judge must not require a judge connection.

Native provider connections use known model capabilities. For custom models,
users confirm text or vision capability when it cannot be inferred.

## Reproducible run snapshot

Run creation stores:

- Ragas and DeepEval versions;
- adapter keys and revisions;
- validated configuration and applied defaults;
- sample kind and normalizer revision;
- selected provider/model roles;
- dataset schema and endpoint/ingestion mappings; and
- raw payload and image snapshot references.

Later dataset, mapping, provider, or adapter changes do not rewrite an existing
run definition. Secrets are never copied into snapshots.

## Result model and reports

All curated metrics normalize to a scalar result:

```text
metric key
score in 0..1
reason
passed
error
optional details
latency_ms
optional usage and estimated cost
```

Adapters validate normalized scores and reject non-finite or out-of-range
values. They must not silently clamp invalid upstream results.

Existing report summaries remain: mean, minimum, maximum, p50, and pass rate.
Trace, tool, conversation, MCP, and image details appear in result drill-downs
without introducing label, pairwise, or SQL result kinds. CSV and JSON exports
include optional details as JSON where necessary.

## Validation, errors, and retries

Preflight validation checks configuration, sample compatibility, mappings, and
provider resources before enqueueing a run.

- A normalization error affects only its sample.
- A metric error affects only its sample/metric pair.
- A run fails completely only when no pair produces a successful result.
- Missing trace, expected tools, turns, role, MCP metadata, or image is an
  incompatibility, never an automatic zero score.
- Cancellation is checked between samples and metric groups.
- Ingestion validation returns `422` with a pointer to the first invalid value.

EvalHub does not automatically retry paid judge calls. Existing safe job
redelivery, lease recovery, and outbox processing remain responsible for
lifecycle durability. Idempotency and persisted progress prevent job recovery
from duplicating already completed results.

## Cost controls

Adapter metadata provides a resource/call hint. Before launch, the UI displays
the selected resource mix and warns when the sample count and selected metrics
imply many judge calls. It does not hardcode provider prices.

Usage and estimated cost are recorded when the provider returns sufficient
information. Recommended presets keep each common run focused instead of
selecting all 25 cards.

## Security and lifecycle

- Datasets, artifacts, assets, mappings, runs, and results remain
  workspace-scoped.
- Provider secrets continue through encrypted storage and are not snapshotted.
- Raw payload and image snapshots are immutable and authorization-scoped.
- Remote-image fetching enforces SSRF and size controls before persistence.
- Dataset/run deletion schedules artifact cleanup through the durable outbox.
- Inputs are not silently redacted because mutation changes evaluation results.

## Backward compatibility

- All ten current adapter keys remain stable.
- Existing `contexts` mappings normalize as `retrieval_contexts`.
- Existing Hallucination runs retain their legacy context fallback.
- Existing scalar results and reports remain readable without reprocessing.
- Existing endpoint response paths are interpreted as the `actual_output`
  mapping.
- API and database changes remain additive until current consumers migrate.

## Testing and acceptance

### Dependency and registry

- Assert installed versions are exactly `ragas==0.4.3` and
  `deepeval==4.1.0`.
- Assert the registry contains exactly the 25 adapter keys in this design.
- Import every named upstream class and fail clearly on dependency drift.
- Do not fail merely because upstream adds an unselected metric.

### Adapter and sample contracts

- Validate every adapter's default config, JSON Schema, dynamic requirements,
  provider resources, input conversion, and score validation.
- Mock upstream judge responses; CI makes no live external model calls.
- Test every typed sample normalizer and invalid shape.
- Test the recommended preset keys and framework deduplication.

### Offline, live, and security

- Test CSV structured JSON and native JSON/JSONL mappings.
- Test endpoint multi-field response extraction.
- Test ingestion authentication, idempotency, immutable snapshots, and `422`
  pointers.
- Test image MIME/size limits, redirects, SSRF protection, and authorization.
- Test current `contexts`, endpoint, dataset, run, and result compatibility.

### UI and reporting

- Test three category tabs, family filters, framework groups, search, fixed
  five-column grid, selection persistence, presets, and disabled reasons.
- Test generated forms, G-Eval criteria, object schema, Prompt Alignment, and
  Advanced JSON validation.
- Test object-schema-to-Pydantic conversion and clear rejection of unsupported
  JSON Schema keywords.
- Test resource prompts for judge, embedding, and multimodal roles.
- Test result details, partial failure, cancellation, summaries, and exports.
- Run complete backend, frontend, type, and production build checks.

The feature is complete only when all 25 cards have an end-to-end passing path
from a supported offline or live source to persisted report output.

## Implementation decomposition

Write and execute five phase-specific plans in order:

1. **Core contract and dependency upgrade** — DeepEval 4.1.0, adapter metadata,
   generated config schema, typed sample foundation, scalar result extensions,
   and compatibility migrations.
2. **RAG and General single-turn** — eight RAG adapters, seven text/safety
   adapters, common/RAG mapping, resource selection, presets, and picker UI.
3. **Agentic trace** — trace/tool samples, Task Completion, Tool Correctness,
   Agent Loop Detection, endpoint trace mapping, and ingestion.
4. **Conversational and MCP** — conversation normalization, three
   conversational adapters, two MCP adapters, mappings, ingestion, and reports.
5. **Multimodal and closeout** — image assets/security, Image Coherence,
   Image Helpfulness, reports/exports, full compatibility, and verification.

A card becomes visible only when its input, validation, execution, persistence,
and reporting paths are runnable. All five phases must land before the curated
catalog is advertised as complete.

## Upstream references

- Ragas available metrics:
  <https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/>
- DeepEval metrics introduction:
  <https://deepeval.com/docs/metrics-introduction>
- DeepEval 4.1.0 release:
  <https://github.com/confident-ai/deepeval/releases/tag/v4.1.0>
