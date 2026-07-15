from importlib.metadata import version
from importlib.util import find_spec
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


def test_deepeval_agent_trace_private_contract_is_available():
    from deepeval.test_case import LLMTestCase

    test_case = LLMTestCase(input="task", actual_output="done")

    assert hasattr(test_case, "_trace_dict")


def test_deepeval_conversational_contract_is_available():
    import inspect

    from deepeval.metrics import (
        ConversationCompletenessMetric,
        MCPTaskCompletionMetric,
        MCPUseMetric,
        RoleAdherenceMetric,
        TurnRelevancyMetric,
    )
    from deepeval.test_case import ConversationalTestCase, Turn
    from deepeval.test_case.mcp import (
        MCPPromptCall,
        MCPResourceCall,
        MCPServer,
        MCPToolCall,
    )

    for metric_class in (ConversationCompletenessMetric, TurnRelevancyMetric):
        assert "window_size" in inspect.signature(
            metric_class.__init__
        ).parameters
    case_fields = set(ConversationalTestCase.model_fields)
    assert {"turns", "chatbot_role", "context", "mcp_servers"} <= case_fields
    assert set(Turn.model_fields) >= {"role", "content"}
    assert set(MCPToolCall.__annotations__) == {"name", "args", "result"}
    assert all(
        (
            MCPTaskCompletionMetric,
            MCPUseMetric,
            RoleAdherenceMetric,
            MCPServer,
            MCPResourceCall,
            MCPPromptCall,
        )
    )
    assert find_spec("mcp") is None
