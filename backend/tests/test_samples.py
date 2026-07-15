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


def test_agent_trace_sample_accepts_nested_events_and_tool_name_shorthand():
    from app.evals.samples import AgentTraceSample

    sample = AgentTraceSample.model_validate(
        {
            "kind": "agent_trace",
            "input": "Book a flight",
            "actual_output": "Booked",
            "agent_trace": [
                {
                    "type": "agent",
                    "name": "planner",
                    "children": [{"type": "tool", "name": "search"}],
                }
            ],
            "expected_tools": ["search", {"name": "book", "arguments": {}}],
        }
    )

    assert sample.agent_trace[0].children[0].name == "search"
    assert [tool.name for tool in sample.expected_tools] == ["search", "book"]


def test_agent_trace_sample_rejects_empty_trace():
    from app.evals.samples import AgentTraceSample

    with pytest.raises(ValidationError):
        AgentTraceSample(input="q", actual_output="a", agent_trace=[])


def test_agent_trace_sample_rejects_unknown_nested_fields():
    from app.evals.samples import AgentTraceSample

    with pytest.raises(ValidationError):
        AgentTraceSample.model_validate(
            {
                "input": "q",
                "actual_output": "a",
                "agent_trace": [{"type": "tool", "unknown": True}],
            }
        )


def test_conversation_sample_accepts_typed_mcp_metadata():
    from app.evals.samples import ConversationSample

    sample = ConversationSample.model_validate(
        {
            "kind": "conversation",
            "turns": [
                {"role": "user", "content": "Book a room"},
                {"role": "assistant", "content": "Booked room 12"},
            ],
            "chatbot_role": "hotel concierge",
            "mcp_metadata": {
                "servers": [
                    {"server_name": "booking", "transport": "stdio"}
                ]
            },
            "mcp_events": [
                {
                    "type": "tool",
                    "name": "reserve",
                    "payload": {
                        "args": {"room": 12},
                        "result": "ok",
                    },
                }
            ],
        }
    )

    assert sample.mcp_metadata.servers[0].server_name == "booking"
    assert sample.mcp_events[0].payload["args"] == {"room": 12}


def test_conversation_sample_defaults_are_backward_compatible():
    from app.evals.samples import ConversationSample

    sample = ConversationSample.model_validate(
        {
            "kind": "conversation",
            "turns": [{"role": "user", "content": "hi"}],
        }
    )

    assert sample.chatbot_role is None
    assert sample.mcp_metadata.servers == []
    assert sample.mcp_events == []


def test_conversation_sample_rejects_empty_turns_and_unknown_metadata_keys():
    from app.evals.samples import ConversationSample

    with pytest.raises(ValidationError):
        ConversationSample.model_validate({"kind": "conversation", "turns": []})
    with pytest.raises(ValidationError):
        ConversationSample.model_validate(
            {
                "kind": "conversation",
                "turns": [{"role": "user", "content": "hi"}],
                "mcp_metadata": {"servers": [], "unexpected": True},
            }
        )


def test_conversation_previews_pick_first_user_and_last_assistant():
    from app.evals.samples import (
        ConversationSample,
        conversation_actual_preview,
        conversation_input_preview,
    )

    sample = ConversationSample.model_validate(
        {
            "kind": "conversation",
            "turns": [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "first answer"},
                {"role": "user", "content": "second question"},
                {"role": "assistant", "content": "final answer"},
            ],
        }
    )

    assert conversation_input_preview(sample) == "first question"
    assert conversation_actual_preview(sample) == "final answer"
