from typing import Any

from app.evals.base import JudgeConfig, MetricScore
from app.evals.json_schema import model_from_object_schema
from app.evals.judges import (
    deepeval_llm,
    deterministic_deepeval_llm,
    usage_snapshot,
)
from app.evals.samples import AgentTraceEvent, AgentTraceSample, EvaluationSample, ToolCall


def _make_metric(name: str, judge: JudgeConfig | None, config: dict | None):
    from deepeval.metrics import (
        AgentLoopDetectionMetric,
        AnswerRelevancyMetric,
        BiasMetric,
        ContextualRelevancyMetric,
        FaithfulnessMetric,
        GEval,
        HallucinationMetric,
        JsonCorrectnessMetric,
        PIILeakageMetric,
        PromptAlignmentMetric,
        ToxicityMetric,
        TaskCompletionMetric,
        ToolCorrectnessMetric,
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


def _test_case(row: EvaluationSample, name: str):
    from deepeval.test_case import LLMTestCase

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
    test_case = _test_case(row, name)
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
