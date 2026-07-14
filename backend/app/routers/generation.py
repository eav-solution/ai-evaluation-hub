import csv
import io
import json
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.connections import DiscoveryError, discover_models
from app.deps import get_db, get_workspace
from app.models import (
    Document,
    GenerationJob,
    GenerationRecord,
    OutboxEvent,
    ProviderConnection,
    Workspace,
)
from app.security import decrypt_secret

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/generation-jobs", tags=["generation"]
)
PAGE_SIZE = 50


class GeneratorIn(BaseModel):
    connection_id: str = Field(min_length=1)
    model: str = Field(min_length=1, max_length=255)


class OptionsIn(BaseModel):
    questions_per_chunk: int = Field(default=3, ge=1, le=5)
    language: str | None = Field(default=None, min_length=1, max_length=50)


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    document_ids: list[str] = Field(min_length=1)
    mode: Literal["chunk", "document"]
    requested_count: int = Field(ge=1)
    generator: GeneratorIn
    options: OptionsIn = OptionsIn()


class RecordPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = None
    answer: str | None = None
    contexts: list[str] | None = None
    deleted: bool | None = None


def _job_out(row: GenerationJob) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "document_ids": row.document_ids,
        "mode": row.mode,
        "requested_count": row.requested_count,
        "max_count": row.max_count,
        "generator_config": row.generator_config,
        "options": row.options,
        "status": row.status,
        "progress_done": row.progress_done,
        "progress_total": row.progress_total,
        "generated_count": row.generated_count,
        "error": row.error,
        "unit_errors": row.unit_errors,
        "dataset_id": row.dataset_id,
        "dataset_created": row.dataset_created,
        "created_at": row.created_at,
        "finished_at": row.finished_at,
    }


def _get_job(
    job_id: str, workspace_id: str, db: Session, *, for_update: bool = False
) -> GenerationJob:
    query = db.query(GenerationJob).filter_by(id=job_id, workspace_id=workspace_id)
    if for_update:
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Generation job not found")
    return row


def _record_out(row: GenerationRecord) -> dict:
    return {
        "id": row.id,
        "record_index": row.record_index,
        "question": row.question,
        "answer": row.answer,
        "contexts": row.contexts,
        "source": row.source,
        "deleted": row.deleted,
    }


@router.post("", status_code=201)
def create_job(
    body: JobIn,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict:
    document_ids = list(dict.fromkeys(body.document_ids))
    if len(document_ids) > settings.max_documents_per_job:
        raise HTTPException(
            status_code=422,
            detail=f"At most {settings.max_documents_per_job} documents per job",
        )
    documents = (
        db.query(Document)
        .filter(Document.workspace_id == ws.id, Document.id.in_(document_ids))
        .with_for_update()
        .all()
    )
    if len(documents) != len(document_ids):
        raise HTTPException(status_code=404, detail="Document not found")
    connection = (
        db.query(ProviderConnection)
        .filter_by(id=body.generator.connection_id, workspace_id=ws.id)
        .first()
    )
    if connection is None:
        raise HTTPException(
            status_code=422, detail="Provider connection not found"
        )
    if connection.connection_type == "openai_compatible":
        api_key = (
            decrypt_secret(connection.encrypted_key)
            if connection.encrypted_key
            else None
        )
        try:
            models = discover_models(connection.base_url, api_key)
        except DiscoveryError as exc:
            raise HTTPException(status_code=422, detail=exc.message) from exc
        if body.generator.model not in models:
            raise HTTPException(
                status_code=422,
                detail="The selected model is not available on this connection",
            )
    max_count = min(
        sum(document.chunk_count for document in documents)
        * body.options.questions_per_chunk,
        settings.max_dataset_rows,
    )
    row = GenerationJob(
        workspace_id=ws.id,
        name=body.name,
        document_ids=document_ids,
        mode=body.mode,
        requested_count=min(body.requested_count, max_count),
        max_count=max_count,
        generator_config={
            "connection_id": connection.id,
            "connection_name": connection.name,
            "connection_type": connection.connection_type,
            "model": body.generator.model,
        },
        options=body.options.model_dump(),
        status="pending",
    )
    db.add(row)
    db.flush()
    event = OutboxEvent(
        kind="generate_dataset",
        dedupe_key=f"generation:{row.id}",
        payload={"job_id": row.id},
    )
    db.add(event)
    db.commit()
    from app.tasks import dispatch_outbox_event

    try:
        dispatch_outbox_event(event.id)
    except Exception:
        pass
    return _job_out(row)


@router.get("")
def list_jobs(
    ws: Workspace = Depends(get_workspace), db: Session = Depends(get_db)
) -> list[dict]:
    rows = (
        db.query(GenerationJob)
        .filter_by(workspace_id=ws.id)
        .order_by(GenerationJob.created_at.desc())
        .all()
    )
    return [_job_out(row) for row in rows]


@router.get("/{job_id}")
def get_job(
    job_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict:
    return _job_out(_get_job(job_id, ws.id, db))


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_job(job_id, ws.id, db)
    if row.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Generation job is already finished")
    row.status = "cancelled"
    row.finished_at = datetime.now(timezone.utc)
    db.commit()
    return _job_out(row)


@router.delete("/{job_id}", status_code=204)
def delete_job(
    job_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> None:
    job = _get_job(job_id, ws.id, db, for_update=True)
    if job.status not in {"completed", "failed", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail="Cancel the active generation job before deleting it",
        )
    db.query(GenerationRecord).filter_by(
        job_id=job.id, workspace_id=ws.id
    ).delete()
    db.query(OutboxEvent).filter_by(
        kind="generate_dataset", dedupe_key=f"generation:{job.id}"
    ).delete()
    db.delete(job)
    db.commit()


@router.get("/{job_id}/records")
def list_records(
    job_id: str,
    page: int = Query(default=1, ge=1),
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict:
    job = _get_job(job_id, ws.id, db)
    query = db.query(GenerationRecord).filter_by(
        job_id=job.id, workspace_id=ws.id
    )
    total = query.count()
    records = (
        query.order_by(GenerationRecord.record_index)
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )
    return {
        "records": [_record_out(row) for row in records],
        "page": page,
        "page_size": PAGE_SIZE,
        "total": total,
    }


@router.patch("/{job_id}/records/{record_id}")
def update_record(
    job_id: str,
    record_id: str,
    body: RecordPatch,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict:
    job = _get_job(job_id, ws.id, db, for_update=True)
    if job.status != "completed" or job.dataset_created:
        raise HTTPException(
            status_code=409,
            detail="Records can only be edited for a completed unsaved job",
        )
    record = (
        db.query(GenerationRecord)
        .filter_by(id=record_id, job_id=job.id, workspace_id=ws.id)
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    if body.question is not None:
        if not body.question.strip():
            raise HTTPException(status_code=422, detail="question cannot be empty")
        record.question = body.question.strip()
    if body.answer is not None:
        if not body.answer.strip():
            raise HTTPException(status_code=422, detail="answer cannot be empty")
        record.answer = body.answer.strip()
    if body.contexts is not None:
        cleaned = [item.strip() for item in body.contexts if item.strip()]
        if not cleaned:
            raise HTTPException(status_code=422, detail="contexts cannot be empty")
        record.contexts = cleaned
    if body.deleted is not None:
        record.deleted = body.deleted
    db.commit()
    return _record_out(record)


def _safe_filename(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return slug or "generation-job"


@router.get("/{job_id}/records.csv")
def download_records_csv(
    job_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> Response:
    job = _get_job(job_id, ws.id, db)
    if job.status != "completed":
        raise HTTPException(status_code=409, detail="Generation job is not completed")
    records = (
        db.query(GenerationRecord)
        .filter_by(job_id=job.id, workspace_id=ws.id, deleted=False)
        .order_by(GenerationRecord.record_index)
        .all()
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["question", "answer", "contexts"])
    for record in records:
        writer.writerow(
            [
                record.question,
                record.answer,
                json.dumps(record.contexts, ensure_ascii=False),
            ]
        )
    filename = _safe_filename(job.name)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )
