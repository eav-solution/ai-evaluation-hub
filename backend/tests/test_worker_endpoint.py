def test_endpoint_worker_continues_after_row_failure(db, monkeypatch):
    from app import storage, tasks
    from app.evals.base import CallableAdapter, MetricScore
    from app.models import (
        Dataset,
        Membership,
        ProviderConnection,
        Run,
        RunResult,
        User,
        Workspace,
    )
    from app.security import encrypt_secret

    user = User(email="endpoint-worker@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Endpoint Worker", owner_id=user.id)
    db.add(workspace)
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Prompts",
        format="json",
        row_count=2,
        storage_path=f"datasets/{workspace.id}/prompts.json",
        schema_map={"input": "prompt"},
    )
    db.add(dataset)
    db.add(
        ProviderConnection(
            workspace_id=workspace.id,
            name="OpenAI",
            connection_type="openai",
            encrypted_key=encrypt_secret("sk-test"),
        )
    )
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        name="Endpoint run",
        mode="endpoint",
        metric_config={"metrics": [{"key": "test.score", "threshold": 0.5}]},
        endpoint_config={
            "url": "https://example.com",
            "method": "POST",
            "headers": {"Authorization": encrypt_secret("Bearer endpoint")},
            "body_template": {"prompt": "{{input}}"},
            "response_jsonpath": None,
            "response_mappings": {
                "actual_output": "$.answer",
                "context": "$.facts",
                "retrieval_contexts": "$.documents",
            },
        },
        judge_config={"provider": "openai", "model": "model"},
        progress_total=2,
    )
    db.add(run)
    db.commit()

    monkeypatch.setattr(
        storage,
        "get_object",
        lambda key: b'[{"prompt":"one"},{"prompt":"two"}]',
    )
    scored_rows = []

    def score(row, judge, config):
        scored_rows.append(row)
        return MetricScore("test.score", 0.9, row.actual_output, True)

    adapter = CallableAdapter(
        key="test.score",
        framework="test",
        display_name="Score",
        description="Score",
        requires=frozenset(),
        scorer=score,
    )
    monkeypatch.setattr(tasks, "METRICS", {"test.score": adapter})
    calls = []

    def fake_call(config, row, *, encrypted_headers):
        calls.append((row.input, encrypted_headers))
        if row.input == "two":
            raise RuntimeError("endpoint unavailable")
        return (
            "answer one",
            {
                "answer": "answer one",
                "facts": ["trusted fact"],
                "documents": ["retrieved document"],
            },
            17.4,
        )

    monkeypatch.setattr(tasks, "call_endpoint", fake_call)
    tasks.evaluate_run.run(run.id)
    db.expire_all()

    stored_run = db.get(Run, run.id)
    results = db.query(RunResult).order_by(RunResult.row_index).all()
    assert stored_run.status == "completed"
    assert stored_run.progress_done == 2
    assert calls == [("one", True), ("two", True)]
    assert results[0].actual == "answer one"
    assert results[0].latency_ms == 17
    assert results[0].scores["test.score"]["score"] == 0.9
    assert results[0].details["sample"]["context"] == ["trusted fact"]
    assert results[0].contexts == ["retrieved document"]
    assert scored_rows[0].context == ["trusted fact"]
    assert scored_rows[0].retrieval_contexts == ["retrieved document"]
    assert results[1].actual is None
    assert results[1].error == "endpoint unavailable"

    stored_run.status = "pending"
    stored_run.finished_at = None
    db.commit()
    tasks.evaluate_run.run(run.id)
    db.expire_all()

    assert db.get(Run, run.id).status == "completed"
    assert calls == [("one", True), ("two", True)]


def test_endpoint_crash_is_not_replayed_after_recovery(db, monkeypatch):
    from datetime import datetime, timedelta, timezone

    import pytest

    from app import storage, tasks
    from app.evals.base import CallableAdapter, MetricScore
    from app.models import Dataset, ProviderConnection, Run, RunResult, User, Workspace
    from app.security import encrypt_secret

    user = User(email="endpoint-crash@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Endpoint crash", owner_id=user.id)
    db.add(workspace)
    db.flush()
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Prompts",
        format="json",
        row_count=1,
        storage_path=f"datasets/{workspace.id}/prompts.json",
        schema_map={"input": "prompt"},
    )
    db.add(dataset)
    db.add(
        ProviderConnection(
            workspace_id=workspace.id,
            name="OpenAI",
            connection_type="openai",
            encrypted_key=encrypt_secret("sk-test"),
        )
    )
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        name="Endpoint crash",
        mode="endpoint",
        metric_config={"metrics": [{"key": "test.score", "threshold": 0.5}]},
        endpoint_config={
            "url": "https://example.com",
            "method": "POST",
            "headers": {},
            "body_template": {"prompt": "{{input}}"},
            "response_jsonpath": "$.answer",
        },
        judge_config={"provider": "openai", "model": "model"},
        definition_snapshot={"schema_map": {"input": "prompt"}},
        progress_total=1,
    )
    db.add(run)
    db.commit()
    monkeypatch.setattr(storage, "get_object", lambda key: b'[{"prompt":"one"}]')
    adapter = CallableAdapter(
        key="test.score",
        framework="test",
        display_name="Score",
        description="Score",
        requires=frozenset(),
        scorer=lambda row, judge, config: MetricScore(
            "test.score", 0.9, "ok", True
        ),
    )
    monkeypatch.setattr(tasks, "METRICS", {"test.score": adapter})
    calls = []

    def crash(config, row, *, encrypted_headers):
        calls.append(row.input)
        raise SystemExit("worker stopped")

    monkeypatch.setattr(tasks, "call_endpoint", crash)
    with pytest.raises(SystemExit, match="worker stopped"):
        tasks.evaluate_run.run(run.id)

    db.expire_all()
    checkpoint = db.query(RunResult).filter_by(run_id=run.id).one()
    assert "interrupted" in checkpoint.error.lower()
    stored_run = db.get(Run, run.id)
    stored_run.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    monkeypatch.setattr(tasks, "dispatch_outbox_event", lambda event_id: True)
    tasks.recover_stale_evaluation_runs()
    tasks.evaluate_run.run(run.id)

    db.expire_all()
    assert calls == ["one"]
    assert db.get(Run, run.id).status == "failed"
    assert "interrupted" in (
        db.query(RunResult).filter_by(run_id=run.id).one().error.lower()
    )
