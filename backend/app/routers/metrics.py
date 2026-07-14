from fastapi import APIRouter

from app.evals.presets import PRESETS
from app.evals.registry import METRICS

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("")
def list_metrics() -> list[dict]:
    return [adapter.catalog_entry() for adapter in METRICS.values()]


@router.get("/presets")
def list_metric_presets() -> list[dict]:
    return list(PRESETS.values())
