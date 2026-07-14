import pytest


def test_ragas_adapter_maps_fields_and_threshold(monkeypatch):
    from app.evals import ragas
    from app.evals.base import EvalRow, JudgeConfig

    captured = {}

    class Result:
        value = 0.8
        reason = "grounded"

    class Metric:
        def score(self, **kwargs):
            captured.update(kwargs)
            return Result()

    monkeypatch.setattr(ragas, "_make_metric", lambda name, judge: Metric())
    result = ragas.score_metric(
        "faithfulness",
        EvalRow(
            input="question",
            actual_output="answer",
            expected_output=None,
            retrieval_contexts=["context"],
        ),
        JudgeConfig("openai", "model", "key"),
        {"threshold": 0.7},
    )
    assert captured == {
        "user_input": "question",
        "response": "answer",
        "retrieved_contexts": ["context"],
    }
    assert result.score == 0.8
    assert result.passed is True


def test_deepeval_adapter_uses_metric_success(monkeypatch):
    from app.evals import deepeval
    from app.evals.base import EvalRow, JudgeConfig

    class Metric:
        reason = "clean"

        def measure(self, test_case, **kwargs):
            assert test_case.actual_output == "answer"
            assert test_case.context == ["legacy context"]
            assert test_case.retrieval_context == ["legacy context"]
            return 0.1

        def is_successful(self):
            return True

    monkeypatch.setattr(deepeval, "_make_metric", lambda *args: Metric())
    result = deepeval.score_metric(
        "toxicity",
        EvalRow(
            input="question",
            actual_output="answer",
            retrieval_contexts=["legacy context"],
        ),
        JudgeConfig("openai", "model", "key"),
        {"threshold": 0.5},
    )
    assert result.score == 0.1
    assert result.passed is True


def test_unsupported_judge_provider():
    from app.evals.base import JudgeConfig
    from app.evals.judges import ragas_llm

    with pytest.raises(ValueError, match="Unsupported judge provider"):
        ragas_llm(JudgeConfig("unknown", "model", "key"))
