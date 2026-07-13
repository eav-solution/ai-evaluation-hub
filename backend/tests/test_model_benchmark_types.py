import pytest
from pydantic import ValidationError

from app.model_benchmarks.types import (
    Availability,
    Modality,
    ModelPricing,
    ModelRecord,
    ModelTier,
    PriceState,
    SourceReference,
    TokenPrice,
    WeightsStatus,
)


def _source(*, url: str = "https://provider.example/model") -> SourceReference:
    return SourceReference(
        title="Official model card",
        publisher="Provider",
        provider_id="openai",
        url=url,
        published_at="2026-07-01",
        verified_at="2026-07-13",
    )


def _model(*, context_window_tokens: int = 128_000) -> ModelRecord:
    source = _source()
    return ModelRecord(
        id="provider-model",
        display_name="Provider Model",
        provider_id="provider",
        tier=ModelTier.FRONTIER,
        tier_reason="Top capability tier",
        release_date="2026-07-01",
        context_window_tokens=context_window_tokens,
        input_modalities=(Modality.TEXT,),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=ModelPricing(
            status=PriceState.NOT_REPORTED,
            source=source,
        ),
        specification_source=source,
        verified_at="2026-07-13",
    )


def test_catalog_records_are_frozen_and_forbid_unknown_fields():
    source = _source()

    with pytest.raises(ValidationError):
        source.title = "Changed"
    with pytest.raises(ValidationError):
        SourceReference(
            title="Official model card",
            publisher="Provider",
            url="https://provider.example/model",
            verified_at="2026-07-13",
            unexpected="rejected",
        )


def test_source_reference_rejects_non_https_url():
    with pytest.raises(ValidationError):
        _source(url="http://provider.example/model")


@pytest.mark.parametrize("context_window_tokens", [0, -1])
def test_model_rejects_non_positive_context_window(context_window_tokens: int):
    with pytest.raises(ValidationError):
        _model(context_window_tokens=context_window_tokens)


def test_reported_price_rejects_negative_amount():
    with pytest.raises(ValidationError):
        TokenPrice(status=PriceState.REPORTED, usd_per_million=-0.01)
