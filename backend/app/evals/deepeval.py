from app.evals.base import EvalRow, JudgeConfig, MetricScore
from app.evals.json_schema import model_from_object_schema
from app.evals.judges import deepeval_llm


def _make_metric(name: str, judge: JudgeConfig, config: dict | None):
    from deepeval.metrics import (
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
    )
    from deepeval.test_case import SingleTurnParams

    options = config or {}
    common = {
        "threshold": options.get("threshold", 0.5),
        "model": deepeval_llm(judge),
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
    }
    try:
        return metrics[name]()
    except KeyError as exc:
        raise ValueError(f"Unknown DeepEval metric: {name}") from exc


def score_metric(
    name: str,
    row: EvalRow,
    judge: JudgeConfig,
    config: dict | None = None,
) -> MetricScore:
    from deepeval.test_case import LLMTestCase

    metric = _make_metric(name, judge, config)
    test_case = LLMTestCase(
        input=row.input,
        actual_output=row.actual_output,
        expected_output=row.expected_output,
        context=row.context or row.retrieval_contexts,
        retrieval_context=row.retrieval_contexts,
    )
    value = float(
        metric.measure(
            test_case,
            _show_indicator=False,
            _log_metric_to_confident=False,
        )
    )
    return MetricScore(
        metric=f"deepeval.{name}",
        score=value,
        reason=metric.reason,
        passed=bool(metric.is_successful()),
    )
