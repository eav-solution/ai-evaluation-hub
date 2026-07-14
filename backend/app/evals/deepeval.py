from app.evals.base import EvalRow, JudgeConfig, MetricScore
from app.evals.judges import deepeval_llm


def _make_metric(name: str, judge: JudgeConfig, config: dict | None):
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        BiasMetric,
        FaithfulnessMetric,
        GEval,
        HallucinationMetric,
        ToxicityMetric,
    )
    from deepeval.test_case import SingleTurnParams

    options = config or {}
    common = {
        "threshold": options.get("threshold", 0.5),
        "model": deepeval_llm(judge),
        "async_mode": False,
    }
    metrics = {
        "answer_relevancy": lambda: AnswerRelevancyMetric(**common),
        "faithfulness": lambda: FaithfulnessMetric(**common),
        "hallucination": lambda: HallucinationMetric(**common),
        "toxicity": lambda: ToxicityMetric(**common),
        "bias": lambda: BiasMetric(**common),
        "geval": lambda: GEval(
            name="G-Eval",
            criteria=options.get("rubric") or "Evaluate the quality of the response.",
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
            ],
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
