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
        progress_total=2,
    )
    db.add(run)
    db.commit()

    monkeypatch.setattr(
        storage,
        "get_object",
        lambda key: b'[{"prompt":"one","answer":"a"},{"prompt":"two","answer":"b"}]',
    )
    good = CallableAdapter(
        key="test.good",
        framework="test",
        display_name="Good",
        description="Good",
        requires=frozenset(),
        scorer=lambda row, judge, config: MetricScore(
            "test.good", 0.8, "ok", True
        ),
    )
    bad = CallableAdapter(
        key="test.bad",
        framework="test",
        display_name="Bad",
        description="Bad",
        requires=frozenset(),
        scorer=lambda row, judge, config: (_ for _ in ()).throw(
            RuntimeError("metric failed")
        ),
    )

    from app import tasks

    monkeypatch.setattr(tasks, "METRICS", {"test.good": good, "test.bad": bad})
    tasks.evaluate_run.run(run.id)
    db.expire_all()

    assert db.get(Run, run.id).status == "completed"
    assert db.get(Run, run.id).progress_done == 2
    results = db.query(RunResult).order_by(RunResult.row_index).all()
    assert len(results) == 2
    assert results[0].scores["test.good"]["score"] == 0.8
    assert results[0].scores["test.bad"]["error"] == "metric failed"
    summary = db.query(RunSummary).filter_by(metric_key="test.good").one()
    assert summary.mean == 0.8
    assert summary.pass_rate == 1.0
