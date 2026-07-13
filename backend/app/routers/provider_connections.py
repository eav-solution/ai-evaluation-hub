from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.connections import (
    DiscoveryError,
    DiscoveryUnauthorized,
    discover_models,
    normalize_base_url,
)
from app.deps import get_db, get_workspace
from app.models import ProviderConnection, Workspace
from app.security import decrypt_secret, encrypt_secret

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/provider-connections",
    tags=["provider-connections"],
)

NATIVE_TYPES = {"openai": "OpenAI", "anthropic": "Anthropic"}
CUSTOM_TYPE = "openai_compatible"


class ConnectionCreate(BaseModel):
    connection_type: Literal["openai", "anthropic", "openai_compatible"]
    name: str | None = Field(default=None, max_length=255)
    base_url: str | None = Field(default=None, max_length=1024)
    api_key: str | None = Field(default=None, min_length=1)


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    base_url: str | None = Field(default=None, max_length=1024)
    api_key: str | None = Field(default=None, min_length=1)
    clear_api_key: bool = False


class ConnectionOut(BaseModel):
    id: str
    name: str
    connection_type: str
    base_url: str | None
    has_key: bool
    key_hint: str | None


def _out(row: ProviderConnection) -> ConnectionOut:
    key_hint = None
    if row.encrypted_key:
        key_hint = "…" + decrypt_secret(row.encrypted_key)[-4:]
    return ConnectionOut(
        id=row.id,
        name=row.name,
        connection_type=row.connection_type,
        base_url=row.base_url,
        has_key=row.encrypted_key is not None,
        key_hint=key_hint,
    )


def _get_connection(
    connection_id: str, workspace_id: str, db: Session
) -> ProviderConnection:
    row = (
        db.query(ProviderConnection)
        .filter_by(id=connection_id, workspace_id=workspace_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return row


def _name_taken(db: Session, workspace_id: str, name: str, exclude_id: str | None) -> bool:
    query = db.query(ProviderConnection).filter(
        ProviderConnection.workspace_id == workspace_id,
        func.lower(ProviderConnection.name) == name.lower(),
    )
    if exclude_id is not None:
        query = query.filter(ProviderConnection.id != exclude_id)
    return db.query(query.exists()).scalar()


def _discover_or_422(base_url: str, api_key: str | None) -> None:
    try:
        discover_models(base_url, api_key)
    except DiscoveryUnauthorized as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except DiscoveryError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.post("", status_code=201)
def create_connection(
    body: ConnectionCreate,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    if body.connection_type in NATIVE_TYPES:
        if not body.api_key:
            raise HTTPException(
                status_code=422, detail="This provider requires an API key"
            )
        exists = (
            db.query(ProviderConnection)
            .filter_by(workspace_id=ws.id, connection_type=body.connection_type)
            .first()
        )
        if exists is not None:
            raise HTTPException(
                status_code=409,
                detail="A connection for this provider already exists; remove it first",
            )
        row = ProviderConnection(
            workspace_id=ws.id,
            name=body.name.strip() if body.name and body.name.strip() else NATIVE_TYPES[body.connection_type],
            connection_type=body.connection_type,
            base_url=None,
            encrypted_key=encrypt_secret(body.api_key),
        )
    else:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Connection name is required")
        if not body.base_url:
            raise HTTPException(status_code=422, detail="Base URL is required")
        try:
            base_url = normalize_base_url(body.base_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        custom_count = (
            db.query(ProviderConnection)
            .filter_by(workspace_id=ws.id, connection_type=CUSTOM_TYPE)
            .count()
        )
        if custom_count >= settings.max_custom_connections:
            raise HTTPException(
                status_code=422,
                detail=f"At most {settings.max_custom_connections} custom connections per workspace",
            )
        if _name_taken(db, ws.id, name, exclude_id=None):
            raise HTTPException(
                status_code=409, detail="A connection with this name already exists"
            )
        _discover_or_422(base_url, body.api_key)
        row = ProviderConnection(
            workspace_id=ws.id,
            name=name,
            connection_type=CUSTOM_TYPE,
            base_url=base_url,
            encrypted_key=encrypt_secret(body.api_key) if body.api_key else None,
        )

    db.add(row)
    db.commit()
    return _out(row)


@router.get("")
def list_connections(
    ws: Workspace = Depends(get_workspace), db: Session = Depends(get_db)
) -> list[ConnectionOut]:
    rows = (
        db.query(ProviderConnection)
        .filter_by(workspace_id=ws.id)
        .order_by(ProviderConnection.created_at)
        .all()
    )
    return [_out(row) for row in rows]


@router.patch("/{connection_id}")
def update_connection(
    connection_id: str,
    body: ConnectionUpdate,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    row = _get_connection(connection_id, ws.id, db)
    is_custom = row.connection_type == CUSTOM_TYPE

    if body.clear_api_key and body.api_key:
        raise HTTPException(
            status_code=422,
            detail="Cannot both replace and clear the API key",
        )
    if body.clear_api_key and not is_custom:
        raise HTTPException(
            status_code=422, detail="This provider requires an API key"
        )
    if body.base_url is not None and not is_custom:
        raise HTTPException(
            status_code=422, detail="Base URL only applies to custom connections"
        )

    new_name = row.name
    if body.name is not None:
        stripped = body.name.strip()
        if not stripped:
            raise HTTPException(status_code=422, detail="Connection name is required")
        if _name_taken(db, ws.id, stripped, exclude_id=row.id):
            raise HTTPException(
                status_code=409, detail="A connection with this name already exists"
            )
        new_name = stripped

    new_base_url = row.base_url
    if body.base_url is not None:
        try:
            new_base_url = normalize_base_url(body.base_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if body.clear_api_key:
        new_encrypted_key = None
    elif body.api_key:
        new_encrypted_key = encrypt_secret(body.api_key)
    else:
        new_encrypted_key = row.encrypted_key

    # Re-verify custom connections before persisting; a failure leaves the row unchanged.
    if is_custom:
        new_api_key = None if new_encrypted_key is None else decrypt_secret(new_encrypted_key)
        _discover_or_422(new_base_url, new_api_key)

    row.name = new_name
    row.base_url = new_base_url
    row.encrypted_key = new_encrypted_key
    db.commit()
    return _out(row)


@router.delete("/{connection_id}", status_code=204)
def delete_connection(
    connection_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> Response:
    row = _get_connection(connection_id, ws.id, db)
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.get("/{connection_id}/models")
def list_models(
    connection_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_connection(connection_id, ws.id, db)
    if row.connection_type != CUSTOM_TYPE:
        raise HTTPException(
            status_code=422,
            detail="Model discovery is only available for custom connections",
        )
    api_key = decrypt_secret(row.encrypted_key) if row.encrypted_key else None
    try:
        models = discover_models(row.base_url, api_key)
    except DiscoveryError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    return {"models": models}
