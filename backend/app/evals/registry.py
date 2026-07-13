from app.evals.base import CallableAdapter

# Metrics that need a separate embedding model. For a custom (openai_compatible)
# connection the embedding model must be selected explicitly at submission.
EMBEDDING_METRICS: frozenset[str] = frozenset({"ragas.answer_relevancy"})


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
    requires: set[str] | None = None,
) -> CallableAdapter:
    framework, metric = key.split(".", 1)
    return CallableAdapter(
        key=key,
        framework=framework,
        display_name=display_name,
        description=description,
        requires=frozenset(requires or set()),
        scorer=_framework_scorer(framework, metric),
    )


METRICS = {
    adapter.key: adapter
    for adapter in [
        _adapter(
            "ragas.faithfulness",
            "Faithfulness",
            "Factual consistency with retrieved contexts.",
            {"contexts"},
        ),
        _adapter(
            "ragas.answer_relevancy",
            "Answer Relevancy",
            "How relevant the answer is to the input.",
        ),
        _adapter(
            "ragas.context_precision",
            "Context Precision",
            "Whether relevant contexts rank above irrelevant contexts.",
            {"contexts", "expected_output"},
        ),
        _adapter(
            "ragas.context_recall",
            "Context Recall",
            "How much of the expected answer is supported by contexts.",
            {"contexts", "expected_output"},
        ),
        _adapter(
            "deepeval.answer_relevancy",
            "Answer Relevancy",
            "How relevant the answer is to the input.",
        ),
        _adapter(
            "deepeval.faithfulness",
            "Faithfulness",
            "Factual consistency with retrieved contexts.",
            {"contexts"},
        ),
        _adapter(
            "deepeval.hallucination",
            "Hallucination",
            "Contradictions against known contexts.",
            {"contexts"},
        ),
        _adapter(
            "deepeval.toxicity",
            "Toxicity",
            "Toxic content in the answer.",
        ),
        _adapter("deepeval.bias", "Bias", "Biased content in the answer."),
        _adapter(
            "deepeval.geval",
            "G-Eval",
            "Custom rubric evaluated by a judge model.",
        ),
    ]
}
