from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.model_benchmarks.types import ScoreDirection


class CatalogRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HarnessRecord(CatalogRecord):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ReasoningModelRecord(CatalogRecord):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    developer: str = Field(min_length=1)


class CriterionDefinition(CatalogRecord):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    minimum: float
    maximum: float
    direction: ScoreDirection


class CriterionScore(CatalogRecord):
    criterion_id: str = Field(min_length=1)
    value: float
    evidence: str | None = None


class TestEntry(CatalogRecord):
    model_id: str = Field(min_length=1)
    harness_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    scores: tuple[CriterionScore, ...] = Field(min_length=1)


class ReasoningTest(CatalogRecord):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    series_id: str | None = None
    conducted_at: date
    task_summary: str = Field(min_length=1)
    methodology: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    criteria: tuple[CriterionDefinition, ...] = Field(min_length=1)
    entries: tuple[TestEntry, ...] = Field(min_length=1)
    findings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class ReasoningBenchmarkCatalog(CatalogRecord):
    catalog_version: str = Field(min_length=1)
    last_updated_at: date
    harnesses: tuple[HarnessRecord, ...] = Field(min_length=1)
    models: tuple[ReasoningModelRecord, ...] = Field(min_length=1)
    tests: tuple[ReasoningTest, ...] = Field(min_length=1)
