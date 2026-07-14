import pytest
from pydantic import TypeAdapter, ValidationError


def test_typed_sample_union_parses_all_four_kinds():
    from app.evals.samples import EvaluationSample

    adapter = TypeAdapter(EvaluationSample)
    samples = [
        {"kind": "single_turn", "input": "q", "actual_output": "a"},
        {
            "kind": "agent_trace",
            "input": "q",
            "actual_output": "a",
            "agent_trace": [{"type": "tool", "name": "search"}],
        },
        {
            "kind": "conversation",
            "turns": [{"role": "user", "content": "hello"}],
            "chatbot_role": "support",
        },
        {
            "kind": "multimodal",
            "input": [{"type": "text", "text": "describe"}],
            "actual_output": [{"type": "image", "asset_id": "asset-1"}],
        },
    ]

    assert [adapter.validate_python(item).kind for item in samples] == [
        "single_turn",
        "agent_trace",
        "conversation",
        "multimodal",
    ]


def test_typed_sample_union_rejects_unknown_kind_and_unresolved_image():
    from app.evals.samples import EvaluationSample

    adapter = TypeAdapter(EvaluationSample)
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "mcp"})
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "kind": "multimodal",
                "input": [{"type": "image", "asset_id": ""}],
                "actual_output": [{"type": "text", "text": "answer"}],
            }
        )


def test_single_turn_keeps_legacy_context_accessor():
    from app.evals.base import EvalRow
    from app.evals.samples import SingleTurnSample

    sample = SingleTurnSample(
        input="q",
        actual_output="a",
        retrieval_contexts=["retrieved"],
    )

    assert sample.contexts == ["retrieved"]
    assert sample.normalizer_revision == "1"
    assert EvalRow is SingleTurnSample
