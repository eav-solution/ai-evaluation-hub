import pytest

LONG_MD = ("EvalHub turns documents into evaluation datasets with an LLM. " * 40).encode()


@pytest.fixture
def fake_generator(monkeypatch):
    from app import generation

    # questions must be globally unique: the source doc repeats one sentence,
    # so text-derived questions would collide and get deduped by the worker
    counter = {"n": 0}

    def fake_generate(text, count, config, language=None):
        items = []
        for _ in range(count):
            counter["n"] += 1
            items.append(
                generation.QAItem(
                    question=f"Unique question number {counter['n']}?",
                    answer="A grounded answer.",
                    context="a verbatim excerpt",
                )
            )
        return items

    monkeypatch.setattr(generation, "generate_qa", fake_generate)
    return fake_generate


@pytest.fixture
def workspace_with_key(client, auth_headers, db):
    from app.models import ProviderConnection
    from app.security import encrypt_secret

    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    db.add(
        ProviderConnection(
            workspace_id=workspace_id,
            name="OpenAI",
            connection_type="openai",
            encrypted_key=encrypt_secret("sk-test"),
        )
    )
    db.commit()
    return workspace_id


def _upload_document(client, auth_headers, workspace_id):
    return client.post(
        f"/api/workspaces/{workspace_id}/documents",
        files=[("files", ("guide.md", LONG_MD, "text/markdown"))],
        headers=auth_headers,
    ).json()[0]


def _connection_id(client, auth_headers, workspace_id):
    connections = client.get(
        f"/api/workspaces/{workspace_id}/provider-connections", headers=auth_headers
    ).json()
    return connections[0]["id"] if connections else "no-connection"


def _create_job(client, auth_headers, workspace_id, document, **overrides):
    body = {
        "name": "From guide",
        "document_ids": [document["id"]],
        "mode": "chunk",
        "requested_count": 4,
        "generator": {
            "connection_id": _connection_id(client, auth_headers, workspace_id),
            "model": "gpt-test",
        },
        "options": {"questions_per_chunk": 3},
    }
    body.update(overrides)
    return client.post(
        f"/api/workspaces/{workspace_id}/generation-jobs",
        json=body,
        headers=auth_headers,
    )


def test_create_job_runs_eagerly_and_clamps(
    client, auth_headers, object_store, fake_generator, workspace_with_key
):
    workspace_id = workspace_with_key
    document = _upload_document(client, auth_headers, workspace_id)
    max_count = document["chunk_count"] * 3

    created = _create_job(
        client, auth_headers, workspace_id, document, requested_count=max_count + 50
    )
    assert created.status_code == 201
    job = created.json()
    assert job["max_count"] == max_count
    assert job["requested_count"] == max_count

    fetched = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}",
        headers=auth_headers,
    ).json()
    # celery eager mode: the job already ran during create
    assert fetched["status"] == "completed"
    assert fetched["generated_count"] == max_count
    assert fetched["progress_done"] == fetched["progress_total"]

    listed = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs", headers=auth_headers
    ).json()
    assert len(listed) == 1


def test_create_job_missing_document_404(
    client, auth_headers, object_store, workspace_with_key
):
    workspace_id = workspace_with_key
    document = {"id": "no-such-document", "chunk_count": 1}
    response = _create_job(client, auth_headers, workspace_id, document)
    assert response.status_code == 404


def test_create_job_missing_provider_key_422(
    client, auth_headers, object_store, fake_generator
):
    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    document = _upload_document(client, auth_headers, workspace_id)
    response = _create_job(client, auth_headers, workspace_id, document)
    assert response.status_code == 422
    assert "connection" in response.json()["detail"].lower()


def test_create_job_rejects_unknown_connection(
    client, auth_headers, object_store, workspace_with_key
):
    workspace_id = workspace_with_key
    document = _upload_document(client, auth_headers, workspace_id)
    response = _create_job(
        client,
        auth_headers,
        workspace_id,
        document,
        generator={"connection_id": "does-not-exist", "model": "model"},
    )
    assert response.status_code == 422


def test_cancel_finished_job_409(
    client, auth_headers, object_store, fake_generator, workspace_with_key
):
    workspace_id = workspace_with_key
    document = _upload_document(client, auth_headers, workspace_id)
    job = _create_job(client, auth_headers, workspace_id, document).json()
    response = client.post(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/cancel",
        headers=auth_headers,
    )
    assert response.status_code == 409


def test_cancel_running_job(client, auth_headers, object_store, db, workspace_with_key):
    from app.models import GenerationJob

    workspace_id = workspace_with_key
    job = GenerationJob(
        workspace_id=workspace_id,
        name="Running",
        document_ids=["doc-x"],
        mode="chunk",
        requested_count=3,
        max_count=3,
        generator_config={"provider": "openai", "model": "m"},
        options={"questions_per_chunk": 3, "language": None},
        status="running",
    )
    db.add(job)
    db.commit()

    response = client.post(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job.id}/cancel",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def _job_with_drafts(db, workspace_id, *, status: str):
    from app.models import Dataset, GenerationJob, GenerationRecord, OutboxEvent

    dataset = Dataset(
        workspace_id=workspace_id,
        name="Saved generated data",
        format="jsonl",
        row_count=1,
        storage_path=f"datasets/{workspace_id}/saved-generated.jsonl",
        schema_map={"input": "question"},
    )
    db.add(dataset)
    db.flush()
    job = GenerationJob(
        workspace_id=workspace_id,
        name="Old generation",
        document_ids=["document-1"],
        mode="chunk",
        requested_count=1,
        max_count=1,
        generator_config={"provider": "openai", "model": "gpt-test"},
        options={"questions_per_chunk": 1, "language": None},
        status=status,
        dataset_id=dataset.id,
        dataset_created=True,
    )
    db.add(job)
    db.flush()
    record = GenerationRecord(
        workspace_id=workspace_id,
        job_id=job.id,
        record_index=0,
        question="Question?",
        answer="Answer.",
        contexts=["Context."],
        source={"document_id": "document-1", "chunk_index": 0},
    )
    event = OutboxEvent(
        kind="generate_dataset",
        dedupe_key=f"generation:{job.id}",
        payload={"job_id": job.id},
    )
    db.add_all([record, event])
    db.commit()
    return job, record, event, dataset


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_delete_finished_job_removes_drafts_and_preserves_dataset(
    client, auth_headers, db, workspace_with_key, status
):
    from app.models import Dataset, GenerationJob, GenerationRecord, OutboxEvent

    job, record, event, dataset = _job_with_drafts(db, workspace_with_key, status=status)
    job_id = job.id
    record_id = record.id
    event_id = event.id
    dataset_id = dataset.id
    response = client.delete(
        f"/api/workspaces/{workspace_with_key}/generation-jobs/{job_id}",
        headers=auth_headers,
    )

    assert response.status_code == 204
    db.expire_all()
    assert db.get(GenerationJob, job_id) is None
    assert db.get(GenerationRecord, record_id) is None
    assert db.get(OutboxEvent, event_id) is None
    assert db.get(Dataset, dataset_id) is not None


@pytest.mark.parametrize("status", ["pending", "running"])
def test_delete_active_job_requires_cancel_first(
    client, auth_headers, db, workspace_with_key, status
):
    from app.models import GenerationJob

    job, _, _, _ = _job_with_drafts(db, workspace_with_key, status=status)
    response = client.delete(
        f"/api/workspaces/{workspace_with_key}/generation-jobs/{job.id}",
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert db.get(GenerationJob, job.id) is not None


def test_delete_missing_job_returns_404(client, auth_headers, workspace_with_key):
    response = client.delete(
        f"/api/workspaces/{workspace_with_key}/generation-jobs/not-a-job",
        headers=auth_headers,
    )

    assert response.status_code == 404


def test_nonmember_cannot_access_jobs(
    client, auth_headers, object_store, workspace_with_key
):
    workspace_id = workspace_with_key
    token = client.post(
        "/api/auth/register",
        json={"email": "gen-intruder@example.com", "password": "password123"},
    ).json()["access_token"]
    response = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_create_job_marks_enqueue_failure(
    client,
    auth_headers,
    object_store,
    workspace_with_key,
    monkeypatch,
    db,
):
    from app import tasks
    from app.models import GenerationJob, OutboxEvent

    workspace_id = workspace_with_key
    document = _upload_document(client, auth_headers, workspace_id)

    def fail_enqueue(*args, **kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(tasks.generate_dataset, "apply_async", fail_enqueue)
    response = _create_job(client, auth_headers, workspace_id, document)

    assert response.status_code == 201
    job = db.query(GenerationJob).filter_by(workspace_id=workspace_id).one()
    db.refresh(job)
    assert job.status == "pending"
    event = db.query(OutboxEvent).filter_by(kind="generate_dataset").one()
    assert event.payload == {"job_id": job.id}
    assert event.attempts == 1
    assert "broker unavailable" in event.error
    first_retry = event.next_attempt_at
    tasks.dispatch_outbox_events()
    db.refresh(event)
    assert event.attempts == 1

    from datetime import datetime, timedelta, timezone

    event.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    tasks.dispatch_outbox_events()
    db.refresh(event)
    assert event.attempts == 2
    assert event.next_attempt_at > first_retry


def test_publish_ack_loss_cannot_overwrite_completed_job(
    client,
    auth_headers,
    object_store,
    fake_generator,
    workspace_with_key,
    monkeypatch,
    db,
):
    from app import tasks
    from app.models import GenerationJob, OutboxEvent

    workspace_id = workspace_with_key
    document = _upload_document(client, auth_headers, workspace_id)

    def deliver_then_lose_ack(args=None, **kwargs):
        tasks.generate_dataset(args[0])
        raise RuntimeError("publish acknowledgement lost")

    monkeypatch.setattr(tasks.generate_dataset, "apply_async", deliver_then_lose_ack)
    response = _create_job(client, auth_headers, workspace_id, document)

    assert response.status_code == 201
    job = db.query(GenerationJob).filter_by(workspace_id=workspace_id).one()
    db.refresh(job)
    assert job.status == "completed"
    assert db.query(OutboxEvent).filter_by(kind="generate_dataset").count() == 1

    monkeypatch.setattr(
        tasks.generate_dataset,
        "apply_async",
        lambda args=None, **kwargs: tasks.generate_dataset(args[0]),
    )
    event = db.query(OutboxEvent).filter_by(kind="generate_dataset").one()
    tasks.dispatch_outbox_event(event.id)
    db.expire_all()
    assert db.get(GenerationJob, job.id).status == "completed"
    assert db.query(OutboxEvent).count() == 0


def _completed_job(client, auth_headers, workspace_id):
    document = _upload_document(client, auth_headers, workspace_id)
    job = _create_job(
        client, auth_headers, workspace_id, document, requested_count=4
    ).json()
    return client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}",
        headers=auth_headers,
    ).json()


def _upload_dataset(client, auth_headers, workspace_id, *, name, rows, schema_map=None):
    import json as jsonlib

    body = ("\n".join(jsonlib.dumps(row) for row in rows) + "\n").encode()
    dataset = client.post(
        f"/api/workspaces/{workspace_id}/datasets",
        data={"name": name},
        files={"file": ("qa.jsonl", body, "application/json")},
        headers=auth_headers,
    ).json()
    if schema_map is not None:
        dataset = client.patch(
            f"/api/workspaces/{workspace_id}/datasets/{dataset['id']}/schema-map",
            json={"schema_map": schema_map},
            headers=auth_headers,
        ).json()
    return dataset


def test_list_records_paginated(
    client, auth_headers, object_store, fake_generator, workspace_with_key
):
    workspace_id = workspace_with_key
    job = _completed_job(client, auth_headers, workspace_id)
    page = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records",
        headers=auth_headers,
    ).json()
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["total"] == job["generated_count"]
    assert len(page["records"]) == job["generated_count"]
    first = page["records"][0]
    assert first["record_index"] == 0
    assert first["question"]
    assert first["answer"]
    assert isinstance(first["contexts"], list)
    assert first["deleted"] is False


def test_patch_record_edits_and_soft_delete(
    client, auth_headers, object_store, fake_generator, workspace_with_key
):
    workspace_id = workspace_with_key
    job = _completed_job(client, auth_headers, workspace_id)
    record = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records",
        headers=auth_headers,
    ).json()["records"][0]

    edited = client.patch(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records/{record['id']}",
        json={"question": "  Edited question?  ", "contexts": ["new context", "  "]},
        headers=auth_headers,
    )
    assert edited.status_code == 200
    assert edited.json()["question"] == "Edited question?"
    assert edited.json()["contexts"] == ["new context"]

    deleted = client.patch(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records/{record['id']}",
        json={"deleted": True},
        headers=auth_headers,
    )
    assert deleted.json()["deleted"] is True

    restored = client.patch(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records/{record['id']}",
        json={"deleted": False},
        headers=auth_headers,
    )
    assert restored.json()["deleted"] is False


def test_patch_record_rejects_blank_question(
    client, auth_headers, object_store, fake_generator, workspace_with_key
):
    workspace_id = workspace_with_key
    job = _completed_job(client, auth_headers, workspace_id)
    record = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records",
        headers=auth_headers,
    ).json()["records"][0]
    response = client.patch(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records/{record['id']}",
        json={"question": "   "},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_patch_record_rejects_unknown_field(
    client, auth_headers, object_store, fake_generator, workspace_with_key
):
    workspace_id = workspace_with_key
    job = _completed_job(client, auth_headers, workspace_id)
    record = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records",
        headers=auth_headers,
    ).json()["records"][0]
    response = client.patch(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records/{record['id']}",
        json={"unexpected": "value"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_patch_missing_record_404(
    client, auth_headers, object_store, fake_generator, workspace_with_key
):
    workspace_id = workspace_with_key
    job = _completed_job(client, auth_headers, workspace_id)
    response = client.patch(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records/nope",
        json={"deleted": True},
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_patch_record_requires_completed_job(
    client, auth_headers, object_store, fake_generator, workspace_with_key, db
):
    from app.models import GenerationJob

    workspace_id = workspace_with_key
    job = _completed_job(client, auth_headers, workspace_id)
    record = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records",
        headers=auth_headers,
    ).json()["records"][0]

    saved_job = db.get(GenerationJob, job["id"])
    saved_job.status = "running"
    db.commit()
    running = client.patch(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records/{record['id']}",
        json={"question": "Too early?"},
        headers=auth_headers,
    )
    assert running.status_code == 409


def test_delete_dataset_queues_failed_storage_cleanup(
    client,
    auth_headers,
    object_store,
    workspace_with_key,
    monkeypatch,
    db,
):
    from app import storage, tasks
    from app.models import OutboxEvent

    workspace_id = workspace_with_key
    dataset = _upload_dataset(
        client,
        auth_headers,
        workspace_id,
        name="Manual QA",
        rows=[{"question": "q", "answer": "a"}],
    )
    monkeypatch.setattr(
        storage,
        "delete_object",
        lambda key: (_ for _ in ()).throw(RuntimeError("storage unavailable")),
    )

    response = client.delete(
        f"/api/workspaces/{workspace_id}/datasets/{dataset['id']}",
        headers=auth_headers,
    )
    assert response.status_code == 204
    db.expire_all()
    event = db.query(OutboxEvent).filter_by(kind="delete_object").one()
    assert event.payload == {"key": dataset["storage_path"]}

    monkeypatch.setattr(storage, "delete_object", object_store.__delitem__)
    tasks.dispatch_outbox_event(event.id)
    db.expire_all()
    assert db.query(OutboxEvent).count() == 0
    assert dataset["storage_path"] not in object_store


def test_generated_dataset_runs_endpoint_evaluation(
    client,
    auth_headers,
    object_store,
    workspace_with_key,
    monkeypatch,
):
    from app.evals.base import CallableAdapter, MetricScore
    from app.evals.registry import METRICS

    workspace_id = workspace_with_key
    # mirrors a downloaded-then-uploaded generated dataset: question/answer/contexts
    dataset = _upload_dataset(
        client,
        auth_headers,
        workspace_id,
        name="Uploaded QA",
        rows=[
            {"question": "What is X?", "answer": "X.", "contexts": ["ctx"]},
            {"question": "What is Y?", "answer": "Y.", "contexts": ["ctx"]},
        ],
        schema_map={
            "input": "question",
            "expected_output": "answer",
            "contexts": "contexts",
        },
    )

    adapter = CallableAdapter(
        key="test.always_pass",
        framework="test",
        display_name="Always pass",
        description="Test metric",
        requires=frozenset(),
        scorer=lambda row, judge, config: MetricScore(
            "test.always_pass", 1.0, None, True
        ),
    )
    monkeypatch.setitem(METRICS, "test.always_pass", adapter)
    monkeypatch.setattr(
        "app.tasks.call_endpoint",
        lambda config, row, *, encrypted_headers: ("system answer", {}, 12.0),
    )

    # generated datasets ship input/expected/contexts — endpoint mode fills actuals
    created = client.post(
        f"/api/workspaces/{workspace_id}/runs",
        json={
            "dataset_id": dataset["id"],
            "name": "Eval generated data",
            "mode": "endpoint",
            "metrics": [{"key": "test.always_pass"}],
            "judge": {
                "connection_id": _connection_id(client, auth_headers, workspace_id),
                "model": "gpt-test",
            },
            "endpoint_config": {
                "url": "https://example.com/chat",
                "method": "POST",
                "headers": {},
                "body_template": {"prompt": "{{input}}"},
                "response_jsonpath": "$.answer",
            },
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    run = client.get(
        f"/api/workspaces/{workspace_id}/runs/{created.json()['id']}",
        headers=auth_headers,
    ).json()
    assert run["status"] == "completed"
    assert run["progress_done"] == dataset["row_count"]


def test_download_records_csv_matches_records(
    client, auth_headers, object_store, fake_generator, workspace_with_key
):
    import csv as csvlib
    import io
    import json as jsonlib

    workspace_id = workspace_with_key
    job = _completed_job(client, auth_headers, workspace_id)
    records = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records",
        headers=auth_headers,
    ).json()["records"]

    response = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records.csv",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    rows = list(csvlib.DictReader(io.StringIO(response.text)))
    assert list(rows[0].keys()) == ["question", "answer", "contexts"]
    assert len(rows) == len(records)
    assert rows[0]["question"] == records[0]["question"]
    assert rows[0]["answer"] == records[0]["answer"]
    assert jsonlib.loads(rows[0]["contexts"]) == records[0]["contexts"]


def test_download_records_csv_excludes_deleted_and_escapes(
    client, auth_headers, object_store, fake_generator, workspace_with_key
):
    import csv as csvlib
    import io

    workspace_id = workspace_with_key
    job = _completed_job(client, auth_headers, workspace_id)
    records = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records",
        headers=auth_headers,
    ).json()["records"]

    client.patch(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records/{records[0]['id']}",
        json={"deleted": True},
        headers=auth_headers,
    )
    tricky = 'He said, "hi"\nnew line'
    client.patch(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records/{records[1]['id']}",
        json={"answer": tricky},
        headers=auth_headers,
    )

    response = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records.csv",
        headers=auth_headers,
    )
    rows = list(csvlib.DictReader(io.StringIO(response.text)))
    assert len(rows) == len(records) - 1
    assert records[0]["question"] not in {row["question"] for row in rows}
    assert tricky in {row["answer"] for row in rows}


def test_download_records_csv_requires_completed(
    client, auth_headers, db, object_store, fake_generator, workspace_with_key
):
    from app.models import GenerationJob

    workspace_id = workspace_with_key
    job = _completed_job(client, auth_headers, workspace_id)
    row = db.get(GenerationJob, job["id"])
    row.status = "pending"
    db.commit()

    response = client.get(
        f"/api/workspaces/{workspace_id}/generation-jobs/{job['id']}/records.csv",
        headers=auth_headers,
    )
    assert response.status_code == 409


def test_download_records_csv_missing_job_returns_404(
    client, auth_headers, workspace_with_key
):
    response = client.get(
        f"/api/workspaces/{workspace_with_key}/generation-jobs/not-a-job/records.csv",
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_create_job_custom_connection(client, auth_headers, object_store, fake_generator, db, monkeypatch):
    from app.models import ProviderConnection
    from app.routers import generation as generation_router

    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    conn = ProviderConnection(
        workspace_id=workspace_id,
        name="Gateway",
        connection_type="openai_compatible",
        base_url="http://gateway/v1",
    )
    db.add(conn)
    db.commit()
    document = _upload_document(client, auth_headers, workspace_id)
    monkeypatch.setattr(
        generation_router, "discover_models", lambda base_url, api_key: ["chat-a"]
    )

    ok = _create_job(
        client, auth_headers, workspace_id, document,
        generator={"connection_id": conn.id, "model": "chat-a"},
    )
    assert ok.status_code == 201
    assert ok.json()["generator_config"]["connection_type"] == "openai_compatible"

    stale = _create_job(
        client, auth_headers, workspace_id, document,
        generator={"connection_id": conn.id, "model": "missing"},
    )
    assert stale.status_code == 422
