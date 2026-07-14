import pytest


LONG_MD = ("EvalHub generates evaluation datasets from documents. " * 40).encode()


def _upload(client, auth_headers, workspace_id, files):
    return client.post(
        f"/api/workspaces/{workspace_id}/documents",
        files=files,
        headers=auth_headers,
    )


def test_upload_list_delete_documents(client, auth_headers, object_store):
    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    response = _upload(
        client,
        auth_headers,
        workspace_id,
        [
            ("files", ("guide.md", LONG_MD, "text/markdown")),
            ("files", ("notes.txt", LONG_MD, "text/plain")),
        ],
    )
    assert response.status_code == 201
    documents = response.json()
    assert len(documents) == 2
    assert documents[0]["filename"] == "guide.md"
    assert documents[0]["char_count"] > 0
    assert documents[0]["chunk_count"] >= 1
    # original + extracted text per document
    assert len(object_store) == 4

    listed = client.get(
        f"/api/workspaces/{workspace_id}/documents", headers=auth_headers
    ).json()
    assert {item["filename"] for item in listed} == {"guide.md", "notes.txt"}

    deleted = client.delete(
        f"/api/workspaces/{workspace_id}/documents/{documents[0]['id']}",
        headers=auth_headers,
    )
    assert deleted.status_code == 204
    assert len(object_store) == 2


def test_upload_rejects_unsupported_format(client, auth_headers, object_store):
    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    response = _upload(
        client,
        auth_headers,
        workspace_id,
        [("files", ("sheet.xlsx", b"binary", "application/octet-stream"))],
    )
    assert response.status_code == 422
    assert "sheet.xlsx" in response.json()["detail"]
    assert object_store == {}


def test_upload_rejects_tiny_document(client, auth_headers, object_store):
    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    response = _upload(
        client,
        auth_headers,
        workspace_id,
        [("files", ("tiny.txt", b"too short", "text/plain"))],
    )
    assert response.status_code == 422
    assert object_store == {}


def test_upload_cleans_original_when_original_write_loses_response(
    client, auth_headers, object_store, monkeypatch
):
    from app import storage

    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]

    def put_then_raise(key, data):
        object_store[key] = data
        raise RuntimeError("original write response lost")

    monkeypatch.setattr(storage, "put_object", put_then_raise)

    with pytest.raises(RuntimeError, match="original write response lost"):
        _upload(
            client,
            auth_headers,
            workspace_id,
            [("files", ("guide.md", LONG_MD, "text/markdown"))],
        )

    assert object_store == {}


def test_upload_cleans_extracted_text_when_write_loses_response(
    client, auth_headers, object_store, monkeypatch
):
    from app import storage

    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    write_count = 0

    def put_then_raise_for_extracted_text(key, data):
        nonlocal write_count
        write_count += 1
        object_store[key] = data
        if write_count == 2:
            raise RuntimeError("extracted-text write response lost")

    monkeypatch.setattr(storage, "put_object", put_then_raise_for_extracted_text)

    with pytest.raises(RuntimeError, match="extracted-text write response lost"):
        _upload(
            client,
            auth_headers,
            workspace_id,
            [("files", ("guide.md", LONG_MD, "text/markdown"))],
        )

    assert object_store == {}


def test_delete_blocked_while_job_active(client, auth_headers, object_store, db):
    from app.models import GenerationJob

    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    document = _upload(
        client,
        auth_headers,
        workspace_id,
        [("files", ("guide.md", LONG_MD, "text/markdown"))],
    ).json()[0]
    db.add(
        GenerationJob(
            workspace_id=workspace_id,
            name="Active",
            document_ids=[document["id"]],
            mode="chunk",
            requested_count=3,
            max_count=3,
            generator_config={"provider": "openai", "model": "m"},
            options={"questions_per_chunk": 3, "language": None},
            status="running",
        )
    )
    db.commit()

    response = client.delete(
        f"/api/workspaces/{workspace_id}/documents/{document['id']}",
        headers=auth_headers,
    )
    assert response.status_code == 409


def test_delete_document_commits_before_best_effort_storage_cleanup(
    client, auth_headers, object_store, monkeypatch, db
):
    from app import storage, tasks
    from app.models import OutboxEvent

    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    document = _upload(
        client,
        auth_headers,
        workspace_id,
        [("files", ("guide.md", LONG_MD, "text/markdown"))],
    ).json()[0]

    monkeypatch.setattr(
        storage,
        "delete_object",
        lambda key: (_ for _ in ()).throw(RuntimeError("storage unavailable")),
    )
    response = client.delete(
        f"/api/workspaces/{workspace_id}/documents/{document['id']}",
        headers=auth_headers,
    )

    assert response.status_code == 204
    listed = client.get(
        f"/api/workspaces/{workspace_id}/documents", headers=auth_headers
    ).json()
    assert listed == []
    db.expire_all()
    assert db.query(OutboxEvent).filter_by(kind="delete_object").count() == 2

    monkeypatch.setattr(storage, "delete_object", object_store.__delitem__)
    for event_id in [row[0] for row in db.query(OutboxEvent.id).all()]:
        tasks.dispatch_outbox_event(event_id)
    db.expire_all()
    assert db.query(OutboxEvent).count() == 0
    assert object_store == {}


def test_create_job_serializes_with_document_delete(
    client, auth_headers, object_store, monkeypatch, db
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from fastapi.testclient import TestClient
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from app import tasks
    from app.main import app
    from app.models import OutboxEvent, ProviderConnection
    from app.security import encrypt_secret

    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    document = _upload(
        client,
        auth_headers,
        workspace_id,
        [("files", ("guide.md", LONG_MD, "text/markdown"))],
    ).json()[0]
    connection = ProviderConnection(
        workspace_id=workspace_id,
        name="OpenAI",
        connection_type="openai",
        encrypted_key=encrypt_secret("sk-test"),
    )
    db.add(connection)
    db.commit()
    connection_id = connection.id
    job_holds_lock = Event()
    release_job = Event()

    def pause_job_commit(session):
        if any(
            isinstance(row, OutboxEvent) and row.kind == "generate_dataset"
            for row in session.new
        ):
            job_holds_lock.set()
            assert release_job.wait(timeout=5)

    monkeypatch.setattr(tasks, "dispatch_outbox_event", lambda event_id: True)

    def create_job():
        with TestClient(app) as concurrent_client:
            return concurrent_client.post(
                f"/api/workspaces/{workspace_id}/generation-jobs",
                json={
                    "name": "From guide",
                    "document_ids": [document["id"]],
                    "mode": "chunk",
                    "requested_count": 1,
                    "generator": {"connection_id": connection_id, "model": "gpt-test"},
                    "options": {"questions_per_chunk": 1},
                },
                headers=auth_headers,
            ).status_code

    def delete_document():
        with TestClient(app) as concurrent_client:
            return concurrent_client.delete(
                f"/api/workspaces/{workspace_id}/documents/{document['id']}",
                headers=auth_headers,
            ).status_code

    try:
        event.listen(Session, "before_commit", pause_job_commit)
        with ThreadPoolExecutor(max_workers=2) as executor:
            create_future = executor.submit(create_job)
            assert job_holds_lock.wait(timeout=5)
            delete_future = executor.submit(delete_document)
            release_job.set()
            assert create_future.result(timeout=5) == 201
            assert delete_future.result(timeout=5) == 409
    finally:
        event.remove(Session, "before_commit", pause_job_commit)
