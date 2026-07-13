import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import storage
from app.config import settings
from app.documents import (
    chunk_text,
    extract_text,
    extract_text_isolated,
    original_storage_key,
    text_storage_key,
)
from app.deps import get_db, get_workspace
from app.models import Document, GenerationJob, OutboxEvent, Workspace

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/documents", tags=["documents"]
)
FORMATS = {"pdf", "docx", "txt", "md", "html"}


class DocumentOut(BaseModel):
    id: str
    filename: str
    format: str
    size_bytes: int
    char_count: int
    chunk_count: int
    created_at: datetime


def _out(row: Document) -> DocumentOut:
    return DocumentOut(
        id=row.id,
        filename=row.filename,
        format=row.format,
        size_bytes=row.size_bytes,
        char_count=row.char_count,
        chunk_count=row.chunk_count,
        created_at=row.created_at,
    )


def _get_document(
    document_id: str, workspace_id: str, db: Session, *, for_update: bool = False
) -> Document:
    query = db.query(Document).filter_by(
        id=document_id, workspace_id=workspace_id
    )
    if for_update:
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


@router.post("", status_code=201)
async def upload_documents(
    files: Annotated[list[UploadFile], File()],
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    if len(files) > settings.max_documents_per_job:
        raise HTTPException(
            status_code=422,
            detail=f"At most {settings.max_documents_per_job} files per upload",
        )
    parsed: list[tuple[str, str, bytes, str, int]] = []
    for file in files:
        filename = file.filename or "document"
        format = Path(filename).suffix.lower().removeprefix(".")
        if format not in FORMATS:
            raise HTTPException(
                status_code=422,
                detail=f"{filename}: file must be PDF, DOCX, TXT, MD, or HTML",
            )
        data = await file.read(settings.max_document_bytes + 1)
        if len(data) > settings.max_document_bytes:
            raise HTTPException(status_code=413, detail=f"{filename}: file is too large")
        try:
            extractor = (
                extract_text_isolated
                if format in {"pdf", "docx", "html"}
                else extract_text
            )
            limits = {
                "max_expanded_bytes": settings.max_document_expanded_bytes,
                "max_pages": settings.max_document_pages,
                "max_chars": settings.max_document_chars,
            }
            if extractor is extract_text_isolated:
                limits.update(
                    timeout_seconds=settings.document_parse_timeout_seconds,
                    max_memory_bytes=settings.document_parse_memory_bytes,
                )
            text = await run_in_threadpool(extractor, data, format, **limits)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{filename}: {exc}") from exc
        chunks = chunk_text(text, settings.generation_chunk_chars)
        if not chunks:
            raise HTTPException(
                status_code=422, detail=f"{filename}: document has too little text"
            )
        parsed.append((filename, format, data, text, len(chunks)))

    rows: list[Document] = []
    written: list[str] = []
    try:
        for filename, format, data, text, chunk_count in parsed:
            document_id = str(uuid.uuid4())
            original_key = original_storage_key(ws.id, document_id, format)
            text_key = text_storage_key(ws.id, document_id)
            written.extend((original_key, text_key))
            storage.put_object(original_key, data)
            storage.put_object(text_key, text.encode("utf-8"))
            row = Document(
                id=document_id,
                workspace_id=ws.id,
                filename=filename,
                format=format,
                size_bytes=len(data),
                storage_path=original_key,
                char_count=len(text),
                chunk_count=chunk_count,
            )
            db.add(row)
            rows.append(row)
        db.commit()
    except Exception:
        db.rollback()
        for key in written:
            try:
                storage.delete_object(key)
            except Exception:
                pass
        raise
    return [_out(row) for row in rows]


@router.get("")
def list_documents(
    ws: Workspace = Depends(get_workspace), db: Session = Depends(get_db)
) -> list[DocumentOut]:
    rows = (
        db.query(Document)
        .filter_by(workspace_id=ws.id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return [_out(row) for row in rows]


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> Response:
    row = _get_document(document_id, ws.id, db, for_update=True)
    active = (
        db.query(GenerationJob)
        .filter(
            GenerationJob.workspace_id == ws.id,
            GenerationJob.status.in_(["pending", "running"]),
            GenerationJob.document_ids.contains([document_id]),
        )
        .first()
    )
    if active is not None:
        raise HTTPException(
            status_code=409, detail="Document is used by an active generation job"
        )
    keys = (row.storage_path, text_storage_key(ws.id, row.id))
    events = [
        OutboxEvent(
            kind="delete_object",
            dedupe_key=f"storage:{hashlib.sha256(key.encode()).hexdigest()}",
            payload={"key": key},
        )
        for key in keys
    ]
    db.add_all(events)
    db.delete(row)
    db.commit()
    from app.tasks import dispatch_outbox_event

    for event in events:
        try:
            dispatch_outbox_event(event.id)
        except Exception:
            pass
    return Response(status_code=204)
