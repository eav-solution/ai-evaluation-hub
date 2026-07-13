from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, UrlConstraints


HttpsUrl = Annotated[HttpUrl, UrlConstraints(allowed_schemes=["https"])]


class CatalogRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelTier(StrEnum):
    FRONTIER = "frontier"
    MID_RANGE = "mid_range"
    LITE = "lite"


class BenchmarkTrack(StrEnum):
    TEXT_CODE = "text_code"
    MULTIMODAL = "multimodal"


class BenchmarkCategory(StrEnum):
    GENERAL_KNOWLEDGE = "general_knowledge"
    REASONING = "reasoning"
    MATHEMATICS = "mathematics"
    CODING = "coding"
    INSTRUCTION_FOLLOWING = "instruction_following"
    LONG_CONTEXT = "long_context"
    MULTIMODAL_UNDERSTANDING = "multimodal_understanding"


class ScoreDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class WeightsStatus(StrEnum):
    OPEN_WEIGHT = "open_weight"
    CLOSED = "closed"


class Availability(StrEnum):
    OFFICIAL_API = "official_api"
    OFFICIAL_WEIGHTS = "official_weights"
    OFFICIAL_API_AND_WEIGHTS = "official_api_and_weights"


class Modality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    PDF = "pdf"


class PriceState(StrEnum):
    REPORTED = "reported"
    NOT_REPORTED = "not_reported"
    NOT_APPLICABLE = "not_applicable"


class SourceReference(CatalogRecord):
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    provider_id: str | None = None
    url: HttpsUrl
    published_at: date | None = None
    verified_at: date


class TokenPrice(CatalogRecord):
    status: PriceState
    usd_per_million: float | None = Field(default=None, ge=0)
    source_amount_per_million: float | None = Field(default=None, ge=0)
    source_currency: str | None = None


class PricingBand(CatalogRecord):
    band_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    is_base: bool = False
    input: TokenPrice
    cached_input: TokenPrice
    output: TokenPrice


class ModelPricing(CatalogRecord):
    status: PriceState
    bands: tuple[PricingBand, ...] = ()
    source: SourceReference
    exchange_rate_source: SourceReference | None = None
    note: str | None = None


class ProviderRecord(CatalogRecord):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    website: HttpsUrl


class ModelRecord(CatalogRecord):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    api_model_id: str | None = None
    provider_id: str = Field(min_length=1)
    tier: ModelTier
    tier_reason: str = Field(min_length=1)
    release_date: date
    context_window_tokens: int = Field(gt=0)
    input_modalities: tuple[Modality, ...]
    output_modalities: tuple[Modality, ...]
    weights_status: WeightsStatus
    availability: Availability
    pricing: ModelPricing
    specification_source: SourceReference
    verified_at: date


class BenchmarkInformation(CatalogRecord):
    meaning: str = Field(min_length=1)
    dataset_and_edition: str = Field(min_length=1)
    scoring_method: str = Field(min_length=1)
    interpretation: str = Field(min_length=1)
    standard_conditions: tuple[str, ...]
    limitations: tuple[str, ...]


class BenchmarkDefinition(CatalogRecord):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    track: BenchmarkTrack
    category: BenchmarkCategory
    dataset_edition: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    minimum: float
    maximum: float
    direction: ScoreDirection
    setup_variant: str = Field(min_length=1)
    info: BenchmarkInformation
    official_source: SourceReference


class SetupDetail(CatalogRecord):
    label: str = Field(min_length=1)
    value: str = Field(min_length=1)


class BenchmarkScore(CatalogRecord):
    model_id: str = Field(min_length=1)
    benchmark_id: str = Field(min_length=1)
    value: float
    setup: tuple[SetupDetail, ...]
    source: SourceReference


class ModelBenchmarkCatalog(CatalogRecord):
    catalog_version: str = Field(min_length=1)
    last_verified_at: date
    providers: tuple[ProviderRecord, ...]
    models: tuple[ModelRecord, ...]
    benchmarks: tuple[BenchmarkDefinition, ...]
    scores: tuple[BenchmarkScore, ...]
