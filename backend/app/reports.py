import csv
import io
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models import Run, RunResult, RunSummary

_environment = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(("html",)),
)


def _datetime(value):
    return value.isoformat() if value is not None else None


def _json(value):
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def build_payload(
    run: Run,
    summaries: list[RunSummary],
    results: list[RunResult],
) -> dict:
    return {
        "run": {
            "id": run.id,
            "dataset_id": run.dataset_id,
            "name": run.name,
            "mode": run.mode,
            "status": run.status,
            "metric_config": run.metric_config,
            "progress_done": run.progress_done,
            "progress_total": run.progress_total,
            "error": run.error,
            "created_at": _datetime(run.created_at),
            "finished_at": _datetime(run.finished_at),
        },
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
            for item in summaries
        ],
        "results": [
            {
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
        ],
    }


def render_csv(run: Run, results: list[RunResult]) -> str:
    metric_keys = [item["key"] for item in run.metric_config["metrics"]]
    base_fields = [
        "row_index",
        "input",
        "expected",
        "actual",
        "contexts",
        "error",
        "latency_ms",
        "details",
        "usage",
        "estimated_cost",
    ]
    metric_fields = [
        f"{key}.{field}"
        for key in metric_keys
        for field in ("score", "passed", "reason", "error")
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=base_fields + metric_fields)
    writer.writeheader()
    for result in results:
        row = {
            "row_index": result.row_index,
            "input": result.input,
            "expected": result.expected,
            "actual": result.actual,
            "contexts": _json(result.contexts),
            "error": result.error,
            "latency_ms": result.latency_ms,
            "details": _json(result.details),
            "usage": _json(result.usage),
            "estimated_cost": result.estimated_cost,
        }
        for key in metric_keys:
            score = result.scores.get(key, {})
            for field in ("score", "passed", "reason", "error"):
                value = score.get(field)
                if isinstance(value, bool):
                    value = str(value).lower()
                row[f"{key}.{field}"] = value
        writer.writerow(row)
    return output.getvalue()


def render_html(
    run: Run,
    summaries: list[RunSummary],
    results: list[RunResult],
) -> str:
    template = _environment.get_template("report.html")
    metric_keys = [item["key"] for item in run.metric_config["metrics"]]
    chart = [
        {
            "key": item.metric_key,
            "mean": item.mean,
            "width": max(0, min(100, item.mean * 100)),
        }
        for item in summaries
    ]
    return template.render(
        run=run,
        summaries=summaries,
        results=results,
        metric_keys=metric_keys,
        chart=chart,
    )
