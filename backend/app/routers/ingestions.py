import hashlib
import json
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import storage
from app.deps import get_db, get_workspace
from app.evals.samples import AgentTraceSample
from app.evals.snapshots import build_ingestion_definition_snapshot
from app.models import (
    EvaluationArtifact,
    OutboxEvent,
    ProviderConnection,
    Run,
    Workspace,
)
from app.routers.runs import (
    JudgeIn,
    MetricIn,
    _confirm_custom_model,
    _validate_metric_selection,
)

router = APIRouter(
    prefix="/api/workspaces/{workspace_id}/ingestions",
    tags=["ingestions"],
)
logger = logging.getLogger(__name__)


class AgentTraceIngestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    sample: dict[str, Any]
    metrics: list[MetricIn] = Field(min_length=1)
    judge: JudgeIn | None = None


def _request_hash(body: AgentTraceIngestionIn) -> str:
    encoded = json.dumps(
        body.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _out(artifact: EvaluationArtifact, run: Run) -> dict[str, str]:
    return {
        "artifact_id": artifact.id,
        "run_id": run.id,
        "status": run.status,
    }


def _existing_association(
    db: Session,
    workspace_id: str,
    idempotency_key: str,
    request_hash: str,
) -> tuple[EvaluationArtifact, Run] | None:
    artifact = (
        db.query(EvaluationArtifact)
        .filter_by(workspace_id=workspace_id, idempotency_key=idempotency_key)
        .first()
    )
    if artifact is None:
        return None
    if artifact.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key was already used with a different request",
        )
    run = db.query(Run).filter_by(artifact_id=artifact.id).one()
    return artifact, run


def _sample_or_422(raw: dict[str, Any]) -> AgentTraceSample:
    try:
        return AgentTraceSample.model_validate(raw)
    except ValidationError as exc:
        errors = []
        for error in exc.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        ):
            errors.append(
                {**error, "loc": ["body", "sample", *error["loc"]]}
            )
        raise HTTPException(status_code=422, detail=errors) from exc


def _delete_losing_upload(key: str) -> None:
    try:
        storage.delete_object(key)
    except Exception:
        logger.exception("Failed to clean up ingestion upload %s", key)


@router.post("/agent-traces", status_code=202)
def ingest_agent_trace(
    body: AgentTraceIngestionIn,
    response: Response,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ],
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    request_hash = _request_hash(body)
    existing = _existing_association(db, ws.id, idempotency_key, request_hash)
    if existing is not None:
        response.status_code = 200
        return _out(*existing)

    _sample_or_422(body.sample)
    selected, resource_roles, sample_kind = _validate_metric_selection(
        body.metrics, set(body.sample)
    )
    if sample_kind != "agent_trace":
        raise HTTPException(
            status_code=422,
            detail="Agent trace ingestion only accepts agent_trace metrics",
        )

    needs_judge = "judge" in resource_roles
    if needs_judge and body.judge is None:
        raise HTTPException(
            status_code=422,
            detail="A judge connection is required for the selected metrics",
        )
    connection = None
    judge_config: dict[str, Any] = {}
    if needs_judge:
        assert body.judge is not None
        connection = (
            db.query(ProviderConnection)
            .filter_by(id=body.judge.connection_id, workspace_id=ws.id)
            .first()
        )
        if connection is None:
            raise HTTPException(status_code=422, detail="Provider connection not found")
        _confirm_custom_model(connection, body.judge.model)
        judge_config = {
            "connection_id": connection.id,
            "connection_name": connection.name,
            "connection_type": connection.connection_type,
            "model": body.judge.model,
        }

    artifact_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    storage_path = f"evaluation-artifacts/{ws.id}/{artifact_id}.json"
    raw_sample = json.dumps(
        body.sample,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    artifact = EvaluationArtifact(
        id=artifact_id,
        workspace_id=ws.id,
        sample_kind="agent_trace",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        storage_path=storage_path,
    )
    run = Run(
        id=run_id,
        workspace_id=ws.id,
        dataset_id=None,
        artifact_id=artifact.id,
        name=body.name,
        mode="ingestion",
        metric_config={
            "metrics": [{"key": adapter.key, **config} for adapter, config in selected]
        },
        judge_config=judge_config,
        definition_snapshot=build_ingestion_definition_snapshot(
            artifact_id=artifact.id,
            selected=selected,
            judge_connection=connection,
            judge_model=body.judge.model if body.judge is not None else None,
        ),
        status="pending",
        progress_total=1,
    )
    event = OutboxEvent(
        kind="evaluate_run",
        dedupe_key=f"evaluation:{run.id}",
        payload={"run_id": run.id},
    )

    uploaded = False
    try:
        storage.put_object(storage_path, raw_sample)
        uploaded = True
        db.add_all([artifact, run, event])
        db.commit()
    except IntegrityError:
        db.rollback()
        if uploaded:
            _delete_losing_upload(storage_path)
        winner = _existing_association(db, ws.id, idempotency_key, request_hash)
        if winner is None:
            raise
        response.status_code = 200
        return _out(*winner)
    except Exception:
        db.rollback()
        if uploaded:
            _delete_losing_upload(storage_path)
        raise

    from app.tasks import dispatch_outbox_event

    try:
        dispatch_outbox_event(event.id)
    except Exception:
        logger.exception(
            "Immediate evaluation dispatch failed for run %s; outbox will retry",
            run.id,
        )
    return _out(artifact, run)
