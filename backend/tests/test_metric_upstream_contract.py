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
