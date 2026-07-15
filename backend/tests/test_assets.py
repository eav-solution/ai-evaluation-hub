from types import SimpleNamespace
from urllib.parse import urlparse

import httpcore
import httpx
import pytest

from app import storage


@pytest.fixture
def workspace(client, auth_headers):
    data = client.get("/api/workspaces", headers=auth_headers).json()[0]
    return SimpleNamespace(**data)


@pytest.fixture
def other_auth_headers(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "other-assets@example.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def other_workspace(client, other_auth_headers):
    data = client.get("/api/workspaces", headers=other_auth_headers).json()[0]
    return SimpleNamespace(**data)


def test_upload_rejects_disallowed_mime_and_oversize(client, workspace, auth_headers):
    url = f"/api/workspaces/{workspace.id}/assets/images"
    bad = client.post(
        url, files={"file": ("a.txt", b"hello", "text/plain")}, headers=auth_headers
    )
    assert bad.status_code == 422
    big = client.post(
        url,
        files={"file": ("a.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
        headers=auth_headers,
    )
    assert big.status_code == 413


def test_upload_and_serve_round_trip(client, workspace, auth_headers, monkeypatch):
    stored = {}
    monkeypatch.setattr(
        storage, "put_object", lambda key, data: stored.setdefault(key, data)
    )
    monkeypatch.setattr(storage, "get_object", lambda key: stored[key])
    url = f"/api/workspaces/{workspace.id}/assets/images"
    created = client.post(
        url,
        files={"file": ("a.png", b"\x89PNG bytes", "image/png")},
        headers=auth_headers,
    )
    assert created.status_code == 201
    asset_id = created.json()["asset_id"]
    served = client.get(
        f"/api/workspaces/{workspace.id}/assets/{asset_id}", headers=auth_headers
    )
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == b"\x89PNG bytes"


def test_serve_is_workspace_scoped(
    client, workspace, other_workspace, auth_headers, other_auth_headers, monkeypatch
):
    stored = {}
    monkeypatch.setattr(
        storage, "put_object", lambda key, data: stored.setdefault(key, data)
    )
    monkeypatch.setattr(storage, "get_object", lambda key: stored[key])
    created = client.post(
        f"/api/workspaces/{workspace.id}/assets/images",
        files={"file": ("a.png", b"\x89PNG bytes", "image/png")},
        headers=auth_headers,
    )
    asset_id = created.json()["asset_id"]
    foreign = client.get(
        f"/api/workspaces/{other_workspace.id}/assets/{asset_id}",
        headers=other_auth_headers,
    )
    assert foreign.status_code == 404


def test_upload_cleans_up_storage_when_commit_fails(
    client, workspace, auth_headers, monkeypatch
):
    stored, deleted = {}, []
    monkeypatch.setattr(
        storage, "put_object", lambda key, data: stored.setdefault(key, data)
    )
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key))
    monkeypatch.setattr(
        "app.routers.assets.Session.commit",
        lambda self: (_ for _ in ()).throw(RuntimeError("db down")),
        raising=False,
    )
    response = client.post(
        f"/api/workspaces/{workspace.id}/assets/images",
        files={"file": ("a.png", b"\x89PNG bytes", "image/png")},
        headers=auth_headers,
    )
    assert response.status_code == 500
    assert deleted == list(stored)


class _FakeStreamResponse:
    def __init__(
        self, status_code=200, headers=None, chunks=(b"\x89PNG",), location=None
    ):
        self.status_code = status_code
        self.headers = dict(headers or {"content-type": "image/png"})
        if location:
            self.headers["location"] = location
        self._chunks = chunks
        self.is_redirect = 300 <= status_code < 400

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def iter_bytes(self):
        yield from self._chunks


class _FakeNetworkStream(httpcore.NetworkStream):
    def __init__(self, tls_hostnames, writes):
        self._response = iter(
            [
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: image/png\r\n"
                b"Content-Length: 4\r\n"
                b"Connection: close\r\n\r\n"
                b"\x89PNG",
                b"",
            ]
        )
        self._tls_hostnames = tls_hostnames
        self._writes = writes

    def read(self, max_bytes, timeout=None):
        return next(self._response, b"")

    def write(self, buffer, timeout=None):
        self._writes.append(buffer)

    def close(self):
        return None

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self._tls_hostnames.append(server_hostname)
        return self

    def get_extra_info(self, info):
        if info == "is_readable":
            return False
        return None


def _patch_stream(monkeypatch, responses):
    queue = list(responses)
    monkeypatch.setattr(
        "app.assets.httpx.Client.stream",
        lambda self, method, url: queue.pop(0),
    )


def test_fetch_remote_image_blocks_private_targets(monkeypatch):
    from app.assets import fetch_remote_image

    monkeypatch.setattr(
        "app.endpoints.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("10.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="private or non-public"):
        fetch_remote_image("https://internal.example/img.png")


def test_fetch_remote_image_blocks_private_targets_when_override_enabled(monkeypatch):
    from app.assets import fetch_remote_image
    from app.endpoints import settings

    monkeypatch.setattr(settings, "allow_private_endpoints", True)
    monkeypatch.setattr(
        "app.endpoints.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("10.0.0.1", 443))],
    )
    _patch_stream(monkeypatch, [_FakeStreamResponse()])

    with pytest.raises(ValueError, match="private or non-public"):
        fetch_remote_image("https://internal.example/img.png")


def test_fetch_remote_image_pins_ip_and_preserves_hostname_semantics(monkeypatch):
    from app.assets import fetch_remote_image

    for name in (
        "ALL_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "all_proxy",
        "https_proxy",
        "http_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "app.endpoints.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    tcp_hosts, tls_hostnames, writes = [], [], []

    def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        tcp_hosts.append(host)
        return _FakeNetworkStream(tls_hostnames, writes)

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect_tcp)

    data, mime = fetch_remote_image("https://origin.example/img.png")

    assert data == b"\x89PNG"
    assert mime == "image/png"
    assert tcp_hosts == ["93.184.216.34"]
    assert tls_hostnames == ["origin.example"]
    assert b"host: origin.example" in b"".join(writes).lower()


def test_fetch_remote_image_disables_environment_proxies(monkeypatch):
    from app.assets import fetch_remote_image

    real_client = httpx.Client
    client_kwargs = []

    class RecordingClient(real_client):
        def __init__(self, *args, **kwargs):
            client_kwargs.append(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setattr("app.assets.httpx.Client", RecordingClient)
    monkeypatch.setattr(
        "app.endpoints.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    _patch_stream(monkeypatch, [_FakeStreamResponse()])

    fetch_remote_image("https://origin.example/img.png")

    assert client_kwargs[0]["trust_env"] is False
    assert client_kwargs[0]["transport"] is not None


def test_fetch_remote_image_deadline_includes_dns(monkeypatch):
    from app import assets
    from app.assets import fetch_remote_image

    clock = {"now": 0.0}
    monkeypatch.setattr(
        assets,
        "time",
        SimpleNamespace(monotonic=lambda: clock["now"]),
        raising=False,
    )

    def slow_resolver(*args, **kwargs):
        clock["now"] = 21.0
        return [(2, 1, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr("app.endpoints.socket.getaddrinfo", slow_resolver)
    _patch_stream(monkeypatch, [_FakeStreamResponse()])

    with pytest.raises(ValueError, match="20-second deadline"):
        fetch_remote_image("https://origin.example/img.png")


def test_fetch_remote_image_deadline_includes_streamed_body(monkeypatch):
    from app import assets
    from app.assets import fetch_remote_image

    clock = {"now": 0.0}
    monkeypatch.setattr(
        assets,
        "time",
        SimpleNamespace(monotonic=lambda: clock["now"]),
        raising=False,
    )
    monkeypatch.setattr(
        "app.endpoints.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )

    def slow_chunks():
        clock["now"] = 21.0
        yield b"\x89PNG"

    _patch_stream(monkeypatch, [_FakeStreamResponse(chunks=slow_chunks())])

    with pytest.raises(ValueError, match="20-second deadline"):
        fetch_remote_image("https://origin.example/img.png")


def test_fetch_remote_image_deadline_does_not_reset_between_redirects(monkeypatch):
    from app import assets
    from app.assets import fetch_remote_image

    clock = {"now": 0.0}
    checked = []
    monkeypatch.setattr(
        assets,
        "time",
        SimpleNamespace(monotonic=lambda: clock["now"]),
        raising=False,
    )

    def validate(url, *args, **kwargs):
        checked.append(url)
        if len(checked) == 2:
            clock["now"] = 21.0
        return urlparse(url), ("93.184.216.34",)

    monkeypatch.setattr("app.assets._validated_https_target", validate)
    _patch_stream(
        monkeypatch,
        [
            _FakeStreamResponse(
                status_code=302,
                location="https://cdn.example/img.png",
            ),
            _FakeStreamResponse(),
        ],
    )

    with pytest.raises(ValueError, match="20-second deadline"):
        fetch_remote_image("https://origin.example/img.png")


def test_fetch_remote_image_validates_every_redirect_hop(monkeypatch):
    from app.assets import fetch_remote_image

    checked = []

    def validate(url, *args, **kwargs):
        checked.append(url)
        return urlparse(url), ("93.184.216.34",)

    monkeypatch.setattr("app.assets._validated_https_target", validate)
    _patch_stream(
        monkeypatch,
        [
            _FakeStreamResponse(
                status_code=302, location="https://cdn.example/img.png"
            ),
            _FakeStreamResponse(),
        ],
    )
    data, mime = fetch_remote_image("https://origin.example/img.png")
    assert checked == [
        "https://origin.example/img.png",
        "https://cdn.example/img.png",
    ]
    assert mime == "image/png"


def test_fetch_remote_image_rejects_http_downgrade_redirect(monkeypatch):
    from app.assets import fetch_remote_image

    monkeypatch.setattr(
        "app.endpoints.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    _patch_stream(
        monkeypatch,
        [
            _FakeStreamResponse(
                status_code=302, location="http://origin.example/img.png"
            ),
        ],
    )
    with pytest.raises(ValueError, match="HTTPS"):
        fetch_remote_image("https://origin.example/img.png")


def test_fetch_remote_image_enforces_mime_size_and_redirect_limit(monkeypatch):
    from app.assets import MAX_IMAGE_BYTES, fetch_remote_image

    monkeypatch.setattr(
        "app.assets._validated_https_target",
        lambda url, *args, **kwargs: (urlparse(url), ("93.184.216.34",)),
    )
    _patch_stream(
        monkeypatch, [_FakeStreamResponse(headers={"content-type": "text/html"})]
    )
    with pytest.raises(ValueError, match="not an allowed image type"):
        fetch_remote_image("https://origin.example/img.png")

    _patch_stream(
        monkeypatch,
        [
            _FakeStreamResponse(chunks=(b"x" * (MAX_IMAGE_BYTES // 2 + 1),) * 2),
        ],
    )
    with pytest.raises(ValueError, match="5 MiB limit"):
        fetch_remote_image("https://origin.example/img.png")

    _patch_stream(
        monkeypatch,
        [_FakeStreamResponse(status_code=302, location="https://origin.example/next")]
        * 4,
    )
    with pytest.raises(ValueError, match="redirect limit"):
        fetch_remote_image("https://origin.example/img.png")
