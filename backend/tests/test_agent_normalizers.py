import pytest


AGENT_MAPPING = {
    "input": "prompt",
    "actual_output": "answer",
    "agent_trace": "trace_json",
    "tools_called": "called_json",
    "expected_tools": "expected_json",
}


def test_normalize_agent_sample_decodes_csv_structured_fields():
    from app.evals.normalizers import normalize_sample

    sample = normalize_sample(
        "agent_trace",
        {
            "prompt": "Find weather",
            "answer": "Sunny",
            "trace_json": '[{"type":"tool","name":"weather"}]',
            "called_json": (
                '[{"name":"weather","arguments":{"city":"Paris"}}]'
            ),
            "expected_json": '["weather"]',
        },
        AGENT_MAPPING,
    )

    assert sample.kind == "agent_trace"
    assert sample.agent_trace[0].name == "weather"
    assert sample.tools_called[0].arguments == {"city": "Paris"}
    assert sample.expected_tools[0].name == "weather"


def test_normalize_agent_sample_preserves_native_objects_and_source():
    from app.evals.normalizers import normalize_sample

    sample = normalize_sample(
        "agent_trace",
        {
            "prompt": "Find weather",
            "answer": "Sunny",
            "trace_json": [{"type": "tool", "name": "weather"}],
            "called_json": [{"name": "weather", "output": "Sunny"}],
            "expected_json": ["weather"],
        },
        AGENT_MAPPING,
        source_ref={"row_index": 4, "external_id": "sample-5"},
    )

    assert sample.source.row_index == 4
    assert sample.source.external_id == "sample-5"
    assert sample.tools_called[0].output == "Sunny"


def test_normalize_agent_sample_preserves_ingested_metadata_and_tags():
    from app.evals.normalizers import normalize_sample

    source = {
        "kind": "agent_trace",
        "input": "Find weather",
        "actual_output": "Sunny",
        "agent_trace": [{"type": "tool", "name": "weather"}],
        "tools_called": [],
        "expected_tools": [],
        "metadata": {"session": "abc-123"},
        "tags": ["prod", "canary"],
    }

    sample = normalize_sample(
        "agent_trace",
        source,
        {field: field for field in source},
    )

    assert sample.metadata == {"session": "abc-123"}
    assert sample.tags == ["prod", "canary"]


def test_normalize_agent_sample_applies_endpoint_overrides_last():
    from app.evals.normalizers import normalize_sample

    sample = normalize_sample(
        "agent_trace",
        {
            "prompt": "Find weather",
            "answer": "stale",
            "trace_json": [{"type": "agent", "name": "old"}],
            "called_json": [],
            "expected_json": ["weather"],
        },
        AGENT_MAPPING,
        overrides={
            "actual_output": "Sunny",
            "agent_trace": [{"type": "tool", "name": "weather"}],
            "tools_called": [{"name": "weather"}],
        },
    )

    assert sample.actual_output == "Sunny"
    assert sample.agent_trace[0].name == "weather"
    assert sample.tools_called[0].name == "weather"


@pytest.mark.parametrize("field", ["agent_trace", "tools_called", "expected_tools"])
def test_normalize_agent_sample_reports_invalid_json_field_and_column(field):
    from app.evals.normalizers import normalize_sample

    source = {
        "prompt": "Find weather",
        "answer": "Sunny",
        "trace_json": '[{"type":"tool","name":"weather"}]',
        "called_json": "[]",
        "expected_json": "[]",
    }
    source[AGENT_MAPPING[field]] = "[broken"

    with pytest.raises(
        ValueError,
        match=rf"Invalid {field} in column '{AGENT_MAPPING[field]}'",
    ):
        normalize_sample("agent_trace", source, AGENT_MAPPING)


def test_normalize_agent_sample_rejects_missing_mapped_value():
    from app.evals.normalizers import normalize_sample

    source = {
        "prompt": "Find weather",
        "answer": "Sunny",
        "called_json": "[]",
        "expected_json": "[]",
    }

    with pytest.raises(ValueError, match="Mapped agent_trace value is missing"):
        normalize_sample("agent_trace", source, AGENT_MAPPING)


def test_normalize_single_turn_preserves_context_compatibility():
    from app.evals.normalizers import normalize_sample

    sample = normalize_sample(
        "single_turn",
        {
            "prompt": "q",
            "answer": "a",
            "trusted": '["trusted"]',
            "retrieved": '["retrieved"]',
        },
        {
            "input": "prompt",
            "actual_output": "answer",
            "context": "trusted",
            "retrieval_contexts": "retrieved",
        },
    )

    assert sample.context == ["trusted"]
    assert sample.retrieval_contexts == ["retrieved"]


def test_normalize_conversation_from_csv_json_strings():
    from app.evals.normalizers import normalize_sample

    sample = normalize_sample(
        "conversation",
        {
            "convo": (
                '[{"role":"user","content":"hi"},'
                '{"role":"assistant","content":"hello"}]'
            ),
            "role_col": "support agent",
            "meta": (
                '{"servers":[{"server_name":"files",'
                '"transport":"stdio"}]}'
            ),
            "events": (
                '[{"type":"tool","name":"read","payload":'
                '{"args":{"path":"a.txt"},"result":"data"}}]'
            ),
        },
        {
            "turns": "convo",
            "chatbot_role": "role_col",
            "mcp_metadata": "meta",
            "mcp_events": "events",
        },
    )

    assert sample.kind == "conversation"
    assert sample.turns[1].content == "hello"
    assert sample.chatbot_role == "support agent"
    assert sample.mcp_metadata.servers[0].server_name == "files"
    assert sample.mcp_events[0].name == "read"


def test_normalize_conversation_requires_turns_and_names_bad_column():
    from app.evals.normalizers import normalize_sample

    with pytest.raises(ValueError, match="Mapped turns value is missing"):
        normalize_sample("conversation", {"x": "1"}, {"chatbot_role": "x"})
    with pytest.raises(ValueError, match="Invalid turns in column 'convo'"):
        normalize_sample("conversation", {"convo": "not json"}, {"turns": "convo"})


def test_normalize_conversation_merges_endpoint_overrides_and_keeps_metadata():
    from app.evals.normalizers import normalize_sample

    sample = normalize_sample(
        "conversation",
        {
            "convo": '[{"role":"user","content":"seed"}]',
            "m": {"note": "n1"},
            "t": ["prod"],
        },
        {"turns": "convo", "metadata": "m", "tags": "t"},
        overrides={
            "turns": [
                {"role": "user", "content": "seed"},
                {"role": "assistant", "content": "reply"},
            ],
            "mcp_events": [
                {
                    "type": "prompt",
                    "name": "greet",
                    "payload": {"result": "ok"},
                }
            ],
        },
    )

    assert [turn.content for turn in sample.turns] == ["seed", "reply"]
    assert sample.mcp_events[0].type == "prompt"
    assert sample.metadata == {"note": "n1"}
    assert sample.tags == ["prod"]
