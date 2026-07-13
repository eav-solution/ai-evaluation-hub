def test_run_result_and_summary_roundtrip(db):
    from app.models import (
        Dataset,
        Membership,
        Run,
        RunResult,
        RunSummary,
        User,
        Workspace,
    )

    user = User(email="run@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Runs", owner_id=user.id)
    db.add(workspace)
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Data",
        format="json",
        row_count=1,
        storage_path=f"datasets/{workspace.id}/data.json",
        schema_map={"input": "prompt", "actual_output": "answer"},
    )
    db.add(dataset)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        name="Baseline",
        mode="static",
        metric_config={"metrics": [{"key": "deepeval.bias", "threshold": 0.5}]},
        judge_config={"provider": "openai", "model": "gpt-4.1-mini"},
    )
    db.add(run)
    db.flush()
    db.add(
        RunResult(
            workspace_id=workspace.id,
            run_id=run.id,
            row_index=0,
            input="Prompt",
            actual="Answer",
            scores={"deepeval.bias": {"score": 0.9, "passed": True}},
        )
    )
    db.add(
        RunSummary(
            workspace_id=workspace.id,
            run_id=run.id,
            metric_key="deepeval.bias",
            mean=0.9,
            min=0.9,
            max=0.9,
            p50=0.9,
            pass_rate=1.0,
            threshold=0.5,
        )
    )
    db.commit()

    assert db.query(RunResult).one().scores["deepeval.bias"]["score"] == 0.9
    assert db.query(RunSummary).one().pass_rate == 1.0


def _ready_dataset(db, provider="openai", schema_map=None):
    from app.models import Dataset, ProviderConnection, Workspace
    from app.security import encrypt_secret

    workspace = db.query(Workspace).filter_by(name="Default").one()
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Ready",
        format="json",
        row_count=1,
        storage_path=f"datasets/{workspace.id}/ready.json",
        schema_map=schema_map
        or {"input": "prompt", "actual_output": "answer", "contexts": "contexts"},
    )
    db.add(dataset)
    connection = None
    if provider:
        connection = ProviderConnection(
            workspace_id=workspace.id,
            name=provider,
            connection_type=provider,
            encrypted_key=encrypt_secret("sk-test"),
        )
        db.add(connection)
    db.commit()
    return workspace, dataset, connection


def test_create_run_validates_and_enqueues(client, auth_headers, db, monkeypatch):
    from app.routers import runs

    workspace, dataset, connection = _ready_dataset(db)
    queued = []
    monkeypatch.setattr(runs, "_enqueue", queued.append)
    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Baseline",
            "mode": "static",
            "metrics": [{"key": "deepeval.bias", "threshold": 0.5}],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert queued == [response.json()["id"]]


def test_create_run_rejects_missing_metric_mapping(
    client, auth_headers, db, monkeypatch
):
    from app.routers import runs

    workspace, dataset, connection = _ready_dataset(
        db, schema_map={"input": "prompt", "actual_output": "answer"}
    )
    monkeypatch.setattr(runs, "_enqueue", lambda run_id: None)
    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Missing context",
            "mode": "static",
            "metrics": [{"key": "ragas.faithfulness"}],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "contexts" in response.json()["detail"]


def test_create_run_requires_provider_key(client, auth_headers, db, monkeypatch):
    from app.routers import runs

    workspace, dataset, connection = _ready_dataset(db, provider=None)
    monkeypatch.setattr(runs, "_enqueue", lambda run_id: None)
    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "No key",
            "mode": "static",
            "metrics": [{"key": "deepeval.bias"}],
            "judge": {"connection_id": "no-such-connection", "model": "gpt-4.1-mini"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "connection" in response.json()["detail"].lower()


def test_cancel_run(client, auth_headers, db, monkeypatch):
    from app.routers import runs

    workspace, dataset, connection = _ready_dataset(db)
    monkeypatch.setattr(runs, "_enqueue", lambda run_id: None)
    created = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Cancel me",
            "mode": "static",
            "metrics": [{"key": "deepeval.bias"}],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
        },
        headers=auth_headers,
    ).json()
    response = client.post(
        f"/api/workspaces/{workspace.id}/runs/{created['id']}/cancel",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_nonmember_cannot_access_run(client, auth_headers, db, monkeypatch):
    from app.routers import runs

    workspace, dataset, connection = _ready_dataset(db)
    monkeypatch.setattr(runs, "_enqueue", lambda run_id: None)
    run_id = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Private",
            "mode": "static",
            "metrics": [{"key": "deepeval.bias"}],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
        },
        headers=auth_headers,
    ).json()["id"]
    token = client.post(
        "/api/auth/register",
        json={"email": "run-intruder@example.com", "password": "password123"},
    ).json()["access_token"]
    response = client.get(
        f"/api/workspaces/{workspace.id}/runs/{run_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_create_endpoint_run_encrypts_headers(
    client, auth_headers, db, monkeypatch
):
    from app.models import Run
    from app.routers import runs
    from app.security import decrypt_secret

    workspace, dataset, connection = _ready_dataset(
        db, schema_map={"input": "prompt", "contexts": "contexts"}
    )
    monkeypatch.setattr(runs, "_enqueue", lambda run_id: None)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Live endpoint",
            "mode": "endpoint",
            "metrics": [{"key": "deepeval.bias"}],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
            "endpoint_config": {
                "url": "https://example.com/evaluate",
                "method": "POST",
                "headers": {"Authorization": "Bearer endpoint-secret"},
                "body_template": {"prompt": "{{input}}"},
                "response_jsonpath": "$.answer",
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    stored = db.query(Run).filter_by(id=response.json()["id"]).one()
    encrypted = stored.endpoint_config["headers"]["Authorization"]
    assert encrypted != "Bearer endpoint-secret"
    assert decrypt_secret(encrypted) == "Bearer endpoint-secret"
    assert "endpoint_config" not in response.json()


def test_create_endpoint_run_requires_config(
    client, auth_headers, db, monkeypatch
):
    from app.routers import runs

    workspace, dataset, connection = _ready_dataset(
        db, schema_map={"input": "prompt"}
    )
    monkeypatch.setattr(runs, "_enqueue", lambda run_id: None)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Missing endpoint",
            "mode": "endpoint",
            "metrics": [{"key": "deepeval.bias"}],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 422


def _custom_connection(db, workspace_id, name="Gateway", key=None):
    from app.models import ProviderConnection
    from app.security import encrypt_secret

    conn = ProviderConnection(
        workspace_id=workspace_id,
        name=name,
        connection_type="openai_compatible",
        base_url="http://gateway/v1",
        encrypted_key=encrypt_secret(key) if key else None,
    )
    db.add(conn)
    db.commit()
    return conn


def test_create_run_custom_connection_valid_model(client, auth_headers, db, monkeypatch):
    from app.routers import runs

    workspace, dataset, _ = _ready_dataset(db, provider=None)
    connection = _custom_connection(db, workspace.id)
    monkeypatch.setattr(runs, "_enqueue", lambda run_id: None)
    monkeypatch.setattr(runs, "discover_models", lambda base_url, api_key: ["chat-a", "chat-b"])
    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Custom judge",
            "mode": "static",
            "metrics": [{"key": "deepeval.bias"}],
            "judge": {"connection_id": connection.id, "model": "chat-a"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["judge_config"]["connection_id"] == connection.id
    assert response.json()["judge_config"]["connection_type"] == "openai_compatible"


def test_create_run_custom_connection_stale_model(client, auth_headers, db, monkeypatch):
    from app.routers import runs

    workspace, dataset, _ = _ready_dataset(db, provider=None)
    connection = _custom_connection(db, workspace.id)
    monkeypatch.setattr(runs, "_enqueue", lambda run_id: None)
    monkeypatch.setattr(runs, "discover_models", lambda base_url, api_key: ["chat-a"])
    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Stale model",
            "mode": "static",
            "metrics": [{"key": "deepeval.bias"}],
            "judge": {"connection_id": connection.id, "model": "gone"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_create_run_foreign_connection_rejected(client, auth_headers, db, monkeypatch):
    from app.models import User, Workspace
    from app.routers import runs

    workspace, dataset, _ = _ready_dataset(db, provider=None)
    other_user = User(email="other-ws@example.com", password_hash="x")
    db.add(other_user)
    db.flush()
    other_ws = Workspace(name="Other", owner_id=other_user.id)
    db.add(other_ws)
    db.flush()
    foreign = _custom_connection(db, other_ws.id, name="Foreign")
    monkeypatch.setattr(runs, "_enqueue", lambda run_id: None)
    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Foreign conn",
            "mode": "static",
            "metrics": [{"key": "deepeval.bias"}],
            "judge": {"connection_id": foreign.id, "model": "chat-a"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_create_run_embedding_from_separate_connection(client, auth_headers, db, monkeypatch):
    from app.routers import runs

    # judge LLM on one custom connection, embeddings on a different one
    workspace, dataset, _ = _ready_dataset(db, provider=None)
    judge_conn = _custom_connection(db, workspace.id, name="LLM Gateway")
    embed_conn = _custom_connection(db, workspace.id, name="Embed Gateway")
    monkeypatch.setattr(runs, "_enqueue", lambda run_id: None)
    monkeypatch.setattr(runs, "discover_models", lambda base_url, api_key: ["chat-a", "embed-x"])

    # missing embedding connection → 422
    missing = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Needs embedding",
            "mode": "static",
            "metrics": [{"key": "ragas.answer_relevancy"}],
            "judge": {"connection_id": judge_conn.id, "model": "chat-a"},
        },
        headers=auth_headers,
    )
    assert missing.status_code == 422
    assert "embedding" in missing.json()["detail"].lower()

    # supplied embedding connection (different from judge) → 201
    supplied = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Cross-provider embedding",
            "mode": "static",
            "metrics": [{"key": "ragas.answer_relevancy"}],
            "judge": {
                "connection_id": judge_conn.id,
                "model": "chat-a",
                "embedding_connection_id": embed_conn.id,
                "embedding_model": "embed-x",
            },
        },
        headers=auth_headers,
    )
    assert supplied.status_code == 201
    cfg = supplied.json()["judge_config"]
    assert cfg["embedding_connection_id"] == embed_conn.id
    assert cfg["embedding_model"] == "embed-x"
    assert cfg["connection_id"] == judge_conn.id


def test_create_run_embedding_connection_must_support_embeddings(client, auth_headers, db, monkeypatch):
    from app.models import ProviderConnection
    from app.routers import runs
    from app.security import encrypt_secret

    workspace, dataset, _ = _ready_dataset(db, provider=None)
    judge_conn = _custom_connection(db, workspace.id, name="LLM Gateway")
    anthropic_conn = ProviderConnection(
        workspace_id=workspace.id,
        name="Anthropic",
        connection_type="anthropic",
        encrypted_key=encrypt_secret("sk-ant"),
    )
    db.add(anthropic_conn)
    db.commit()
    monkeypatch.setattr(runs, "_enqueue", lambda run_id: None)
    monkeypatch.setattr(runs, "discover_models", lambda base_url, api_key: ["chat-a"])

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Bad embedding provider",
            "mode": "static",
            "metrics": [{"key": "ragas.answer_relevancy"}],
            "judge": {
                "connection_id": judge_conn.id,
                "model": "chat-a",
                "embedding_connection_id": anthropic_conn.id,
                "embedding_model": "whatever",
            },
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "OpenAI" in response.json()["detail"]
