import asyncio
import json
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.connections import openai_client_args
from app.evals.base import JudgeConfig

_OPENAI_TYPES = ("openai", "openai_compatible")
_TRUNCATED_MESSAGE = (
    "Judge hit the token limit; raise JUDGE_MAX_TOKENS or shorten the input"
)


def _usage_value(usage: Any, *names: str) -> int:
    for name in names:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if value is not None:
            return int(value)
    return 0


def _model_prices(provider: str, model: str) -> tuple[float, float] | None:
    if provider == "openai":
        from deepeval.models.llms.constants import OPENAI_MODELS_DATA

        registry = OPENAI_MODELS_DATA
    elif provider == "anthropic":
        from deepeval.models.llms.constants import ANTHROPIC_MODELS_DATA

        registry = ANTHROPIC_MODELS_DATA
    else:
        return None
    if model not in registry:
        return None
    model_data = registry[model]
    if model_data.input_price is None or model_data.output_price is None:
        return None
    return float(model_data.input_price), float(model_data.output_price)


@dataclass
class UsageTracker:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    observed: bool = False

    def record_response(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        self.input_tokens += _usage_value(usage, "input_tokens", "prompt_tokens")
        self.output_tokens += _usage_value(
            usage, "output_tokens", "completion_tokens"
        )
        self.observed = True

    def snapshot(self) -> tuple[dict[str, int] | None, float | None]:
        if not self.observed:
            return None, None
        usage = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }
        prices = _model_prices(self.provider, self.model)
        estimated_cost = (
            self.input_tokens * prices[0] + self.output_tokens * prices[1]
            if prices is not None
            else None
        )
        return usage, estimated_cost


def usage_snapshot(model: Any) -> tuple[dict[str, int] | None, float | None]:
    tracker = getattr(model, "_evalhub_usage_tracker", None)
    return tracker.snapshot() if isinstance(tracker, UsageTracker) else (None, None)


def _client(judge: JudgeConfig):
    if judge.provider in _OPENAI_TYPES:
        from openai import OpenAI

        return OpenAI(
            **openai_client_args(
                judge.provider, judge.base_url, judge.api_key, async_=False
            )
        )
    if judge.provider == "anthropic":
        from anthropic import Anthropic

        return Anthropic(api_key=judge.api_key)
    raise ValueError(f"Unsupported judge provider: {judge.provider}")


def _async_openai_from(provider: str, base_url: str | None, api_key: str | None):
    from openai import AsyncOpenAI

    return AsyncOpenAI(**openai_client_args(provider, base_url, api_key, async_=True))


def _async_client(judge: JudgeConfig):
    # Ragas metric.score() drives an async pipeline that calls llm.agenerate(),
    # which rejects a synchronous client. Give the ragas path an async client.
    if judge.provider in _OPENAI_TYPES:
        return _async_openai_from(judge.provider, judge.base_url, judge.api_key)
    if judge.provider == "anthropic":
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(api_key=judge.api_key)
    raise ValueError(f"Unsupported judge provider: {judge.provider}")


def _parse_schema(text: str, schema):
    """Parse a schema object from free-form model text (no structured-output API)."""
    try:
        return schema.model_validate_json(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise
        return schema.model_validate(json.loads(text[start : end + 1]))


def _split_marker_prompt(prompt: str):
    """Return None for plain prompts, else parsed text and image segments."""
    from deepeval.test_case import MLLMImage

    if "[DEEPEVAL:" not in prompt:
        return None
    # DeepEval 4.1.0 exposes this parser on MLLMImage. Task 4 locks the contract.
    segments = MLLMImage.parse_multimodal_string(prompt)
    if all(isinstance(segment, str) for segment in segments):
        return None
    return segments


def _openai_content(segments) -> list[dict]:
    parts = []
    for segment in segments:
        if isinstance(segment, str):
            if segment:
                parts.append({"type": "text", "text": segment})
            continue
        if not segment.dataBase64 or not segment.mimeType:
            raise ValueError("Image was not hydrated before the judge call")
        parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{segment.mimeType};base64,{segment.dataBase64}"
                },
            }
        )
    return parts


def _anthropic_content(segments) -> list[dict]:
    parts = []
    for segment in segments:
        if isinstance(segment, str):
            if segment:
                parts.append({"type": "text", "text": segment})
            continue
        if not segment.dataBase64 or not segment.mimeType:
            raise ValueError("Image was not hydrated before the judge call")
        parts.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": segment.mimeType,
                    "data": segment.dataBase64,
                },
            }
        )
    return parts


def ragas_llm(judge: JudgeConfig):
    from ragas.llms import llm_factory

    # OpenAI-compatible gateways speak the OpenAI wire format; the base URL is
    # carried by the client, so ragas is told provider="openai".
    provider = "openai" if judge.provider in _OPENAI_TYPES else judge.provider
    llm = llm_factory(
        judge.model,
        provider=provider,
        client=_async_client(judge),
    )
    tracker = UsageTracker(judge.provider, judge.model)
    llm.client.hooks.on("completion:response", tracker.record_response)
    llm._evalhub_usage_tracker = tracker
    return llm


def ragas_embeddings(judge: JudgeConfig):
    from ragas.embeddings import embedding_factory

    # Embeddings use their own connection, independent of the judge LLM.
    provider = judge.embedding_provider
    if provider not in _OPENAI_TYPES:
        raise ValueError(
            "Answer relevancy needs an OpenAI or OpenAI-compatible embedding connection"
        )
    if not judge.embedding_model:
        raise ValueError("An embedding model is required for answer relevancy")
    client = _async_openai_from(
        provider, judge.embedding_base_url, judge.embedding_api_key
    )
    return embedding_factory("openai", model=judge.embedding_model, client=client)


def deepeval_llm(judge: JudgeConfig):
    from deepeval.models.base_model import DeepEvalBaseLLM

    class ProviderLLM(DeepEvalBaseLLM):
        def __init__(self):
            self.client = _client(judge)
            self._evalhub_usage_tracker = UsageTracker(judge.provider, judge.model)

        def load_model(self):
            return self.client

        def supports_multimodal(self):
            return True

        def generate(self, prompt: str, schema=None):
            segments = _split_marker_prompt(prompt)
            content = prompt
            if segments is not None:
                content = (
                    _openai_content(segments)
                    if judge.provider in _OPENAI_TYPES
                    else _anthropic_content(segments)
                )
            if judge.provider == "openai":
                if schema is not None:
                    response = self.client.chat.completions.parse(
                        model=judge.model,
                        messages=[{"role": "user", "content": content}],
                        response_format=schema,
                        max_tokens=settings.judge_max_tokens,
                    )
                    self._evalhub_usage_tracker.record_response(response)
                    if response.choices[0].finish_reason == "length":
                        raise ValueError(_TRUNCATED_MESSAGE)
                    return response.choices[0].message.parsed
                response = self.client.chat.completions.create(
                    model=judge.model,
                    messages=[{"role": "user", "content": content}],
                    max_tokens=settings.judge_max_tokens,
                )
                self._evalhub_usage_tracker.record_response(response)
                if response.choices[0].finish_reason == "length":
                    raise ValueError(_TRUNCATED_MESSAGE)
                return response.choices[0].message.content or ""

            if judge.provider == "openai_compatible":
                # Compatible gateways may not implement structured-output helpers;
                # use plain Chat Completions and parse the JSON ourselves.
                response = self.client.chat.completions.create(
                    model=judge.model,
                    messages=[{"role": "user", "content": content}],
                    max_tokens=settings.judge_max_tokens,
                )
                self._evalhub_usage_tracker.record_response(response)
                if response.choices[0].finish_reason == "length":
                    raise ValueError(_TRUNCATED_MESSAGE)
                text = response.choices[0].message.content or ""
                if schema is None:
                    return text
                return _parse_schema(text, schema)

            response = self.client.messages.create(
                model=judge.model,
                max_tokens=settings.judge_max_tokens,
                messages=[{"role": "user", "content": content}],
            )
            self._evalhub_usage_tracker.record_response(response)
            if response.stop_reason == "max_tokens":
                raise ValueError(_TRUNCATED_MESSAGE)
            text = "".join(block.text for block in response.content if hasattr(block, "text"))
            if schema is None:
                return text
            return _parse_schema(text, schema)

        async def a_generate(self, prompt: str, schema=None):
            return await asyncio.to_thread(self.generate, prompt, schema)

        def get_model_name(self):
            return f"{judge.provider}:{judge.model}"

    return ProviderLLM()


def deterministic_deepeval_llm():
    from deepeval.models.base_model import DeepEvalBaseLLM

    class DeterministicLLM(DeepEvalBaseLLM):
        def load_model(self):
            return self

        def generate(self, *args, **kwargs):
            raise RuntimeError("Deterministic metric attempted to call an LLM")

        async def a_generate(self, *args, **kwargs):
            raise RuntimeError("Deterministic metric attempted to call an LLM")

        def get_model_name(self):
            return "evalhub-deterministic"

    return DeterministicLLM()
