from app.evals.base import (
    CallableAdapter,
    DeepEvalMetricConfig,
    GEvalConfig,
    MetricCategory,
    MetricConfig,
    ResourceRole,
)
from app.evals.metric_info import METRIC_INFO


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
) -> CallableAdapter:
    framework, metric = key.split(".", 1)
    config_model = (
        GEvalConfig
        if key == "deepeval.geval"
        else (DeepEvalMetricConfig if framework == "deepeval" else MetricConfig)
    )
    resource_roles = frozenset(resources or {"judge"})
    return CallableAdapter(
        key=key,
        framework=framework,
        category=category,
        family=family,
        display_name=display_name,
        description=description,
        requires=frozenset(requires or set()),
        scorer=_framework_scorer(framework, metric),
        config_model=config_model,
        info=METRIC_INFO[key],
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
            {"contexts"},
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
            "ragas.context_precision",
            "Context Precision",
            "Whether relevant contexts rank above irrelevant contexts.",
            "rag",
            "retrieval",
            {"contexts", "expected_output"},
        ),
        _adapter(
            "ragas.context_recall",
            "Context Recall",
            "How much of the expected answer is supported by contexts.",
            "rag",
            "retrieval",
            {"contexts", "expected_output"},
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
            {"contexts"},
        ),
        _adapter(
            "deepeval.hallucination",
            "Hallucination",
            "Contradictions against known contexts.",
            "general",
            "text_safety",
            {"contexts"},
        ),
        _adapter(
            "deepeval.toxicity",
            "Toxicity",
            "Toxic content in the answer.",
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
        ),
    ]
}
