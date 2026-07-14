import json
import time
from datetime import datetime, timedelta, timezone
from statistics import fmean, median

from app import generation, storage
from app.celery_app import celery_app
from app.config import settings
from app.datasets import parse_dataset
from app.db import SessionLocal
from app.documents import text_storage_key
from app.endpoints import call_endpoint
from app.evals.base import EvalRow, JudgeConfig
from app.evals.registry import METRICS
from app.models import (
    Dataset,
    Document,
    GenerationJob,
    GenerationRecord,
    OutboxEvent,
    Run,
    RunResult,
    RunSummary,
)
from app.connections import resolve_connection


def dispatch_outbox_event(event_id: str) -> bool:
    db = SessionLocal()
    try:
        event = (
            db.query(OutboxEvent)
            .filter_by(id=event_id)
            .with_for_update(skip_locked=True)
            .one_or_none()
        )
        if event is None:
            db.rollback()
            return True
        try:
            if event.kind == "generate_dataset":
                generate_dataset.apply_async(
                    args=[event.payload["job_id"]],
                    task_id=f"generation-{event.id}",
                )
            elif event.kind == "evaluate_run":
                evaluate_run.apply_async(
                    args=[event.payload["run_id"]],
                    task_id=f"evaluation-{event.id}",
                )
            elif event.kind == "delete_object":
                storage.delete_object(event.payload["key"])
            else:
                raise ValueError(f"Unknown outbox event kind: {event.kind}")
        except Exception as exc:
            if event.kind == "delete_object" and isinstance(exc, KeyError):
                db.delete(event)
                db.commit()
                return True
            event.attempts += 1
            event.error = str(exc)
            retry_seconds = min(30 * (2 ** (event.attempts - 1)), 3600)
            event.next_attempt_at = datetime.now(timezone.utc) + timedelta(
                seconds=retry_seconds
            )
            event.created_at = datetime.now(timezone.utc)
            db.commit()
            return False
        db.delete(event)
        db.commit()
        return True
    finally:
        db.close()


@celery_app.task(name="app.tasks.dispatch_outbox_events")
def dispatch_outbox_events(limit: int = 100) -> None:
    db = SessionLocal()
    try:
        event_ids = [
            row[0]
            for row in db.query(OutboxEvent.id)
            .filter(OutboxEvent.next_attempt_at <= datetime.now(timezone.utc))
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .all()
        ]
    finally:
        db.close()
    for event_id in event_ids:
        dispatch_outbox_event(event_id)


def _text(value) -> str | None:
    return None if value is None else str(value)


def _contexts(value) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
    return [str(value)]


_MISSING = object()


def _eval_row(
    source: dict,
    mapping: dict,
    actual_output=_MISSING,
) -> EvalRow:
    input_value = source.get(mapping["input"])
    actual = (
        source.get(mapping["actual_output"])
        if actual_output is _MISSING
        else actual_output
    )
    if input_value is None or actual is None:
        raise ValueError("Mapped input or actual_output value is missing")
    return EvalRow(
        input=str(input_value),
        actual_output=str(actual),
        expected_output=_text(source.get(mapping.get("expected_output"))),
        retrieval_contexts=_contexts(source.get(mapping.get("contexts"))),
    )


def _run_schema_map(run: Run, dataset: Dataset) -> dict[str, str]:
    mapping = (run.definition_snapshot or {}).get("schema_map")
    return (
        dict(mapping)
        if isinstance(mapping, dict) and mapping
        else dict(dataset.schema_map)
    )


def _run_dataset_source(run: Run, dataset: Dataset) -> tuple[str, str]:
    snapshot = (run.definition_snapshot or {}).get("dataset")
    if isinstance(snapshot, dict):
        storage_path = snapshot.get("storage_path")
        dataset_format = snapshot.get("format")
        if isinstance(storage_path, str) and isinstance(dataset_format, str):
            return storage_path, dataset_format
    return dataset.storage_path, dataset.format


def _summarize(db, run: Run, results: list[RunResult]) -> None:
    for config in run.metric_config["metrics"]:
        values = [
            result.scores[config["key"]]["score"]
            for result in results
            if result.scores.get(config["key"], {}).get("score") is not None
        ]
        if not values:
            continue
        passed = [
            result.scores[config["key"]]["passed"]
            for result in results
            if result.scores.get(config["key"], {}).get("passed") is not None
        ]
        db.add(
            RunSummary(
                workspace_id=run.workspace_id,
                run_id=run.id,
                metric_key=config["key"],
                mean=fmean(values),
                min=min(values),
                max=max(values),
                p50=median(values),
                pass_rate=fmean(passed) if passed else None,
                threshold=config.get("threshold"),
            )
        )


def _claim_run(db, run_id: str) -> tuple[Run, int] | None:
    now = datetime.now(timezone.utc)
    claimed = (
        db.query(Run)
        .filter_by(id=run_id, status="pending")
        .update(
            {
                Run.status: "running",
                Run.error: None,
                Run.attempt: Run.attempt + 1,
                Run.heartbeat_at: now,
                Run.finished_at: None,
            },
            synchronize_session=False,
        )
    )
    if claimed != 1:
        db.rollback()
        return None
    db.commit()
    run = db.get(Run, run_id)
    return run, run.attempt


def _finish_run(db, run_id: str, attempt: int, values: dict) -> bool:
    updated = (
        db.query(Run)
        .filter_by(id=run_id, status="running", attempt=attempt)
        .update(values, synchronize_session=False)
    )
    db.commit()
    return updated == 1


_INTERRUPTED_ENDPOINT = "Endpoint request interrupted before its result was persisted"
_INTERRUPTED_METRIC = "Evaluation interrupted before its result was persisted"


def _result_complete(result: RunResult, metric_keys: list[str]) -> bool:
    if result.error is not None:
        return True
    scores = result.scores or {}
    return all(
        key in scores and not scores[key].get("in_progress", False)
        for key in metric_keys
    )


def _stored_row(result: RunResult) -> EvalRow:
    return EvalRow(
        input=result.input,
        actual_output=result.actual or "",
        expected_output=result.expected,
        retrieval_contexts=result.contexts,
    )


@celery_app.task(name="app.tasks.evaluate_run")
def evaluate_run(run_id: str) -> None:
    db = SessionLocal()
    claimed = _claim_run(db, run_id)
    if claimed is None:
        db.close()
        return
    run, attempt = claimed
    try:
        dataset = db.get(Dataset, run.dataset_id)
        if dataset is None:
            raise ValueError("Dataset not found")
        schema_map = _run_schema_map(run, dataset)
        runtime = resolve_connection(db, run.workspace_id, run.judge_config)
        embedding_connection_id = run.judge_config.get("embedding_connection_id")
        if embedding_connection_id:
            embedding_runtime = resolve_connection(
                db, run.workspace_id, {"connection_id": embedding_connection_id}
            )
        else:
            # Legacy/unspecified snapshots: embeddings share the judge connection.
            embedding_runtime = runtime
        judge = JudgeConfig(
            provider=runtime.connection_type,
            model=run.judge_config["model"],
            api_key=runtime.api_key,
            base_url=runtime.base_url,
            embedding_model=run.judge_config.get("embedding_model"),
            embedding_provider=embedding_runtime.connection_type,
            embedding_base_url=embedding_runtime.base_url,
            embedding_api_key=embedding_runtime.api_key,
        )
        storage_path, dataset_format = _run_dataset_source(run, dataset)
        source_rows = parse_dataset(
            storage.get_object(storage_path),
            dataset_format,
            settings.max_dataset_rows,
        )
        metric_configs = run.metric_config["metrics"]
        metric_keys = [config["key"] for config in metric_configs]
        stored_results = {
            result.row_index: result
            for result in db.query(RunResult).filter_by(run_id=run.id).all()
        }
        run.progress_total = len(source_rows)
        run.progress_done = sum(
            _result_complete(result, metric_keys) for result in stored_results.values()
        )
        run.heartbeat_at = datetime.now(timezone.utc)
        db.commit()

        for offset in range(0, len(source_rows), settings.eval_batch_size):
            batch = source_rows[offset : offset + settings.eval_batch_size]
            for index, source in enumerate(batch, start=offset):
                db.refresh(run)
                if run.status != "running" or run.attempt != attempt:
                    return
                started = time.perf_counter()
                row = None
                result = stored_results.get(index)
                if result is None:
                    try:
                        row = _eval_row(
                            source,
                            schema_map,
                            "" if run.mode == "endpoint" else _MISSING,
                        )
                    except Exception as exc:
                        result = RunResult(
                            workspace_id=run.workspace_id,
                            run_id=run.id,
                            row_index=index,
                            input=_text(source.get(schema_map.get("input"))) or "",
                            expected=None,
                            actual=None,
                            contexts=None,
                            scores={},
                            error=str(exc),
                            latency_ms=round((time.perf_counter() - started) * 1000),
                        )
                        db.add(result)
                        db.commit()
                    else:
                        result = RunResult(
                            workspace_id=run.workspace_id,
                            run_id=run.id,
                            row_index=index,
                            input=row.input,
                            expected=row.expected_output,
                            actual=(
                                None if run.mode == "endpoint" else row.actual_output
                            ),
                            contexts=row.contexts,
                            scores={},
                            error=(
                                _INTERRUPTED_ENDPOINT
                                if run.mode == "endpoint"
                                else None
                            ),
                            latency_ms=None,
                        )
                        db.add(result)
                        run.heartbeat_at = datetime.now(timezone.utc)
                        db.commit()
                        if run.mode == "endpoint":
                            try:
                                if run.endpoint_config is None:
                                    raise ValueError(
                                        "Endpoint configuration is missing"
                                    )
                                answer, _payload, endpoint_latency = call_endpoint(
                                    run.endpoint_config,
                                    row,
                                    encrypted_headers=True,
                                )
                            except Exception as exc:
                                result.error = str(exc)
                                result.latency_ms = round(
                                    (time.perf_counter() - started) * 1000
                                )
                                db.commit()
                            else:
                                db.refresh(run)
                                if run.status != "running" or run.attempt != attempt:
                                    return
                                result.actual = answer
                                result.error = None
                                result.latency_ms = round(endpoint_latency)
                                row = EvalRow(
                                    input=row.input,
                                    actual_output=answer,
                                    expected_output=row.expected_output,
                                    retrieval_contexts=row.contexts,
                                )
                                db.commit()
                        else:
                            result.latency_ms = round(
                                (time.perf_counter() - started) * 1000
                            )
                            db.commit()
                    stored_results[index] = result
                elif result.error is None:
                    row = _stored_row(result)

                if result.error is None and row is not None:
                    for config in metric_configs:
                        metric_key = config["key"]
                        scores = dict(result.scores or {})
                        existing = scores.get(metric_key)
                        if existing is not None:
                            if existing.get("in_progress", False):
                                scores[metric_key] = {
                                    **existing,
                                    "error": _INTERRUPTED_METRIC,
                                    "in_progress": False,
                                }
                                result.scores = scores
                                db.commit()
                            continue

                        db.refresh(run)
                        if run.status != "running" or run.attempt != attempt:
                            return
                        scores[metric_key] = {
                            "score": None,
                            "reason": None,
                            "passed": None,
                            "error": _INTERRUPTED_METRIC,
                            "in_progress": True,
                        }
                        result.scores = scores
                        run.heartbeat_at = datetime.now(timezone.utc)
                        db.commit()
                        try:
                            score = METRICS[metric_key].score(row, judge, config)
                            terminal = {
                                "score": score.score,
                                "reason": score.reason,
                                "passed": score.passed,
                                "error": None,
                                "in_progress": False,
                            }
                        except Exception as exc:
                            terminal = {
                                "score": None,
                                "reason": None,
                                "passed": None,
                                "error": str(exc),
                                "in_progress": False,
                            }
                        db.refresh(run)
                        if run.status != "running" or run.attempt != attempt:
                            return
                        scores = dict(result.scores or {})
                        scores[metric_key] = terminal
                        result.scores = scores
                        run.heartbeat_at = datetime.now(timezone.utc)
                        db.commit()

                    scores = result.scores or {}
                    result.error = (
                        "All metrics failed"
                        if all(
                            scores.get(key, {}).get("score") is None
                            for key in metric_keys
                        )
                        else None
                    )
                    db.commit()

                run.progress_done = sum(
                    _result_complete(item, metric_keys)
                    for item in stored_results.values()
                )
                run.heartbeat_at = datetime.now(timezone.utc)
                db.commit()

        db.query(RunSummary).filter_by(run_id=run.id).delete()
        results = db.query(RunResult).filter_by(run_id=run.id).all()
        _summarize(db, run, results)
        failed_rows = sum(result.error is not None for result in results)
        status = "failed" if failed_rows == len(results) else "completed"
        _finish_run(
            db,
            run.id,
            attempt,
            {
                Run.status: status,
                Run.error: "All rows failed" if status == "failed" else None,
                Run.finished_at: datetime.now(timezone.utc),
                Run.heartbeat_at: None,
            },
        )
    except Exception as exc:
        db.rollback()
        _finish_run(
            db,
            run_id,
            attempt,
            {
                Run.status: "failed",
                Run.error: str(exc),
                Run.finished_at: datetime.now(timezone.utc),
                Run.heartbeat_at: None,
            },
        )
    finally:
        db.close()


@celery_app.task(name="app.tasks.recover_stale_evaluation_runs")
def recover_stale_evaluation_runs() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.evaluation_lease_seconds
    )
    db = SessionLocal()
    event_ids: list[str] = []
    try:
        candidate_ids = [
            row[0]
            for row in db.query(Run.id)
            .filter(
                Run.status == "running",
                (Run.heartbeat_at.is_(None)) | (Run.heartbeat_at < cutoff),
            )
            .all()
        ]
        for run_id in candidate_ids:
            dedupe_key = f"evaluation:{run_id}"
            event = (
                db.query(OutboxEvent)
                .filter_by(dedupe_key=dedupe_key)
                .with_for_update()
                .one_or_none()
            )
            run = (
                db.query(Run)
                .filter_by(id=run_id, status="running")
                .with_for_update(skip_locked=True)
                .populate_existing()
                .one_or_none()
            )
            if run is None or (
                run.heartbeat_at is not None and run.heartbeat_at >= cutoff
            ):
                db.rollback()
                continue
            run.status = "pending"
            run.heartbeat_at = None
            if event is None:
                event = OutboxEvent(
                    kind="evaluate_run",
                    dedupe_key=dedupe_key,
                    payload={"run_id": run.id},
                )
                db.add(event)
            db.flush()
            event_ids.append(event.id)
            db.commit()
    finally:
        db.close()
    for event_id in event_ids:
        dispatch_outbox_event(event_id)


@celery_app.task(name="app.tasks.generate_dataset")
def generate_dataset(job_id: str) -> None:
    db = SessionLocal()
    attempt: int | None = None
    try:
        now = datetime.now(timezone.utc)
        claimed = (
            db.query(GenerationJob)
            .filter_by(id=job_id, status="pending")
            .update(
                {
                    GenerationJob.status: "running",
                    GenerationJob.error: None,
                    GenerationJob.unit_errors: [],
                    GenerationJob.generated_count: 0,
                    GenerationJob.progress_done: 0,
                    GenerationJob.progress_total: 0,
                    GenerationJob.attempt: GenerationJob.attempt + 1,
                    GenerationJob.heartbeat_at: now,
                    GenerationJob.finished_at: None,
                },
                synchronize_session=False,
            )
        )
        if claimed != 1:
            db.rollback()
            return
        db.query(GenerationRecord).filter_by(job_id=job_id).delete()
        db.commit()
        job = db.get(GenerationJob, job_id)
        attempt = job.attempt

        runtime = resolve_connection(db, job.workspace_id, job.generator_config)
        config = generation.GeneratorConfig(
            provider=runtime.connection_type,
            model=job.generator_config["model"],
            api_key=runtime.api_key,
            base_url=runtime.base_url,
        )

        documents: list[tuple[str, str]] = []
        for document_id in job.document_ids:
            document = (
                db.query(Document)
                .filter_by(id=document_id, workspace_id=job.workspace_id)
                .first()
            )
            if document is None:
                raise ValueError("Document not found")
            text = storage.get_object(
                text_storage_key(job.workspace_id, document.id)
            ).decode("utf-8")
            documents.append((document.id, text))

        options = job.options or {}
        units = generation.build_units(
            documents,
            job.mode,
            job.requested_count,
            chunk_chars=settings.generation_chunk_chars,
            context_chars=settings.generation_context_chars,
            questions_per_chunk=options.get("questions_per_chunk", 3),
        )
        if not units:
            raise ValueError("Documents contain no usable text")
        job = (
            db.query(GenerationJob)
            .filter_by(id=job_id, status="running", attempt=attempt)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        if job is None:
            db.rollback()
            return
        job.progress_total = len(units)
        job.heartbeat_at = datetime.now(timezone.utc)
        db.commit()

        seen: set[str] = set()
        unit_errors: list[dict] = []
        next_index = 0
        for unit_number, unit in enumerate(units):
            db.refresh(job)
            if job.status != "running" or job.attempt != attempt:
                return
            items = None
            unit_error = None
            try:
                items = generation.generate_qa(
                    unit.text, unit.quota, config, options.get("language")
                )
            except Exception as exc:
                unit_error = str(exc)
            job = (
                db.query(GenerationJob)
                .filter_by(id=job_id, status="running", attempt=attempt)
                .with_for_update()
                .populate_existing()
                .one_or_none()
            )
            if job is None:
                db.rollback()
                return
            if unit_error is not None:
                unit_errors.append({"unit": unit_number, "error": unit_error})
            else:
                usable_items = items[: unit.quota]
                if job.mode == "document":
                    usable_items = [
                        item for item in usable_items if item.context.strip()
                    ]
                if not usable_items:
                    message = (
                        "No generated records had supporting context"
                        if job.mode == "document"
                        else "No records were generated"
                    )
                    unit_errors.append({"unit": unit_number, "error": message})
                for item in usable_items:
                    key = generation.normalize_question(item.question)
                    if key in seen:
                        continue
                    seen.add(key)
                    if job.mode == "chunk":
                        contexts = [unit.text]
                    else:
                        contexts = [item.context]
                    db.add(
                        GenerationRecord(
                            workspace_id=job.workspace_id,
                            job_id=job.id,
                            record_index=next_index,
                            question=item.question,
                            answer=item.answer,
                            contexts=contexts,
                            source={
                                "document_id": unit.document_id,
                                "chunk_index": unit.chunk_index,
                            },
                        )
                    )
                    next_index += 1
            job.unit_errors = list(unit_errors)
            job.progress_done = unit_number + 1
            job.generated_count = next_index
            job.heartbeat_at = datetime.now(timezone.utc)
            db.commit()

        if len(unit_errors) == len(units):
            raise ValueError("All generation units failed")
        (
            db.query(GenerationJob)
            .filter_by(id=job_id, status="running", attempt=attempt)
            .update(
                {
                    GenerationJob.status: "completed",
                    GenerationJob.finished_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        (
            db.query(GenerationJob)
            .filter_by(id=job_id, status="running", attempt=attempt)
            .update(
                {
                    GenerationJob.status: "failed",
                    GenerationJob.error: str(exc),
                    GenerationJob.finished_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )
        db.commit()
    finally:
        db.close()


@celery_app.task(name="app.tasks.recover_stale_generation_jobs")
def recover_stale_generation_jobs() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.generation_lease_seconds
    )
    db = SessionLocal()
    event_ids: list[str] = []
    try:
        candidate_ids = [
            row[0]
            for row in db.query(GenerationJob.id)
            .filter(
                GenerationJob.status == "running",
                (GenerationJob.heartbeat_at.is_(None))
                | (GenerationJob.heartbeat_at < cutoff),
            )
            .all()
        ]
        for job_id in candidate_ids:
            dedupe_key = f"generation:{job_id}"
            event = (
                db.query(OutboxEvent)
                .filter_by(dedupe_key=dedupe_key)
                .with_for_update()
                .one_or_none()
            )
            job = (
                db.query(GenerationJob)
                .filter_by(id=job_id, status="running")
                .with_for_update(skip_locked=True)
                .populate_existing()
                .one_or_none()
            )
            if job is None or (
                job.heartbeat_at is not None and job.heartbeat_at >= cutoff
            ):
                db.rollback()
                continue
            job.status = "pending"
            job.heartbeat_at = None
            if event is None:
                event = OutboxEvent(
                    kind="generate_dataset",
                    dedupe_key=dedupe_key,
                    payload={"job_id": job.id},
                )
                db.add(event)
            db.flush()
            event_ids.append(event.id)
            db.commit()
    finally:
        db.close()
    for event_id in event_ids:
        dispatch_outbox_event(event_id)
