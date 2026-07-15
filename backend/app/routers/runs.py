import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.connections import DiscoveryError, discover_models
from app.deps import get_db, get_workspace
from app.endpoints import EndpointConfig
from app.evals.base import MetricAdapter, ResourceRole, SampleKind
from app.evals.registry import METRICS
from app.evals.snapshots import build_definition_snapshot
from app.models import (
    Dataset,
    OutboxEvent,
    ProviderConnection,
    Run,
    RunResult,
    RunSummary,
    Workspace,
)
from app.security import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/api/workspaces/{workspace_id}/runs", tags=["runs"])
logger = logging.getLogger(__name__)

EMBEDDING_CONNECTION_TYPES = {"openai", "openai_compatible"}


def _available_sample_fields(
    schema_map: dict[str, str], endpoint_config: EndpointConfig | None
) -> set[str]:
    fields = set(schema_map)
    if "contexts" in fields:
        fields.add("retrieval_contexts")
    if endpoint_config is not None:
        response_fields = set(endpoint_config.resolved_response_mappings())
        fields.update(response_fields)
    return fields


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
    config: dict[str, Any] = Field(default_factory=dict)
    threshold: float | None = Field(default=None, ge=0, le=1)
    rubric: str | None = None

    @model_validator(mode="after")
    def merge_legacy_config(self):
        merged = dict(self.config)
        for name in ("threshold", "rubric"):
            legacy_value = getattr(self, name)
            if legacy_value is None:
                continue
            if name in merged and merged[name] != legacy_value:
                raise ValueError(
                    f"Metric config conflict for {name}: nested and legacy values differ"
                )
            merged[name] = legacy_value
        self.config = merged
        return self


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
    judge: JudgeIn | None = None
    endpoint_config: EndpointConfig | None = None


def _run_out(row: Run, summaries: list[RunSummary] | None = None) -> dict:
    return {
        "id": row.id,
        "dataset_id": row.dataset_id,
        "artifact_id": row.artifact_id,
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


def _validate_metric_selection(
    metrics: list[MetricIn], available_fields: set[str]
) -> tuple[
    list[tuple[MetricAdapter, dict[str, Any]]],
    frozenset[ResourceRole],
    SampleKind,
]:
    metric_keys = [item.key for item in metrics]
    if len(metric_keys) != len(set(metric_keys)):
        raise HTTPException(status_code=422, detail="Metrics must be unique")

    selected: list[tuple[MetricAdapter, dict[str, Any]]] = []
    for index, item in enumerate(metrics):
        adapter = METRICS.get(item.key)
        if adapter is None:
            raise HTTPException(status_code=422, detail=f"Unknown metric: {item.key}")
        try:
            config = adapter.validate_config(item.config)
        except ValidationError as exc:
            errors = []
            for error in exc.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            ):
                errors.append(
                    {
                        **error,
                        "loc": ["body", "metrics", index, "config", *error["loc"]],
                    }
                )
            raise HTTPException(status_code=422, detail=errors) from exc
        selected.append((adapter, config))

    sample_kinds = {adapter.sample_kind for adapter, _ in selected}
    if len(sample_kinds) != 1:
        raise HTTPException(
            status_code=422,
            detail="Metrics with different sample kinds need a separate run",
        )
    sample_kind = next(iter(sample_kinds))
    sample_requirements = {
        "agent_trace": {"agent_trace"},
        "conversation": {"turns"},
        "multimodal": {"input", "actual_output"},
    }.get(sample_kind, set())
    missing_sample_fields = sample_requirements - available_fields
    if missing_sample_fields:
        field = sorted(missing_sample_fields)[0]
        raise HTTPException(
            status_code=422,
            detail=f"{sample_kind} samples need a {field} column",
        )

    resource_roles: set[ResourceRole] = set()
    for adapter, config in selected:
        missing = adapter.missing_requirements(config, available_fields)
        if missing:
            field = sorted(missing)[0]
            raise HTTPException(
                status_code=422,
                detail=f"{adapter.display_name} needs a {field} column",
            )
        resource_roles.update(adapter.resources(config))

    return selected, frozenset(resource_roles), sample_kind


@router.post("", status_code=201)
def create_run(
    body: RunIn,
    ws: Workspace = Depends(get_workspace),
    db: Session = Depends(get_db),
) -> dict:
    dataset = (
        db.query(Dataset).filter_by(id=body.dataset_id, workspace_id=ws.id).first()
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
        raise HTTPException(
            status_code=422, detail="Endpoint runs need endpoint_config"
        )

    available_fields = _available_sample_fields(
        dataset.schema_map,
        body.endpoint_config if body.mode == "endpoint" else None,
    )
    selected, resource_roles, _sample_kind = _validate_metric_selection(
        body.metrics, available_fields
    )

    needs_judge = "judge" in resource_roles
    if needs_judge and body.judge is None:
        raise HTTPException(
            status_code=422,
            detail="A judge connection is required for the selected metrics",
        )
    connection = None
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

    # Embeddings use their own connection, chosen only when a metric needs one.
    needs_embedding = "embedding" in resource_roles
    embedding_connection = None
    if needs_embedding:
        assert body.judge is not None
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
            raise HTTPException(
                status_code=422, detail="Embedding connection not found"
            )
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

    judge_config: dict[str, Any] = {}
    if connection is not None:
        assert body.judge is not None
        judge_config = {
            "connection_id": connection.id,
            "connection_name": connection.name,
            "connection_type": connection.connection_type,
            "model": body.judge.model,
            "embedding_connection_id": (
                embedding_connection.id if embedding_connection else None
            ),
            "embedding_connection_name": (
                embedding_connection.name if embedding_connection else None
            ),
            "embedding_connection_type": (
                embedding_connection.connection_type if embedding_connection else None
            ),
            "embedding_model": (
                body.judge.embedding_model if embedding_connection else None
            ),
        }

    row = Run(
        workspace_id=ws.id,
        dataset_id=dataset.id,
        name=body.name,
        mode=body.mode,
        metric_config={
            "metrics": [{"key": adapter.key, **config} for adapter, config in selected]
        },
        endpoint_config=endpoint_config,
        judge_config=judge_config,
        definition_snapshot=build_definition_snapshot(
            dataset=dataset,
            selected=selected,
            judge_connection=connection,
            judge_model=body.judge.model if body.judge is not None else None,
            embedding_connection=embedding_connection,
            embedding_model=(
                body.judge.embedding_model if body.judge is not None else None
            ),
            endpoint_config=body.endpoint_config,
        ),
        status="pending",
        progress_total=dataset.row_count,
    )
    db.add(row)
    db.flush()
    event = OutboxEvent(
        kind="evaluate_run",
        dedupe_key=f"evaluation:{row.id}",
        payload={"run_id": row.id},
    )
    db.add(event)
    db.commit()
    from app.tasks import dispatch_outbox_event

    try:
        dispatch_outbox_event(event.id)
    except Exception:
        logger.exception(
            "Immediate evaluation dispatch failed for run %s; outbox will retry",
            row.id,
        )
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
    summaries = db.query(RunSummary).filter_by(run_id=row.id, workspace_id=ws.id).all()
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
            "details": item.details,
            "usage": item.usage,
            "estimated_cost": item.estimated_cost,
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
