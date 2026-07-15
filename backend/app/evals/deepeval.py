from typing import Any

from app.evals.base import JudgeConfig, MetricScore
from app.evals.json_schema import model_from_object_schema
from app.evals.judges import (
    deepeval_llm,
    deterministic_deepeval_llm,
    usage_snapshot,
)
from app.evals.samples import (
    AgentTraceEvent,
    AgentTraceSample,
    ConversationSample,
    EvaluationSample,
    MultimodalSample,
    ToolCall,
    conversation_actual_preview,
    conversation_input_preview,
    multimodal_input_preview,
)


_MCP_SINGLE_TURN_METRICS = {"mcp_use"}


def _make_metric(name: str, judge: JudgeConfig | None, config: dict | None):
    from deepeval.metrics import (
        AgentLoopDetectionMetric,
        AnswerRelevancyMetric,
        BiasMetric,
        ContextualRelevancyMetric,
        ConversationCompletenessMetric,
        FaithfulnessMetric,
        GEval,
        HallucinationMetric,
        ImageCoherenceMetric,
        ImageHelpfulnessMetric,
        JsonCorrectnessMetric,
        MCPTaskCompletionMetric,
        MCPUseMetric,
        PIILeakageMetric,
        PromptAlignmentMetric,
        RoleAdherenceMetric,
        ToxicityMetric,
        TaskCompletionMetric,
        ToolCorrectnessMetric,
        TurnRelevancyMetric,
    )
    from deepeval.test_case import SingleTurnParams, ToolCallParams

    options = config or {}
    deterministic_names = {"tool_correctness", "agent_loop_detection"}
    if judge is None and name not in deterministic_names:
        raise ValueError(f"DeepEval metric '{name}' requires a judge")
    judge_model = deepeval_llm(judge) if judge is not None else None
    common = {
        "threshold": options.get("threshold", 0.5),
        "model": judge_model,
        "async_mode": False,
    }
    reasoned = {
        **common,
        "include_reason": options.get("include_reason", True),
        "strict_mode": options.get("strict_mode", False),
    }
    evaluation_params = {
        "input": SingleTurnParams.INPUT,
        "actual_output": SingleTurnParams.ACTUAL_OUTPUT,
        "expected_output": SingleTurnParams.EXPECTED_OUTPUT,
        "context": SingleTurnParams.CONTEXT,
        "retrieval_contexts": SingleTurnParams.RETRIEVAL_CONTEXT,
    }
    metrics = {
        "answer_relevancy": lambda: AnswerRelevancyMetric(**reasoned),
        "faithfulness": lambda: FaithfulnessMetric(**reasoned),
        "contextual_relevancy": lambda: ContextualRelevancyMetric(**reasoned),
        "hallucination": lambda: HallucinationMetric(**reasoned),
        "prompt_alignment": lambda: PromptAlignmentMetric(
            prompt_instructions=options["prompt_instructions"],
            **reasoned,
        ),
        "json_correctness": lambda: JsonCorrectnessMetric(
            expected_schema=model_from_object_schema(options["expected_schema"]),
            **reasoned,
        ),
        "toxicity": lambda: ToxicityMetric(**reasoned),
        "pii_leakage": lambda: PIILeakageMetric(**reasoned),
        "bias": lambda: BiasMetric(**reasoned),
        "geval": lambda: GEval(
            name="G-Eval",
            criteria=options.get("rubric") or "Evaluate the quality of the response.",
            evaluation_params=[
                evaluation_params[field]
                for field in options.get(
                    "evaluation_fields", ["input", "actual_output"]
                )
            ],
            strict_mode=options.get("strict_mode", False),
            **common,
        ),
        "task_completion": lambda: TaskCompletionMetric(
            task=options.get("task"),
            **reasoned,
        ),
        "tool_correctness": lambda: ToolCorrectnessMetric(
            threshold=options.get("threshold", 0.5),
            evaluation_params=[
                ToolCallParams(value) for value in options.get("evaluation_params", [])
            ],
            model=deterministic_deepeval_llm(),
            include_reason=options.get("include_reason", True),
            async_mode=False,
            strict_mode=options.get("strict_mode", False),
            should_exact_match=options.get("should_exact_match", False),
            should_consider_ordering=options.get("should_consider_ordering", False),
        ),
        "agent_loop_detection": lambda: AgentLoopDetectionMetric(
            threshold=options.get("threshold", 0.5),
            repetition_threshold=options.get("repetition_threshold", 3),
            similarity_threshold=options.get("similarity_threshold", 0.85),
            check_tool_repetition=options.get("check_tool_repetition", True),
            check_reasoning_stagnation=options.get(
                "check_reasoning_stagnation", True
            ),
            check_call_graph_cycles=options.get("check_call_graph_cycles", True),
            include_reason=options.get("include_reason", True),
            async_mode=False,
            strict_mode=options.get("strict_mode", False),
        ),
        "conversation_completeness": lambda: ConversationCompletenessMetric(
            window_size=options.get("window_size", 3),
            **reasoned,
        ),
        "turn_relevancy": lambda: TurnRelevancyMetric(
            window_size=options.get("window_size", 10),
            **reasoned,
        ),
        "role_adherence": lambda: RoleAdherenceMetric(**reasoned),
        "mcp_task_completion": lambda: MCPTaskCompletionMetric(**reasoned),
        "mcp_use": lambda: MCPUseMetric(**reasoned),
        "image_coherence": lambda: ImageCoherenceMetric(
            max_context_size=options.get("max_context_size"),
            threshold=options.get("threshold", 0.5),
            strict_mode=options.get("strict_mode", False),
            model=judge_model,
            async_mode=False,
        ),
        "image_helpfulness": lambda: ImageHelpfulnessMetric(
            max_context_size=options.get("max_context_size"),
            threshold=options.get("threshold", 0.5),
            strict_mode=options.get("strict_mode", False),
            model=judge_model,
            async_mode=False,
        ),
    }
    try:
        return metrics[name]()
    except KeyError as exc:
        raise ValueError(f"Unknown DeepEval metric: {name}") from exc


def _deepeval_tool_call(tool: ToolCall):
    from deepeval.test_case import ToolCall as DeepEvalToolCall

    return DeepEvalToolCall(
        name=tool.name,
        input_parameters=tool.arguments or None,
        output=tool.output,
    )


def _trace_event(event: AgentTraceEvent) -> dict[str, Any]:
    return {
        "type": event.type,
        "name": event.name,
        "input": event.input,
        "output": event.output,
        "details": event.details,
        "children": [_trace_event(child) for child in event.children],
    }


def _trace_dict(sample: AgentTraceSample) -> dict[str, Any]:
    return {
        "type": "agent",
        "name": "evalhub-agent-trace",
        "input": sample.input,
        "output": sample.actual_output,
        "children": [_trace_event(event) for event in sample.agent_trace],
    }


def _deepeval_turns(sample: ConversationSample):
    from deepeval.test_case import Turn

    turns = [
        Turn(role=turn.role, content=turn.content)
        for turn in sample.turns
        if turn.role in ("user", "assistant")
    ]
    if not any(turn.role == "user" for turn in turns) or not any(
        turn.role == "assistant" for turn in turns
    ):
        raise ValueError(
            "Conversation needs at least one user and one assistant turn"
        )
    return turns


def _mcp_servers(sample: ConversationSample):
    from deepeval.test_case.mcp import MCPServer

    return [
        MCPServer(server_name=server.server_name, transport=server.transport)
        for server in sample.mcp_metadata.servers
    ] or None


def _conversational_test_case(sample: ConversationSample):
    from deepeval.test_case import ConversationalTestCase

    return ConversationalTestCase(
        turns=_deepeval_turns(sample),
        chatbot_role=sample.chatbot_role,
        context=sample.conversation_context or None,
        mcp_servers=_mcp_servers(sample),
        metadata=sample.metadata,
        tags=sample.tags,
    )


def _mcp_llm_test_case(sample: ConversationSample):
    from deepeval.test_case import LLMTestCase
    from deepeval.test_case.mcp import (
        MCPPromptCall,
        MCPResourceCall,
        MCPToolCall,
    )

    _deepeval_turns(sample)
    tools, resources, prompts = [], [], []
    for event in sample.mcp_events:
        payload = event.payload
        if event.type == "tool":
            tools.append(
                MCPToolCall(
                    name=event.name or "",
                    args=payload.get("args", {}),
                    result=payload.get("result"),
                )
            )
        elif event.type == "resource":
            resources.append(
                MCPResourceCall(
                    uri=payload["uri"], result=payload.get("result")
                )
            )
        elif event.type == "prompt":
            prompts.append(
                MCPPromptCall(
                    name=event.name or "", result=payload.get("result")
                )
            )
        else:
            raise ValueError(f"Unsupported MCP event type: {event.type}")
    test_case = LLMTestCase(
        input=conversation_input_preview(sample),
        actual_output=conversation_actual_preview(sample),
        mcp_servers=_mcp_servers(sample),
        metadata=sample.metadata,
        tags=sample.tags,
    )
    # DeepEval 4.1.0 imports the optional `mcp` package when these fields are
    # passed to LLMTestCase.__init__. Our typed models are sufficient for the
    # MCPUseMetric, so assign them after the base test case is validated.
    test_case.mcp_tools_called = tools or None
    test_case.mcp_resources_called = resources or None
    test_case.mcp_prompts_called = prompts or None
    return test_case


def _marker_text(
    blocks, created_ids: list[str], image_context: str | None = None
) -> str:
    from deepeval.test_case import MLLMImage

    parts = []
    for block in blocks:
        if block.type == "text":
            parts.append(block.text)
            continue
        if not block.data_base64 or not block.mime_type:
            raise ValueError("Image block was not hydrated before scoring")
        image = MLLMImage(
            dataBase64=block.data_base64,
            mimeType=block.mime_type,
        )
        created_ids.append(image._id)
        if image_context:
            parts.append(image_context)
        parts.append(str(image))
    return " ".join(parts)


def _multimodal_test_case(
    sample: MultimodalSample,
    name: str,
) -> tuple[Any, list[str]]:
    from deepeval.test_case import LLMTestCase

    if not any(block.type == "image" for block in sample.actual_output):
        # DeepEval 4.1.0 requires an image in actual_output, even when input
        # already contains one.
        raise ValueError(
            "Multimodal sample needs at least one image block in actual_output"
        )
    created_ids: list[str] = []
    try:
        request = multimodal_input_preview(sample)
        test_case = LLMTestCase(
            input=_marker_text(sample.input, created_ids),
            actual_output=_marker_text(
                sample.actual_output,
                created_ids,
                (
                    f"User request: {request}"
                    if name == "image_helpfulness" and request
                    else None
                ),
            ),
            metadata=sample.metadata,
            tags=sample.tags,
        )
    except Exception:
        _release_marker_images(created_ids)
        raise
    return test_case, created_ids


def _release_marker_images(image_ids: list[str]) -> None:
    # DeepEval keeps strong references in a module-level registry. Release
    # only the marker images created by this score call.
    from deepeval.test_case.llm_test_case import _MLLM_IMAGE_REGISTRY

    for image_id in image_ids:
        _MLLM_IMAGE_REGISTRY.pop(image_id, None)


def _test_case(row: EvaluationSample, name: str):
    from deepeval.test_case import LLMTestCase

    if isinstance(row, ConversationSample):
        if name == "role_adherence" and not row.chatbot_role:
            raise ValueError("Role adherence needs a chatbot role")
        if name in {"mcp_task_completion", "mcp_use"} and not (
            row.mcp_metadata.servers
        ):
            raise ValueError("MCP metadata needs at least one server")
        if name == "mcp_use" and not row.mcp_events:
            raise ValueError("MCP use needs at least one event")
        if name in _MCP_SINGLE_TURN_METRICS:
            return _mcp_llm_test_case(row)
        return _conversational_test_case(row)

    if isinstance(row, AgentTraceSample):
        test_case = LLMTestCase(
            input=row.input,
            actual_output=row.actual_output,
            tools_called=[_deepeval_tool_call(tool) for tool in row.tools_called],
            expected_tools=[_deepeval_tool_call(tool) for tool in row.expected_tools],
            metadata=row.metadata,
            tags=row.tags,
        )
        test_case._trace_dict = _trace_dict(row)
        return test_case

    return LLMTestCase(
        input=row.input,
        actual_output=row.actual_output,
        expected_output=row.expected_output,
        context=(
            row.context or row.retrieval_contexts
            if name == "hallucination"
            else row.context
        ),
        retrieval_context=row.retrieval_contexts,
        metadata=row.metadata,
        tags=row.tags,
    )


def score_metric(
    name: str,
    row: EvaluationSample,
    judge: JudgeConfig | None,
    config: dict | None = None,
) -> MetricScore:

    metric = _make_metric(name, judge, config)
    created_image_ids: list[str] = []
    if isinstance(row, MultimodalSample):
        test_case, created_image_ids = _multimodal_test_case(row, name)
    else:
        test_case = _test_case(row, name)
    try:
        value = float(
            metric.measure(
                test_case,
                _show_indicator=False,
                _log_metric_to_confident=False,
            )
        )
        usage, estimated_cost = usage_snapshot(getattr(metric, "model", None))
        return MetricScore(
            metric=f"deepeval.{name}",
            score=value,
            reason=metric.reason,
            passed=bool(metric.is_successful()),
            usage=usage,
            estimated_cost=estimated_cost,
        )
    finally:
        _release_marker_images(created_image_ids)
