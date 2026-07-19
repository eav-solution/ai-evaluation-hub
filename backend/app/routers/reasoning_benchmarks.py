from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.reasoning_benchmarks.catalog import CATALOG
from app.reasoning_benchmarks.types import ReasoningBenchmarkCatalog

router = APIRouter(
    prefix="/api/reasoning-benchmarks",
    tags=["reasoning-benchmarks"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=ReasoningBenchmarkCatalog)
def get_reasoning_benchmarks() -> ReasoningBenchmarkCatalog:
    return CATALOG
