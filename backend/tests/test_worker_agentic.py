import json


def _workspace(db, email: str):
    from app.models import User, Workspace

    user = User(email=email, password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name=email, owner_id=user.id)
    db.add(workspace)
    db.flush()
    return workspace


def _agent_adapter(key, scorer):
    from app.evals.base import CallableAdapter

    return CallableAdapter(
        key=key,
        framework="test",
        display_name=key,
        description=key,
        requires=frozenset(),
        scorer=scorer,
        sample_kind="agent_trace",
        resource_fn=lambda config: frozenset(),
    )


def test_static_agent_worker_scores_typed_sample_without_provider(db, monkeypatch):
    from app import storage, tasks
    from app.evals.base import MetricScore
    from app.evals.samples import AgentTraceSample
    from app.models import Dataset, Run, RunResult

    workspace = _workspace(db, "agent-static@example.com")
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Agent rows",
        format="json",
        row_count=1,
        storage_path=f"datasets/{workspace.id}/agents.json",
        schema_map={
            "input": "prompt",
            "actual_output": "answer",
            "agent_trace": "trace",
            "tools_called": "called",
            "expected_tools": "expected",
        },
    )
    db.add(dataset)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        name="Agent static",
        mode="static",
        metric_config={
            "metrics": [
                {"key": "test.complete"},
                {"key": "test.loop"},
                {"key": "test.tools"},
            ]
        },
        judge_config={},
        definition_snapshot={
            "schema_map": dict(dataset.schema_map),
            "sample": {"kind": "agent_trace"},
        },
    )
    db.add(run)
    db.commit()
    monkeypatch.setattr(
        storage,
        "get_object",
        lambda key: json.dumps(
            [
                {
                    "prompt": "Book VN1",
                    "answer": "Booked",
                    "trace": [{"type": "tool", "name": "book"}],
                    "called": [{"name": "book", "arguments": {"flight": "VN1"}}],
                    "expected": ["book"],
                }
            ]
        ).encode(),
    )
    monkeypatch.setattr(
        tasks,
        "resolve_connection",
        lambda *args: (_ for _ in ()).throw(AssertionError("provider resolved")),
    )
    seen = []

    def score(key, value):
        def scorer(sample, judge, config):
            assert isinstance(sample, AgentTraceSample)
            assert judge is None
            seen.append((key, sample))
            if key == "test.loop":
                raise RuntimeError("loop metric failed")
            return MetricScore(key, value, "ok", True)

        return scorer

    monkeypatch.setattr(
        tasks,
        "METRICS",
        {
            "test.complete": _agent_adapter("test.complete", score("test.complete", 0.9)),
            "test.loop": _agent_adapter("test.loop", score("test.loop", 0.0)),
            "test.tools": _agent_adapter("test.tools", score("test.tools", 1.0)),
        },
    )

    tasks.evaluate_run.run(run.id)
    db.expire_all()

    stored = db.get(Run, run.id)
    result = db.query(RunResult).filter_by(run_id=run.id).one()
    assert stored.status == "completed"
    assert [item[0] for item in seen] == ["test.complete", "test.loop", "test.tools"]
    assert result.scores["test.loop"]["error"] == "loop metric failed"
    assert result.details["sample"]["kind"] == "agent_trace"
    assert result.details["sample"]["agent_trace"][0]["name"] == "book"
    assert result.details["sample"]["tools_called"][0]["arguments"] == {
        "flight": "VN1"
    }
    assert result.details["sample"]["expected_tools"][0]["name"] == "book"


def test_endpoint_agent_worker_normalizes_named_response_fields(db, monkeypatch):
    from app import storage, tasks
    from app.evals.base import MetricScore
    from app.evals.samples import AgentTraceSample
    from app.models import Dataset, Run, RunResult

    workspace = _workspace(db, "agent-endpoint@example.com")
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Prompts",
        format="json",
        row_count=1,
        storage_path=f"datasets/{workspace.id}/prompts.json",
        schema_map={"input": "prompt"},
    )
    db.add(dataset)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        name="Agent endpoint",
        mode="endpoint",
        metric_config={"metrics": [{"key": "test.tools"}]},
        endpoint_config={
            "url": "https://example.com/agent",
            "method": "POST",
            "headers": {},
            "body_template": {"input": "{{input}}"},
            "response_mappings": {
                "actual_output": "$.answer",
                "agent_trace": "$.trace",
                "tools_called": "$.called",
                "expected_tools": "$.expected",
            },
        },
        judge_config={},
        definition_snapshot={
            "schema_map": {"input": "prompt"},
            "sample": {"kind": "agent_trace"},
        },
    )
    db.add(run)
    db.commit()
    monkeypatch.setattr(storage, "get_object", lambda key: b'[{"prompt":"Book VN1"}]')
    monkeypatch.setattr(
        tasks,
        "resolve_connection",
        lambda *args: (_ for _ in ()).throw(AssertionError("provider resolved")),
    )
    payload = {
        "answer": "Booked",
        "trace": [{"type": "tool", "name": "book"}],
        "called": [{"name": "book", "arguments": {"flight": "VN1"}}],
        "expected": ["book"],
    }
    monkeypatch.setattr(
        tasks,
        "call_endpoint",
        lambda *args, **kwargs: ("Booked", payload, 12.2),
    )
    seen = []

    def scorer(sample, judge, config):
        assert isinstance(sample, AgentTraceSample)
        seen.append(sample)
        return MetricScore("test.tools", 1.0, "ok", True)

    monkeypatch.setattr(
        tasks, "METRICS", {"test.tools": _agent_adapter("test.tools", scorer)}
    )

    tasks.evaluate_run.run(run.id)
    db.expire_all()

    result = db.query(RunResult).filter_by(run_id=run.id).one()
    assert result.error is None
    assert result.actual == "Booked"
    assert result.latency_ms == 12
    assert seen[0].agent_trace[0].name == "book"
    assert seen[0].expected_tools[0].name == "book"


def test_ingestion_worker_loads_artifact_and_recovers_typed_sample(db, monkeypatch):
    from app import storage, tasks
    from app.evals.base import MetricScore
    from app.evals.samples import AgentTraceSample
    from app.models import EvaluationArtifact, Run, RunResult

    workspace = _workspace(db, "agent-ingestion@example.com")
    sample = {
        "kind": "agent_trace",
        "input": "Book VN1",
        "actual_output": "Booked",
        "agent_trace": [{"type": "tool", "name": "book"}],
        "tools_called": [{"name": "book", "arguments": {"flight": "VN1"}}],
        "expected_tools": ["book"],
    }
    artifact = EvaluationArtifact(
        workspace_id=workspace.id,
        sample_kind="agent_trace",
        idempotency_key="worker-trace",
        request_hash="a" * 64,
        storage_path=f"evaluation-artifacts/{workspace.id}/trace.json",
    )
    db.add(artifact)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=None,
        artifact_id=artifact.id,
        name="Ingestion worker",
        mode="ingestion",
        metric_config={
            "metrics": [{"key": "test.done"}, {"key": "test.remaining"}]
        },
        judge_config={},
        definition_snapshot={"sample": {"kind": "agent_trace"}},
        progress_total=1,
    )
    db.add(run)
    db.flush()
    db.add(
        RunResult(
            workspace_id=workspace.id,
            run_id=run.id,
            row_index=0,
            input=sample["input"],
            actual=sample["actual_output"],
            scores={
                "test.done": {
                    "score": 1.0,
                    "reason": "done",
                    "passed": True,
                    "error": None,
                    "in_progress": False,
                }
            },
            details={
                "sample": {
                    "kind": "agent_trace",
                    "agent_trace": sample["agent_trace"],
                    "tools_called": sample["tools_called"],
                    "expected_tools": [{"name": "book"}],
                    "metadata": {},
                    "tags": [],
                }
            },
        )
    )
    db.commit()
    requested = []

    def get_object(key):
        requested.append(key)
        return json.dumps(sample).encode()

    monkeypatch.setattr(storage, "get_object", get_object)
    monkeypatch.setattr(
        tasks,
        "resolve_connection",
        lambda *args: (_ for _ in ()).throw(AssertionError("provider resolved")),
    )
    calls = []

    def done(sample, judge, config):
        calls.append("done")
        return MetricScore("test.done", 1.0, "done", True)

    def remaining(sample, judge, config):
        assert isinstance(sample, AgentTraceSample)
        assert sample.expected_tools[0].name == "book"
        calls.append("remaining")
        return MetricScore("test.remaining", 0.8, "ok", True)

    monkeypatch.setattr(
        tasks,
        "METRICS",
        {
            "test.done": _agent_adapter("test.done", done),
            "test.remaining": _agent_adapter("test.remaining", remaining),
        },
    )

    tasks.evaluate_run.run(run.id)
    db.expire_all()

    assert requested == [artifact.storage_path]
    assert calls == ["remaining"]
    assert db.get(Run, run.id).status == "completed"
    result = db.query(RunResult).filter_by(run_id=run.id).one()
    assert result.scores["test.done"]["score"] == 1.0
    assert result.scores["test.remaining"]["score"] == 0.8
