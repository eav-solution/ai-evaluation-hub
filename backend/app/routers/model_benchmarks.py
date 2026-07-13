from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.model_benchmarks.catalog import CATALOG
from app.model_benchmarks.types import ModelBenchmarkCatalog

router = APIRouter(
    prefix="/api/model-benchmarks",
    tags=["model-benchmarks"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=ModelBenchmarkCatalog)
def get_model_benchmarks() -> ModelBenchmarkCatalog:
    return CATALOG
