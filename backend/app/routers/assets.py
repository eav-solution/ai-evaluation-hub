import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app import storage
from app.assets import ALLOWED_IMAGE_MIME_TYPES, MAX_IMAGE_BYTES, store_image_asset
from app.deps import get_db, get_workspace
from app.models import EvaluationAsset, Workspace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces/{workspace_id}/assets", tags=["assets"])


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
