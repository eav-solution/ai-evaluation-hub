import pytest
from pydantic import BaseModel

from app.evals.base import JudgeConfig
from app.evals.judges import deepeval_llm


class _Schema(BaseModel):
    score: int
    reasoning: str


class _FakeMessage:
    content = '{"score": 1, "reasoning": "ok"}'
    parsed = _Schema(score=1, reasoning="ok")


class _FakeChoice:
    message = _FakeMessage()
    finish_reason = "stop"


class _FakeCompletion:
    choices = [_FakeChoice()]
    usage = None


def _marker_prompt():
    from deepeval.test_case import MLLMImage

    image = MLLMImage(dataBase64="aGVsbG8=", mimeType="image/png")
    return f"Rate this. {image}", image


def _openai_judge(monkeypatch, captured, provider="openai_compatible"):
    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            captured["method"] = "create"
            return _FakeCompletion()

        def parse(self, **kwargs):
            captured.update(kwargs)
            captured["method"] = "parse"
            return _FakeCompletion()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("app.evals.judges._client", lambda judge: FakeClient())
    return JudgeConfig(
        provider=provider,
        model="local-vlm",
        api_key="k",
        base_url="https://gw.test" if provider == "openai_compatible" else None,
    )


def _anthropic_judge(monkeypatch, captured):
    class FakeBlock:
        text = '{"score": 1, "reasoning": "ok"}'

    class FakeResponse:
        content = [FakeBlock()]
        stop_reason = "end_turn"
        usage = None

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr("app.evals.judges._client", lambda judge: FakeClient())
    return JudgeConfig(
        provider="anthropic", model="claude-3-opus-20240229", api_key="k"
    )


@pytest.mark.parametrize(
    ("provider", "schema", "expected_method"),
    [
        pytest.param("openai", _Schema, "parse", id="native-structured"),
        pytest.param("openai", None, "create", id="native-plain"),
        pytest.param("openai_compatible", _Schema, "create", id="compatible-json"),
        pytest.param("openai_compatible", None, "create", id="compatible-plain"),
    ],
)
def test_openai_judge_builds_image_url_parts(
    monkeypatch, provider, schema, expected_method
):
    prompt, _image = _marker_prompt()
    captured: dict = {}
    judge = _openai_judge(monkeypatch, captured, provider)

    deepeval_llm(judge).generate(prompt, schema)

    assert captured["method"] == expected_method
    content = captured["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Rate this. "}
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aGVsbG8="},
    }


def test_anthropic_judge_builds_image_blocks(monkeypatch):
    prompt, _image = _marker_prompt()
    captured: dict = {}
    judge = _anthropic_judge(monkeypatch, captured)

    deepeval_llm(judge).generate(prompt)

    content = captured["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Rate this. "}
    assert content[1] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "aGVsbG8=",
        },
    }


@pytest.mark.parametrize(
    ("provider", "schema"),
    [
        pytest.param("openai", _Schema, id="native-structured"),
        pytest.param("openai", None, id="native-plain"),
        pytest.param("openai_compatible", _Schema, id="compatible-json"),
        pytest.param("openai_compatible", None, id="compatible-plain"),
    ],
)
def test_openai_plain_prompt_stays_string(monkeypatch, provider, schema):
    captured: dict = {}
    judge = _openai_judge(monkeypatch, captured, provider)

    deepeval_llm(judge).generate("plain text prompt", schema)

    assert captured["messages"][0]["content"] == "plain text prompt"


def test_anthropic_plain_prompt_stays_string(monkeypatch):
    captured: dict = {}
    judge = _anthropic_judge(monkeypatch, captured)

    deepeval_llm(judge).generate("plain text prompt")

    assert captured["messages"][0]["content"] == "plain text prompt"


def test_unhydrated_image_marker_raises(monkeypatch):
    from deepeval.test_case import MLLMImage

    captured: dict = {}
    judge = _openai_judge(monkeypatch, captured)
    image = MLLMImage(url="https://example.com/x.png")

    with pytest.raises(ValueError, match="hydrated"):
        deepeval_llm(judge).generate(f"Rate this. {image}")


def test_provider_llm_reports_multimodal_support(monkeypatch):
    judge = _openai_judge(monkeypatch, {})

    assert deepeval_llm(judge).supports_multimodal() is True
