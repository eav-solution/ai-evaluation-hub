import pytest


def test_normalize_base_url_accepts_and_strips_trailing_slash():
    from app.connections import normalize_base_url

    assert normalize_base_url("http://localhost:11434/v1") == "http://localhost:11434/v1"
    assert normalize_base_url("https://host/api/") == "https://host/api"
    assert normalize_base_url("https://host///") == "https://host"


def test_normalize_base_url_rejects_bad_urls():
    from app.connections import normalize_base_url

    for bad in [
        "ftp://host/v1",
        "http:///v1",  # no host
        "https://user:pass@host/v1",  # credentials
        "https://host/v1?x=1",  # query
        "https://host/v1#frag",  # fragment
        "not a url",
    ]:
        with pytest.raises(ValueError):
            normalize_base_url(bad)


def _make_connection(db, connection_type="openai", **kw):
    from app.models import ProviderConnection, User, Workspace
    from app.security import encrypt_secret

    user = User(email=f"resolve-{connection_type}-{kw}@x.com", password_hash="x")
    db.add(user)
    db.flush()
    workspace = Workspace(name="RW", owner_id=user.id)
    db.add(workspace)
    db.flush()
    conn = ProviderConnection(
        workspace_id=workspace.id,
        name=kw.get("name", "OpenAI"),
        connection_type=connection_type,
        base_url=kw.get("base_url"),
        encrypted_key=encrypt_secret(kw["key"]) if kw.get("key") else None,
    )
    db.add(conn)
    db.commit()
    return workspace, conn


def test_resolve_connection_by_id_decrypts_key(db):
    from app.connections import resolve_connection

    workspace, conn = _make_connection(db, "openai", key="sk-live")
    runtime = resolve_connection(
        db, workspace.id, {"connection_id": conn.id, "model": "gpt-x"}
    )
    assert runtime.id == conn.id
    assert runtime.connection_type == "openai"
    assert runtime.api_key == "sk-live"
    assert runtime.base_url is None


def test_resolve_connection_custom_keyless(db):
    from app.connections import resolve_connection

    workspace, conn = _make_connection(
        db, "openai_compatible", name="Ollama", base_url="http://localhost:11434/v1"
    )
    runtime = resolve_connection(db, workspace.id, {"connection_id": conn.id})
    assert runtime.connection_type == "openai_compatible"
    assert runtime.base_url == "http://localhost:11434/v1"
    assert runtime.api_key is None


def test_resolve_connection_legacy_snapshot(db):
    from app.connections import resolve_connection

    workspace, conn = _make_connection(db, "openai", key="sk-legacy")
    # historical snapshot with no connection_id, keyed by provider == connection_type
    runtime = resolve_connection(
        db, workspace.id, {"provider": "openai", "model": "gpt-x"}
    )
    assert runtime.id == conn.id
    assert runtime.api_key == "sk-legacy"


def test_resolve_connection_missing_raises(db):
    from app.connections import ConnectionResolutionError, resolve_connection

    workspace, conn = _make_connection(db, "openai", key="sk-live")
    with pytest.raises(ConnectionResolutionError):
        resolve_connection(db, workspace.id, {"connection_id": "does-not-exist"})
    with pytest.raises(ConnectionResolutionError):
        resolve_connection(db, workspace.id, {"provider": "anthropic"})


def _mock_transport(handler):
    import httpx

    return httpx.MockTransport(handler)


def test_discover_models_sorts_and_dedupes_and_sends_auth():
    import httpx

    from app.connections import discover_models

    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}, {"id": "a"}]})

    models = discover_models(
        "http://localhost:11434/v1", "sk-super-secret-XYZ", _transport=_mock_transport(handler)
    )
    assert models == ["a", "b"]
    assert captured["auth"] == "Bearer sk-super-secret-XYZ"
    assert captured["url"] == "http://localhost:11434/v1/models"


def test_discover_models_omits_auth_when_keyless():
    import httpx

    from app.connections import discover_models

    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": [{"id": "m"}]})

    discover_models("http://host/v1", None, _transport=_mock_transport(handler))
    assert captured["auth"] is None


def test_discover_models_unauthorized():
    import httpx

    from app.connections import DiscoveryUnauthorized, discover_models

    def handler(request):
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(DiscoveryUnauthorized) as exc:
        discover_models("http://host/v1", "sk-secret-abc", _transport=_mock_transport(handler))
    assert "sk-secret-abc" not in str(exc.value)


def test_discover_models_unreachable_on_connect_error_and_redirect():
    import httpx

    from app.connections import DiscoveryUnreachable, discover_models

    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(DiscoveryUnreachable):
        discover_models("http://host/v1", None, _transport=_mock_transport(boom))

    def redirect(request):
        return httpx.Response(302, headers={"location": "http://elsewhere/"})

    with pytest.raises(DiscoveryUnreachable):
        discover_models("http://host/v1", None, _transport=_mock_transport(redirect))


def test_discover_models_invalid_response():
    import httpx

    from app.connections import DiscoveryInvalidResponse, discover_models

    def empty(request):
        return httpx.Response(200, json={"data": []})

    with pytest.raises(DiscoveryInvalidResponse):
        discover_models("http://host/v1", None, _transport=_mock_transport(empty))

    def notjson(request):
        return httpx.Response(200, text="hello not json")

    with pytest.raises(DiscoveryInvalidResponse):
        discover_models("http://host/v1", None, _transport=_mock_transport(notjson))


def test_discover_models_rejects_oversized_body(monkeypatch):
    import httpx

    from app.config import settings
    from app.connections import DiscoveryInvalidResponse, discover_models

    monkeypatch.setattr(settings, "provider_discovery_max_bytes", 16)

    def big(request):
        return httpx.Response(200, json={"data": [{"id": "x" * 1000}]})

    with pytest.raises(DiscoveryInvalidResponse):
        discover_models("http://host/v1", None, _transport=_mock_transport(big))
