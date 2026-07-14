import ipaddress
import json
import socket
import time
from typing import Any, Literal
from urllib.parse import ParseResult, urlparse

import httpx
from jsonpath_ng.ext import parse
from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import settings
from app.evals.base import EvalRow
from app.security import decrypt_secret


def render_template(template, row: EvalRow):
    values = {
        "{{input}}": row.input,
        "{{contexts}}": row.contexts or [],
        "{{context}}": row.context or [],
        "{{retrieval_contexts}}": row.retrieval_contexts or [],
        "{{expected_output}}": row.expected_output,
        "{{actual_output}}": row.actual_output,
    }
    if isinstance(template, dict):
        return {key: render_template(value, row) for key, value in template.items()}
    if isinstance(template, list):
        return [render_template(value, row) for value in template]
    if not isinstance(template, str):
        return template
    if template in values:
        return values[template]
    for placeholder, value in values.items():
        replacement = json.dumps(value) if isinstance(value, (dict, list)) else str(value or "")
        template = template.replace(placeholder, replacement)
    return template


def extract_answer(payload, expression: str) -> str:
    matches = parse(expression).find(payload)
    if not matches:
        raise ValueError("Response JSONPath matched no values")
    value = matches[0].value
    return value if isinstance(value, str) else json.dumps(value)


def _resolved_response_mappings(config: dict) -> dict[str, str]:
    mappings = dict(config.get("response_mappings") or {})
    legacy = config.get("response_jsonpath")
    if legacy and "actual_output" not in mappings:
        mappings["actual_output"] = legacy
    return mappings


def extract_response_fields(payload, config: dict) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field, expression in _resolved_response_mappings(config).items():
        matches = parse(expression).find(payload)
        if not matches:
            raise ValueError(f"Response JSONPath for {field} matched no values")
        value = matches[0].value
        values[field] = (
            value
            if field != "actual_output" or isinstance(value, str)
            else json.dumps(value)
        )
    return values


def validate_url(url: str) -> ParseResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Endpoint URL must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("Endpoint URL must not contain credentials")
    return parsed


def _validate_destination(parsed: ParseResult) -> None:
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = socket.getaddrinfo(
        parsed.hostname,
        port,
        type=socket.SOCK_STREAM,
    )
    if not addresses:
        raise ValueError("Endpoint hostname did not resolve")
    if settings.allow_private_endpoints:
        return
    for address in addresses:
        resolved = ipaddress.ip_address(address[4][0])
        if not resolved.is_global:
            raise ValueError("Endpoint resolves to a private or non-public address")


def _request(method: str, url: str, headers: dict[str, str], body):
    return httpx.request(
        method,
        url,
        headers=headers,
        json=body,
        timeout=settings.endpoint_timeout_seconds,
        follow_redirects=False,
    )


def call_endpoint(
    config: dict,
    row: EvalRow,
    *,
    encrypted_headers: bool = True,
    retries: int | None = None,
) -> tuple[str, object, float]:
    method = config.get("method", "POST").upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("Unsupported endpoint method")

    headers = {
        key: decrypt_secret(value) if encrypted_headers else value
        for key, value in config.get("headers", {}).items()
    }
    body = render_template(config.get("body_template"), row)
    url = config["url"]
    max_retries = settings.endpoint_retries if retries is None else retries

    for attempt in range(max_retries + 1):
        parsed = validate_url(url)
        _validate_destination(parsed)
        started = time.perf_counter()
        try:
            response = _request(method, url, headers, body)
            response.raise_for_status()
        except httpx.HTTPError:
            if attempt >= max_retries:
                raise
            time.sleep(2**attempt)
            continue

        latency_ms = (time.perf_counter() - started) * 1000
        payload = response.json()
        answer = extract_response_fields(payload, config)["actual_output"]
        return answer, payload, latency_ms

    raise RuntimeError("Endpoint retry loop exhausted")


class EndpointConfig(BaseModel):
    url: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: Any = None
    response_jsonpath: str | None = Field(default=None, min_length=1)
    response_mappings: dict[str, str] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _valid_url(cls, value: str) -> str:
        validate_url(value)
        return value

    @field_validator("response_jsonpath")
    @classmethod
    def _valid_jsonpath(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            parse(value)
        except Exception as exc:
            raise ValueError("Invalid response JSONPath") from exc
        return value

    @field_validator("response_mappings")
    @classmethod
    def _valid_response_mappings(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"actual_output", "context", "retrieval_contexts"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"Unknown response mapping: {sorted(unknown)[0]}")
        for field, expression in value.items():
            if not expression:
                raise ValueError(f"Response mapping for {field} must not be empty")
            try:
                parse(expression)
            except Exception as exc:
                raise ValueError(f"Invalid response JSONPath for {field}") from exc
        return value

    @model_validator(mode="after")
    def _actual_output_mapping(self):
        named = self.response_mappings.get("actual_output")
        if self.response_jsonpath and named and self.response_jsonpath != named:
            raise ValueError("Legacy and named actual_output mappings conflict")
        if not self.response_jsonpath and not named:
            raise ValueError("Endpoint response needs an actual_output mapping")
        return self

    def resolved_response_mappings(self) -> dict[str, str]:
        return _resolved_response_mappings(self.model_dump())
