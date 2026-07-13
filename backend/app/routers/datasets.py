import hashlib
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import storage
from app.config import settings
from app.datasets import parse_dataset
from app.deps import get_db, get_workspace
from app.models import Dataset, GenerationJob, OutboxEvent, Workspace

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/datasets", tags=["datasets"]
)
SCHEMA_FIELDS = {"input", "expected_output", "contexts", "actual_output"}


class DatasetOut(BaseModel):
    id: str
    name: str
    format: str
    row_count: int
    storage_path: str
    schema_map: dict[str, str]


class DatasetDetail(DatasetOut):
    preview: list[dict]


class SchemaMapIn(BaseModel):
    schema_map: dict[str, str]


def _out(row: Dataset) -> DatasetOut:
    return DatasetOut(
        id=row.id,
        name=row.name,
        format=row.format,
        row_count=row.row_count,
        storage_path=row.storage_path,
        schema_map=row.schema_map,
    )


def _get_dataset(dataset_id: str, workspace_id: str, db: Session) -> Dataset:
    row = (
        db.query(Dataset)
        .filter_by(id=dataset_id, workspace_id=workspace_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return row


def _rows(row: Dataset) -> list[dict]:
    return parse_dataset(
        storage.get_object(row.storage_path), row.format, settings.max_dataset_rows
    )


@router.post("", status_code=201)
async def upload_dataset(
    name: Annotated[str, Form(min_length=1, max_length=255)],
    file: Annotated[UploadFile, File()],
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> DatasetDetail:
    format = Path(file.filename or "").suffix.lower().removeprefix(".")
    if format not in {"csv", "json", "jsonl"}:
        raise HTTPException(status_code=422, detail="File must be CSV, JSON, or JSONL")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Dataset file is too large")
    try:
        rows = parse_dataset(data, format, settings.max_dataset_rows)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    dataset_id = str(uuid.uuid4())
    key = f"datasets/{ws.id}/{dataset_id}.{format}"
    row = Dataset(
        id=dataset_id,
        workspace_id=ws.id,
        name=name,
        format=format,
        row_count=len(rows),
        storage_path=key,
        schema_map={},
    )
    try:
        storage.put_object(key, data)
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        try:
            storage.delete_object(key)
        except Exception:
            pass
        raise
    return DatasetDetail(**_out(row).model_dump(), preview=rows[:5])


@router.get("")
def list_datasets(
    ws: Workspace = Depends(get_workspace), db: Session = Depends(get_db)
) -> list[DatasetOut]:
    rows = (
        db.query(Dataset)
        .filter_by(workspace_id=ws.id)
        .order_by(Dataset.created_at.desc())
        .all()
    )
    return [_out(row) for row in rows]


@router.get("/{dataset_id}")
def get_dataset(
    dataset_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> DatasetDetail:
    row = _get_dataset(dataset_id, ws.id, db)
    return DatasetDetail(**_out(row).model_dump(), preview=_rows(row)[:5])


@router.patch("/{dataset_id}/schema-map")
def update_schema_map(
    dataset_id: str,
    body: SchemaMapIn,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> DatasetOut:
    row = _get_dataset(dataset_id, ws.id, db)
    if not set(body.schema_map).issubset(SCHEMA_FIELDS):
        raise HTTPException(status_code=422, detail="Unknown schema field")
    columns = set().union(*(record.keys() for record in _rows(row)))
    if not set(body.schema_map.values()).issubset(columns):
        raise HTTPException(status_code=422, detail="Mapped column does not exist")
    row.schema_map = body.schema_map
    db.commit()
    return _out(row)


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> Response:
    row = _get_dataset(dataset_id, ws.id, db)
    key = row.storage_path
    event = OutboxEvent(
        kind="delete_object",
        dedupe_key=f"storage:{hashlib.sha256(key.encode()).hexdigest()}",
        payload={"key": key},
    )
    try:
        (
            db.query(GenerationJob)
            .filter_by(workspace_id=ws.id, dataset_id=row.id)
            .update(
                {GenerationJob.dataset_id: None}, synchronize_session=False
            )
        )
        db.add(event)
        db.delete(row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    from app.tasks import dispatch_outbox_event

    try:
        dispatch_outbox_event(event.id)
    except Exception:
        pass
    return Response(status_code=204)
