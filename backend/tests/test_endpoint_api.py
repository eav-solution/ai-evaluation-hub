def test_endpoint_test_returns_extracted_answer(
    client, auth_headers, db, monkeypatch
):
    from app.models import Workspace
    from app.routers import endpoint_test

    workspace = db.query(Workspace).filter_by(name="Default").one()
    monkeypatch.setattr(
        endpoint_test,
        "call_endpoint",
        lambda config, row, encrypted_headers, retries: (
            "Hello",
            {"data": {"answer": "Hello"}},
            12.5,
        ),
    )

    response = client.post(
        f"/api/workspaces/{workspace.id}/endpoint-test",
        json={
            "config": {
                "url": "https://example.com/evaluate",
                "method": "POST",
                "headers": {"Authorization": "Bearer secret"},
                "body_template": {"prompt": "{{input}}"},
                "response_jsonpath": "$.data.answer",
            },
            "input": "Hi",
            "contexts": ["Greeting"],
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "raw_response": {"data": {"answer": "Hello"}},
        "extracted_answer": "Hello",
        "latency_ms": 12.5,
    }


def test_endpoint_test_requires_workspace_membership(client, auth_headers, db):
    from app.models import Workspace

    workspace = db.query(Workspace).filter_by(name="Default").one()
    token = client.post(
        "/api/auth/register",
        json={"email": "endpoint-intruder@example.com", "password": "password123"},
    ).json()["access_token"]

    response = client.post(
        f"/api/workspaces/{workspace.id}/endpoint-test",
        json={
            "config": {
                "url": "https://example.com",
                "method": "POST",
                "body_template": {},
                "response_jsonpath": "$.answer",
            },
            "input": "Hi",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


def test_endpoint_test_makes_single_attempt(client, auth_headers, db, monkeypatch):
    import httpx

    from app import endpoints
    from app.models import Workspace

    workspace = db.query(Workspace).filter_by(name="Default").one()
    monkeypatch.setattr(endpoints.settings, "endpoint_retries", 2)
    monkeypatch.setattr(endpoints.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(endpoints, "_validate_destination", lambda parsed: None)
    attempts = []

    def request(method, url, headers, body):
        attempts.append(method)
        raise httpx.ConnectError("down")

    monkeypatch.setattr(endpoints, "_request", request)

    response = client.post(
        f"/api/workspaces/{workspace.id}/endpoint-test",
        json={
            "config": {
                "url": "https://example.com/evaluate",
                "method": "POST",
                "body_template": {"prompt": "{{input}}"},
                "response_jsonpath": "$.answer",
            },
            "input": "Hi",
        },
        headers=auth_headers,
    )

    assert response.status_code == 502
    assert len(attempts) == 1
