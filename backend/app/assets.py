import uuid

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


def _validated_https_target(url: str):
    """Validate scheme, credentials, and resolved addresses before any request."""
    parsed = validate_url(url)
    if parsed.scheme != "https":
        raise ValueError("Remote images must use HTTPS")
    _validate_destination(parsed)
    return parsed


def fetch_remote_image(url: str) -> tuple[bytes, str]:
    # Redirects are followed manually so every hop is validated before fetching.
    current = url
    try:
        with httpx.Client(
            timeout=_FETCH_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                _validated_https_target(current)
                with client.stream("GET", current) as response:
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
) -> EvaluationAsset:
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError(f"'{mime_type}' is not an allowed image type")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 5 MiB limit")
    asset = EvaluationAsset(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        mime_type=mime_type,
        byte_size=len(data),
        source_url=source_url,
        storage_path="",
    )
    asset.storage_path = asset_storage_path(workspace_id, asset.id)
    storage.put_object(asset.storage_path, data)
    db.add(asset)
    return asset
