import pytest


def test_render_template_preserves_whole_value_types():
    from app.endpoints import render_template
    from app.evals.base import EvalRow

    row = EvalRow(
        input="hello",
        actual_output="",
        expected_output="expected",
        context=["trusted"],
        retrieval_contexts=["one", "two"],
    )
    rendered = render_template(
        {
            "message": "Question: {{input}}",
            "contexts": "{{contexts}}",
            "context": "{{context}}",
            "retrieval_contexts": "{{retrieval_contexts}}",
            "nested": [{"expected": "{{expected_output}}"}],
        },
        row,
    )
    assert rendered == {
        "message": "Question: hello",
        "contexts": ["one", "two"],
        "context": ["trusted"],
        "retrieval_contexts": ["one", "two"],
        "nested": [{"expected": "expected"}],
    }


def test_extract_answer_jsonpath():
    from app.endpoints import extract_answer

    payload = {"choices": [{"message": {"content": "answer"}}]}
    assert extract_answer(payload, "$.choices[0].message.content") == "answer"


def test_extract_answer_requires_match():
    from app.endpoints import extract_answer

    with pytest.raises(ValueError, match="matched no values"):
        extract_answer({"answer": "x"}, "$.missing")


def test_extract_named_response_fields_and_legacy_alias():
    from app.endpoints import EndpointConfig, extract_response_fields

    payload = {
        "answer": "response",
        "facts": ["trusted fact"],
        "documents": ["retrieved document"],
    }
    config = EndpointConfig(
        url="https://example.test/chat",
        response_mappings={
            "actual_output": "$.answer",
            "context": "$.facts",
            "retrieval_contexts": "$.documents",
        },
    )
    assert extract_response_fields(payload, config.model_dump()) == {
        "actual_output": "response",
        "context": ["trusted fact"],
        "retrieval_contexts": ["retrieved document"],
    }

    legacy = EndpointConfig(
        url="https://example.test/chat",
        response_jsonpath="$.answer",
    )
    assert extract_response_fields(payload, legacy.model_dump()) == {
        "actual_output": "response"
    }


def test_extract_named_context_fields_collects_wildcard_matches():
    from app.endpoints import extract_response_fields

    payload = {
        "answers": ["first", "second"],
        "documents": [{"text": "d1"}, {"text": "d2"}],
    }

    assert extract_response_fields(
        payload,
        {
            "response_mappings": {
                "actual_output": "$.answers[*]",
                "retrieval_contexts": "$.documents[*].text",
            }
        },
    ) == {
        "actual_output": "first",
        "retrieval_contexts": ["d1", "d2"],
    }


def test_extract_named_context_fields_always_produce_lists():
    from app.endpoints import extract_response_fields

    payload = {
        "answer": "response",
        "documents": [{"text": "only"}],
        "fact": "single trusted fact",
    }

    assert extract_response_fields(
        payload,
        {
            "response_mappings": {
                "actual_output": "$.answer",
                "retrieval_contexts": "$.documents[*].text",
                "context": "$.fact",
            }
        },
    ) == {
        "actual_output": "response",
        "retrieval_contexts": ["only"],
        "context": ["single trusted fact"],
    }


def test_extract_agentic_response_fields_preserves_structured_arrays():
    from app.endpoints import EndpointConfig, extract_response_fields

    payload = {
        "answer": "Booked",
        "trace": [{"type": "tool", "name": "book"}],
        "called": [{"name": "book", "arguments": {"flight": "VN1"}}],
        "expected": ["book"],
    }
    config = EndpointConfig(
        url="https://example.test/agent",
        response_mappings={
            "actual_output": "$.answer",
            "agent_trace": "$.trace",
            "tools_called": "$.called",
            "expected_tools": "$.expected",
        },
    )

    assert extract_response_fields(payload, config.model_dump()) == {
        "actual_output": "Booked",
        "agent_trace": [{"type": "tool", "name": "book"}],
        "tools_called": [
            {"name": "book", "arguments": {"flight": "VN1"}}
        ],
        "expected_tools": ["book"],
    }


def test_endpoint_mappings_accept_conversation_fields():
    from app.endpoints import EndpointConfig, extract_response_fields

    config = EndpointConfig(
        url="https://example.test/chat",
        response_mappings={
            "actual_output": "$.answer",
            "turns": "$.turns",
            "mcp_events": "$.events",
        },
    )
    payload = {
        "answer": "done",
        "turns": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "done"},
        ],
        "events": [{"type": "tool", "name": "read", "payload": {}}],
    }

    fields = extract_response_fields(payload, config.model_dump())

    assert fields["turns"][1] == {"role": "assistant", "content": "done"}
    assert fields["mcp_events"][0]["name"] == "read"


def test_render_template_exposes_conversation_values():
    import json

    from app.endpoints import render_template
    from app.evals.samples import ConversationSample

    sample = ConversationSample.model_validate(
        {
            "kind": "conversation",
            "chatbot_role": "concierge",
            "turns": [
                {"role": "user", "content": "book a room"},
                {"role": "assistant", "content": "which date?"},
            ],
        }
    )
    body = render_template(
        {
            "conversation": "{{turns}}",
            "role": "{{chatbot_role}}",
            "probe": "{{input}}",
        },
        sample,
    )

    assert body["conversation"][0]["content"] == "book a room"
    assert body["role"] == "concierge"
    assert body["probe"] == "book a room"
    interpolated = render_template({"note": "history: {{turns}}"}, sample)
    assert json.loads(interpolated["note"].removeprefix("history: "))[0][
        "role"
    ] == "user"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"response_mappings": {"unknown": "$.answer"}}, "response mapping"),
        (
            {
                "response_jsonpath": "$.answer",
                "response_mappings": {"actual_output": "$.other"},
            },
            "conflict",
        ),
        ({"response_mappings": {"actual_output": "not["}}, "JSONPath"),
        ({"response_mappings": {"context": "$.facts"}}, "actual_output"),
    ],
)
def test_endpoint_config_rejects_invalid_named_response_mappings(kwargs, message):
    from pydantic import ValidationError

    from app.endpoints import EndpointConfig

    with pytest.raises(ValidationError, match=message):
        EndpointConfig(url="https://example.test/chat", **kwargs)


def test_endpoint_client_blocks_private_addresses(monkeypatch):
    import socket

    from app import endpoints
    from app.evals.base import EvalRow

    monkeypatch.setattr(endpoints.settings, "allow_private_endpoints", False)
    monkeypatch.setattr(
        endpoints.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ],
    )
    with pytest.raises(ValueError, match="private"):
        endpoints.call_endpoint(
            {
                "url": "http://example.test/chat",
                "method": "POST",
                "headers": {},
                "body_template": {"input": "{{input}}"},
                "response_jsonpath": "$.answer",
            },
            EvalRow(input="hello", actual_output=""),
            encrypted_headers=False,
        )


def test_endpoint_client_retries_and_extracts(monkeypatch):
    import socket

    import httpx

    from app import endpoints
    from app.evals.base import EvalRow

    monkeypatch.setattr(endpoints.settings, "allow_private_endpoints", False)
    monkeypatch.setattr(endpoints.settings, "endpoint_retries", 2)
    monkeypatch.setattr(endpoints.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        endpoints.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    attempts = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"answer": "world"}

    def request(method, url, headers, body):
        attempts.append((method, url, headers, body))
        if len(attempts) < 3:
            raise httpx.ConnectError("temporary")
        return Response()

    monkeypatch.setattr(endpoints, "_request", request)
    answer, payload, latency = endpoints.call_endpoint(
        {
            "url": "https://example.test/chat",
            "method": "POST",
            "headers": {"X-Test": "yes"},
            "body_template": {"input": "{{input}}"},
            "response_jsonpath": "$.answer",
        },
        EvalRow(input="hello", actual_output=""),
        encrypted_headers=False,
    )
    assert answer == "world"
    assert payload == {"answer": "world"}
    assert latency >= 0
    assert len(attempts) == 3
    assert attempts[-1][2] == {"X-Test": "yes"}


def test_endpoint_client_retries_override_disables_retries(monkeypatch):
    import httpx
    import pytest

    from app import endpoints
    from app.evals.base import EvalRow

    monkeypatch.setattr(endpoints.settings, "endpoint_retries", 2)
    monkeypatch.setattr(endpoints.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(endpoints, "_validate_destination", lambda parsed: None)
    attempts = []

    def request(method, url, headers, body):
        attempts.append(method)
        raise httpx.ConnectError("down")

    monkeypatch.setattr(endpoints, "_request", request)
    with pytest.raises(httpx.ConnectError):
        endpoints.call_endpoint(
            {
                "url": "https://example.test/chat",
                "method": "POST",
                "body_template": {"input": "{{input}}"},
                "response_jsonpath": "$.answer",
            },
            EvalRow(input="hello", actual_output=""),
            encrypted_headers=False,
            retries=0,
        )
    assert len(attempts) == 1


def test_endpoint_client_rejects_non_http_url():
    from app.endpoints import validate_url

    with pytest.raises(ValueError, match="HTTP"):
        validate_url("file:///etc/passwd")
