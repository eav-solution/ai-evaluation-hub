EXPECTED_DIRECTIONS = {
    "ragas.faithfulness": "higher_is_better",
    "ragas.answer_relevancy": "higher_is_better",
    "ragas.context_relevance": "higher_is_better",
    "ragas.context_precision": "higher_is_better",
    "ragas.context_recall": "higher_is_better",
    "deepeval.answer_relevancy": "higher_is_better",
    "deepeval.faithfulness": "higher_is_better",
    "deepeval.contextual_relevancy": "higher_is_better",
    "deepeval.hallucination": "lower_is_better",
    "deepeval.prompt_alignment": "higher_is_better",
    "deepeval.json_correctness": "higher_is_better",
    "deepeval.toxicity": "lower_is_better",
    "deepeval.pii_leakage": "lower_is_better",
    "deepeval.bias": "lower_is_better",
    "deepeval.geval": "higher_is_better",
    "deepeval.task_completion": "higher_is_better",
    "deepeval.agent_loop_detection": "higher_is_better",
    "deepeval.tool_correctness": "higher_is_better",
    "deepeval.conversation_completeness": "higher_is_better",
    "deepeval.turn_relevancy": "higher_is_better",
    "deepeval.role_adherence": "higher_is_better",
    "deepeval.mcp_task_completion": "higher_is_better",
    "deepeval.mcp_use": "higher_is_better",
    "deepeval.image_coherence": "higher_is_better",
    "deepeval.image_helpfulness": "higher_is_better",
}


def test_metric_catalog_contains_complete_v1_info(client):
    response = client.get("/api/metrics")
    assert response.status_code == 200
    metrics = {item["key"]: item for item in response.json()}
    assert set(metrics) == set(EXPECTED_DIRECTIONS)
    assert metrics["ragas.faithfulness"]["requires"] == ["retrieval_contexts"]

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


def test_metric_presets_publish_approved_rag_sets(client):
    response = client.get("/api/metrics/presets")
    assert response.status_code == 200
    presets = {item["id"]: item for item in response.json()}

    assert presets["rag_live"]["metric_keys"] == [
        "deepeval.answer_relevancy",
        "deepeval.faithfulness",
        "deepeval.contextual_relevancy",
    ]
    assert presets["rag_offline_references"]["metric_keys"] == [
        "deepeval.answer_relevancy",
        "deepeval.faithfulness",
        "deepeval.contextual_relevancy",
        "ragas.context_precision",
        "ragas.context_recall",
    ]
    assert presets["agentic"]["metric_keys"] == [
        "deepeval.task_completion",
        "deepeval.agent_loop_detection",
    ]
    assert all(
        {"id", "display_name", "description", "category", "mode_hint", "metric_keys"}
        <= set(preset)
        for preset in presets.values()
    )


def test_phase_5_presets_cover_remaining_categories():
    from app.evals.presets import PRESETS

    assert {preset["id"] for preset in PRESETS.values()} == {
        "rag_live",
        "rag_offline_references",
        "agentic",
        "conversational",
        "mcp",
        "multimodal",
    }
    assert PRESETS["multimodal"]["metric_keys"] == [
        "deepeval.image_coherence",
        "deepeval.image_helpfulness",
    ]
    assert PRESETS["conversational"]["metric_keys"] == [
        "deepeval.conversation_completeness",
        "deepeval.turn_relevancy",
        "deepeval.role_adherence",
    ]
    assert PRESETS["mcp"]["metric_keys"] == [
        "deepeval.mcp_task_completion",
        "deepeval.mcp_use",
    ]


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
