import json

import pytest


def _sample():
    return {
        "kind": "agent_trace",
        "input": "Book flight VN1",
        "actual_output": "Booked",
        "agent_trace": [{"type": "tool", "name": "book"}],
        "tools_called": [
            {"name": "book", "arguments": {"flight": "VN1"}, "output": "ok"}
        ],
        "expected_tools": ["book"],
    }


def _body():
    return {
        "name": "Live trace",
        "sample": _sample(),
        "metrics": [{"key": "deepeval.agent_loop_detection"}],
        "judge": None,
    }


def _url(client, auth_headers):
    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    return f"/api/workspaces/{workspace_id}/ingestions/agent-traces"


def _conversation_url(client, auth_headers):
    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    return f"/api/workspaces/{workspace_id}/ingestions/conversations"


def _judge_id(db):
    from app.models import ProviderConnection, Workspace
    from app.security import encrypt_secret

    workspace = db.query(Workspace).filter_by(name="Default").one()
    connection = ProviderConnection(
        workspace_id=workspace.id,
        name="Conversation judge",
        connection_type="openai",
        encrypted_key=encrypt_secret("sk-conversation"),
    )
    db.add(connection)
    db.commit()
    return connection.id


def _conversation_body(judge_id):
    return {
        "name": "Support chat eval",
        "sample": {
            "kind": "conversation",
            "turns": [
                {"role": "user", "content": "Where is my order?"},
                {"role": "assistant", "content": "It ships tomorrow."},
            ],
            "chatbot_role": "support agent",
        },
        "metrics": [{"key": "deepeval.role_adherence"}],
        "judge": {"connection_id": judge_id, "model": "gpt-4.1-mini"},
    }


def test_ingestion_accepts_immutable_artifact_run_and_outbox(
    client, auth_headers, db, object_store, monkeypatch
):
    from app.models import EvaluationArtifact, OutboxEvent, Run

    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
    response = client.post(
        _url(client, auth_headers),
        json=_body(),
        headers={**auth_headers, "Idempotency-Key": "trace-1"},
    )

    assert response.status_code == 202
    payload = response.json()
    artifact = db.get(EvaluationArtifact, payload["artifact_id"])
    run = db.get(Run, payload["run_id"])
    assert run.dataset_id is None
    assert run.artifact_id == artifact.id
    assert run.mode == "ingestion"
    assert json.loads(object_store[artifact.storage_path]) == _sample()
    event = db.query(OutboxEvent).filter_by(kind="evaluate_run").one()
    assert event.payload == {"run_id": run.id}
    assert "storage_path" not in payload
    run_response = client.get(
        f"/api/workspaces/{run.workspace_id}/runs/{run.id}", headers=auth_headers
    )
    export_response = client.get(
        f"/api/workspaces/{run.workspace_id}/runs/{run.id}/results.json",
        headers=auth_headers,
    )
    assert run_response.json()["artifact_id"] == artifact.id
    assert export_response.json()["run"]["artifact_id"] == artifact.id


def test_ingestion_replay_returns_same_association_without_duplicates(
    client, auth_headers, db, object_store, monkeypatch
):
    from app.models import EvaluationArtifact, OutboxEvent, Run

    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
    headers = {**auth_headers, "Idempotency-Key": "trace-replay"}

    first = client.post(_url(client, auth_headers), json=_body(), headers=headers)
    replay = client.post(_url(client, auth_headers), json=_body(), headers=headers)

    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert db.query(EvaluationArtifact).count() == 1
    assert db.query(Run).count() == 1
    assert db.query(OutboxEvent).count() == 1
    assert len(object_store) == 1


def test_ingestion_rejects_changed_request_for_same_key(
    client, auth_headers, object_store, monkeypatch
):
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
    headers = {**auth_headers, "Idempotency-Key": "trace-conflict"}
    first = client.post(_url(client, auth_headers), json=_body(), headers=headers)
    changed = _body()
    changed["name"] = "Changed trace"

    conflict = client.post(_url(client, auth_headers), json=changed, headers=headers)

    assert first.status_code == 202
    assert conflict.status_code == 409


def test_ingestion_requires_idempotency_key_and_valid_trace(
    client, auth_headers, object_store
):
    missing_key = client.post(_url(client, auth_headers), json=_body(), headers=auth_headers)
    invalid = _body()
    invalid["sample"]["agent_trace"] = []
    invalid_trace = client.post(
        _url(client, auth_headers),
        json=invalid,
        headers={**auth_headers, "Idempotency-Key": "invalid-trace"},
    )

    assert missing_key.status_code == 422
    assert invalid_trace.status_code == 422
    assert invalid_trace.json()["detail"][0]["loc"] == [
        "body",
        "sample",
        "agent_trace",
    ]
    assert object_store == {}


def test_ingestion_rejects_oversized_trace_before_upload(
    client, auth_headers, object_store, monkeypatch
):
    monkeypatch.setattr("app.routers.ingestions.MAX_INGESTION_BYTES", 128)
    body = _body()
    body["sample"]["actual_output"] = "x" * 256

    response = client.post(
        _url(client, auth_headers),
        json=body,
        headers={**auth_headers, "Idempotency-Key": "trace-too-large"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Ingestion payload exceeds the 5 MiB limit"
    assert object_store == {}


def test_ingestion_caps_raw_request_before_json_parsing(
    client, auth_headers, object_store, monkeypatch
):
    monkeypatch.setattr("app.routers.ingestions.MAX_INGESTION_BYTES", 128)

    response = client.post(
        _url(client, auth_headers),
        content=b'{"sample":"' + b"x" * 256,
        headers={
            **auth_headers,
            "Content-Type": "application/json",
            "Idempotency-Key": "trace-raw-too-large",
        },
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Ingestion payload exceeds the 5 MiB limit"
    assert object_store == {}


def test_ingestion_artifact_does_not_snapshot_provider_secret(
    client, auth_headers, db, object_store, monkeypatch
):
    from app.models import EvaluationArtifact, ProviderConnection, Workspace
    from app.security import encrypt_secret

    workspace = db.query(Workspace).filter_by(name="Default").one()
    connection = ProviderConnection(
        workspace_id=workspace.id,
        name="Judge",
        connection_type="openai",
        encrypted_key=encrypt_secret("sk-ingestion-secret"),
    )
    db.add(connection)
    db.commit()
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
    body = _body()
    body["metrics"] = [{"key": "deepeval.task_completion"}]
    body["judge"] = {"connection_id": connection.id, "model": "gpt-4.1-mini"}

    response = client.post(
        _url(client, auth_headers),
        json=body,
        headers={**auth_headers, "Idempotency-Key": "trace-secret"},
    )

    assert response.status_code == 202
    artifact = db.get(EvaluationArtifact, response.json()["artifact_id"])
    raw = object_store[artifact.storage_path].decode()
    assert "sk-ingestion-secret" not in raw
    assert "connection_id" not in raw


def test_ingestion_cleans_up_upload_when_database_commit_fails(
    client, auth_headers, db, object_store, monkeypatch
):
    from app.deps import get_db

    client.app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("db")))
    try:
        with pytest.raises(RuntimeError, match="db"):
            client.post(
                _url(client, auth_headers),
                json=_body(),
                headers={**auth_headers, "Idempotency-Key": "trace-db-fail"},
            )
    finally:
        client.app.dependency_overrides.clear()

    assert object_store == {}


def test_conversation_ingestion_is_idempotent_and_snapshots_kind(
    client, auth_headers, db, object_store, monkeypatch
):
    from app.models import EvaluationArtifact, Run

    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
    body = _conversation_body(_judge_id(db))
    headers = {**auth_headers, "Idempotency-Key": "conversation-replay"}

    first = client.post(
        _conversation_url(client, auth_headers), json=body, headers=headers
    )
    replay = client.post(
        _conversation_url(client, auth_headers), json=body, headers=headers
    )

    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.json() == first.json()
    artifact = db.get(EvaluationArtifact, first.json()["artifact_id"])
    run = db.get(Run, first.json()["run_id"])
    assert artifact.sample_kind == "conversation"
    assert run.definition_snapshot["sample"]["kind"] == "conversation"
    assert json.loads(object_store[artifact.storage_path]) == body["sample"]


def test_conversation_ingestion_rejects_changed_replay(
    client, auth_headers, db, object_store, monkeypatch
):
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
    body = _conversation_body(_judge_id(db))
    headers = {**auth_headers, "Idempotency-Key": "conversation-conflict"}
    first = client.post(
        _conversation_url(client, auth_headers), json=body, headers=headers
    )
    changed = {**body, "name": "Changed conversation"}

    conflict = client.post(
        _conversation_url(client, auth_headers),
        json=changed,
        headers=headers,
    )

    assert first.status_code == 202
    assert conflict.status_code == 409


def test_conversation_ingestion_validates_sample(
    client, auth_headers, db, object_store
):
    body = _conversation_body(_judge_id(db))
    body["sample"]["turns"] = []

    response = client.post(
        _conversation_url(client, auth_headers),
        json=body,
        headers={**auth_headers, "Idempotency-Key": "invalid-conversation"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == [
        "body",
        "sample",
        "turns",
    ]


def test_conversation_ingestion_only_accepts_conversation_metrics(
    client, auth_headers, db, object_store
):
    body = _conversation_body(_judge_id(db))
    body["metrics"] = [{"key": "deepeval.answer_relevancy"}]

    response = client.post(
        _conversation_url(client, auth_headers),
        json=body,
        headers={**auth_headers, "Idempotency-Key": "wrong-kind"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Conversation ingestion only accepts conversation metrics"
    )


def test_conversation_ingestion_requires_judge(
    client, auth_headers, object_store
):
    body = _conversation_body("unused")
    body["judge"] = None

    response = client.post(
        _conversation_url(client, auth_headers),
        json=body,
        headers={**auth_headers, "Idempotency-Key": "conversation-no-judge"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "A judge connection is required for the selected metrics"
    )


def test_conversation_ingestion_caps_raw_body(
    client, auth_headers, object_store
):
    body = _conversation_body("unused")
    body["sample"]["turns"][1]["content"] = "x" * (5 * 1024 * 1024)

    response = client.post(
        _conversation_url(client, auth_headers),
        json=body,
        headers={**auth_headers, "Idempotency-Key": "conversation-too-large"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Ingestion payload exceeds the 5 MiB limit"
    assert object_store == {}
