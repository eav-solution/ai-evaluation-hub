import pytest
from pydantic import ValidationError


PHASE_4_KEYS = {
    "ragas.faithfulness",
    "ragas.answer_relevancy",
    "ragas.context_relevance",
    "ragas.context_precision",
    "ragas.context_recall",
    "deepeval.answer_relevancy",
    "deepeval.faithfulness",
    "deepeval.contextual_relevancy",
    "deepeval.hallucination",
    "deepeval.prompt_alignment",
    "deepeval.json_correctness",
    "deepeval.toxicity",
    "deepeval.pii_leakage",
    "deepeval.bias",
    "deepeval.geval",
    "deepeval.task_completion",
    "deepeval.agent_loop_detection",
    "deepeval.tool_correctness",
    "deepeval.conversation_completeness",
    "deepeval.turn_relevancy",
    "deepeval.role_adherence",
    "deepeval.mcp_task_completion",
    "deepeval.mcp_use",
}
PHASE_5_KEYS = PHASE_4_KEYS | {
    "deepeval.image_coherence",
    "deepeval.image_helpfulness",
}


def test_adapter_exposes_generated_config_and_dynamic_resources():
    from app.evals.registry import METRICS

    adapter = METRICS["ragas.answer_relevancy"]
    assert adapter.revision == "1"
    assert adapter.category == "rag"
    assert adapter.family == "generation"
    assert adapter.sample_kind == "single_turn"
    assert adapter.default_config() == {"threshold": None}
    assert adapter.resources(adapter.default_config()) == frozenset(
        {"judge", "embedding"}
    )
    assert adapter.config_schema()["additionalProperties"] is False


def test_adapter_rejects_unknown_or_invalid_config():
    from app.evals.registry import METRICS

    adapter = METRICS["deepeval.geval"]
    assert adapter.category == "general"
    assert adapter.family == "text_safety"
    with pytest.raises(ValidationError):
        adapter.validate_config({"threshold": 2})
    with pytest.raises(ValidationError):
        adapter.validate_config({"unknown": True})


def test_metric_catalog_is_generated_from_adapter_metadata(client):
    response = client.get("/api/metrics")

    assert response.status_code == 200
    metric = next(
        item for item in response.json() if item["key"] == "ragas.answer_relevancy"
    )
    assert metric["revision"] == "1"
    assert metric["category"] == "rag"
    assert metric["family"] == "generation"
    assert metric["sample_kind"] == "single_turn"
    assert metric["default_config"] == {"threshold": None}
    assert metric["resources"] == ["embedding", "judge"]
    assert metric["recommended"] is True
    assert metric["config_schema"]["additionalProperties"] is False


def test_current_metric_capability_metadata_matches_the_approved_catalog():
    from app.evals.registry import METRICS

    expected = {
        "ragas.faithfulness": ("rag", "generation"),
        "ragas.answer_relevancy": ("rag", "generation"),
        "ragas.context_relevance": ("rag", "retrieval"),
        "ragas.context_precision": ("rag", "retrieval"),
        "ragas.context_recall": ("rag", "retrieval"),
        "deepeval.answer_relevancy": ("rag", "generation"),
        "deepeval.faithfulness": ("rag", "generation"),
        "deepeval.contextual_relevancy": ("rag", "retrieval"),
        "deepeval.hallucination": ("general", "text_safety"),
        "deepeval.prompt_alignment": ("general", "text_safety"),
        "deepeval.json_correctness": ("general", "text_safety"),
        "deepeval.toxicity": ("general", "text_safety"),
        "deepeval.pii_leakage": ("general", "text_safety"),
        "deepeval.bias": ("general", "text_safety"),
        "deepeval.geval": ("general", "text_safety"),
        "deepeval.task_completion": ("agentic", "trace"),
        "deepeval.agent_loop_detection": ("agentic", "trace"),
        "deepeval.tool_correctness": ("agentic", "tools"),
        "deepeval.conversation_completeness": ("general", "conversational"),
        "deepeval.turn_relevancy": ("general", "conversational"),
        "deepeval.role_adherence": ("general", "conversational"),
        "deepeval.mcp_task_completion": ("agentic", "mcp"),
        "deepeval.mcp_use": ("agentic", "mcp"),
        "deepeval.image_coherence": ("general", "multimodal"),
        "deepeval.image_helpfulness": ("general", "multimodal"),
    }

    assert {
        key: (adapter.category, adapter.family) for key, adapter in METRICS.items()
    } == expected
    assert set(METRICS) == PHASE_5_KEYS


def test_catalog_exposes_dynamic_requirements_and_legacy_aliases():
    from app.evals.registry import METRICS

    assert METRICS["deepeval.geval"].catalog_entry()["requirement_rule"] == {
        "config_field": "evaluation_fields",
        "exclude": ["actual_output", "input"],
    }
    assert METRICS["deepeval.hallucination"].catalog_entry()[
        "requirement_aliases"
    ] == {"context": ["contexts"]}


def test_agentic_adapters_publish_sample_requirements_and_resources():
    from app.evals.registry import METRICS

    assert len(METRICS) == len(PHASE_5_KEYS)
    assert METRICS["deepeval.task_completion"].requires == frozenset(
        {"agent_trace"}
    )
    assert METRICS["deepeval.task_completion"].resources({}) == frozenset(
        {"judge"}
    )
    assert METRICS["deepeval.tool_correctness"].requires == frozenset(
        {"tools_called", "expected_tools"}
    )
    assert METRICS["deepeval.tool_correctness"].resources({}) == frozenset()
    assert METRICS["deepeval.agent_loop_detection"].resources({}) == frozenset()
    assert all(
        METRICS[key].sample_kind == "agent_trace"
        for key in (
            "deepeval.task_completion",
            "deepeval.tool_correctness",
            "deepeval.agent_loop_detection",
        )
    )


def test_agentic_adapter_config_is_generated_and_validated():
    from app.evals.registry import METRICS

    task = METRICS["deepeval.task_completion"]
    assert task.default_config()["task"] is None
    task_types = task.config_schema()["properties"]["task"]["anyOf"]
    assert {item.get("maxLength") for item in task_types} == {None, 10_000}

    tools = METRICS["deepeval.tool_correctness"]
    assert tools.default_config()["evaluation_params"] == []
    assert tools.default_config()["should_exact_match"] is False

    loops = METRICS["deepeval.agent_loop_detection"]
    assert loops.default_config()["repetition_threshold"] == 3
    assert loops.default_config()["similarity_threshold"] == 0.85
    with pytest.raises(ValidationError, match="At least one loop check"):
        loops.validate_config(
            {
                "check_tool_repetition": False,
                "check_reasoning_stagnation": False,
                "check_call_graph_cycles": False,
            }
        )


def test_conversational_and_mcp_adapter_metadata():
    from app.evals.registry import METRICS

    keys = (
        "deepeval.conversation_completeness",
        "deepeval.turn_relevancy",
        "deepeval.role_adherence",
        "deepeval.mcp_task_completion",
        "deepeval.mcp_use",
    )
    for key in keys:
        assert METRICS[key].sample_kind == "conversation"
        assert METRICS[key].resources({}) == frozenset({"judge"})
    assert METRICS["deepeval.conversation_completeness"].category == "general"
    assert METRICS["deepeval.conversation_completeness"].family == (
        "conversational"
    )
    assert METRICS["deepeval.mcp_use"].category == "agentic"
    assert METRICS["deepeval.mcp_use"].family == "mcp"
    assert METRICS["deepeval.role_adherence"].requirements({}) == frozenset(
        {"turns", "chatbot_role"}
    )
    assert METRICS["deepeval.mcp_task_completion"].requirements({}) == (
        frozenset({"turns", "mcp_metadata"})
    )
    assert METRICS["deepeval.mcp_use"].requirements({}) == frozenset(
        {"turns", "mcp_metadata", "mcp_events"}
    )


def test_conversation_window_defaults_follow_upstream():
    from app.evals.registry import METRICS

    completeness = METRICS["deepeval.conversation_completeness"].default_config()
    relevancy = METRICS["deepeval.turn_relevancy"].default_config()
    assert completeness["window_size"] == 3
    assert relevancy["window_size"] == 10


def test_multimodal_adapter_metadata():
    from app.evals.registry import METRICS

    for key in ("deepeval.image_coherence", "deepeval.image_helpfulness"):
        adapter = METRICS[key]
        assert adapter.category == "general"
        assert adapter.family == "multimodal"
        assert adapter.sample_kind == "multimodal"
        assert adapter.resources({}) == frozenset({"judge", "multimodal"})
        assert adapter.requirements({}) == frozenset({"input", "actual_output"})
        assert adapter.info["score_direction"] == "higher_is_better"
        assert adapter.default_config() == {
            "threshold": 0.5,
            "strict_mode": False,
            "max_context_size": None,
        }
