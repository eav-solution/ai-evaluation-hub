from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.connections import DiscoveryError, discover_models
from app.deps import get_db, get_workspace
from app.endpoints import EndpointConfig
from app.evals.registry import EMBEDDING_METRICS, METRICS
from app.models import (
    Dataset,
    ProviderConnection,
    Run,
    RunResult,
    RunSummary,
    Workspace,
)
from app.security import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/api/workspaces/{workspace_id}/runs", tags=["runs"])

EMBEDDING_CONNECTION_TYPES = {"openai", "openai_compatible"}


def _confirm_custom_model(connection: ProviderConnection, model: str) -> None:
    """For a custom connection, confirm the model is present in its live /models."""
    if connection.connection_type != "openai_compatible":
        return
    api_key = (
        decrypt_secret(connection.encrypted_key) if connection.encrypted_key else None
    )
    try:
        models = discover_models(connection.base_url, api_key)
    except DiscoveryError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    if model not in models:
        raise HTTPException(
            status_code=422,
            detail="The selected model is not available on this connection",
        )


class MetricIn(BaseModel):
    key: str
    threshold: float | None = Field(default=None, ge=0, le=1)
    rubric: str | None = None


class JudgeIn(BaseModel):
    connection_id: str = Field(min_length=1)
    model: str = Field(min_length=1, max_length=255)
    embedding_connection_id: str | None = Field(default=None)
    embedding_model: str | None = Field(default=None, max_length=255)


class RunIn(BaseModel):
    dataset_id: str
    name: str = Field(min_length=1, max_length=255)
    mode: Literal["static", "endpoint"]
    metrics: list[MetricIn] = Field(min_length=1)
    judge: JudgeIn
    endpoint_config: EndpointConfig | None = None


def _run_out(row: Run, summaries: list[RunSummary] | None = None) -> dict:
    return {
        "id": row.id,
        "dataset_id": row.dataset_id,
        "name": row.name,
        "mode": row.mode,
        "metric_config": row.metric_config,
        "judge_config": row.judge_config,
        "status": row.status,
        "progress_done": row.progress_done,
        "progress_total": row.progress_total,
        "error": row.error,
        "created_at": row.created_at,
        "finished_at": row.finished_at,
        "summaries": [
            {
                "metric_key": item.metric_key,
                "mean": item.mean,
                "min": item.min,
                "max": item.max,
                "p50": item.p50,
                "pass_rate": item.pass_rate,
                "threshold": item.threshold,
            }
            for item in summaries or []
        ],
    }


def _get_run(run_id: str, workspace_id: str, db: Session) -> Run:
    row = db.query(Run).filter_by(id=run_id, workspace_id=workspace_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


def _enqueue(run_id: str) -> None:
    from app.tasks import evaluate_run

    evaluate_run.delay(run_id)


@router.post("", status_code=201)
def create_run(
    body: RunIn,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict:
    dataset = (
        db.query(Dataset)
        .filter_by(id=body.dataset_id, workspace_id=ws.id)
        .first()
    )
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if "input" not in dataset.schema_map:
        raise HTTPException(
            status_code=422,
            detail="Runs need an input column mapping",
        )
    if body.mode == "static" and "actual_output" not in dataset.schema_map:
        raise HTTPException(
            status_code=422,
            detail="Static runs need an actual_output column mapping",
        )
    if body.mode == "endpoint" and body.endpoint_config is None:
        raise HTTPException(status_code=422, detail="Endpoint runs need endpoint_config")

    metric_keys = [item.key for item in body.metrics]
    if len(metric_keys) != len(set(metric_keys)):
        raise HTTPException(status_code=422, detail="Metrics must be unique")
    for item in body.metrics:
        adapter = METRICS.get(item.key)
        if adapter is None:
            raise HTTPException(status_code=422, detail=f"Unknown metric: {item.key}")
        missing = adapter.requires - dataset.schema_map.keys()
        if missing:
            field = sorted(missing)[0]
            raise HTTPException(
                status_code=422,
                detail=f"{adapter.display_name} needs a {field} column",
            )

    connection = (
        db.query(ProviderConnection)
        .filter_by(id=body.judge.connection_id, workspace_id=ws.id)
        .first()
    )
    if connection is None:
        raise HTTPException(
            status_code=422, detail="Provider connection not found"
        )
    _confirm_custom_model(connection, body.judge.model)

    # Embeddings use their own connection, chosen only when a metric needs one.
    needs_embedding = bool(set(metric_keys) & EMBEDDING_METRICS)
    embedding_connection = None
    if needs_embedding:
        if not body.judge.embedding_connection_id or not body.judge.embedding_model:
            raise HTTPException(
                status_code=422,
                detail="An embedding connection and model are required for the selected metrics",
            )
        embedding_connection = (
            db.query(ProviderConnection)
            .filter_by(id=body.judge.embedding_connection_id, workspace_id=ws.id)
            .first()
        )
        if embedding_connection is None:
            raise HTTPException(status_code=422, detail="Embedding connection not found")
        if embedding_connection.connection_type not in EMBEDDING_CONNECTION_TYPES:
            raise HTTPException(
                status_code=422,
                detail="The embedding connection must be OpenAI or OpenAI-compatible",
            )
        _confirm_custom_model(embedding_connection, body.judge.embedding_model)

    endpoint_config = None
    if body.endpoint_config is not None:
        endpoint_config = body.endpoint_config.model_dump()
        endpoint_config["headers"] = {
            key: encrypt_secret(value)
            for key, value in endpoint_config["headers"].items()
        }

    row = Run(
        workspace_id=ws.id,
        dataset_id=dataset.id,
        name=body.name,
        mode=body.mode,
        metric_config={"metrics": [item.model_dump() for item in body.metrics]},
        endpoint_config=endpoint_config,
        judge_config={
            "connection_id": connection.id,
            "connection_name": connection.name,
            "connection_type": connection.connection_type,
            "model": body.judge.model,
            "embedding_connection_id": embedding_connection.id if embedding_connection else None,
            "embedding_connection_name": embedding_connection.name if embedding_connection else None,
            "embedding_connection_type": (
                embedding_connection.connection_type if embedding_connection else None
            ),
            "embedding_model": body.judge.embedding_model if embedding_connection else None,
        },
        status="pending",
        progress_total=dataset.row_count,
    )
    db.add(row)
    db.commit()
    _enqueue(row.id)
    return _run_out(row)


@router.get("")
def list_runs(
    ws: Workspace = Depends(get_workspace), db: Session = Depends(get_db)
) -> list[dict]:
    rows = (
        db.query(Run)
        .filter_by(workspace_id=ws.id)
        .order_by(Run.created_at.desc())
        .all()
    )
    return [_run_out(row) for row in rows]


@router.get("/{run_id}")
def get_run(
    run_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_run(run_id, ws.id, db)
    summaries = (
        db.query(RunSummary)
        .filter_by(run_id=row.id, workspace_id=ws.id)
        .all()
    )
    return _run_out(row, summaries)


@router.get("/{run_id}/results")
def list_results(
    run_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> list[dict]:
    row = _get_run(run_id, ws.id, db)
    results = (
        db.query(RunResult)
        .filter_by(run_id=row.id, workspace_id=ws.id)
        .order_by(RunResult.row_index)
        .all()
    )
    return [
        {
            "id": item.id,
            "row_index": item.row_index,
            "input": item.input,
            "expected": item.expected,
            "actual": item.actual,
            "contexts": item.contexts,
            "scores": item.scores,
            "error": item.error,
            "latency_ms": item.latency_ms,
        }
        for item in results
    ]


@router.post("/{run_id}/cancel")
def cancel_run(
    run_id: str,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict:
    row = _get_run(run_id, ws.id, db)
    if row.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Run is already finished")
    row.status = "cancelled"
    row.finished_at = datetime.now(timezone.utc)
    db.commit()
    return _run_out(row)
