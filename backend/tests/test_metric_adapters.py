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
    from app.evals.judges import UsageTracker

    class Metric:
        reason = "clean"
        model = type("Model", (), {})()
        model._evalhub_usage_tracker = UsageTracker(
            provider="openai_compatible", model="model"
        )

        def measure(self, test_case, **kwargs):
            assert test_case.actual_output == "answer"
            assert test_case.context is None
            assert test_case.retrieval_context == ["legacy context"]
            self.model._evalhub_usage_tracker.record_response(
                type(
                    "Response",
                    (),
                    {
                        "usage": type(
                            "Usage",
                            (),
                            {"prompt_tokens": 5, "completion_tokens": 2},
                        )()
                    },
                )()
            )
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
    assert result.usage == {"input_tokens": 5, "output_tokens": 2}
    assert result.estimated_cost is None


def test_deepeval_hallucination_keeps_legacy_context_fallback(monkeypatch):
    from app.evals import deepeval
    from app.evals.base import EvalRow, JudgeConfig

    class Metric:
        reason = "checked"

        def measure(self, test_case, **kwargs):
            assert test_case.context == ["legacy context"]
            assert test_case.retrieval_context == ["legacy context"]
            return 0.2

        def is_successful(self):
            return True

    monkeypatch.setattr(deepeval, "_make_metric", lambda *args: Metric())
    deepeval.score_metric(
        "hallucination",
        EvalRow(
            input="question",
            actual_output="answer",
            retrieval_contexts=["legacy context"],
        ),
        JudgeConfig("openai", "model", "key"),
        {"threshold": 0.5},
    )


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


def test_deepeval_agentic_metric_constructors_use_validated_config(monkeypatch):
    from deepeval import metrics
    from deepeval.test_case import ToolCallParams

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

    for class_name in (
        "TaskCompletionMetric",
        "ToolCorrectnessMetric",
        "AgentLoopDetectionMetric",
    ):
        monkeypatch.setattr(metrics, class_name, factory(class_name))
    monkeypatch.setattr(deepeval, "deepeval_llm", lambda judge: "judge")

    deepeval._make_metric(
        "task_completion",
        JudgeConfig("openai", "model", "key"),
        {
            "threshold": 0.6,
            "include_reason": False,
            "strict_mode": True,
            "task": "Book the flight",
        },
    )
    deepeval._make_metric(
        "tool_correctness",
        None,
        {
            "threshold": 0.7,
            "include_reason": True,
            "strict_mode": False,
            "evaluation_params": ["input_parameters", "output"],
            "should_exact_match": True,
            "should_consider_ordering": True,
        },
    )
    deepeval._make_metric(
        "agent_loop_detection",
        None,
        {
            "threshold": 0.8,
            "include_reason": True,
            "strict_mode": False,
            "repetition_threshold": 4,
            "similarity_threshold": 0.9,
            "check_tool_repetition": True,
            "check_reasoning_stagnation": False,
            "check_call_graph_cycles": True,
        },
    )

    assert captured["TaskCompletionMetric"]["model"] == "judge"
    assert captured["TaskCompletionMetric"]["task"] == "Book the flight"
    assert captured["ToolCorrectnessMetric"]["evaluation_params"] == [
        ToolCallParams.INPUT_PARAMETERS,
        ToolCallParams.OUTPUT,
    ]
    assert captured["ToolCorrectnessMetric"]["model"].get_model_name() == (
        "evalhub-deterministic"
    )
    assert captured["ToolCorrectnessMetric"]["should_exact_match"] is True
    assert captured["AgentLoopDetectionMetric"]["repetition_threshold"] == 4
    assert captured["AgentLoopDetectionMetric"]["similarity_threshold"] == 0.9
    assert captured["AgentLoopDetectionMetric"]["check_reasoning_stagnation"] is False


@pytest.mark.parametrize(
    "metric_name", ["task_completion", "tool_correctness", "agent_loop_detection"]
)
def test_deepeval_agentic_scoring_converts_tools_and_trace(monkeypatch, metric_name):
    from app.evals import deepeval
    from app.evals.base import JudgeConfig
    from app.evals.samples import AgentTraceSample

    captured = {}

    class Metric:
        reason = "complete"

        def measure(self, test_case, **kwargs):
            captured["test_case"] = test_case
            return 0.9

        def is_successful(self):
            return True

    monkeypatch.setattr(deepeval, "_make_metric", lambda *args: Metric())
    sample = AgentTraceSample.model_validate(
        {
            "input": "Find weather",
            "actual_output": "Sunny",
            "agent_trace": [
                {
                    "type": "agent",
                    "name": "planner",
                    "children": [{"type": "tool", "name": "weather"}],
                }
            ],
            "tools_called": [
                {
                    "name": "weather",
                    "arguments": {"city": "Paris"},
                    "output": "Sunny",
                }
            ],
            "expected_tools": ["weather"],
        }
    )
    judge = (
        JudgeConfig("openai", "model", "key")
        if metric_name == "task_completion"
        else None
    )

    result = deepeval.score_metric(metric_name, sample, judge, {})

    test_case = captured["test_case"]
    assert test_case.tools_called[0].input_parameters == {"city": "Paris"}
    assert test_case.tools_called[0].output == "Sunny"
    assert test_case.expected_tools[0].name == "weather"
    assert test_case._trace_dict["children"][0]["children"][0]["type"] == "tool"
    assert result.score == 0.9
    assert result.passed is True


def _conversation_sample(**extra):
    from app.evals.samples import ConversationSample

    return ConversationSample.model_validate(
        {
            "kind": "conversation",
            "turns": [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "open a.txt"},
                {"role": "tool", "content": "raw bytes"},
                {"role": "assistant", "content": "done"},
            ],
            **extra,
        }
    )


def test_deepeval_conversation_constructors_map_validated_config(monkeypatch):
    from deepeval import metrics

    from app.evals import deepeval
    from app.evals.base import JudgeConfig

    captured = {}

    def factory(name):
        def build(**kwargs):
            captured[name] = kwargs
            return object()

        return build

    names = (
        "ConversationCompletenessMetric",
        "TurnRelevancyMetric",
        "RoleAdherenceMetric",
        "MCPTaskCompletionMetric",
        "MCPUseMetric",
    )
    for name in names:
        monkeypatch.setattr(metrics, name, factory(name))
    monkeypatch.setattr(deepeval, "deepeval_llm", lambda judge: "judge")
    judge = JudgeConfig("openai", "model", "key")

    deepeval._make_metric(
        "conversation_completeness",
        judge,
        {"threshold": 0.7, "window_size": 5},
    )
    deepeval._make_metric(
        "turn_relevancy", judge, {"threshold": 0.6, "window_size": 8}
    )
    for name in ("role_adherence", "mcp_task_completion", "mcp_use"):
        deepeval._make_metric(name, judge, {"threshold": 0.55})

    assert captured["ConversationCompletenessMetric"]["window_size"] == 5
    assert captured["ConversationCompletenessMetric"]["threshold"] == 0.7
    assert captured["TurnRelevancyMetric"]["window_size"] == 8
    assert captured["RoleAdherenceMetric"]["model"] == "judge"
    assert captured["MCPTaskCompletionMetric"]["async_mode"] is False
    assert captured["MCPUseMetric"]["threshold"] == 0.55


def _capture_conversation_case(monkeypatch, metric_name, sample):
    from app.evals import deepeval
    from app.evals.base import JudgeConfig

    captured = {}

    class Metric:
        reason = "ok"
        model = None

        def measure(self, test_case, **kwargs):
            captured["test_case"] = test_case
            return 0.9

        def is_successful(self):
            return True

    monkeypatch.setattr(deepeval, "_make_metric", lambda *args: Metric())
    deepeval.score_metric(
        metric_name,
        sample,
        JudgeConfig("openai", "model", "key"),
        {},
    )
    return captured["test_case"]


def test_conversational_test_case_filters_roles(monkeypatch):
    test_case = _capture_conversation_case(
        monkeypatch, "conversation_completeness", _conversation_sample()
    )

    assert [turn.role for turn in test_case.turns] == ["user", "assistant"]


def test_role_adherence_receives_chatbot_role(monkeypatch):
    test_case = _capture_conversation_case(
        monkeypatch,
        "role_adherence",
        _conversation_sample(chatbot_role="support agent"),
    )

    assert test_case.chatbot_role == "support agent"


def test_mcp_task_completion_receives_servers(monkeypatch):
    test_case = _capture_conversation_case(
        monkeypatch,
        "mcp_task_completion",
        _conversation_sample(
            mcp_metadata={
                "servers": [{"server_name": "files", "transport": "stdio"}]
            }
        ),
    )

    assert test_case.mcp_servers[0].server_name == "files"


def test_mcp_use_builds_llm_test_case_from_turns_and_events(monkeypatch):
    test_case = _capture_conversation_case(
        monkeypatch,
        "mcp_use",
        _conversation_sample(
            mcp_metadata={
                "servers": [{"server_name": "files", "transport": "stdio"}]
            },
            mcp_events=[
                {
                    "type": "tool",
                    "name": "read",
                    "payload": {
                        "args": {"path": "a.txt"},
                        "result": "data",
                    },
                },
                {
                    "type": "resource",
                    "name": None,
                    "payload": {"uri": "file://a.txt", "result": "data"},
                },
                {
                    "type": "prompt",
                    "name": "summarize",
                    "payload": {"result": "short"},
                },
            ],
        ),
    )

    assert test_case.input == "open a.txt"
    assert test_case.actual_output == "done"
    assert test_case.mcp_tools_called[0].name == "read"
    assert test_case.mcp_tools_called[0].args == {"path": "a.txt"}
    assert str(test_case.mcp_resources_called[0].uri).startswith("file://a.txt")
    assert test_case.mcp_prompts_called[0].name == "summarize"


def test_conversation_without_user_or_assistant_turn_fails_row(monkeypatch):
    from app.evals import deepeval
    from app.evals.base import JudgeConfig
    from app.evals.samples import ConversationSample

    monkeypatch.setattr(deepeval, "_make_metric", lambda *args: object())
    only_system = ConversationSample.model_validate(
        {
            "kind": "conversation",
            "turns": [{"role": "system", "content": "be brief"}],
        }
    )
    with pytest.raises(ValueError, match="user and one assistant"):
        deepeval.score_metric(
            "conversation_completeness",
            only_system,
            JudgeConfig("openai", "model", "key"),
            {},
        )


def test_conversation_metrics_require_judge():
    from app.evals import deepeval

    with pytest.raises(ValueError, match="requires a judge"):
        deepeval.score_metric("turn_relevancy", _conversation_sample(), None, {})


def test_role_adherence_requires_a_nonempty_role(monkeypatch):
    from app.evals import deepeval
    from app.evals.base import JudgeConfig

    monkeypatch.setattr(deepeval, "_make_metric", lambda *args: object())
    with pytest.raises(ValueError, match="chatbot role"):
        deepeval.score_metric(
            "role_adherence",
            _conversation_sample(),
            JudgeConfig("openai", "model", "key"),
            {},
        )


@pytest.mark.parametrize(
    ("metric_name", "extra", "message"),
    [
        ("mcp_task_completion", {}, "MCP metadata needs at least one server"),
        (
            "mcp_use",
            {"mcp_metadata": {"servers": [{"server_name": "files"}]}},
            "MCP use needs at least one event",
        ),
    ],
)
def test_empty_mcp_inputs_fail_the_row(monkeypatch, metric_name, extra, message):
    from app.evals import deepeval
    from app.evals.base import JudgeConfig

    monkeypatch.setattr(deepeval, "_make_metric", lambda *args: object())
    with pytest.raises(ValueError, match=message):
        deepeval.score_metric(
            metric_name,
            _conversation_sample(**extra),
            JudgeConfig("openai", "model", "key"),
            {},
        )


def _multimodal_sample():
    from app.evals.samples import MultimodalSample

    return MultimodalSample.model_validate(
        {
            "kind": "multimodal",
            "input": [{"type": "text", "text": "Describe the chart"}],
            "actual_output": [
                {"type": "text", "text": "Revenue"},
                {"type": "image", "asset_id": "a1"},
            ],
        }
    )


def _hydrated(sample):
    for block in sample.actual_output + sample.input:
        if block.type == "image":
            block.data_base64 = "aGVsbG8="
            block.mime_type = "image/png"
    return sample


def _capture_image_metric(monkeypatch, captured):
    class FakeMetric:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs
            self.reason = "ok"

        def measure(self, test_case, **kwargs):
            captured["measure_args"] = (test_case,)
            return 0.9

        def is_successful(self):
            return True

    import deepeval.metrics

    monkeypatch.setattr(deepeval.metrics, "ImageCoherenceMetric", FakeMetric)
    monkeypatch.setattr(deepeval.metrics, "ImageHelpfulnessMetric", FakeMetric)


def test_image_metric_receives_marker_test_case(monkeypatch):
    from app.evals.deepeval import score_metric
    from app.evals.base import JudgeConfig

    captured: dict = {}
    _capture_image_metric(monkeypatch, captured)
    score_metric(
        "image_coherence",
        _hydrated(_multimodal_sample()),
        JudgeConfig("openai", "model", "key"),
        {"max_context_size": 500},
    )
    test_case = captured["measure_args"][0]
    assert test_case.multimodal is True
    assert "[DEEPEVAL:IMAGE:" in test_case.actual_output
    assert captured["init_kwargs"]["max_context_size"] == 500
    assert "include_reason" not in captured["init_kwargs"]


def test_image_metric_without_actual_output_image_fails_before_measure(monkeypatch):
    from app.evals import deepeval
    from app.evals.base import JudgeConfig
    from app.evals.samples import MultimodalSample

    measured = False

    class Metric:
        def measure(self, test_case, **kwargs):
            nonlocal measured
            measured = True
            return 0.9

    monkeypatch.setattr(deepeval, "_make_metric", lambda *args: Metric())
    input_only_image = MultimodalSample.model_validate(
        {
            "kind": "multimodal",
            "input": [
                {"type": "text", "text": "Describe"},
                {"type": "image", "asset_id": "a1"},
            ],
            "actual_output": [
                {"type": "text", "text": "a plain text answer"}
            ],
        }
    )
    _hydrated(input_only_image)

    with pytest.raises(ValueError, match="image block in actual_output"):
        deepeval.score_metric(
            "image_coherence",
            input_only_image,
            JudgeConfig("openai", "model", "key"),
            {},
        )
    assert measured is False


def test_image_metric_with_unhydrated_block_fails_row(monkeypatch):
    from app.evals import deepeval
    from app.evals.base import JudgeConfig

    monkeypatch.setattr(deepeval, "_make_metric", lambda *args: object())
    with pytest.raises(ValueError, match="hydrated"):
        deepeval.score_metric(
            "image_helpfulness",
            _multimodal_sample(),
            JudgeConfig("openai", "model", "key"),
            {},
        )


def test_image_metrics_require_judge():
    from app.evals.deepeval import score_metric

    with pytest.raises(ValueError, match="requires a judge"):
        score_metric(
            "image_coherence", _hydrated(_multimodal_sample()), None, {}
        )


def test_score_metric_releases_only_current_marker_registry_entries(monkeypatch):
    from deepeval.test_case import MLLMImage
    from deepeval.test_case.llm_test_case import _MLLM_IMAGE_REGISTRY

    from app.evals.base import JudgeConfig
    from app.evals.deepeval import score_metric

    captured: dict = {}
    _capture_image_metric(monkeypatch, captured)
    unrelated = MLLMImage(dataBase64="dW5yZWxhdGVk", mimeType="image/png")
    before = set(_MLLM_IMAGE_REGISTRY)
    try:
        score_metric(
            "image_coherence",
            _hydrated(_multimodal_sample()),
            JudgeConfig("openai", "model", "key"),
            {},
        )
        assert set(_MLLM_IMAGE_REGISTRY) == before
        assert _MLLM_IMAGE_REGISTRY[unrelated._id] is unrelated
    finally:
        _MLLM_IMAGE_REGISTRY.pop(unrelated._id, None)


def test_score_metric_releases_registry_when_test_case_construction_raises(
    monkeypatch,
):
    from deepeval.test_case import MLLMImage
    from deepeval.test_case.llm_test_case import _MLLM_IMAGE_REGISTRY

    from app.evals import deepeval
    from app.evals.base import JudgeConfig
    from app.evals.samples import MultimodalSample

    monkeypatch.setattr(deepeval, "_make_metric", lambda *args: object())
    sample = MultimodalSample.model_validate(
        {
            "kind": "multimodal",
            "input": [{"type": "image", "asset_id": "input-image"}],
            "actual_output": [{"type": "image", "asset_id": "output-image"}],
        }
    )
    sample.input[0].data_base64 = "aGVsbG8="
    sample.input[0].mime_type = "image/png"
    unrelated = MLLMImage(dataBase64="dW5yZWxhdGVk", mimeType="image/png")
    before = set(_MLLM_IMAGE_REGISTRY)
    try:
        with pytest.raises(ValueError, match="hydrated"):
            deepeval.score_metric(
                "image_coherence",
                sample,
                JudgeConfig("openai", "model", "key"),
                {},
            )
        assert set(_MLLM_IMAGE_REGISTRY) == before
        assert _MLLM_IMAGE_REGISTRY[unrelated._id] is unrelated
    finally:
        _MLLM_IMAGE_REGISTRY.pop(unrelated._id, None)


def test_score_metric_releases_registry_even_when_measure_raises(monkeypatch):
    from deepeval.test_case import MLLMImage
    from deepeval.test_case.llm_test_case import _MLLM_IMAGE_REGISTRY

    from app.evals import deepeval
    from app.evals.base import JudgeConfig

    class ExplodingMetric:
        def __init__(self, **kwargs):
            pass

        def measure(self, test_case, **kwargs):
            raise RuntimeError("judge failed")

    from deepeval import metrics as deepeval_metrics

    monkeypatch.setattr(
        deepeval_metrics, "ImageCoherenceMetric", ExplodingMetric
    )
    unrelated = MLLMImage(dataBase64="dW5yZWxhdGVk", mimeType="image/png")
    before = set(_MLLM_IMAGE_REGISTRY)
    try:
        with pytest.raises(RuntimeError, match="judge failed"):
            deepeval.score_metric(
                "image_coherence",
                _hydrated(_multimodal_sample()),
                JudgeConfig("openai", "model", "key"),
                {},
            )
        assert set(_MLLM_IMAGE_REGISTRY) == before
        assert _MLLM_IMAGE_REGISTRY[unrelated._id] is unrelated
    finally:
        _MLLM_IMAGE_REGISTRY.pop(unrelated._id, None)
