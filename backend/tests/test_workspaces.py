def _register(client, email):
    resp = client.post(
        "/api/auth/register", json={"email": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_list_workspaces_shows_default(client, auth_headers):
    resp = client.get("/api/workspaces", headers=auth_headers)
    assert resp.status_code == 200
    ws = resp.json()
    assert len(ws) == 1
    assert ws[0]["name"] == "Default"
    assert ws[0]["role"] == "owner"


def test_create_workspace(client, auth_headers):
    resp = client.post("/api/workspaces", json={"name": "Team A"}, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["name"] == "Team A"
    assert len(client.get("/api/workspaces", headers=auth_headers).json()) == 2


def test_nonmember_cannot_see_workspace(client, auth_headers):
    ws_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    other = _register(client, "other@example.com")
    resp = client.get(f"/api/workspaces/{ws_id}/members", headers=other)
    assert resp.status_code == 404


def test_owner_adds_member(client, auth_headers):
    ws_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    _register(client, "friend@example.com")
    resp = client.post(
        f"/api/workspaces/{ws_id}/members",
        json={"email": "friend@example.com", "role": "member"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    emails = [
        m["email"]
        for m in client.get(
            f"/api/workspaces/{ws_id}/members", headers=auth_headers
        ).json()
    ]
    assert "friend@example.com" in emails


def test_member_cannot_add_members(client, auth_headers):
    ws_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    friend = _register(client, "friend2@example.com")
    client.post(
        f"/api/workspaces/{ws_id}/members",
        json={"email": "friend2@example.com", "role": "member"},
        headers=auth_headers,
    )
    _register(client, "third@example.com")
    resp = client.post(
        f"/api/workspaces/{ws_id}/members",
        json={"email": "third@example.com", "role": "member"},
        headers=friend,
    )
    assert resp.status_code == 403


def test_add_member_unknown_email_404(client, auth_headers):
    ws_id = client.get("/api/workspaces", headers=auth_headers).json()[0]["id"]
    resp = client.post(
        f"/api/workspaces/{ws_id}/members",
        json={"email": "ghost@example.com", "role": "member"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
