import pytest


def test_render_template_preserves_whole_value_types():
    from app.endpoints import render_template
    from app.evals.base import EvalRow

    row = EvalRow(
        input="hello",
        actual_output="",
        expected_output="expected",
        retrieval_contexts=["one", "two"],
    )
    rendered = render_template(
        {
            "message": "Question: {{input}}",
            "contexts": "{{contexts}}",
            "nested": [{"expected": "{{expected_output}}"}],
        },
        row,
    )
    assert rendered == {
        "message": "Question: hello",
        "contexts": ["one", "two"],
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
