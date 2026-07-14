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
