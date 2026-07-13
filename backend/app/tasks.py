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
        contexts=_contexts(source.get(mapping.get("contexts"))),
    )


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


@celery_app.task(name="app.tasks.evaluate_run")
def evaluate_run(run_id: str) -> None:
    db = SessionLocal()
    run = db.get(Run, run_id)
    if run is None or run.status == "cancelled":
        db.close()
        return
    try:
        run.status = "running"
        run.error = None
        db.query(RunResult).filter_by(run_id=run.id).delete()
        db.query(RunSummary).filter_by(run_id=run.id).delete()
        db.commit()

        dataset = db.get(Dataset, run.dataset_id)
        if dataset is None:
            raise ValueError("Dataset not found")
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
        source_rows = parse_dataset(
            storage.get_object(dataset.storage_path),
            dataset.format,
            settings.max_dataset_rows,
        )
        run.progress_total = len(source_rows)
        db.commit()

        results = []
        for offset in range(0, len(source_rows), settings.eval_batch_size):
            db.refresh(run)
            if run.status == "cancelled":
                return
            batch = source_rows[offset : offset + settings.eval_batch_size]
            for index, source in enumerate(batch, start=offset):
                started = time.perf_counter()
                row = None
                endpoint_latency = None
                try:
                    row = _eval_row(
                        source,
                        dataset.schema_map,
                        "" if run.mode == "endpoint" else _MISSING,
                    )
                    if run.mode == "endpoint":
                        if run.endpoint_config is None:
                            raise ValueError("Endpoint configuration is missing")
                        answer, _payload, endpoint_latency = call_endpoint(
                            run.endpoint_config,
                            row,
                            encrypted_headers=True,
                        )
                        row = EvalRow(
                            input=row.input,
                            actual_output=answer,
                            expected_output=row.expected_output,
                            contexts=row.contexts,
                        )
                except Exception as exc:
                    result = RunResult(
                        workspace_id=run.workspace_id,
                        run_id=run.id,
                        row_index=index,
                        input=(
                            row.input
                            if row is not None
                            else _text(source.get(dataset.schema_map.get("input"))) or ""
                        ),
                        expected=row.expected_output if row is not None else None,
                        actual=None,
                        contexts=row.contexts if row is not None else None,
                        scores={},
                        error=str(exc),
                        latency_ms=round((time.perf_counter() - started) * 1000),
                    )
                    db.add(result)
                    results.append(result)
                    continue

                scores = {}
                for config in run.metric_config["metrics"]:
                    try:
                        score = METRICS[config["key"]].score(row, judge, config)
                        scores[config["key"]] = {
                            "score": score.score,
                            "reason": score.reason,
                            "passed": score.passed,
                            "error": None,
                        }
                    except Exception as exc:
                        scores[config["key"]] = {
                            "score": None,
                            "reason": None,
                            "passed": None,
                            "error": str(exc),
                        }
                row_error = (
                    "All metrics failed"
                    if all(item["score"] is None for item in scores.values())
                    else None
                )
                result = RunResult(
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    row_index=index,
                    input=row.input,
                    expected=row.expected_output,
                    actual=row.actual_output,
                    contexts=row.contexts,
                    scores=scores,
                    error=row_error,
                    latency_ms=round(
                        endpoint_latency
                        if endpoint_latency is not None
                        else (time.perf_counter() - started) * 1000
                    ),
                )
                db.add(result)
                results.append(result)
            run.progress_done = min(offset + len(batch), len(source_rows))
            db.commit()

        _summarize(db, run, results)
        failed_rows = sum(result.error is not None for result in results)
        run.status = "failed" if failed_rows == len(results) else "completed"
        run.error = "All rows failed" if run.status == "failed" else None
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(Run, run_id)
        if run is not None:
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


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
