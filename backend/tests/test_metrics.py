EXPECTED_DIRECTIONS = {
    "ragas.faithfulness": "higher_is_better",
    "ragas.answer_relevancy": "higher_is_better",
    "ragas.context_precision": "higher_is_better",
    "ragas.context_recall": "higher_is_better",
    "deepeval.answer_relevancy": "higher_is_better",
    "deepeval.faithfulness": "higher_is_better",
    "deepeval.hallucination": "lower_is_better",
    "deepeval.toxicity": "lower_is_better",
    "deepeval.bias": "lower_is_better",
    "deepeval.geval": "higher_is_better",
}


def test_metric_catalog_contains_complete_v1_info(client):
    response = client.get("/api/metrics")
    assert response.status_code == 200
    metrics = {item["key"]: item for item in response.json()}
    assert set(metrics) == set(EXPECTED_DIRECTIONS)
    assert metrics["ragas.faithfulness"]["requires"] == ["contexts"]

    for key, expected_direction in EXPECTED_DIRECTIONS.items():
        info = metrics[key]["info"]
        assert info["meaning"].strip()
        assert info["score_direction"] == expected_direction
        assert 2 <= len(info["calculation_steps"]) <= 4
        assert all(step.strip() for step in info["calculation_steps"])
        assert info["formula"].strip()
        assert len(info["examples"]) == 2
        assert info["improvement_tips"]
        assert info["required_data"]
        for example in info["examples"]:
            assert example["title"].strip()
            assert example["inputs"]
            assert example["checks"]
            assert example["result"].strip()
            assert {check["outcome"] for check in example["checks"]} <= {
                "pass",
                "fail",
                "neutral",
            }


def test_callable_adapter_normalizes_score():
    from app.evals.base import CallableAdapter, EvalRow, JudgeConfig, MetricScore

    adapter = CallableAdapter(
        key="test",
        framework="test",
        display_name="Test",
        description="Test",
        requires=frozenset(),
        scorer=lambda row, judge, config: MetricScore("test", 1.4, "ok", None),
    )
    score = adapter.score(
        EvalRow("input", "actual", None, None),
        JudgeConfig("openai", "model", "key"),
    )
    assert score.score == 1.0


def test_callable_adapter_rejects_non_finite_score():
    import pytest

    from app.evals.base import CallableAdapter, EvalRow, JudgeConfig, MetricScore

    adapter = CallableAdapter(
        key="test",
        framework="test",
        display_name="Test",
        description="Test",
        requires=frozenset(),
        scorer=lambda row, judge, config: MetricScore("test", float("nan"), None, None),
    )
    with pytest.raises(ValueError, match="finite"):
        adapter.score(
            EvalRow("input", "actual", None, None),
            JudgeConfig("openai", "model", "key"),
        )
