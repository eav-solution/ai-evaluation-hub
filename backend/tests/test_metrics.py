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


def test_callable_adapter_accepts_score_boundaries():
    from app.evals.base import CallableAdapter, EvalRow, JudgeConfig, MetricScore

    for value in (0.0, 1.0):
        adapter = CallableAdapter(
            key="test",
            framework="test",
            display_name="Test",
            description="Test",
            requires=frozenset(),
            scorer=lambda row, judge, config, value=value: MetricScore(
                "test", value, "ok", None
            ),
        )
        score = adapter.score(
            EvalRow(input="input", actual_output="actual"),
            JudgeConfig("openai", "model", "key"),
        )
        assert score.score == value


def test_callable_adapter_rejects_invalid_score():
    import pytest

    from app.evals.base import CallableAdapter, EvalRow, JudgeConfig, MetricScore

    for value in (-0.01, 1.01, float("nan"), float("inf")):
        adapter = CallableAdapter(
            key="test",
            framework="test",
            display_name="Test",
            description="Test",
            requires=frozenset(),
            scorer=lambda row, judge, config, value=value: MetricScore(
                "test", value, None, None
            ),
        )
        with pytest.raises(ValueError, match="score in the range 0..1"):
            adapter.score(
                EvalRow(input="input", actual_output="actual"),
                JudgeConfig("openai", "model", "key"),
            )
