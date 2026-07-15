import pytest


def test_create_user_workspace_membership(db):
    from app.models import Membership, User, Workspace

    user = User(email="a@b.com", password_hash="x")
    db.add(user)
    db.flush()
    ws = Workspace(name="Default", owner_id=user.id)
    db.add(ws)
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=ws.id, role="owner"))
    db.commit()

    assert db.get(User, user.id).email == "a@b.com"
    m = db.query(Membership).filter_by(user_id=user.id).one()
    assert m.workspace_id == ws.id
    assert m.role == "owner"


def test_run_snapshot_and_lease_roundtrip(db):
    from app.models import Dataset, Run, User, Workspace

    user = User(email="run-lease@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Run lease", owner_id=user.id)
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
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        name="Snapshot",
        mode="static",
        metric_config={"metrics": []},
        judge_config={},
        definition_snapshot={"schema_map": {"input": "prompt"}},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    assert run.definition_snapshot == {"schema_map": {"input": "prompt"}}
    assert run.attempt == 0
    assert run.heartbeat_at is None


def test_run_result_extensions_are_nullable_and_roundtrip(db):
    from app.models import Dataset, Run, RunResult, User, Workspace

    user = User(email="result-contract@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Result contract", owner_id=user.id)
    db.add(workspace)
    db.flush()
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Rows",
        format="json",
        row_count=2,
        storage_path=f"datasets/{workspace.id}/results.json",
        schema_map={"input": "prompt", "actual_output": "answer"},
    )
    db.add(dataset)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=dataset.id,
        name="Extended results",
        mode="static",
        metric_config={"metrics": []},
        judge_config={},
    )
    db.add(run)
    db.flush()
    db.add_all(
        [
            RunResult(
                workspace_id=workspace.id,
                run_id=run.id,
                row_index=0,
                input="Extended",
                scores={},
                details={"trace": [{"type": "tool", "name": "search"}]},
                usage={"input_tokens": 12, "output_tokens": 4},
                estimated_cost=0.0012,
            ),
            RunResult(
                workspace_id=workspace.id,
                run_id=run.id,
                row_index=1,
                input="Legacy",
                scores={},
            ),
        ]
    )
    db.commit()

    extended, legacy = db.query(RunResult).order_by(RunResult.row_index).all()
    assert extended.details == {"trace": [{"type": "tool", "name": "search"}]}
    assert extended.usage == {"input_tokens": 12, "output_tokens": 4}
    assert extended.estimated_cost == 0.0012
    assert legacy.details is None
    assert legacy.usage is None
    assert legacy.estimated_cost is None


def test_artifact_backed_run_roundtrip(db):
    from app.models import EvaluationArtifact, Run, User, Workspace

    user = User(email="artifact-run@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Artifact run", owner_id=user.id)
    db.add(workspace)
    db.flush()
    artifact = EvaluationArtifact(
        workspace_id=workspace.id,
        sample_kind="agent_trace",
        idempotency_key="trace-1",
        request_hash="a" * 64,
        storage_path=f"evaluation-artifacts/{workspace.id}/trace-1.json",
    )
    db.add(artifact)
    db.flush()
    run = Run(
        workspace_id=workspace.id,
        dataset_id=None,
        artifact_id=artifact.id,
        name="Ingested trace",
        mode="ingestion",
        metric_config={"metrics": []},
        judge_config={},
    )
    db.add(run)
    db.commit()

    saved = db.get(Run, run.id)
    assert saved.dataset_id is None
    assert saved.artifact_id == artifact.id


def test_artifact_idempotency_key_is_unique_per_workspace(db):
    import sqlalchemy as sa

    from app.models import EvaluationArtifact, User, Workspace

    user = User(email="artifact-unique@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Artifact unique", owner_id=user.id)
    db.add(workspace)
    db.flush()
    db.add_all(
        [
            EvaluationArtifact(
                workspace_id=workspace.id,
                sample_kind="agent_trace",
                idempotency_key="same",
                request_hash="a" * 64,
                storage_path=f"evaluation-artifacts/{workspace.id}/one.json",
            ),
            EvaluationArtifact(
                workspace_id=workspace.id,
                sample_kind="agent_trace",
                idempotency_key="same",
                request_hash="b" * 64,
                storage_path=f"evaluation-artifacts/{workspace.id}/two.json",
            ),
        ]
    )

    with pytest.raises(sa.exc.IntegrityError):
        db.commit()


def test_generation_models_roundtrip(db):
    from app.models import (
        Document,
        GenerationJob,
        GenerationRecord,
        User,
        Workspace,
    )

    user = User(email="generation-models@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Gen", owner_id=user.id)
    db.add(workspace)
    db.flush()
    document = Document(
        workspace_id=workspace.id,
        filename="guide.md",
        format="md",
        size_bytes=1234,
        storage_path=f"documents/{workspace.id}/doc1.md",
        char_count=1200,
        chunk_count=2,
    )
    db.add(document)
    db.flush()
    job = GenerationJob(
        workspace_id=workspace.id,
        name="From guide",
        document_ids=[document.id],
        mode="chunk",
        requested_count=6,
        max_count=6,
        generator_config={"provider": "openai", "model": "gpt-test"},
        options={"questions_per_chunk": 3, "language": None},
    )
    db.add(job)
    db.flush()
    record = GenerationRecord(
        workspace_id=workspace.id,
        job_id=job.id,
        record_index=0,
        question="What is EvalHub?",
        answer="An evaluation platform.",
        contexts=["chunk text"],
        source={"document_id": document.id, "chunk_index": 0},
    )
    db.add(record)
    db.commit()

    saved_job = db.get(GenerationJob, job.id)
    assert saved_job.document_ids == [document.id]
    assert saved_job.status == "pending"
    assert saved_job.unit_errors == []
    assert saved_job.generated_count == 0
    assert saved_job.attempt == 0
    assert saved_job.heartbeat_at is None
    assert saved_job.dataset_id is None
    assert saved_job.dataset_created is False
    saved_record = db.get(GenerationRecord, record.id)
    assert saved_record.contexts == ["chunk text"]
    assert saved_record.deleted is False


def test_provider_connection_roundtrip(db):
    import sqlalchemy as sa

    from app.models import ProviderConnection, User, Workspace

    user = User(email="conn-model@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Conn", owner_id=user.id)
    db.add(workspace)
    db.flush()

    native = ProviderConnection(
        workspace_id=workspace.id,
        name="OpenAI",
        connection_type="openai",
        encrypted_key="enc",
    )
    custom_a = ProviderConnection(
        workspace_id=workspace.id,
        name="Local Ollama",
        connection_type="openai_compatible",
        base_url="http://localhost:11434/v1",
        encrypted_key=None,
    )
    custom_b = ProviderConnection(
        workspace_id=workspace.id,
        name="LM Studio",
        connection_type="openai_compatible",
        base_url="http://localhost:1234/v1",
        encrypted_key=None,
    )
    db.add_all([native, custom_a, custom_b])
    db.commit()

    saved = (
        db.query(ProviderConnection)
        .filter_by(workspace_id=workspace.id)
        .order_by(ProviderConnection.name)
        .all()
    )
    assert {row.name for row in saved} == {"OpenAI", "Local Ollama", "LM Studio"}
    assert db.get(ProviderConnection, native.id).encrypted_key == "enc"
    assert db.get(ProviderConnection, custom_a.id).base_url == "http://localhost:11434/v1"
    assert db.get(ProviderConnection, custom_a.id).encrypted_key is None

    # case-insensitive unique name within a workspace
    db.add(
        ProviderConnection(
            workspace_id=workspace.id,
            name="lm studio",
            connection_type="openai_compatible",
            base_url="http://localhost:9/v1",
        )
    )
    try:
        db.commit()
        raise AssertionError("duplicate case-insensitive name should fail")
    except sa.exc.IntegrityError:
        db.rollback()

    # one native connection per type
    db.add(
        ProviderConnection(
            workspace_id=workspace.id,
            name="Second OpenAI",
            connection_type="openai",
            encrypted_key="enc2",
        )
    )
    try:
        db.commit()
        raise AssertionError("second openai connection should fail")
    except sa.exc.IntegrityError:
        db.rollback()


def test_provider_connection_settings_defaults():
    from app.config import Settings

    s = Settings()
    assert s.provider_discovery_timeout_seconds == 10
    assert s.provider_discovery_max_bytes == 2 * 1024 * 1024
    assert s.max_custom_connections == 20
