import hashlib
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app import storage
from app.assets import ALLOWED_IMAGE_MIME_TYPES, MAX_IMAGE_BYTES, store_image_asset
from app.deps import get_db, get_workspace
from app.models import (
    Dataset,
    EvaluationArtifact,
    EvaluationAsset,
    OutboxEvent,
    RunResult,
    Workspace,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces/{workspace_id}/assets", tags=["assets"])


def _references_asset(value, asset_id: str) -> bool:
    if isinstance(value, dict):
        if value.get("asset_id") == asset_id:
            return True
        return any(_references_asset(item, asset_id) for item in value.values())
    if isinstance(value, list):
        return any(_references_asset(item, asset_id) for item in value)
    return False


def _assert_asset_unreferenced(db: Session, workspace_id: str, asset_id: str) -> None:
    details = (
        row[0]
        for row in db.query(RunResult.details)
        .filter(
            RunResult.workspace_id == workspace_id,
            RunResult.details.is_not(None),
        )
        .all()
    )
    if any(_references_asset(value, asset_id) for value in details):
        raise HTTPException(status_code=409, detail="Asset is still referenced")

    paths = [
        row[0]
        for row in db.query(EvaluationArtifact.storage_path)
        .filter_by(workspace_id=workspace_id)
        .all()
    ]
    paths.extend(
        row[0]
        for row in db.query(Dataset.storage_path)
        .filter_by(workspace_id=workspace_id)
        .all()
    )
    needle = asset_id.encode()
    try:
        referenced = any(needle in storage.get_object(path) for path in paths)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Asset references could not be verified",
        ) from exc
    if referenced:
        raise HTTPException(status_code=409, detail="Asset is still referenced")


@router.post("/images", status_code=201)
def upload_image(
    file: Annotated[UploadFile, File()],
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict:
    if (file.content_type or "").lower() not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported image type")
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds the 5 MiB limit")
    if not data:
        raise HTTPException(status_code=422, detail="Image file is empty")
    asset = store_image_asset(db, ws.id, data, file.content_type.lower())
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            storage.delete_object(asset.storage_path)
        except Exception:
            logger.exception("Failed to clean up asset upload %s", asset.storage_path)
        raise HTTPException(status_code=500, detail="Failed to save image asset") from exc
    return {
        "asset_id": asset.id,
        "mime_type": asset.mime_type,
        "byte_size": asset.byte_size,
    }


@router.get("/{asset_id}")
def serve_image(
    asset_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> Response:
    asset = (
        db.query(EvaluationAsset)
        .filter_by(id=asset_id, workspace_id=ws.id)
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return Response(
        content=storage.get_object(asset.storage_path),
        media_type=asset.mime_type,
    )


@router.delete("/{asset_id}", status_code=204)
def delete_image(
    asset_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> Response:
    asset = (
        db.query(EvaluationAsset)
        .filter_by(id=asset_id, workspace_id=ws.id)
        .with_for_update()
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.run_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Run-owned assets are deleted with their run",
        )
    _assert_asset_unreferenced(db, ws.id, asset.id)
    event = OutboxEvent(
        kind="delete_object",
        dedupe_key=f"storage:{hashlib.sha256(asset.storage_path.encode()).hexdigest()}",
        payload={"key": asset.storage_path},
    )
    try:
        db.add(event)
        db.flush()
        db.delete(asset)
        db.commit()
    except Exception:
        db.rollback()
        raise
    from app.tasks import dispatch_outbox_event

    try:
        dispatch_outbox_event(event.id)
    except Exception:
        logger.exception("Immediate asset cleanup dispatch failed for %s", asset.id)
    return Response(status_code=204)
