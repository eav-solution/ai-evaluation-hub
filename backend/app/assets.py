import queue
import threading
import time
import uuid

import httpcore
import httpx

from app import storage
from app.endpoints import _validate_destination, validate_url
from app.models import EvaluationAsset

ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
_FETCH_TIMEOUT_SECONDS = 20.0
_MAX_REDIRECTS = 3


def asset_storage_path(workspace_id: str, asset_id: str) -> str:
    return f"image-assets/{workspace_id}/{asset_id}"


def _normalized_mime(content_type: str | None) -> str:
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError(f"'{mime or 'unknown'}' is not an allowed image type")
    return mime


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("Remote image fetch exceeded the 20-second deadline")
    return remaining


def _bounded_timeout(timeout: float | None, deadline: float) -> float:
    remaining = _remaining_seconds(deadline)
    return remaining if timeout is None else min(timeout, remaining)


class _DeadlineNetworkStream(httpcore.NetworkStream):
    def __init__(self, stream: httpcore.NetworkStream, deadline: float):
        self._stream = stream
        self._deadline = deadline

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._stream.read(
            max_bytes,
            _bounded_timeout(timeout, self._deadline),
        )

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._stream.write(buffer, _bounded_timeout(timeout, self._deadline))

    def close(self) -> None:
        self._stream.close()

    def start_tls(
        self,
        ssl_context,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.NetworkStream:
        stream = self._stream.start_tls(
            ssl_context,
            server_hostname,
            _bounded_timeout(timeout, self._deadline),
        )
        return _DeadlineNetworkStream(stream, self._deadline)

    def get_extra_info(self, info: str):
        return self._stream.get_extra_info(info)


class _PinnedSyncBackend(httpcore.SyncBackend):
    def __init__(self, hostname: str, ip_address: str, deadline: float):
        self._hostname = hostname.encode("idna").decode("ascii").lower()
        self._ip_address = ip_address
        self._deadline = deadline

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ) -> httpcore.NetworkStream:
        connect_host = self._ip_address if host.lower() == self._hostname else host
        stream = super().connect_tcp(
            connect_host,
            port,
            timeout=_bounded_timeout(timeout, self._deadline),
            local_address=local_address,
            socket_options=socket_options,
        )
        return _DeadlineNetworkStream(stream, self._deadline)


class _PinnedHTTPTransport(httpx.HTTPTransport):
    def __init__(self, hostname: str, ip_address: str, deadline: float):
        super().__init__(trust_env=False)
        self._pool._network_backend = _PinnedSyncBackend(  # type: ignore[attr-defined]
            hostname,
            ip_address,
            deadline,
        )


def _validate_before_deadline(parsed, deadline: float) -> tuple[str, ...]:
    result = queue.Queue(maxsize=1)

    def validate() -> None:
        try:
            addresses = _validate_destination(parsed, allow_private=False)
            result.put((addresses, None))
        except Exception as exc:
            result.put((None, exc))

    _remaining_seconds(deadline)
    threading.Thread(target=validate, daemon=True).start()
    try:
        addresses, error = result.get(timeout=_remaining_seconds(deadline))
    except queue.Empty as exc:
        raise ValueError("Remote image fetch exceeded the 20-second deadline") from exc
    if error is not None:
        raise error
    _remaining_seconds(deadline)
    return addresses


def _validated_https_target(url: str, deadline: float):
    """Validate scheme, credentials, and resolved addresses before any request."""
    parsed = validate_url(url)
    if parsed.scheme != "https":
        raise ValueError("Remote images must use HTTPS")
    addresses = _validate_before_deadline(parsed, deadline)
    return parsed, addresses


def fetch_remote_image(url: str) -> tuple[bytes, str]:
    # Redirects are followed manually so every hop is validated before fetching.
    current = url
    deadline = time.monotonic() + _FETCH_TIMEOUT_SECONDS
    try:
        for _ in range(_MAX_REDIRECTS + 1):
            _remaining_seconds(deadline)
            parsed, addresses = _validated_https_target(current, deadline)
            _remaining_seconds(deadline)
            transport = _PinnedHTTPTransport(
                parsed.hostname,
                addresses[0],
                deadline,
            )
            with httpx.Client(
                transport=transport,
                timeout=_remaining_seconds(deadline),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                with client.stream("GET", current) as response:
                    _remaining_seconds(deadline)
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Remote image redirect has no location")
                        current = str(httpx.URL(current).join(location))
                        continue
                    response.raise_for_status()
                    mime = _normalized_mime(response.headers.get("content-type"))
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        _remaining_seconds(deadline)
                        if len(data) > MAX_IMAGE_BYTES:
                            raise ValueError("Remote image exceeds the 5 MiB limit")
                    if not data:
                        raise ValueError("Remote image is empty")
                    return bytes(data), mime
        raise ValueError("Remote image exceeded the redirect limit")
    except httpx.HTTPError as exc:
        raise ValueError(f"Remote image fetch failed: {exc}") from exc


def store_image_asset(
    db,
    workspace_id: str,
    data: bytes,
    mime_type: str,
    source_url: str | None = None,
    run_id: str | None = None,
) -> EvaluationAsset:
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError(f"'{mime_type}' is not an allowed image type")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 5 MiB limit")
    if (run_id is None) != (source_url is None):
        raise ValueError("Remote image snapshots need a run owner and source URL")
    asset = EvaluationAsset(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        run_id=run_id,
        mime_type=mime_type,
        byte_size=len(data),
        source_url=source_url,
        storage_path="",
    )
    asset.storage_path = asset_storage_path(workspace_id, asset.id)
    storage.put_object(asset.storage_path, data)
    db.add(asset)
    return asset
