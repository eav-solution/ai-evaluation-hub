from types import SimpleNamespace

import pytest


class _FakeMessage:
    def __init__(self, content):
        self.content = content
        self.parsed = None


class _FakeChoice:
    def __init__(self, content, finish_reason):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeCompletion:
    def __init__(self, content, finish_reason):
        self.choices = [_FakeChoice(content, finish_reason)]
        self.usage = SimpleNamespace(prompt_tokens=12, completion_tokens=4)


class _FakeCompletions:
    def __init__(self, store, content, finish_reason):
        self._store = store
        self._content = content
        self._finish_reason = finish_reason

    def create(self, **kwargs):
        self._store["create_kwargs"] = kwargs
        return _FakeCompletion(self._content, self._finish_reason)


class _FakeChat:
    def __init__(self, store, content, finish_reason):
        self.completions = _FakeCompletions(store, content, finish_reason)


class _FakeOpenAI:
    last: dict = {}
    content = "raw output"
    finish_reason = "stop"

    def __init__(self, **kwargs):
        _FakeOpenAI.last = {"init": kwargs}
        self.chat = _FakeChat(_FakeOpenAI.last, _FakeOpenAI.content, _FakeOpenAI.finish_reason)


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeAnthropicMessage:
    def __init__(self, text, stop_reason):
        self.content = [_FakeBlock(text)]
        self.stop_reason = stop_reason
        self.usage = SimpleNamespace(input_tokens=7, output_tokens=3)


class _FakeAnthropicMessages:
    def __init__(self, store, text, stop_reason):
        self._store = store
        self._text = text
        self._stop = stop_reason

    def create(self, **kwargs):
        self._store["create_kwargs"] = kwargs
        return _FakeAnthropicMessage(self._text, self._stop)


class _FakeAnthropic:
    last: dict = {}
    text = "raw output"
    stop_reason = "end_turn"

    def __init__(self, **kwargs):
        _FakeAnthropic.last = {"init": kwargs}
        self.messages = _FakeAnthropicMessages(
            _FakeAnthropic.last, _FakeAnthropic.text, _FakeAnthropic.stop_reason
        )


@pytest.fixture(autouse=True)
def _reset_fakes():
    _FakeOpenAI.content = "raw output"
    _FakeOpenAI.finish_reason = "stop"
    _FakeAnthropic.text = "raw output"
    _FakeAnthropic.stop_reason = "end_turn"
    yield


def test_openai_client_args_keyless_strips_auth():
    import httpx

    from app.connections import openai_client_args

    args = openai_client_args("openai_compatible", "http://h/v1", None, async_=False)
    assert args["base_url"] == "http://h/v1"
    assert args["api_key"]  # placeholder present so the SDK constructs
    client = args["http_client"]
    request = httpx.Request(
        "GET", "http://h/v1/models", headers={"Authorization": "Bearer placeholder"}
    )
    for hook in client.event_hooks["request"]:
        hook(request)
    assert "authorization" not in request.headers


def test_openai_client_args_keyed_no_custom_http_client():
    from app.connections import openai_client_args

    args = openai_client_args("openai_compatible", "http://h/v1", "sk-real", async_=False)
    assert args["api_key"] == "sk-real"
    assert "http_client" not in args


def test_openai_client_args_native_has_no_base_url():
    from app.connections import openai_client_args

    args = openai_client_args("openai", None, "sk-native", async_=False)
    assert args == {"api_key": "sk-native"}


def test_deepeval_llm_custom_parses_json_without_parse_helper(monkeypatch):
    import openai
    from pydantic import BaseModel

    from app.evals.base import JudgeConfig
    from app.evals.judges import deepeval_llm

    class Schema(BaseModel):
        verdict: str

    _FakeOpenAI.content = 'Here is the result: {"verdict": "yes"} thanks'
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    judge = JudgeConfig(
        provider="openai_compatible", model="m", api_key=None, base_url="http://h/v1"
    )
    llm = deepeval_llm(judge)
    result = llm.generate("prompt", Schema)
    assert isinstance(result, Schema)
    assert result.verdict == "yes"
    # plain create() used, never the structured-output parse helper
    assert "response_format" not in _FakeOpenAI.last["create_kwargs"]
    assert _FakeOpenAI.last["create_kwargs"]["messages"][0]["content"] == "prompt"


def test_ragas_embeddings_custom_requires_embedding_model():
    from app.evals.base import JudgeConfig
    from app.evals.judges import ragas_embeddings

    judge = JudgeConfig(
        provider="openai_compatible",
        model="m",
        api_key=None,
        base_url="http://h/v1",
        embedding_model=None,
    )
    with pytest.raises(ValueError):
        ragas_embeddings(judge)


def test_deepeval_custom_raises_on_truncation(monkeypatch):
    import openai

    from app.evals.base import JudgeConfig
    from app.evals.judges import deepeval_llm

    _FakeOpenAI.finish_reason = "length"
    _FakeOpenAI.content = "partial"
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    judge = JudgeConfig(
        provider="openai_compatible", model="m", api_key=None, base_url="http://h/v1"
    )
    llm = deepeval_llm(judge)
    with pytest.raises(ValueError, match="token limit"):
        llm.generate("prompt")


def test_deepeval_judge_uses_judge_max_tokens(monkeypatch):
    import openai

    from app.config import settings
    from app.evals.base import JudgeConfig
    from app.evals.judges import deepeval_llm

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    judge = JudgeConfig(
        provider="openai_compatible", model="m", api_key=None, base_url="http://h/v1"
    )
    deepeval_llm(judge).generate("prompt")
    assert _FakeOpenAI.last["create_kwargs"]["max_tokens"] == settings.judge_max_tokens


def test_deepeval_judge_tracks_usage_without_pricing_custom_models(monkeypatch):
    import openai

    from app.evals.base import JudgeConfig
    from app.evals.judges import deepeval_llm, usage_snapshot

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    judge = JudgeConfig(
        provider="openai_compatible",
        model="gpt-4o-mini",
        api_key=None,
        base_url="http://h/v1",
    )
    llm = deepeval_llm(judge)
    llm.generate("prompt")

    usage, estimated_cost = usage_snapshot(llm)
    assert usage == {"input_tokens": 12, "output_tokens": 4}
    assert estimated_cost is None


def test_native_openai_usage_uses_known_model_prices(monkeypatch):
    import openai

    from app.evals.base import JudgeConfig
    from app.evals.judges import deepeval_llm, usage_snapshot

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    llm = deepeval_llm(JudgeConfig("openai", "gpt-4o-mini", "sk-test"))
    llm.generate("prompt")

    usage, estimated_cost = usage_snapshot(llm)
    assert usage == {"input_tokens": 12, "output_tokens": 4}
    assert estimated_cost == pytest.approx(4.2e-6)


def test_native_anthropic_usage_uses_provider_token_fields(monkeypatch):
    import anthropic

    from app.evals.base import JudgeConfig
    from app.evals.judges import deepeval_llm, usage_snapshot

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    llm = deepeval_llm(
        JudgeConfig("anthropic", "claude-3-5-sonnet-20241022", "sk-test")
    )
    llm.generate("prompt")

    usage, estimated_cost = usage_snapshot(llm)
    assert usage == {"input_tokens": 7, "output_tokens": 3}
    assert estimated_cost == pytest.approx(66e-6)


def test_ragas_judge_tracks_usage_from_completion_hook(monkeypatch):
    import ragas.llms as ragas_llms

    from app.evals import judges
    from app.evals.base import JudgeConfig

    captured = {}

    class Hooks:
        def on(self, event, handler):
            captured[event] = handler

    llm = SimpleNamespace(client=SimpleNamespace(hooks=Hooks()))
    monkeypatch.setattr(judges, "_async_client", lambda judge: object())
    monkeypatch.setattr(ragas_llms, "llm_factory", lambda *args, **kwargs: llm)

    result = judges.ragas_llm(
        JudgeConfig("openai_compatible", "model", None, "http://h/v1")
    )
    captured["completion:response"](
        SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=9, completion_tokens=2)
        )
    )

    assert judges.usage_snapshot(result) == (
        {"input_tokens": 9, "output_tokens": 2},
        None,
    )


def test_ragas_embeddings_uses_separate_embedding_connection(monkeypatch):
    import openai
    import ragas.embeddings as ragas_embeddings_module

    from app.evals import judges
    from app.evals.base import JudgeConfig

    captured = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client_init"] = kwargs

    def fake_embedding_factory(provider, model=None, client=None, **kwargs):
        captured["provider"] = provider
        captured["model"] = model
        return "EMBEDDINGS"

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setattr(ragas_embeddings_module, "embedding_factory", fake_embedding_factory)

    # judge LLM is Anthropic (no embeddings); embeddings come from a custom connection
    judge = JudgeConfig(
        provider="anthropic",
        model="claude",
        api_key="ak",
        base_url=None,
        embedding_model="text-embed",
        embedding_provider="openai_compatible",
        embedding_base_url="http://emb/v1",
        embedding_api_key=None,
    )
    assert judges.ragas_embeddings(judge) == "EMBEDDINGS"
    assert captured["model"] == "text-embed"
    # the async client was built against the EMBEDDING base URL, not the judge
    assert captured["client_init"]["base_url"] == "http://emb/v1"


def test_ragas_embeddings_rejects_non_embedding_provider():
    from app.evals.base import JudgeConfig
    from app.evals.judges import ragas_embeddings

    judge = JudgeConfig(
        provider="openai",
        model="gpt",
        api_key="k",
        embedding_provider="anthropic",  # cannot embed
        embedding_model="whatever",
    )
    with pytest.raises(ValueError):
        ragas_embeddings(judge)
