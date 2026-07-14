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


def test_ragas_context_relevance_maps_retrieval_fields(monkeypatch):
    from app.evals import ragas
    from app.evals.base import EvalRow, JudgeConfig

    captured = {}

    class Result:
        value = 0.75
        reason = "relevant"

    class Metric:
        def score(self, **kwargs):
            captured.update(kwargs)
            return Result()

    monkeypatch.setattr(ragas, "_make_metric", lambda name, judge: Metric())
    result = ragas.score_metric(
        "context_relevance",
        EvalRow(
            input="question",
            actual_output="answer",
            retrieval_contexts=["retrieved"],
        ),
        JudgeConfig("openai", "model", "key"),
        {"threshold": 0.7},
    )

    assert captured == {
        "user_input": "question",
        "retrieved_contexts": ["retrieved"],
    }
    assert result.score == 0.75
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


def test_deepeval_phase_2_metric_constructors_use_validated_config(monkeypatch):
    from deepeval import metrics

    from app.evals import deepeval
    from app.evals.base import JudgeConfig

    captured = {}

    class Metric:
        pass

    def factory(name):
        def build(**kwargs):
            captured[name] = kwargs
            return Metric()

        return build

    monkeypatch.setattr(deepeval, "deepeval_llm", lambda judge: "judge")
    for class_name in (
        "ContextualRelevancyMetric",
        "PromptAlignmentMetric",
        "JsonCorrectnessMetric",
        "PIILeakageMetric",
    ):
        monkeypatch.setattr(metrics, class_name, factory(class_name))

    judge = JudgeConfig("openai", "model", "key")
    deepeval._make_metric(
        "contextual_relevancy",
        judge,
        {"threshold": 0.6, "include_reason": False, "strict_mode": True},
    )
    deepeval._make_metric(
        "prompt_alignment",
        judge,
        {
            "threshold": 0.4,
            "include_reason": True,
            "strict_mode": False,
            "prompt_instructions": ["Be concise"],
        },
    )
    deepeval._make_metric(
        "json_correctness",
        judge,
        {
            "threshold": 0.5,
            "include_reason": False,
            "strict_mode": True,
            "expected_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
    )
    deepeval._make_metric(
        "pii_leakage",
        judge,
        {"threshold": 0.3, "include_reason": True, "strict_mode": False},
    )

    assert captured["ContextualRelevancyMetric"] == {
        "threshold": 0.6,
        "model": "judge",
        "async_mode": False,
        "include_reason": False,
        "strict_mode": True,
    }
    assert captured["PromptAlignmentMetric"]["prompt_instructions"] == ["Be concise"]
    schema_model = captured["JsonCorrectnessMetric"]["expected_schema"]
    assert schema_model.model_validate_json('{"answer":"yes"}').answer == "yes"
    assert captured["PIILeakageMetric"]["threshold"] == 0.3


def test_unsupported_judge_provider():
    from app.evals.base import JudgeConfig
    from app.evals.judges import ragas_llm

    with pytest.raises(ValueError, match="Unsupported judge provider"):
        ragas_llm(JudgeConfig("unknown", "model", "key"))
