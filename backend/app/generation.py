from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.documents import chunk_text

_TRUNCATED_MESSAGE = (
    "Generator hit the token limit; reduce questions per chunk or raise "
    "GENERATION_MAX_TOKENS"
)

@dataclass(frozen=True)
class GeneratorConfig:
    provider: str  # 'openai' | 'anthropic' | 'openai_compatible'
    model: str
    api_key: str | None
    base_url: str | None = None


@dataclass(frozen=True)
class GenerationUnit:
    document_id: str
    chunk_index: int | None
    text: str
    quota: int


class QAItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    context: str


class QAResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[QAItem]


_PROMPT = """You are building an evaluation dataset from source material.
Generate at most {count} question-answer pairs strictly grounded in the SOURCE TEXT below.
Rules:
- Every question must be answerable from the source text alone; never invent facts.
- If the text supports fewer than {count} distinct questions, return fewer.
- Questions must be distinct from each other.
- Answers are concise and factual.
- "context" is a short verbatim excerpt from the source text that supports the answer.
- {language_rule}
Return ONLY a JSON object, no prose: {{"items": [{{"question": "...", "answer": "...", "context": "..."}}]}}

SOURCE TEXT:
{text}"""


def build_prompt(text: str, count: int, language: str | None) -> str:
    language_rule = (
        f"Write questions and answers in {language}."
        if language
        else "Write questions and answers in the same language as the source text."
    )
    return _PROMPT.format(count=count, language_rule=language_rule, text=text)


def distribute_evenly(total: int, buckets: int, cap: int) -> list[int]:
    base, remainder = divmod(total, buckets)
    quotas = [base + 1 if index < remainder else base for index in range(buckets)]
    return [min(quota, cap) for quota in quotas]


def distribute_proportional(total: int, weights: list[int]) -> list[int]:
    weight_sum = sum(weights)
    shares = [total * weight / weight_sum for weight in weights]
    quotas = [int(share) for share in shares]
    by_remainder = sorted(
        range(len(weights)), key=lambda index: shares[index] - quotas[index], reverse=True
    )
    for index in by_remainder[: total - sum(quotas)]:
        quotas[index] += 1
    return quotas


def build_units(
    documents: list[tuple[str, str]],
    mode: str,
    requested: int,
    *,
    chunk_chars: int,
    context_chars: int,
    questions_per_chunk: int,
) -> list[GenerationUnit]:
    if mode == "chunk":
        chunks = [
            (document_id, chunk_index, chunk)
            for document_id, text in documents
            for chunk_index, chunk in enumerate(chunk_text(text, chunk_chars))
        ]
        if not chunks:
            return []
        quotas = distribute_evenly(requested, len(chunks), questions_per_chunk)
        return [
            GenerationUnit(document_id, chunk_index, chunk, quota)
            for (document_id, chunk_index, chunk), quota in zip(chunks, quotas)
            if quota > 0
        ]

    pieces: list[tuple[str, int | None, str]] = []
    for document_id, text in documents:
        if len(text) <= context_chars:
            pieces.append((document_id, None, text))
            continue
        piece_index = 0
        current = ""
        for chunk in chunk_text(text, chunk_chars):
            if current and len(current) + len(chunk) + 2 > context_chars:
                pieces.append((document_id, piece_index, current))
                piece_index += 1
                current = chunk
            else:
                current = f"{current}\n\n{chunk}" if current else chunk
        if current:
            pieces.append((document_id, piece_index, current))
    if not pieces:
        return []
    quotas = distribute_proportional(requested, [len(text) for _, _, text in pieces])
    return [
        GenerationUnit(document_id, chunk_index, text, quota)
        for (document_id, chunk_index, text), quota in zip(pieces, quotas)
        if quota > 0
    ]


def normalize_question(question: str) -> str:
    return " ".join(question.split()).casefold()


def _structured_model(config: GeneratorConfig):
    if config.provider in ("openai", "openai_compatible"):
        from langchain_openai import ChatOpenAI

        from app.connections import openai_client_args

        model = ChatOpenAI(
            model=config.model,
            max_tokens=settings.generation_max_tokens,
            **openai_client_args(
                config.provider, config.base_url, config.api_key, async_=False
            ),
        )
        if config.provider == "openai_compatible":
            return model.with_structured_output(
                QAResponse, method="json_mode", include_raw=True
            )
        return model.with_structured_output(
            QAResponse, method="json_schema", strict=True, include_raw=True
        )
    if config.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        model = ChatAnthropic(
            model=config.model,
            api_key=config.api_key,
            max_tokens=settings.generation_max_tokens,
        )
        return model.with_structured_output(QAResponse, include_raw=True)
    raise ValueError(f"Unsupported generator provider: {config.provider}")


def _items_from_result(result: dict) -> list[QAItem]:
    metadata = getattr(result.get("raw"), "response_metadata", {})
    if (
        metadata.get("finish_reason") == "length"
        or metadata.get("stop_reason") == "max_tokens"
    ):
        raise ValueError(_TRUNCATED_MESSAGE)
    if error := result.get("parsing_error"):
        detail = " ".join(str(error).split())[:500]
        raise ValueError(
            f"Generator returned invalid structured output: {detail}"
        ) from error
    parsed = result.get("parsed")
    if not isinstance(parsed, QAResponse) or not parsed.items:
        raise ValueError("Generator returned no usable records")
    return parsed.items


def generate_qa(
    text: str,
    count: int,
    config: GeneratorConfig,
    language: str | None = None,
) -> list[QAItem]:
    if config.provider not in {"openai", "anthropic", "openai_compatible"}:
        raise ValueError(f"Unsupported generator provider: {config.provider}")
    result = _structured_model(config).invoke(build_prompt(text, count, language))
    return _items_from_result(result)
