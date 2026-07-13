import pytest


def _ws(client, headers):
    return client.get("/api/workspaces", headers=headers).json()[0]["id"]


@pytest.fixture
def fake_discovery(monkeypatch):
    from app.routers import provider_connections

    calls = []

    def fake(base_url, api_key, **kw):
        calls.append({"base_url": base_url, "api_key": api_key})
        return ["chat-a", "chat-b", "embed-x"]

    monkeypatch.setattr(provider_connections, "discover_models", fake)
    return calls


def _no_key_material(payload, secret):
    text = repr(payload)
    assert secret not in text
    assert "encrypted_key" not in text


def test_create_native_openai(client, auth_headers):
    ws = _ws(client, auth_headers)
    resp = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={"connection_type": "openai", "api_key": "sk-secret-1234"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["connection_type"] == "openai"
    assert body["name"] == "OpenAI"
    assert body["has_key"] is True
    assert body["key_hint"] == "…1234"
    assert body["base_url"] is None
    _no_key_material(body, "sk-secret-1234")


def test_duplicate_native_409(client, auth_headers):
    ws = _ws(client, auth_headers)
    body = {"connection_type": "openai", "api_key": "sk-first-0001"}
    assert client.post(f"/api/workspaces/{ws}/provider-connections", json=body, headers=auth_headers).status_code == 201
    assert client.post(f"/api/workspaces/{ws}/provider-connections", json=body, headers=auth_headers).status_code == 409


def test_create_native_requires_key(client, auth_headers):
    ws = _ws(client, auth_headers)
    resp = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={"connection_type": "anthropic"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_create_custom_connections(client, auth_headers, fake_discovery):
    ws = _ws(client, auth_headers)
    a = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={
            "connection_type": "openai_compatible",
            "name": "Local Ollama",
            "base_url": "http://localhost:11434/v1/",
            "api_key": "sk-optional-9999",
        },
        headers=auth_headers,
    )
    assert a.status_code == 201
    assert a.json()["base_url"] == "http://localhost:11434/v1"  # trailing slash stripped
    assert a.json()["has_key"] is True
    _no_key_material(a.json(), "sk-optional-9999")

    b = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={"connection_type": "openai_compatible", "name": "LM Studio", "base_url": "http://localhost:1234/v1"},
        headers=auth_headers,
    )
    assert b.status_code == 201
    assert b.json()["has_key"] is False
    assert b.json()["key_hint"] is None

    listed = client.get(f"/api/workspaces/{ws}/provider-connections", headers=auth_headers).json()
    assert {c["name"] for c in listed} == {"Local Ollama", "LM Studio"}


def test_duplicate_custom_name_case_insensitive_409(client, auth_headers, fake_discovery):
    ws = _ws(client, auth_headers)
    payload = {"connection_type": "openai_compatible", "name": "Gateway", "base_url": "http://h/v1"}
    assert client.post(f"/api/workspaces/{ws}/provider-connections", json=payload, headers=auth_headers).status_code == 201
    dup = {"connection_type": "openai_compatible", "name": "gateway", "base_url": "http://h2/v1"}
    assert client.post(f"/api/workspaces/{ws}/provider-connections", json=dup, headers=auth_headers).status_code == 409


def test_create_custom_discovery_failure_422_and_not_persisted(client, auth_headers, monkeypatch):
    from app.connections import DiscoveryUnreachable
    from app.routers import provider_connections

    def boom(base_url, api_key, **kw):
        raise DiscoveryUnreachable("Could not reach the model service")

    monkeypatch.setattr(provider_connections, "discover_models", boom)
    ws = _ws(client, auth_headers)
    resp = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={"connection_type": "openai_compatible", "name": "Broken", "base_url": "http://h/v1"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert client.get(f"/api/workspaces/{ws}/provider-connections", headers=auth_headers).json() == []


def test_custom_connection_cap(client, auth_headers, fake_discovery, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_custom_connections", 1)
    ws = _ws(client, auth_headers)
    first = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={"connection_type": "openai_compatible", "name": "One", "base_url": "http://h/v1"},
        headers=auth_headers,
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={"connection_type": "openai_compatible", "name": "Two", "base_url": "http://h2/v1"},
        headers=auth_headers,
    )
    assert second.status_code == 422


def test_patch_key_mutation_contract(client, auth_headers, fake_discovery):
    ws = _ws(client, auth_headers)
    conn = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={"connection_type": "openai_compatible", "name": "C", "base_url": "http://h/v1", "api_key": "sk-old-0000"},
        headers=auth_headers,
    ).json()
    cid = conn["id"]

    # replace key
    replaced = client.patch(
        f"/api/workspaces/{ws}/provider-connections/{cid}",
        json={"api_key": "sk-new-5555"},
        headers=auth_headers,
    )
    assert replaced.status_code == 200
    assert replaced.json()["key_hint"] == "…5555"

    # both replacement and clear -> 422
    conflict = client.patch(
        f"/api/workspaces/{ws}/provider-connections/{cid}",
        json={"api_key": "sk-x-1111", "clear_api_key": True},
        headers=auth_headers,
    )
    assert conflict.status_code == 422

    # clear key on custom
    cleared = client.patch(
        f"/api/workspaces/{ws}/provider-connections/{cid}",
        json={"clear_api_key": True},
        headers=auth_headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["has_key"] is False


def test_patch_clear_key_on_native_rejected(client, auth_headers):
    ws = _ws(client, auth_headers)
    conn = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={"connection_type": "openai", "api_key": "sk-native-0000"},
        headers=auth_headers,
    ).json()
    resp = client.patch(
        f"/api/workspaces/{ws}/provider-connections/{conn['id']}",
        json={"clear_api_key": True},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_patch_custom_base_url_rediscovers(client, auth_headers, fake_discovery):
    ws = _ws(client, auth_headers)
    conn = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={"connection_type": "openai_compatible", "name": "C", "base_url": "http://old/v1"},
        headers=auth_headers,
    ).json()
    fake_discovery.clear()
    resp = client.patch(
        f"/api/workspaces/{ws}/provider-connections/{conn['id']}",
        json={"base_url": "http://new/v1/"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["base_url"] == "http://new/v1"
    assert fake_discovery[-1]["base_url"] == "http://new/v1"


def test_models_endpoint(client, auth_headers, fake_discovery):
    ws = _ws(client, auth_headers)
    conn = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={"connection_type": "openai_compatible", "name": "C", "base_url": "http://h/v1"},
        headers=auth_headers,
    ).json()
    resp = client.get(
        f"/api/workspaces/{ws}/provider-connections/{conn['id']}/models",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["models"] == ["chat-a", "chat-b", "embed-x"]


def test_models_endpoint_native_422(client, auth_headers):
    ws = _ws(client, auth_headers)
    conn = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={"connection_type": "openai", "api_key": "sk-native-0000"},
        headers=auth_headers,
    ).json()
    resp = client.get(
        f"/api/workspaces/{ws}/provider-connections/{conn['id']}/models",
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_delete_connection(client, auth_headers):
    ws = _ws(client, auth_headers)
    conn = client.post(
        f"/api/workspaces/{ws}/provider-connections",
        json={"connection_type": "openai", "api_key": "sk-del-0000"},
        headers=auth_headers,
    ).json()
    assert client.delete(f"/api/workspaces/{ws}/provider-connections/{conn['id']}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/workspaces/{ws}/provider-connections", headers=auth_headers).json() == []


def test_nonmember_cannot_access(client, auth_headers):
    ws = _ws(client, auth_headers)
    token = client.post(
        "/api/auth/register",
        json={"email": "conn-intruder@example.com", "password": "password123"},
    ).json()["access_token"]
    resp = client.get(
        f"/api/workspaces/{ws}/provider-connections",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
