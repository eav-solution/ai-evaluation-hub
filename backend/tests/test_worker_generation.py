from app.documents import text_storage_key

DOC_TEXT = "EvalHub evaluates AI systems with configurable metrics. " * 40


def _setup(db, object_store, *, mode="chunk", requested=4):
    from app.models import Document, GenerationJob, Membership, ProviderConnection, User, Workspace
    from app.security import encrypt_secret

    user = User(email=f"gen-worker-{mode}-{requested}@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Gen worker", owner_id=user.id)
    db.add(workspace)
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    db.add(
        ProviderConnection(
            workspace_id=workspace.id,
            name="OpenAI",
            connection_type="openai",
            encrypted_key=encrypt_secret("sk-test"),
        )
    )
    document = Document(
        workspace_id=workspace.id,
        filename="guide.txt",
        format="txt",
        size_bytes=len(DOC_TEXT),
        storage_path=f"documents/{workspace.id}/doc.txt",
        char_count=len(DOC_TEXT),
        chunk_count=2,
    )
    db.add(document)
    db.flush()
    object_store[text_storage_key(workspace.id, document.id)] = DOC_TEXT.encode()
    job = GenerationJob(
        workspace_id=workspace.id,
        name="Job",
        document_ids=[document.id],
        mode=mode,
        requested_count=requested,
        max_count=6,
        generator_config={"provider": "openai", "model": "gpt-test"},
        options={"questions_per_chunk": 3, "language": None},
    )
    db.add(job)
    db.commit()
    return workspace, document, job


def test_generate_dataset_chunk_mode_happy_path(db, object_store, monkeypatch):
    from app import generation, tasks
    from app.models import GenerationJob, GenerationRecord

    workspace, document, job = _setup(db, object_store)
    calls = []

    def fake_generate(text, count, config, language=None):
        calls.append(count)
        return [
            generation.QAItem(
                question=f"Question {len(calls)}-{index}?",
                answer="Answer.",
                context="ignored in chunk mode",
            )
            for index in range(count)
        ]

    monkeypatch.setattr(generation, "generate_qa", fake_generate)
    tasks.generate_dataset(job.id)

    saved = db.get(GenerationJob, job.id)
    db.refresh(saved)
    assert saved.status == "completed"
    assert saved.generated_count == 4
    assert saved.progress_done == saved.progress_total
    records = (
        db.query(GenerationRecord)
        .filter_by(job_id=job.id)
        .order_by(GenerationRecord.record_index)
        .all()
    )
    assert len(records) == 4
    # chunk mode: contexts is the chunk text, not the LLM's context field
    assert records[0].contexts[0].startswith("EvalHub evaluates")
    assert records[0].source["document_id"] == document.id
    assert records[0].source["chunk_index"] == 0


def test_generate_dataset_document_mode_uses_llm_context(db, object_store, monkeypatch):
    from app import generation, tasks
    from app.models import GenerationJob, GenerationRecord

    workspace, document, job = _setup(db, object_store, mode="document", requested=2)

    def fake_generate(text, count, config, language=None):
        return [
            generation.QAItem(question=f"Q{index}?", answer="A.", context="verbatim excerpt")
            for index in range(count)
        ]

    monkeypatch.setattr(generation, "generate_qa", fake_generate)
    tasks.generate_dataset(job.id)

    records = db.query(GenerationRecord).filter_by(job_id=job.id).all()
    assert len(records) == 2
    assert records[0].contexts == ["verbatim excerpt"]
    assert records[0].source["chunk_index"] is None
    saved = db.get(GenerationJob, job.id)
    db.refresh(saved)
    assert saved.status == "completed"
    assert saved.progress_total == 1


def test_generate_dataset_drops_duplicate_questions(db, object_store, monkeypatch):
    from app import generation, tasks
    from app.models import GenerationJob

    workspace, document, job = _setup(db, object_store)

    def fake_generate(text, count, config, language=None):
        return [
            generation.QAItem(question="Same  QUESTION?", answer="A.", context="")
            for _ in range(count)
        ]

    monkeypatch.setattr(generation, "generate_qa", fake_generate)
    tasks.generate_dataset(job.id)

    saved = db.get(GenerationJob, job.id)
    db.refresh(saved)
    assert saved.status == "completed"
    assert saved.generated_count == 1


def test_generate_dataset_continues_after_unit_failure(db, object_store, monkeypatch):
    from app import generation, tasks
    from app.models import GenerationJob

    workspace, document, job = _setup(db, object_store)
    calls = []

    def fake_generate(text, count, config, language=None):
        calls.append(count)
        if len(calls) == 1:
            raise RuntimeError("provider exploded")
        return [generation.QAItem(question=f"Q{len(calls)}?", answer="A.", context="")]

    monkeypatch.setattr(generation, "generate_qa", fake_generate)
    tasks.generate_dataset(job.id)

    saved = db.get(GenerationJob, job.id)
    db.refresh(saved)
    assert saved.status == "completed"
    assert saved.generated_count >= 1
    assert len(saved.unit_errors) == 1
    assert "provider exploded" in saved.unit_errors[0]["error"]
    assert saved.error is None


def test_generate_dataset_fails_when_all_units_fail(db, object_store, monkeypatch):
    from app import generation, tasks
    from app.models import GenerationJob

    workspace, document, job = _setup(db, object_store)

    def fake_generate(text, count, config, language=None):
        raise RuntimeError("always broken")

    monkeypatch.setattr(generation, "generate_qa", fake_generate)
    tasks.generate_dataset(job.id)

    saved = db.get(GenerationJob, job.id)
    db.refresh(saved)
    assert saved.status == "failed"
    assert saved.error == "All generation units failed"


def test_generate_dataset_fails_without_provider_key(db, object_store, monkeypatch):
    from app import tasks
    from app.models import GenerationJob, ProviderConnection

    workspace, document, job = _setup(db, object_store)
    db.query(ProviderConnection).filter_by(workspace_id=workspace.id).delete()
    db.commit()

    tasks.generate_dataset(job.id)

    saved = db.get(GenerationJob, job.id)
    db.refresh(saved)
    assert saved.status == "failed"
    assert "provider connection" in saved.error


def test_generate_dataset_stops_on_cancellation(db, object_store, monkeypatch):
    from app import generation, tasks
    from app.db import SessionLocal
    from app.models import GenerationJob

    workspace, document, job = _setup(
        db, object_store, mode="document", requested=2
    )
    job_id = job.id

    def fake_generate(text, count, config, language=None):
        cancel_db = SessionLocal()
        other = cancel_db.get(GenerationJob, job_id)
        other.status = "cancelled"
        cancel_db.commit()
        cancel_db.close()
        return [generation.QAItem(question="Q?", answer="A.", context="")]

    monkeypatch.setattr(generation, "generate_qa", fake_generate)
    tasks.generate_dataset(job_id)

    saved = db.get(GenerationJob, job_id)
    db.refresh(saved)
    assert saved.status == "cancelled"
    assert saved.progress_done <= 1


def test_generate_dataset_preserves_cancellation_when_unit_raises(
    db, object_store, monkeypatch
):
    from app import generation, tasks
    from app.db import SessionLocal
    from app.models import GenerationJob

    workspace, document, job = _setup(
        db, object_store, mode="document", requested=2
    )
    job_id = job.id

    def fake_generate(text, count, config, language=None):
        cancel_db = SessionLocal()
        other = cancel_db.get(GenerationJob, job_id)
        other.status = "cancelled"
        cancel_db.commit()
        cancel_db.close()
        raise RuntimeError("provider failed after cancellation")

    monkeypatch.setattr(generation, "generate_qa", fake_generate)
    tasks.generate_dataset(job_id)

    saved = db.get(GenerationJob, job_id)
    db.refresh(saved)
    assert saved.status == "cancelled"
    assert saved.error is None


def test_generate_dataset_ignores_redelivery_after_completion(
    db, object_store, monkeypatch
):
    from app import generation, tasks
    from app.models import GenerationJob, GenerationRecord

    workspace, document, job = _setup(db, object_store)
    job.status = "completed"
    job.generated_count = 1
    db.add(
        GenerationRecord(
            workspace_id=workspace.id,
            job_id=job.id,
            record_index=0,
            question="Reviewed question?",
            answer="Reviewed answer.",
            contexts=["Reviewed context."],
            source={"document_id": document.id, "chunk_index": 0},
        )
    )
    db.commit()

    monkeypatch.setattr(
        generation,
        "generate_qa",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("completed job must not rerun")
        ),
    )
    tasks.generate_dataset(job.id)

    saved = db.get(GenerationJob, job.id)
    db.refresh(saved)
    records = db.query(GenerationRecord).filter_by(job_id=job.id).all()
    assert saved.status == "completed"
    assert saved.generated_count == 1
    assert [record.question for record in records] == ["Reviewed question?"]


def test_generate_dataset_claims_pending_job_once(db, object_store, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app import generation, tasks
    from app.models import GenerationJob, GenerationRecord

    workspace, document, job = _setup(
        db, object_store, mode="document", requested=1
    )
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def fake_generate(text, count, config, language=None):
        calls.append(count)
        entered.set()
        assert release.wait(timeout=5)
        return [generation.QAItem(question="Once?", answer="A.", context="ctx")]

    monkeypatch.setattr(generation, "generate_qa", fake_generate)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(tasks.generate_dataset, job.id)
        assert entered.wait(timeout=5)
        second = executor.submit(tasks.generate_dataset, job.id)
        second.result(timeout=5)
        release.set()
        first.result(timeout=5)

    saved = db.get(GenerationJob, job.id)
    db.refresh(saved)
    assert saved.status == "completed"
    assert calls == [1]
    assert db.query(GenerationRecord).filter_by(job_id=job.id).count() == 1


def test_document_mode_skips_items_without_supporting_context(
    db, object_store, monkeypatch
):
    from app import generation, tasks
    from app.models import GenerationJob, GenerationRecord

    workspace, document, job = _setup(
        db, object_store, mode="document", requested=1
    )

    monkeypatch.setattr(
        generation,
        "generate_qa",
        lambda *args, **kwargs: [
            generation.QAItem(question="Unsupported?", answer="A.", context="")
        ],
    )
    tasks.generate_dataset(job.id)

    saved = db.get(GenerationJob, job.id)
    db.refresh(saved)
    assert saved.status == "failed"
    assert saved.generated_count == 0
    assert saved.unit_errors == [
        {"unit": 0, "error": "No generated records had supporting context"}
    ]
    assert db.query(GenerationRecord).filter_by(job_id=job.id).count() == 0


def test_recover_stale_generation_job(db, object_store, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app import generation, tasks
    from app.models import GenerationJob

    workspace, document, job = _setup(
        db, object_store, mode="document", requested=1
    )
    job.status = "running"
    job.attempt = 1
    job.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

    monkeypatch.setattr(
        generation,
        "generate_qa",
        lambda *args, **kwargs: [
            generation.QAItem(question="Recovered?", answer="Yes.", context="ctx")
        ],
    )
    tasks.recover_stale_generation_jobs()

    saved = db.get(GenerationJob, job.id)
    db.refresh(saved)
    assert saved.status == "completed"
    assert saved.attempt == 2
    assert saved.generated_count == 1


def test_recovery_republishes_when_dispatch_races_existing_event(
    db, object_store, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone

    from app import tasks
    from app.db import SessionLocal
    from app.models import GenerationJob, OutboxEvent

    workspace, document, job = _setup(db, object_store)
    job.status = "running"
    job.attempt = 1
    job.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=1)
    event = OutboxEvent(
        kind="generate_dataset",
        dedupe_key=f"generation:{job.id}",
        payload={"job_id": job.id},
    )
    db.add(event)
    db.commit()

    first_publish = threading.Event()
    release_publish = threading.Event()
    observed_statuses = []

    def fake_publish(args=None, **kwargs):
        check_db = SessionLocal()
        current = check_db.get(GenerationJob, args[0])
        observed_statuses.append(current.status)
        check_db.close()
        if len(observed_statuses) == 1:
            first_publish.set()
            assert release_publish.wait(timeout=5)

    monkeypatch.setattr(tasks.generate_dataset, "apply_async", fake_publish)
    with ThreadPoolExecutor(max_workers=2) as executor:
        dispatch = executor.submit(tasks.dispatch_outbox_event, event.id)
        assert first_publish.wait(timeout=5)
        recover = executor.submit(tasks.recover_stale_generation_jobs)
        threading.Event().wait(0.1)
        assert not recover.done()
        release_publish.set()
        assert dispatch.result(timeout=5) is True
        recover.result(timeout=5)

    assert observed_statuses == ["running", "pending"]
