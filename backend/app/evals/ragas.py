from app.evals.base import EvalRow, JudgeConfig, MetricScore
from app.evals.judges import ragas_embeddings, ragas_llm, usage_snapshot


def _make_metric(name: str, judge: JudgeConfig):
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRelevance,
        ContextRecall,
        Faithfulness,
    )

    llm = ragas_llm(judge)
    metrics = {
        "faithfulness": lambda: Faithfulness(llm),
        "answer_relevancy": lambda: AnswerRelevancy(llm, ragas_embeddings(judge)),
        "context_relevance": lambda: ContextRelevance(llm),
        "context_precision": lambda: ContextPrecisionWithReference(llm),
        "context_recall": lambda: ContextRecall(llm),
    }
    try:
        return metrics[name]()
    except KeyError as exc:
        raise ValueError(f"Unknown Ragas metric: {name}") from exc


def score_metric(
    name: str,
    row: EvalRow,
    judge: JudgeConfig,
    config: dict | None = None,
) -> MetricScore:
    metric = _make_metric(name, judge)
    kwargs = {
        "faithfulness": {
            "user_input": row.input,
            "response": row.actual_output,
            "retrieved_contexts": row.retrieval_contexts,
        },
        "answer_relevancy": {
            "user_input": row.input,
            "response": row.actual_output,
        },
        "context_relevance": {
            "user_input": row.input,
            "retrieved_contexts": row.retrieval_contexts,
        },
        "context_precision": {
            "user_input": row.input,
            "reference": row.expected_output,
            "retrieved_contexts": row.retrieval_contexts,
        },
        "context_recall": {
            "user_input": row.input,
            "reference": row.expected_output,
            "retrieved_contexts": row.retrieval_contexts,
        },
    }
    try:
        result = metric.score(**kwargs[name])
    except KeyError as exc:
        raise ValueError(f"Unknown Ragas metric: {name}") from exc
    threshold = (config or {}).get("threshold")
    value = float(result.value)
    usage, estimated_cost = usage_snapshot(getattr(metric, "llm", None))
    return MetricScore(
        metric=f"ragas.{name}",
        score=value,
        reason=result.reason,
        passed=value >= threshold if threshold is not None else None,
        usage=usage,
        estimated_cost=estimated_cost,
    )
