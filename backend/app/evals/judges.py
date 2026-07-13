import asyncio
import json

from app.config import settings
from app.connections import openai_client_args
from app.evals.base import JudgeConfig

_OPENAI_TYPES = ("openai", "openai_compatible")
_TRUNCATED_MESSAGE = (
    "Judge hit the token limit; raise JUDGE_MAX_TOKENS or shorten the input"
)


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


def ragas_llm(judge: JudgeConfig):
    from ragas.llms import llm_factory

    # OpenAI-compatible gateways speak the OpenAI wire format; the base URL is
    # carried by the client, so ragas is told provider="openai".
    provider = "openai" if judge.provider in _OPENAI_TYPES else judge.provider
    return llm_factory(
        judge.model,
        provider=provider,
        client=_async_client(judge),
    )


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

        def load_model(self):
            return self.client

        def generate(self, prompt: str, schema=None):
            if judge.provider == "openai":
                if schema is not None:
                    response = self.client.chat.completions.parse(
                        model=judge.model,
                        messages=[{"role": "user", "content": prompt}],
                        response_format=schema,
                        max_tokens=settings.judge_max_tokens,
                    )
                    if response.choices[0].finish_reason == "length":
                        raise ValueError(_TRUNCATED_MESSAGE)
                    return response.choices[0].message.parsed
                response = self.client.chat.completions.create(
                    model=judge.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=settings.judge_max_tokens,
                )
                if response.choices[0].finish_reason == "length":
                    raise ValueError(_TRUNCATED_MESSAGE)
                return response.choices[0].message.content or ""

            if judge.provider == "openai_compatible":
                # Compatible gateways may not implement structured-output helpers;
                # use plain Chat Completions and parse the JSON ourselves.
                response = self.client.chat.completions.create(
                    model=judge.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=settings.judge_max_tokens,
                )
                if response.choices[0].finish_reason == "length":
                    raise ValueError(_TRUNCATED_MESSAGE)
                text = response.choices[0].message.content or ""
                if schema is None:
                    return text
                return _parse_schema(text, schema)

            response = self.client.messages.create(
                model=judge.model,
                max_tokens=settings.judge_max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
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
