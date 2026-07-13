from fastapi import APIRouter

from app.evals.metric_info import METRIC_INFO
from app.evals.registry import METRICS

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("")
def list_metrics() -> list[dict]:
    return [
        {
            "key": adapter.key,
            "framework": adapter.framework,
            "display_name": adapter.display_name,
            "description": adapter.description,
            "requires": sorted(adapter.requires),
            "info": METRIC_INFO[adapter.key],
        }
        for adapter in METRICS.values()
    ]
