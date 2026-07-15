import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from app import storage
from app.deps import get_db, get_workspace
from app.evals.registry import METRICS
from app.evals.samples import AgentTraceSample, ConversationSample, MultimodalSample
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
MAX_INGESTION_BYTES = 5 * 1024 * 1024
_TOO_LARGE_DETAIL = "Ingestion payload exceeds the 5 MiB limit"
_LIMITED_SUFFIXES = (
    "/ingestions/agent-traces",
    "/ingestions/conversations",
    "/ingestions/multimodal",
)
_KIND_LABELS = {
    "agent_trace": "Agent trace",
    "conversation": "Conversation",
    "multimodal": "Multimodal",
}


class AgentTraceBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].endswith(_LIMITED_SUFFIXES)
        ):
            await self.app(scope, receive, send)
            return

        received = 0
        messages = []
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_INGESTION_BYTES:
                    response = JSONResponse(
                        status_code=413,
                        content={"detail": _TOO_LARGE_DETAIL},
                    )
                    await response(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                break

        async def replay_receive():
            if messages:
                return messages.pop(0)
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)


class IngestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    sample: dict[str, Any]
    metrics: list[MetricIn] = Field(min_length=1)
    judge: JudgeIn | None = None


def _request_hash(body: IngestionIn) -> str:
    encoded = json.dumps(
        body.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _encode_sample(sample: dict[str, Any]) -> bytes:
    encoded = json.dumps(
        sample,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    if len(encoded) > MAX_INGESTION_BYTES:
        raise HTTPException(
            status_code=413,
            detail=_TOO_LARGE_DETAIL,
        )
    return encoded


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


def _validated_sample_or_422(raw: dict[str, Any], model):
    try:
        return model.model_validate(raw)
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


def _sample_or_422(raw: dict[str, Any]) -> AgentTraceSample:
    return _validated_sample_or_422(raw, AgentTraceSample)


def _conversation_or_422(raw: dict[str, Any]) -> ConversationSample:
    return _validated_sample_or_422(raw, ConversationSample)


def _multimodal_or_422(raw: dict[str, Any]) -> MultimodalSample:
    return _validated_sample_or_422(raw, MultimodalSample)


def _delete_losing_upload(key: str) -> None:
    try:
        storage.delete_object(key)
    except Exception:
        logger.exception("Failed to clean up ingestion upload %s", key)


def _ingest_sample(
    *,
    body: IngestionIn,
    response: Response,
    idempotency_key: str,
    ws: Workspace,
    db: Session,
    sample_kind: Literal["agent_trace", "conversation", "multimodal"],
    validate_sample: Callable[[dict[str, Any]], Any],
) -> dict[str, str]:
    raw_sample = _encode_sample(body.sample)
    request_hash = _request_hash(body)
    existing = _existing_association(db, ws.id, idempotency_key, request_hash)
    if existing is not None:
        response.status_code = 200
        return _out(*existing)

    validated_sample = validate_sample(body.sample)
    if sample_kind == "multimodal":
        raw_sample = _encode_sample(validated_sample.model_dump(mode="json"))
        selected_adapters = [METRICS.get(item.key) for item in body.metrics]
        if all(
            adapter is not None and adapter.sample_kind != sample_kind
            for adapter in selected_adapters
        ):
            raise HTTPException(
                status_code=422,
                detail="Multimodal ingestion only accepts multimodal metrics",
            )
    selected, resource_roles, selected_kind = _validate_metric_selection(
        body.metrics, set(body.sample)
    )
    if selected_kind != sample_kind:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{_KIND_LABELS[sample_kind]} ingestion only accepts "
                f"{sample_kind} metrics"
            ),
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
    artifact = EvaluationArtifact(
        id=artifact_id,
        workspace_id=ws.id,
        sample_kind=sample_kind,
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
            sample_kind=sample_kind,
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


@router.post("/agent-traces", status_code=202)
def ingest_agent_trace(
    body: IngestionIn,
    response: Response,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ],
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    return _ingest_sample(
        body=body,
        response=response,
        idempotency_key=idempotency_key,
        ws=ws,
        db=db,
        sample_kind="agent_trace",
        validate_sample=_sample_or_422,
    )


@router.post("/conversations", status_code=202)
def ingest_conversation(
    body: IngestionIn,
    response: Response,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ],
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    return _ingest_sample(
        body=body,
        response=response,
        idempotency_key=idempotency_key,
        ws=ws,
        db=db,
        sample_kind="conversation",
        validate_sample=_conversation_or_422,
    )


@router.post("/multimodal", status_code=202)
def ingest_multimodal(
    body: IngestionIn,
    response: Response,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ],
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    return _ingest_sample(
        body=body,
        response=response,
        idempotency_key=idempotency_key,
        ws=ws,
        db=db,
        sample_kind="multimodal",
        validate_sample=_multimodal_or_422,
    )
