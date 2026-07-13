"""Provider connection resolution and OpenAI-compatible model discovery.

This is the single boundary that turns a stored connection (or a legacy
`{provider, model}` snapshot) into a decrypted runtime configuration, and the
only place that performs outbound `/models` discovery for custom connections.
"""
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ProviderConnection
from app.security import decrypt_secret


class ConnectionResolutionError(Exception):
    """Raised when a run/generation snapshot cannot be resolved to a connection."""


class DiscoveryError(Exception):
    """Base class for model-discovery failures. `.message` is browser-safe."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class DiscoveryUnreachable(DiscoveryError):
    """The /models endpoint could not be reached, timed out, or redirected."""


class DiscoveryUnauthorized(DiscoveryError):
    """The /models endpoint rejected the credentials."""


class DiscoveryInvalidResponse(DiscoveryError):
    """The /models response was not a valid, non-empty OpenAI model list."""


@dataclass(frozen=True)
class RuntimeConnection:
    id: str | None
    connection_type: str
    base_url: str | None
    api_key: str | None
    name: str


def normalize_base_url(raw: str) -> str:
    """Validate a custom base URL and strip only trailing slashes.

    Rules: http/https scheme, a host, no embedded credentials, no query
    string, no fragment. Never appends `/v1`.
    """
    parsed = urlparse(raw.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Base URL must use HTTP or HTTPS")
    if not parsed.hostname:
        raise ValueError("Base URL must include a host")
    if parsed.username or parsed.password:
        raise ValueError("Base URL must not contain embedded credentials")
    if parsed.query:
        raise ValueError("Base URL must not contain a query string")
    if parsed.fragment:
        raise ValueError("Base URL must not contain a fragment")
    return raw.strip().rstrip("/")


def discover_models(
    base_url: str, api_key: str | None, *, _transport: "httpx.BaseTransport | None" = None
) -> list[str]:
    """Fetch and normalize the model list from an OpenAI-compatible endpoint.

    Sends `GET {base_url}/models`, with `Authorization: Bearer` only when a
    key is configured. Bounded timeout, no redirects, response capped at
    `provider_discovery_max_bytes`. Returns sorted, de-duplicated model IDs.
    Raises a `DiscoveryError` subclass whose message never contains the key.
    """
    url = normalize_base_url(base_url) + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    max_bytes = settings.provider_discovery_max_bytes
    client = httpx.Client(
        timeout=settings.provider_discovery_timeout_seconds,
        follow_redirects=False,
        transport=_transport,
    )
    try:
        with client:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code in (401, 403):
                    raise DiscoveryUnauthorized(
                        "The model service rejected the API key"
                    )
                if response.is_redirect:
                    raise DiscoveryUnreachable(
                        "The model service issued a redirect"
                    )
                if response.status_code >= 400:
                    raise DiscoveryUnreachable(
                        "The model service returned an error"
                    )
                total = 0
                chunks: list[bytes] = []
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise DiscoveryInvalidResponse(
                            "The model list response was too large"
                        )
                    chunks.append(chunk)
                body = b"".join(chunks)
    except httpx.HTTPError as exc:
        raise DiscoveryUnreachable("Could not reach the model service") from exc

    import json

    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise DiscoveryInvalidResponse(
            "The endpoint is not OpenAI-compatible"
        ) from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        raise DiscoveryInvalidResponse("The endpoint is not OpenAI-compatible")
    ids = [
        item["id"].strip()
        for item in data
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item["id"].strip()
    ]
    if not ids:
        raise DiscoveryInvalidResponse("The endpoint is not OpenAI-compatible")
    return sorted(set(ids))


def _strip_authorization(request: "httpx.Request") -> None:
    if "authorization" in request.headers:
        del request.headers["authorization"]


def openai_client_args(
    connection_type: str,
    base_url: str | None,
    api_key: str | None,
    *,
    async_: bool,
) -> dict:
    """Build constructor kwargs for the OpenAI/AsyncOpenAI SDK.

    Native connections just pass their key. Custom (`openai_compatible`)
    connections set `base_url`; when keyless they pass a placeholder key (the
    SDK demands one) plus an httpx client that removes the `Authorization`
    header the SDK would otherwise send.
    """
    if connection_type != "openai_compatible":
        return {"api_key": api_key}
    args: dict = {"base_url": base_url}
    if api_key:
        args["api_key"] = api_key
    else:
        args["api_key"] = "not-needed"
        hooks = {"request": [_strip_authorization]}
        args["http_client"] = (
            httpx.AsyncClient(event_hooks=hooks)
            if async_
            else httpx.Client(event_hooks=hooks)
        )
    return args


def resolve_connection(
    db: Session, workspace_id: str, snapshot: dict
) -> RuntimeConnection:
    """Resolve a config snapshot to a decrypted runtime connection.

    New snapshots carry `connection_id`. Legacy snapshots carry `provider`,
    which is matched against `connection_type` (the migrated native rows).
    """
    connection_id = snapshot.get("connection_id")
    if connection_id:
        row = (
            db.query(ProviderConnection)
            .filter_by(id=connection_id, workspace_id=workspace_id)
            .one_or_none()
        )
        if row is None:
            raise ConnectionResolutionError(
                "The provider connection for this work was removed"
            )
    else:
        provider = snapshot.get("provider")
        if not provider:
            raise ConnectionResolutionError("No provider connection was configured")
        row = (
            db.query(ProviderConnection)
            .filter_by(workspace_id=workspace_id, connection_type=provider)
            .one_or_none()
        )
        if row is None:
            raise ConnectionResolutionError(
                f"No {provider} provider connection is configured"
            )

    return RuntimeConnection(
        id=row.id,
        connection_type=row.connection_type,
        base_url=row.base_url,
        api_key=decrypt_secret(row.encrypted_key) if row.encrypted_key else None,
        name=row.name,
    )
