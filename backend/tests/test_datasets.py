def test_dataset_metadata_roundtrip(db):
    from app.models import Dataset, Membership, User, Workspace

    user = User(email="dataset@example.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="Data", owner_id=user.id)
    db.add(workspace)
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    dataset = Dataset(
        workspace_id=workspace.id,
        name="Questions",
        format="csv",
        row_count=2,
        storage_path=f"datasets/{workspace.id}/data.csv",
        schema_map={"input": "question", "actual_output": "answer"},
    )
    db.add(dataset)
    db.commit()

    assert db.get(Dataset, dataset.id).schema_map["input"] == "question"


def test_dataset_upload_map_preview_and_delete(client, auth_headers, object_store):
    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    uploaded = client.post(
        f"/api/workspaces/{workspace_id}/datasets",
        data={"name": "Questions"},
        files={
            "file": (
                "questions.csv",
                b"question,answer\nWhat?,This.\nWhy?,Because.\n",
                "text/csv",
            )
        },
        headers=auth_headers,
    )
    assert uploaded.status_code == 201
    dataset = uploaded.json()
    assert dataset["row_count"] == 2
    assert dataset["preview"][0]["question"] == "What?"
    assert list(object_store) == [dataset["storage_path"]]

    mapped = client.patch(
        f"/api/workspaces/{workspace_id}/datasets/{dataset['id']}/schema-map",
        json={"schema_map": {"input": "question", "actual_output": "answer"}},
        headers=auth_headers,
    )
    assert mapped.status_code == 200
    assert mapped.json()["schema_map"]["input"] == "question"

    assert len(
        client.get(f"/api/workspaces/{workspace_id}/datasets", headers=auth_headers).json()
    ) == 1
    detail = client.get(
        f"/api/workspaces/{workspace_id}/datasets/{dataset['id']}",
        headers=auth_headers,
    )
    assert detail.json()["preview"][1]["answer"] == "Because."

    deleted = client.delete(
        f"/api/workspaces/{workspace_id}/datasets/{dataset['id']}",
        headers=auth_headers,
    )
    assert deleted.status_code == 204
    assert object_store == {}


def test_dataset_upload_rejects_invalid_format(client, auth_headers, object_store):
    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    response = client.post(
        f"/api/workspaces/{workspace_id}/datasets",
        data={"name": "Bad"},
        files={"file": ("bad.txt", b"hello", "text/plain")},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_dataset_schema_map_accepts_canonical_and_legacy_context_fields(
    client, auth_headers, object_store
):
    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    uploaded = client.post(
        f"/api/workspaces/{workspace_id}/datasets",
        data={"name": "RAG rows"},
        files={
            "file": (
                "rag.csv",
                b"question,facts,documents\nWhat?,trusted,retrieved\n",
                "text/csv",
            )
        },
        headers=auth_headers,
    ).json()
    url = f"/api/workspaces/{workspace_id}/datasets/{uploaded['id']}/schema-map"

    canonical = client.patch(
        url,
        json={
            "schema_map": {
                "input": "question",
                "context": "facts",
                "retrieval_contexts": "documents",
            }
        },
        headers=auth_headers,
    )
    assert canonical.status_code == 200

    legacy = client.patch(
        url,
        json={"schema_map": {"input": "question", "contexts": "documents"}},
        headers=auth_headers,
    )
    assert legacy.status_code == 200

    unknown = client.patch(
        url,
        json={"schema_map": {"input": "question", "documents": "documents"}},
        headers=auth_headers,
    )
    assert unknown.status_code == 422


def test_dataset_schema_map_accepts_agentic_structured_fields(
    client, auth_headers, object_store
):
    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    uploaded = client.post(
        f"/api/workspaces/{workspace_id}/datasets",
        data={"name": "Agent traces"},
        files={
            "file": (
                "agent.json",
                b'[{"prompt":"q","answer":"a","trace":[],"called":[],"expected":[]}]',
                "application/json",
            )
        },
        headers=auth_headers,
    ).json()

    response = client.patch(
        f"/api/workspaces/{workspace_id}/datasets/{uploaded['id']}/schema-map",
        json={
            "schema_map": {
                "input": "prompt",
                "actual_output": "answer",
                "agent_trace": "trace",
                "tools_called": "called",
                "expected_tools": "expected",
            }
        },
        headers=auth_headers,
    )

    assert response.status_code == 200


def test_dataset_schema_map_accepts_conversation_fields(
    client, auth_headers, object_store
):
    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    uploaded = client.post(
        f"/api/workspaces/{workspace_id}/datasets",
        data={"name": "Conversations"},
        files={
            "file": (
                "conversations.json",
                b'[{"history":[],"role":"agent","context":[],"servers":{},"events":[]}]',
                "application/json",
            )
        },
        headers=auth_headers,
    ).json()
    url = f"/api/workspaces/{workspace_id}/datasets/{uploaded['id']}/schema-map"

    response = client.patch(
        url,
        json={
            "schema_map": {
                "turns": "history",
                "chatbot_role": "role",
                "conversation_context": "context",
                "mcp_metadata": "servers",
                "mcp_events": "events",
            }
        },
        headers=auth_headers,
    )
    unknown = client.patch(
        url,
        json={"schema_map": {"conversation_unknown": "history"}},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert unknown.status_code == 422


def test_nonmember_cannot_access_dataset(client, auth_headers, object_store):
    workspace_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    token = client.post(
        "/api/auth/register",
        json={"email": "dataset-intruder@example.com", "password": "password123"},
    ).json()["access_token"]
    response = client.get(
        f"/api/workspaces/{workspace_id}/datasets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
