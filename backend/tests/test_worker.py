def _one_row_run(db, *, name="One row"):
    from app.models import Dataset, ProviderConnection, Run, User, Workspace
    from app.security import encrypt_secret

    user = User(
        email=f"{name.lower().replace(' ', '-')}@example.com", password_hash="x"
    )
    db.add(user)
    db.flush()
    workspace = Workspace(name=name, owner_id=user.id)
    db.add(workspace)
    db.flush()
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Rows",
        format="json",
        row_count=1,
        storage_path=f"datasets/{workspace.id}/rows.json",
        schema_map={"input": "prompt", "actual_output": "answer"},
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
        name=name,
        mode="static",
        metric_config={"metrics": [{"key": "test.score", "threshold": 0.5}]},
        judge_config={"provider": "openai", "model": "model"},
        definition_snapshot={"schema_map": dict(dataset.schema_map)},
        progress_total=1,
    )
    db.add(run)
    db.commit()
    return run


def test_worker_scores_rows_and_builds_summaries(db, monkeypatch):
    from app import storage
    from app.evals.base import CallableAdapter, MetricScore
    from app.models import (
        Dataset,
        Membership,
        ProviderConnection,
        Run,
        RunResult,
        RunSummary,
        User,
        Workspace,
    )
    from app.security import encrypt_secret

    user = User(email="worker@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Worker", owner_id=user.id)
    db.add(workspace)
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Rows",
        format="json",
        row_count=2,
        storage_path=f"datasets/{workspace.id}/rows.json",
        schema_map={"input": "prompt", "actual_output": "answer"},
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
        name="Worker run",
        mode="static",
        metric_config={
            "metrics": [
                {"key": "test.good", "threshold": 0.5},
                {"key": "test.bad", "threshold": 0.5},
            ]
        },
        judge_config={"provider": "openai", "model": "model"},
        definition_snapshot={
            "schema_map": {"input": "prompt", "actual_output": "answer"}
        },
        progress_total=2,
    )
    db.add(run)
    db.commit()
    original_storage_path = dataset.storage_path
    run.definition_snapshot = {
        **run.definition_snapshot,
        "dataset": {
            "storage_path": original_storage_path,
            "format": "json",
        },
    }
    dataset.schema_map = {
        "input": "changed_prompt",
        "actual_output": "changed_answer",
    }
    dataset.storage_path = f"datasets/{workspace.id}/replacement.csv"
    dataset.format = "csv"
    db.commit()

    requested_keys = []

    def get_snapshot_object(key):
        requested_keys.append(key)
        return (
            b'[{"prompt":"one","answer":"a","changed_prompt":"wrong-one",'
            b'"changed_answer":"wrong-a"},{"prompt":"two","answer":"b",'
            b'"changed_prompt":"wrong-two","changed_answer":"wrong-b"}]'
        )

    monkeypatch.setattr(
        storage,
        "get_object",
        get_snapshot_object,
    )
    scorer_calls = []

    def score_good(row, judge, config):
        scorer_calls.append(("test.good", row.input))
        return MetricScore("test.good", 0.8, "ok", True)

    def score_bad(row, judge, config):
        scorer_calls.append(("test.bad", row.input))
        raise RuntimeError("metric failed")

    good = CallableAdapter(
        key="test.good",
        framework="test",
        display_name="Good",
        description="Good",
        requires=frozenset(),
        scorer=score_good,
    )
    bad = CallableAdapter(
        key="test.bad",
        framework="test",
        display_name="Bad",
        description="Bad",
        requires=frozenset(),
        scorer=score_bad,
    )

    from app import tasks

    monkeypatch.setattr(tasks, "METRICS", {"test.good": good, "test.bad": bad})
    tasks.evaluate_run.run(run.id)
    db.expire_all()

    assert db.get(Run, run.id).status == "completed"
    assert db.get(Run, run.id).progress_done == 2
    results = db.query(RunResult).order_by(RunResult.row_index).all()
    assert len(results) == 2
    assert results[0].input == "one"
    assert results[0].actual == "a"
    assert requested_keys == [original_storage_path]
    assert results[0].scores["test.good"]["score"] == 0.8
    assert results[0].scores["test.bad"]["error"] == "metric failed"
    summary = db.query(RunSummary).filter_by(metric_key="test.good").one()
    assert summary.mean == 0.8
    assert summary.pass_rate == 1.0
    stored_run = db.get(Run, run.id)
    stored_run.status = "pending"
    stored_run.finished_at = None
    db.commit()
    tasks.evaluate_run.run(run.id)
    db.expire_all()
    assert db.get(Run, run.id).attempt == 2
    assert scorer_calls == [
        ("test.good", "one"),
        ("test.bad", "one"),
        ("test.good", "two"),
        ("test.bad", "two"),
    ]


def test_dispatch_outbox_event_enqueues_evaluation(db, monkeypatch):
    from app import tasks
    from app.models import OutboxEvent

    event = OutboxEvent(
        kind="evaluate_run",
        dedupe_key="evaluation:run-1",
        payload={"run_id": "run-1"},
    )
    db.add(event)
    db.commit()
    event_id = event.id
    published = []
    monkeypatch.setattr(
        tasks.evaluate_run,
        "apply_async",
        lambda **kwargs: published.append(kwargs),
    )

    assert tasks.dispatch_outbox_event(event_id) is True
    assert published == [{"args": ["run-1"], "task_id": f"evaluation-{event_id}"}]
    db.expire_all()
    assert db.get(OutboxEvent, event_id) is None


def test_recovery_resumes_without_repeating_interrupted_metric(db, monkeypatch):
    from datetime import datetime, timedelta, timezone

    import pytest

    from app import storage, tasks
    from app.evals.base import CallableAdapter
    from app.models import Run, RunResult

    run = _one_row_run(db, name="Interrupted metric")
    monkeypatch.setattr(
        storage,
        "get_object",
        lambda key: b'[{"prompt":"one","answer":"a"}]',
    )
    calls = []

    def crash(row, judge, config):
        calls.append(row.input)
        raise SystemExit("worker stopped")

    adapter = CallableAdapter(
        key="test.score",
        framework="test",
        display_name="Score",
        description="Score",
        requires=frozenset(),
        scorer=crash,
    )
    monkeypatch.setattr(tasks, "METRICS", {"test.score": adapter})

    with pytest.raises(SystemExit, match="worker stopped"):
        tasks.evaluate_run.run(run.id)

    db.expire_all()
    checkpoint = db.query(RunResult).filter_by(run_id=run.id).one()
    assert checkpoint.scores["test.score"]["in_progress"] is True
    stored_run = db.get(Run, run.id)
    stored_run.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    monkeypatch.setattr(tasks, "dispatch_outbox_event", lambda event_id: True)
    tasks.recover_stale_evaluation_runs()
    tasks.evaluate_run.run(run.id)

    db.expire_all()
    stored_run = db.get(Run, run.id)
    checkpoint = db.query(RunResult).filter_by(run_id=run.id).one()
    assert calls == ["one"]
    assert stored_run.status == "failed"
    assert checkpoint.scores["test.score"]["in_progress"] is False
    assert "interrupted" in checkpoint.scores["test.score"]["error"].lower()


def test_recover_stale_evaluation_run_requeues_outbox(db, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app import tasks
    from app.models import OutboxEvent, Run

    run = _one_row_run(db, name="Stale evaluation")
    run.status = "running"
    run.attempt = 1
    run.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    dispatched = []
    monkeypatch.setattr(tasks, "dispatch_outbox_event", dispatched.append)

    tasks.recover_stale_evaluation_runs()

    db.expire_all()
    stored_run = db.get(Run, run.id)
    event = db.query(OutboxEvent).filter_by(dedupe_key=f"evaluation:{run.id}").one()
    assert stored_run.status == "pending"
    assert stored_run.heartbeat_at is None
    assert event.payload == {"run_id": run.id}
    assert dispatched == [event.id]
