def test_register_returns_token_and_creates_default_workspace(client, db):
    resp = client.post(
        "/api/auth/register",
        json={"email": "new@example.com", "password": "password123"},
    )
    assert resp.status_code == 201
    assert "access_token" in resp.json()

    from app.models import Membership, User, Workspace

    user = db.query(User).filter_by(email="new@example.com").one()
    ws = db.query(Workspace).filter_by(owner_id=user.id).one()
    assert ws.name == "Default"
    m = db.query(Membership).filter_by(user_id=user.id, workspace_id=ws.id).one()
    assert m.role == "owner"


def test_register_duplicate_email_409(client):
    body = {"email": "dup@example.com", "password": "password123"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/register", json=body).status_code == 409


def test_login_and_me(client):
    client.post(
        "/api/auth/register",
        json={"email": "log@example.com", "password": "password123"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "log@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "log@example.com"


def test_login_wrong_password_401(client):
    client.post(
        "/api/auth/register",
        json={"email": "w@example.com", "password": "password123"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "w@example.com", "password": "nope-nope"},
    )
    assert resp.status_code == 401


def test_me_without_token_401(client):
    assert client.get("/api/me").status_code == 401
