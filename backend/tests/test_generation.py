import pytest


def test_distribute_evenly_spreads_remainder_to_earliest():
    from app.generation import distribute_evenly

    assert distribute_evenly(7, 3, 5) == [3, 2, 2]
    assert distribute_evenly(6, 2, 3) == [3, 3]
    assert distribute_evenly(1, 3, 5) == [1, 0, 0]


def test_distribute_proportional_matches_total():
    from app.generation import distribute_proportional

    quotas = distribute_proportional(10, [300, 100])
    assert sum(quotas) == 10
    assert quotas == [8, 2]


def test_build_units_chunk_mode_assigns_quota_and_context_index():
    from app.generation import build_units

    paragraph = "This paragraph is long enough to be its own chunk for the test. " * 5
    documents = [("doc1", f"{paragraph}\n\n{paragraph}")]
    units = build_units(
        documents,
        "chunk",
        4,
        chunk_chars=len(paragraph) + 10,
        context_chars=300_000,
        questions_per_chunk=3,
    )
    assert len(units) == 2
    assert [unit.quota for unit in units] == [2, 2]
    assert units[0].document_id == "doc1"
    assert units[0].chunk_index == 0
    assert units[1].chunk_index == 1


def test_build_units_document_mode_single_unit_when_text_fits():
    from app.generation import build_units

    documents = [("doc1", "Some source text. " * 20)]
    units = build_units(
        documents,
        "document",
        5,
        chunk_chars=2000,
        context_chars=300_000,
        questions_per_chunk=3,
    )
    assert len(units) == 1
    assert units[0].chunk_index is None
    assert units[0].quota == 5


def test_build_units_document_mode_splits_oversized_document():
    from app.generation import build_units

    paragraph = "Sentence for the split test goes right here. " * 10
    text = "\n\n".join([paragraph] * 8)
    units = build_units(
        [("doc1", text)],
        "document",
        8,
        chunk_chars=len(paragraph) + 10,
        context_chars=len(paragraph) * 3,
        questions_per_chunk=3,
    )
    assert len(units) > 1
    assert sum(unit.quota for unit in units) == 8
    assert all(len(unit.text) <= len(paragraph) * 3 for unit in units)


def test_build_prompt_language_rules():
    from app.generation import build_prompt

    default = build_prompt("TEXT", 3, None)
    assert "same language as the source text" in default
    override = build_prompt("TEXT", 3, "Vietnamese")
    assert "in Vietnamese" in override
    assert "TEXT" in default


def test_normalize_question_casefold_and_whitespace():
    from app.generation import normalize_question

    assert normalize_question("  What IS\n EvalHub? ") == "what is evalhub?"


def test_qa_item_strips_text_and_rejects_blank_question_or_answer():
    from pydantic import ValidationError

    from app.generation import QAItem

    item = QAItem(question="  Q?  ", answer="  A.  ", context="  C  ")
    assert (item.question, item.answer, item.context) == ("Q?", "A.", "C")
    with pytest.raises(ValidationError):
        QAItem(question="   ", answer="A.", context="C")
    with pytest.raises(ValidationError):
        QAItem(question="Q?", answer="   ", context="C")


def test_generate_qa_rejects_unknown_provider():
    from app.generation import GeneratorConfig, generate_qa

    with pytest.raises(ValueError):
        generate_qa("text", 1, GeneratorConfig("mystery", "m", "k"), None)


@pytest.mark.parametrize(
    ("provider", "method", "strict"),
    [
        ("openai", "json_schema", True),
        ("openai_compatible", "json_mode", None),
    ],
)
def test_generate_qa_uses_langchain_structured_output(
    monkeypatch, provider, method, strict
):
    import langchain_openai
    import openai

    from app.generation import GeneratorConfig, QAItem, QAResponse, generate_qa

    captured = {}

    class Raw:
        response_metadata = {"finish_reason": "stop"}

    class Structured:
        def invoke(self, prompt):
            captured["prompt"] = prompt
            parsed = QAResponse(
                items=[QAItem(question="Q?", answer="A.", context="C")]
            )
            return {"raw": Raw(), "parsed": parsed, "parsing_error": None}

    class ChatModel:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def with_structured_output(self, schema, **kwargs):
            captured["schema"] = schema
            captured["structured"] = kwargs
            return Structured()

    class DirectSdkMustNotBeUsed:
        def __init__(self, **kwargs):
            raise AssertionError("direct OpenAI SDK was used")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", ChatModel)
    monkeypatch.setattr(openai, "OpenAI", DirectSdkMustNotBeUsed)
    config = GeneratorConfig(
        provider=provider,
        model="model",
        api_key="key",
        base_url="http://llama/v1" if provider == "openai_compatible" else None,
    )

    items = generate_qa("SOURCE", 1, config)

    assert items == [QAItem(question="Q?", answer="A.", context="C")]
    assert captured["structured"] == {
        "method": method,
        "include_raw": True,
        **({"strict": strict} if strict is not None else {}),
    }
    assert captured["init"]["model"] == "model"
    assert "SOURCE" in captured["prompt"]
    assert "at most 1" in captured["prompt"]
    if provider == "openai_compatible":
        assert captured["init"]["base_url"] == "http://llama/v1"


def test_generate_qa_uses_langchain_anthropic_structured_output(monkeypatch):
    import langchain_anthropic

    from app.generation import GeneratorConfig, QAItem, QAResponse, generate_qa

    captured = {}

    class Raw:
        response_metadata = {"stop_reason": "end_turn"}

    class Structured:
        def invoke(self, prompt):
            parsed = QAResponse(
                items=[QAItem(question="Q?", answer="A.", context="C")]
            )
            return {"raw": Raw(), "parsed": parsed, "parsing_error": None}

    class ChatModel:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def with_structured_output(self, schema, **kwargs):
            captured["structured"] = kwargs
            return Structured()

    monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", ChatModel)

    items = generate_qa("SOURCE", 1, GeneratorConfig("anthropic", "claude", "key"))

    assert items == [QAItem(question="Q?", answer="A.", context="C")]
    assert captured["structured"] == {"include_raw": True}
    assert captured["init"]["model"] == "claude"


@pytest.mark.parametrize(
    "metadata",
    [{"finish_reason": "length"}, {"stop_reason": "max_tokens"}],
)
def test_structured_result_reports_token_limit(metadata):
    from app.generation import QAResponse, _items_from_result

    raw = type("Raw", (), {"response_metadata": metadata})()
    with pytest.raises(ValueError, match="token limit"):
        _items_from_result(
            {"raw": raw, "parsed": QAResponse(items=[]), "parsing_error": None}
        )


def test_structured_result_reports_bounded_validation_error():
    from app.generation import _items_from_result

    error = ValueError("bad\noutput " + "x" * 1000)
    with pytest.raises(ValueError) as caught:
        _items_from_result({"raw": None, "parsed": None, "parsing_error": error})

    assert "invalid structured output" in str(caught.value)
    assert "\n" not in str(caught.value)
    assert len(str(caught.value)) < 560
