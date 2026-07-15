from app.evals.base import (
    AgentLoopDetectionConfig,
    CallableAdapter,
    ConversationWindowConfig,
    DeepEvalMetricConfig,
    GEvalConfig,
    ImageMetricConfig,
    JsonCorrectnessConfig,
    MetricCategory,
    MetricConfig,
    PromptAlignmentConfig,
    ResourceRole,
    TaskCompletionConfig,
    ToolCorrectnessConfig,
    TurnRelevancyConfig,
)
from app.evals.metric_info import METRIC_INFO
from pydantic import BaseModel


def _framework_scorer(framework: str, metric: str):
    def score(row, judge, config):
        if framework == "ragas":
            from app.evals.ragas import score_metric
        else:
            from app.evals.deepeval import score_metric
        return score_metric(metric, row, judge, config)

    return score


def _adapter(
    key: str,
    display_name: str,
    description: str,
    category: MetricCategory,
    family: str,
    requires: set[str] | None = None,
    resources: set[ResourceRole] | None = None,
    config_model: type[BaseModel] | None = None,
    requirement_config_field: str | None = None,
    requirement_exclusions: set[str] | None = None,
    requirement_aliases: dict[str, set[str]] | None = None,
    sample_kind: str = "single_turn",
) -> CallableAdapter:
    framework, metric = key.split(".", 1)
    resolved_config_model = config_model or (
        GEvalConfig
        if key == "deepeval.geval"
        else (DeepEvalMetricConfig if framework == "deepeval" else MetricConfig)
    )
    resource_roles = frozenset({"judge"} if resources is None else resources)
    return CallableAdapter(
        key=key,
        framework=framework,
        category=category,
        family=family,
        display_name=display_name,
        description=description,
        sample_kind=sample_kind,
        requires=frozenset(requires or set()),
        scorer=_framework_scorer(framework, metric),
        config_model=resolved_config_model,
        info=METRIC_INFO[key],
        requirement_config_field=requirement_config_field,
        requirement_exclusions=frozenset(requirement_exclusions or set()),
        requirement_aliases={
            key: frozenset(value)
            for key, value in (requirement_aliases or {}).items()
        },
        resource_fn=lambda config: resource_roles,
    )


METRICS = {
    adapter.key: adapter
    for adapter in [
        _adapter(
            "ragas.faithfulness",
            "Faithfulness",
            "Factual consistency with retrieved contexts.",
            "rag",
            "generation",
            {"retrieval_contexts"},
        ),
        _adapter(
            "ragas.answer_relevancy",
            "Answer Relevancy",
            "How relevant the answer is to the input.",
            "rag",
            "generation",
            resources={"judge", "embedding"},
        ),
        _adapter(
            "ragas.context_relevance",
            "Context Relevancy",
            "How relevant the retrieved contexts are to the input.",
            "rag",
            "retrieval",
            {"retrieval_contexts"},
        ),
        _adapter(
            "ragas.context_precision",
            "Context Precision",
            "Whether relevant contexts rank above irrelevant contexts.",
            "rag",
            "retrieval",
            {"retrieval_contexts", "expected_output"},
        ),
        _adapter(
            "ragas.context_recall",
            "Context Recall",
            "How much of the expected answer is supported by contexts.",
            "rag",
            "retrieval",
            {"retrieval_contexts", "expected_output"},
        ),
        _adapter(
            "deepeval.answer_relevancy",
            "Answer Relevancy",
            "How relevant the answer is to the input.",
            "rag",
            "generation",
        ),
        _adapter(
            "deepeval.faithfulness",
            "Faithfulness",
            "Factual consistency with retrieved contexts.",
            "rag",
            "generation",
            {"retrieval_contexts"},
        ),
        _adapter(
            "deepeval.contextual_relevancy",
            "Contextual Relevancy",
            "How relevant each retrieved context is to the input.",
            "rag",
            "retrieval",
            {"retrieval_contexts"},
        ),
        _adapter(
            "deepeval.hallucination",
            "Hallucination",
            "Contradictions against known contexts.",
            "general",
            "text_safety",
            {"context"},
            requirement_aliases={"context": {"contexts"}},
        ),
        _adapter(
            "deepeval.prompt_alignment",
            "Prompt Alignment",
            "Whether the response follows configured prompt constraints.",
            "general",
            "text_safety",
            config_model=PromptAlignmentConfig,
        ),
        _adapter(
            "deepeval.json_correctness",
            "JSON Correctness",
            "Whether the response matches a supported object schema.",
            "general",
            "text_safety",
            config_model=JsonCorrectnessConfig,
        ),
        _adapter(
            "deepeval.toxicity",
            "Toxicity",
            "Toxic content in the answer.",
            "general",
            "text_safety",
        ),
        _adapter(
            "deepeval.pii_leakage",
            "PII Leakage",
            "Personal information exposed by the response.",
            "general",
            "text_safety",
        ),
        _adapter(
            "deepeval.bias",
            "Bias",
            "Biased content in the answer.",
            "general",
            "text_safety",
        ),
        _adapter(
            "deepeval.geval",
            "G-Eval",
            "Custom rubric evaluated by a judge model.",
            "general",
            "text_safety",
            config_model=GEvalConfig,
            requirement_config_field="evaluation_fields",
            requirement_exclusions={"input", "actual_output"},
        ),
        _adapter(
            "deepeval.task_completion",
            "Task Completion",
            "Whether the agent trace completed the requested task.",
            "agentic",
            "trace",
            {"agent_trace"},
            {"judge"},
            config_model=TaskCompletionConfig,
            sample_kind="agent_trace",
        ),
        _adapter(
            "deepeval.agent_loop_detection",
            "Agent Loop Detection",
            "Whether the agent avoided repetitive or cyclic execution.",
            "agentic",
            "trace",
            {"agent_trace"},
            set(),
            config_model=AgentLoopDetectionConfig,
            sample_kind="agent_trace",
        ),
        _adapter(
            "deepeval.tool_correctness",
            "Tool Correctness",
            "Whether the agent called the expected tools correctly.",
            "agentic",
            "tools",
            {"tools_called", "expected_tools"},
            set(),
            config_model=ToolCorrectnessConfig,
            sample_kind="agent_trace",
        ),
        _adapter(
            "deepeval.conversation_completeness",
            "Conversation Completeness",
            "Whether the conversation satisfied the user's intentions end to end.",
            "general",
            "conversational",
            {"turns"},
            config_model=ConversationWindowConfig,
            sample_kind="conversation",
        ),
        _adapter(
            "deepeval.turn_relevancy",
            "Turn Relevancy",
            "Whether each assistant turn stays relevant to the recent conversation.",
            "general",
            "conversational",
            {"turns"},
            config_model=TurnRelevancyConfig,
            sample_kind="conversation",
        ),
        _adapter(
            "deepeval.role_adherence",
            "Role Adherence",
            "Whether the assistant stays in its declared chatbot role.",
            "general",
            "conversational",
            {"turns", "chatbot_role"},
            sample_kind="conversation",
        ),
        _adapter(
            "deepeval.mcp_task_completion",
            "MCP Task Completion",
            "Whether the conversation completed the task using its MCP servers.",
            "agentic",
            "mcp",
            {"turns", "mcp_metadata"},
            sample_kind="conversation",
        ),
        _adapter(
            "deepeval.mcp_use",
            "MCP Use",
            "Whether MCP tools, resources, and prompts were used correctly.",
            "agentic",
            "mcp",
            {"turns", "mcp_metadata", "mcp_events"},
            sample_kind="conversation",
        ),
        _adapter(
            "deepeval.image_coherence",
            "Image Coherence",
            "Whether each image fits the surrounding response text.",
            "general",
            "multimodal",
            {"input", "actual_output"},
            {"judge", "multimodal"},
            config_model=ImageMetricConfig,
            sample_kind="multimodal",
        ),
        _adapter(
            "deepeval.image_helpfulness",
            "Image Helpfulness",
            "Whether images help answer the user's request.",
            "general",
            "multimodal",
            {"input", "actual_output"},
            {"judge", "multimodal"},
            config_model=ImageMetricConfig,
            sample_kind="multimodal",
        ),
    ]
}
