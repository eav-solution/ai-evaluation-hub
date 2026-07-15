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
    from app import tasks
    from app.models import OutboxEvent, Run

    workspace, dataset, connection = _ready_dataset(db)
    queued = []
    monkeypatch.setattr(tasks, "dispatch_outbox_event", queued.append)
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
    stored = db.get(Run, response.json()["id"])
    assert stored.definition_snapshot["schema_map"] == dataset.schema_map
    assert stored.definition_snapshot["dataset"] == {
        "storage_path": dataset.storage_path,
        "format": dataset.format,
    }
    event = db.query(OutboxEvent).filter_by(kind="evaluate_run").one()
    assert event.dedupe_key == f"evaluation:{stored.id}"
    assert event.payload == {"run_id": stored.id}
    assert queued == [event.id]


def test_create_run_normalizes_nested_metric_config_and_snapshot(
    client, auth_headers, db, monkeypatch
):
    from app.models import Run

    workspace, dataset, connection = _ready_dataset(db)
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Configured G-Eval",
            "mode": "static",
            "metrics": [{"key": "deepeval.geval", "config": {"rubric": "Be concise"}}],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    stored = db.get(Run, response.json()["id"])
    assert stored.metric_config["metrics"] == [
        {
            "key": "deepeval.geval",
            "threshold": 0.5,
            "rubric": "Be concise",
            "strict_mode": False,
            "evaluation_fields": ["input", "actual_output"],
        }
    ]
    assert stored.definition_snapshot["libraries"] == {
        "ragas": "0.4.3",
        "deepeval": "4.1.0",
    }
    assert stored.definition_snapshot["metrics"] == [
        {
            "key": "deepeval.geval",
            "revision": "1",
            "config": {
                "threshold": 0.5,
                "rubric": "Be concise",
                "strict_mode": False,
                "evaluation_fields": ["input", "actual_output"],
            },
        }
    ]
    assert stored.definition_snapshot["sample"] == {
        "kind": "single_turn",
        "normalizer_revision": "1",
    }
    assert stored.definition_snapshot["resources"]["judge"] == {
        "connection_id": connection.id,
        "connection_name": connection.name,
        "connection_type": connection.connection_type,
        "model": "gpt-4.1-mini",
    }
    serialized = str(stored.definition_snapshot).lower()
    assert "api_key" not in serialized
    assert "authorization" not in serialized


def test_create_run_rejects_invalid_or_conflicting_metric_config(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, connection = _ready_dataset(db)
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
    base = {
        "dataset_id": dataset.id,
        "name": "Invalid config",
        "mode": "static",
        "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
    }

    unknown = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            **base,
            "metrics": [{"key": "deepeval.bias", "config": {"unknown": True}}],
        },
        headers=auth_headers,
    )
    conflict = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            **base,
            "metrics": [
                {
                    "key": "deepeval.geval",
                    "threshold": 0.7,
                    "config": {"threshold": 0.2},
                }
            ],
        },
        headers=auth_headers,
    )

    assert unknown.status_code == 422
    assert "unknown" in str(unknown.json()["detail"]).lower()
    assert conflict.status_code == 422
    assert "conflict" in str(conflict.json()["detail"]).lower()


def test_create_run_returns_422_for_reserved_json_schema_property(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, connection = _ready_dataset(db)
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Invalid JSON schema",
            "mode": "static",
            "metrics": [
                {
                    "key": "deepeval.json_correctness",
                    "config": {
                        "expected_schema": {
                            "type": "object",
                            "properties": {"model_dump": {"type": "string"}},
                        }
                    },
                }
            ],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "reserved property name" in str(response.json()["detail"])


def test_create_run_preserves_legacy_metric_config_fields(
    client, auth_headers, db, monkeypatch
):
    from app.models import Run

    workspace, dataset, connection = _ready_dataset(db)
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Legacy G-Eval",
            "mode": "static",
            "metrics": [
                {
                    "key": "deepeval.geval",
                    "threshold": 0.7,
                    "rubric": "Prefer a direct answer",
                }
            ],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    stored = db.get(Run, response.json()["id"])
    assert stored.metric_config["metrics"] == [
        {
            "key": "deepeval.geval",
            "threshold": 0.7,
            "rubric": "Prefer a direct answer",
            "strict_mode": False,
            "evaluation_fields": ["input", "actual_output"],
        }
    ]


def test_create_run_logs_dispatch_failure_and_keeps_outbox(
    client, auth_headers, db, monkeypatch, caplog
):
    from app import tasks
    from app.models import OutboxEvent

    workspace, dataset, connection = _ready_dataset(db)

    def fail_dispatch(event_id):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(tasks, "dispatch_outbox_event", fail_dispatch)
    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Durable evaluation",
            "mode": "static",
            "metrics": [{"key": "deepeval.bias"}],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    event = db.query(OutboxEvent).filter_by(kind="evaluate_run").one()
    assert event.payload == {"run_id": response.json()["id"]}
    assert "Immediate evaluation dispatch failed" in caplog.text


def test_create_run_rejects_missing_metric_mapping(
    client, auth_headers, db, monkeypatch
):

    workspace, dataset, connection = _ready_dataset(
        db, schema_map={"input": "prompt", "actual_output": "answer"}
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
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


def test_legacy_context_alias_is_limited_to_hallucination(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, connection = _ready_dataset(db)
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
    base = {
        "dataset_id": dataset.id,
        "mode": "static",
        "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
    }

    hallucination = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            **base,
            "name": "Legacy hallucination",
            "metrics": [{"key": "deepeval.hallucination"}],
        },
        headers=auth_headers,
    )
    geval = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            **base,
            "name": "G-Eval needs trusted context",
            "metrics": [
                {
                    "key": "deepeval.geval",
                    "config": {"evaluation_fields": ["input", "context"]},
                }
            ],
        },
        headers=auth_headers,
    )

    assert hallucination.status_code == 201
    assert geval.status_code == 422
    assert "context" in geval.json()["detail"]


def test_create_run_requires_provider_key(client, auth_headers, db, monkeypatch):

    workspace, dataset, connection = _ready_dataset(db, provider=None)
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
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

    workspace, dataset, connection = _ready_dataset(db)
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
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

    workspace, dataset, connection = _ready_dataset(db)
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
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


def test_create_endpoint_run_encrypts_headers(client, auth_headers, db, monkeypatch):
    from app.models import Run
    from app.security import decrypt_secret

    workspace, dataset, connection = _ready_dataset(
        db, schema_map={"input": "prompt", "contexts": "contexts"}
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

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
    snapshot = stored.definition_snapshot
    assert snapshot["endpoint"] == {
        "method": "POST",
        "response_mappings": {"actual_output": "$.answer"},
    }
    assert "authorization" not in str(snapshot).lower()


def test_endpoint_response_mappings_satisfy_metric_requirements(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, connection = _ready_dataset(
        db, schema_map={"input": "prompt"}
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Mapped endpoint",
            "mode": "endpoint",
            "metrics": [{"key": "deepeval.contextual_relevancy"}],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
            "endpoint_config": {
                "url": "https://example.com/evaluate",
                "response_mappings": {
                    "actual_output": "$.answer",
                    "retrieval_contexts": "$.documents",
                },
            },
        },
        headers=auth_headers,
    )
    assert response.status_code == 201


def test_endpoint_response_mappings_reject_unknown_field(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, connection = _ready_dataset(
        db, schema_map={"input": "prompt"}
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Bad endpoint mapping",
            "mode": "endpoint",
            "metrics": [{"key": "deepeval.bias"}],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
            "endpoint_config": {
                "url": "https://example.com/evaluate",
                "response_mappings": {
                    "actual_output": "$.answer",
                    "documents": "$.documents",
                },
            },
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_static_run_does_not_use_unused_endpoint_response_mappings(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, connection = _ready_dataset(
        db, schema_map={"input": "prompt", "actual_output": "answer"}
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Static mappings stay static",
            "mode": "static",
            "metrics": [{"key": "deepeval.contextual_relevancy"}],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
            "endpoint_config": {
                "url": "https://example.com/evaluate",
                "response_mappings": {
                    "actual_output": "$.answer",
                    "retrieval_contexts": "$.documents",
                },
            },
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "retrieval_contexts" in response.json()["detail"]


def test_create_endpoint_run_requires_config(client, auth_headers, db, monkeypatch):

    workspace, dataset, connection = _ready_dataset(db, schema_map={"input": "prompt"})
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

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


def test_create_static_agent_loop_run_without_judge(
    client, auth_headers, db, monkeypatch
):
    from app.models import Run

    workspace, dataset, _ = _ready_dataset(
        db,
        provider=None,
        schema_map={
            "input": "prompt",
            "actual_output": "answer",
            "agent_trace": "trace",
        },
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Loop check",
            "mode": "static",
            "metrics": [{"key": "deepeval.agent_loop_detection"}],
            "judge": None,
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["judge_config"] == {}
    stored = db.get(Run, response.json()["id"])
    assert stored.definition_snapshot["sample"]["kind"] == "agent_trace"
    assert stored.definition_snapshot["resources"] == {}


def test_create_tool_correctness_run_without_judge(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, _ = _ready_dataset(
        db,
        provider=None,
        schema_map={
            "input": "prompt",
            "actual_output": "answer",
            "agent_trace": "trace",
            "tools_called": "called",
            "expected_tools": "expected",
        },
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Tool check",
            "mode": "static",
            "metrics": [{"key": "deepeval.tool_correctness"}],
            "judge": None,
        },
        headers=auth_headers,
    )

    assert response.status_code == 201


def test_create_task_completion_run_requires_judge(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, _ = _ready_dataset(
        db,
        provider=None,
        schema_map={
            "input": "prompt",
            "actual_output": "answer",
            "agent_trace": "trace",
        },
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Completion check",
            "mode": "static",
            "metrics": [{"key": "deepeval.task_completion"}],
            "judge": None,
        },
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "judge connection" in response.json()["detail"].lower()


def test_create_run_rejects_mixed_sample_kinds(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, connection = _ready_dataset(
        db,
        schema_map={
            "input": "prompt",
            "actual_output": "answer",
            "agent_trace": "trace",
        },
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Mixed samples",
            "mode": "static",
            "metrics": [
                {"key": "deepeval.agent_loop_detection"},
                {"key": "deepeval.bias"},
            ],
            "judge": {"connection_id": connection.id, "model": "gpt-4.1-mini"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "separate run" in response.json()["detail"].lower()


def test_create_endpoint_agent_run_uses_named_trace_and_tool_mappings(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, _ = _ready_dataset(
        db, provider=None, schema_map={"input": "prompt"}
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Endpoint tools",
            "mode": "endpoint",
            "metrics": [{"key": "deepeval.tool_correctness"}],
            "judge": None,
            "endpoint_config": {
                "url": "https://example.com/agent",
                "response_mappings": {
                    "actual_output": "$.answer",
                    "agent_trace": "$.trace",
                    "tools_called": "$.called",
                    "expected_tools": "$.expected",
                },
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == 201


def test_create_agent_run_rejects_missing_structured_mapping(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, _ = _ready_dataset(
        db,
        provider=None,
        schema_map={
            "input": "prompt",
            "actual_output": "answer",
            "agent_trace": "trace",
            "tools_called": "called",
        },
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Missing expected tools",
            "mode": "static",
            "metrics": [{"key": "deepeval.tool_correctness"}],
            "judge": None,
        },
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "expected_tools" in response.json()["detail"]


def test_create_tool_run_also_requires_the_agent_trace_sample_field(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, _ = _ready_dataset(
        db,
        provider=None,
        schema_map={
            "input": "prompt",
            "actual_output": "answer",
            "tools_called": "called",
            "expected_tools": "expected",
        },
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Missing trace",
            "mode": "static",
            "metrics": [{"key": "deepeval.tool_correctness"}],
            "judge": None,
        },
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert "agent_trace" in response.json()["detail"]


def _post_conversation_run(
    client,
    auth_headers,
    db,
    monkeypatch,
    *,
    metric="deepeval.conversation_completeness",
    schema_map=None,
    judge=True,
    mode="static",
    endpoint_config=None,
):
    workspace, dataset, connection = _ready_dataset(
        db,
        provider="openai" if judge else None,
        schema_map=schema_map or {"turns": "conversation"},
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
    payload = {
        "dataset_id": dataset.id,
        "name": "Conversation check",
        "mode": mode,
        "metrics": [{"key": metric}],
        "judge": (
            {"connection_id": connection.id, "model": "gpt-4.1-mini"}
            if connection
            else None
        ),
    }
    if endpoint_config is not None:
        payload["endpoint_config"] = endpoint_config
    return client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json=payload,
        headers=auth_headers,
    )


def test_create_static_conversation_run_needs_no_single_turn_columns(
    client, auth_headers, db, monkeypatch
):
    response = _post_conversation_run(
        client, auth_headers, db, monkeypatch
    )

    assert response.status_code == 201


def test_create_role_adherence_run_requires_role_mapping(
    client, auth_headers, db, monkeypatch
):
    response = _post_conversation_run(
        client,
        auth_headers,
        db,
        monkeypatch,
        metric="deepeval.role_adherence",
    )

    assert response.status_code == 422
    assert "chatbot_role" in response.json()["detail"]


def test_create_mcp_use_run_requires_event_mapping(
    client, auth_headers, db, monkeypatch
):
    response = _post_conversation_run(
        client,
        auth_headers,
        db,
        monkeypatch,
        metric="deepeval.mcp_use",
        schema_map={
            "turns": "conversation",
            "mcp_metadata": "servers",
        },
    )

    assert response.status_code == 422
    assert "mcp_events" in response.json()["detail"]


def test_create_run_rejects_mixed_conversation_and_single_turn_metrics(
    client, auth_headers, db, monkeypatch
):
    workspace, dataset, connection = _ready_dataset(
        db,
        schema_map={
            "input": "prompt",
            "actual_output": "answer",
            "turns": "conversation",
        },
    )
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)

    response = client.post(
        f"/api/workspaces/{workspace.id}/runs",
        json={
            "dataset_id": dataset.id,
            "name": "Mixed conversation",
            "mode": "static",
            "metrics": [
                {"key": "deepeval.turn_relevancy"},
                {"key": "deepeval.answer_relevancy"},
            ],
            "judge": {
                "connection_id": connection.id,
                "model": "gpt-4.1-mini",
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Metrics with different sample kinds need a separate run"
    )


def test_create_conversation_run_requires_judge(
    client, auth_headers, db, monkeypatch
):
    response = _post_conversation_run(
        client,
        auth_headers,
        db,
        monkeypatch,
        metric="deepeval.turn_relevancy",
        judge=False,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "A judge connection is required for the selected metrics"
    )


def test_create_endpoint_conversation_run_accepts_turn_mapping(
    client, auth_headers, db, monkeypatch
):
    response = _post_conversation_run(
        client,
        auth_headers,
        db,
        monkeypatch,
        mode="endpoint",
        endpoint_config={
            "url": "https://example.com/chat",
            "response_mappings": {
                "actual_output": "$.answer",
                "turns": "$.turns",
            },
        },
    )

    assert response.status_code == 201


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


def test_create_run_custom_connection_valid_model(
    client, auth_headers, db, monkeypatch
):
    from app.routers import runs

    workspace, dataset, _ = _ready_dataset(db, provider=None)
    connection = _custom_connection(db, workspace.id)
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
    monkeypatch.setattr(
        runs, "discover_models", lambda base_url, api_key: ["chat-a", "chat-b"]
    )
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


def test_create_run_custom_connection_stale_model(
    client, auth_headers, db, monkeypatch
):
    from app.routers import runs

    workspace, dataset, _ = _ready_dataset(db, provider=None)
    connection = _custom_connection(db, workspace.id)
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
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

    workspace, dataset, _ = _ready_dataset(db, provider=None)
    other_user = User(email="other-ws@example.com", password_hash="x")
    db.add(other_user)
    db.flush()
    other_ws = Workspace(name="Other", owner_id=other_user.id)
    db.add(other_ws)
    db.flush()
    foreign = _custom_connection(db, other_ws.id, name="Foreign")
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
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


def test_create_run_embedding_from_separate_connection(
    client, auth_headers, db, monkeypatch
):
    from app.routers import runs

    # judge LLM on one custom connection, embeddings on a different one
    workspace, dataset, _ = _ready_dataset(db, provider=None)
    judge_conn = _custom_connection(db, workspace.id, name="LLM Gateway")
    embed_conn = _custom_connection(db, workspace.id, name="Embed Gateway")
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
    monkeypatch.setattr(
        runs, "discover_models", lambda base_url, api_key: ["chat-a", "embed-x"]
    )

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


def test_create_run_embedding_connection_must_support_embeddings(
    client, auth_headers, db, monkeypatch
):
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
    monkeypatch.setattr("app.tasks.dispatch_outbox_event", lambda event_id: True)
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
