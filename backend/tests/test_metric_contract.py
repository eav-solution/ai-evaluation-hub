import pytest
from pydantic import ValidationError


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
    }

    assert {
        key: (adapter.category, adapter.family) for key, adapter in METRICS.items()
    } == expected


def test_catalog_exposes_dynamic_requirements_and_legacy_aliases():
    from app.evals.registry import METRICS

    assert METRICS["deepeval.geval"].catalog_entry()["requirement_rule"] == {
        "config_field": "evaluation_fields",
        "exclude": ["actual_output", "input"],
    }
    assert METRICS["deepeval.hallucination"].catalog_entry()[
        "requirement_aliases"
    ] == {"context": ["contexts"]}
