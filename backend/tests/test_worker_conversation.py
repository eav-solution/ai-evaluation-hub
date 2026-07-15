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


def _conversation_adapter(key, scorer):
    from app.evals.base import CallableAdapter

    return CallableAdapter(
        key=key,
        framework="test",
        display_name=key,
        description=key,
        requires=frozenset(),
        scorer=scorer,
        sample_kind="conversation",
        resource_fn=lambda config: frozenset(),
    )


def _sample():
    return {
        "kind": "conversation",
        "turns": [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Open a.txt"},
            {"role": "assistant", "content": "Done"},
        ],
        "chatbot_role": "file assistant",
        "conversation_context": ["workspace policy"],
        "mcp_metadata": {
            "servers": [{"server_name": "files", "transport": "stdio"}]
        },
        "mcp_events": [
            {
                "type": "tool",
                "name": "read",
                "payload": {"args": {"path": "a.txt"}, "result": "data"},
            }
        ],
        "metadata": {"session": "chat-1"},
        "tags": ["prod"],
    }


def test_static_conversation_worker_persists_typed_sample(db, monkeypatch):
    from app import storage, tasks
    from app.evals.base import MetricScore
    from app.evals.samples import ConversationSample
    from app.models import Dataset, Run, RunResult

    workspace = _workspace(db, "conversation-static@example.com")
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Conversations",
        format="jsonl",
        row_count=1,
        storage_path=f"datasets/{workspace.id}/conversations.jsonl",
        schema_map={
            "turns": "turns",
            "chatbot_role": "chatbot_role",
            "conversation_context": "conversation_context",
            "mcp_metadata": "mcp_metadata",
            "mcp_events": "mcp_events",
            "metadata": "metadata",
            "tags": "tags",
        },
    )
    db.add(dataset)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        name="Conversation static",
        mode="static",
        metric_config={"metrics": [{"key": "test.conversation"}]},
        judge_config={},
        definition_snapshot={
            "schema_map": dict(dataset.schema_map),
            "sample": {"kind": "conversation"},
        },
    )
    db.add(run)
    db.commit()
    monkeypatch.setattr(
        storage, "get_object", lambda key: (json.dumps(_sample()) + "\n").encode()
    )
    seen = []

    def scorer(sample, judge, config):
        assert isinstance(sample, ConversationSample)
        assert sample.chatbot_role == "file assistant"
        assert sample.mcp_metadata.servers[0].server_name == "files"
        assert sample.mcp_events[0].name == "read"
        seen.append(sample)
        return MetricScore("test.conversation", 0.9, "ok", True)

    monkeypatch.setattr(
        tasks,
        "METRICS",
        {"test.conversation": _conversation_adapter("test.conversation", scorer)},
    )

    tasks.evaluate_run.run(run.id)
    db.expire_all()

    result = db.query(RunResult).filter_by(run_id=run.id).one()
    sample_details = result.details["sample"]
    assert len(seen) == 1
    assert result.input == "Open a.txt"
    assert result.actual == "Done"
    assert result.expected is None
    assert result.contexts is None
    assert set(sample_details) == {
        "kind",
        "turns",
        "chatbot_role",
        "conversation_context",
        "mcp_metadata",
        "mcp_events",
        "metadata",
        "tags",
        "source",
        "normalizer_revision",
    }
    assert sample_details["kind"] == "conversation"
    assert sample_details["metadata"] == {"session": "chat-1"}
    assert sample_details["tags"] == ["prod"]
    assert sample_details["source"] == {"row_index": 0, "event_id": None, "external_id": None}


def test_ingestion_conversation_worker_recovers_persisted_sample(db, monkeypatch):
    from app import storage, tasks
    from app.evals.base import MetricScore
    from app.evals.samples import ConversationSample
    from app.models import EvaluationArtifact, Run, RunResult

    workspace = _workspace(db, "conversation-ingestion@example.com")
    sample = _sample()
    artifact = EvaluationArtifact(
        workspace_id=workspace.id,
        sample_kind="conversation",
        idempotency_key="conversation-worker",
        request_hash="b" * 64,
        storage_path=f"evaluation-artifacts/{workspace.id}/conversation.json",
    )
    db.add(artifact)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=None,
        artifact_id=artifact.id,
        name="Conversation ingestion",
        mode="ingestion",
        metric_config={
            "metrics": [{"key": "test.done"}, {"key": "test.remaining"}]
        },
        judge_config={},
        definition_snapshot={"sample": {"kind": "conversation"}},
        progress_total=1,
    )
    db.add(run)
    db.flush()
    db.add(
        RunResult(
            workspace_id=workspace.id,
            run_id=run.id,
            row_index=0,
            input="Open a.txt",
            actual="Done",
            scores={
                "test.done": {
                    "score": 1.0,
                    "reason": "done",
                    "passed": True,
                    "error": None,
                    "in_progress": False,
                }
            },
            details={"sample": sample},
        )
    )
    db.commit()
    requested = []

    def get_object(key):
        requested.append(key)
        return json.dumps(sample).encode()

    monkeypatch.setattr(storage, "get_object", get_object)
    calls = []

    def done(sample, judge, config):
        calls.append("done")
        return MetricScore("test.done", 1.0, "done", True)

    def remaining(sample, judge, config):
        assert isinstance(sample, ConversationSample)
        assert sample.metadata == {"session": "chat-1"}
        assert sample.tags == ["prod"]
        assert sample.mcp_events[0].name == "read"
        calls.append("remaining")
        return MetricScore("test.remaining", 0.8, "ok", True)

    monkeypatch.setattr(
        tasks,
        "METRICS",
        {
            "test.done": _conversation_adapter("test.done", done),
            "test.remaining": _conversation_adapter("test.remaining", remaining),
        },
    )

    tasks.evaluate_run.run(run.id)
    db.expire_all()

    result = db.query(RunResult).filter_by(run_id=run.id).one()
    assert requested == [artifact.storage_path]
    assert calls == ["remaining"]
    assert result.scores["test.done"]["score"] == 1.0
    assert result.scores["test.remaining"]["score"] == 0.8


def test_endpoint_conversation_worker_overrides_turns_and_isolates_bad_row(
    db, monkeypatch
):
    from app import storage, tasks
    from app.endpoints import render_template
    from app.evals.base import MetricScore
    from app.evals.samples import ConversationSample
    from app.models import Dataset, Run, RunResult

    workspace = _workspace(db, "conversation-endpoint@example.com")
    seed_turns = [
        {"role": "user", "content": "seed one"},
        {"role": "assistant", "content": "seed answer"},
    ]
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Conversation seeds",
        format="json",
        row_count=2,
        storage_path=f"datasets/{workspace.id}/seeds.json",
        schema_map={"turns": "history"},
    )
    db.add(dataset)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        name="Conversation endpoint",
        mode="endpoint",
        metric_config={"metrics": [{"key": "test.conversation"}]},
        endpoint_config={
            "url": "https://example.com/chat",
            "method": "POST",
            "headers": {},
            "body_template": {"history": "{{turns}}"},
            "response_mappings": {
                "actual_output": "$.answer",
                "turns": "$.turns",
                "mcp_events": "$.events",
            },
        },
        judge_config={},
        definition_snapshot={
            "schema_map": {"turns": "history"},
            "sample": {"kind": "conversation"},
        },
    )
    db.add(run)
    db.commit()
    monkeypatch.setattr(
        storage,
        "get_object",
        lambda key: json.dumps(
            [{"history": seed_turns}, {"history": seed_turns}]
        ).encode(),
    )
    requests = []
    response_turns = [
        {"role": "user", "content": "response question"},
        {"role": "assistant", "content": "response answer"},
    ]

    def endpoint(config, row, *, encrypted_headers):
        assert isinstance(row, ConversationSample)
        requests.append(render_template(config["body_template"], row))
        if len(requests) == 1:
            payload = {
                "answer": "response answer",
                "turns": response_turns,
                "events": [
                    {"type": "tool", "name": "read", "payload": {}}
                ],
            }
        else:
            payload = {
                "answer": "bad",
                "turns": "not json",
                "events": [],
            }
        return payload["answer"], payload, 11.7

    monkeypatch.setattr(tasks, "call_endpoint", endpoint)
    scored = []

    def scorer(sample, judge, config):
        assert isinstance(sample, ConversationSample)
        scored.append(sample)
        return MetricScore("test.conversation", 0.9, "ok", True)

    monkeypatch.setattr(
        tasks,
        "METRICS",
        {"test.conversation": _conversation_adapter("test.conversation", scorer)},
    )

    tasks.evaluate_run.run(run.id)
    db.expire_all()

    results = db.query(RunResult).order_by(RunResult.row_index).all()
    assert [turn["content"] for turn in requests[0]["history"]] == [
        "seed one",
        "seed answer",
    ]
    assert len(scored) == 1
    assert scored[0].turns[-1].content == "response answer"
    assert scored[0].mcp_events[0].name == "read"
    assert results[0].input == "response question"
    assert results[0].actual == "response answer"
    assert results[0].error is None
    assert "expected valid JSON" in results[1].error
