from datetime import date

from app.model_benchmarks.types import (
    Availability,
    BenchmarkCategory,
    BenchmarkDefinition,
    BenchmarkInformation,
    BenchmarkScore,
    BenchmarkTrack,
    ModelBenchmarkCatalog,
    ModelPricing,
    ModelRecord,
    ModelTier,
    Modality,
    PriceState,
    PricingBand,
    ProviderRecord,
    ScoreDirection,
    SetupDetail,
    SourceReference,
    TokenPrice,
    WeightsStatus,
)


PROVIDER_IDS = (
    "openai",
    "anthropic",
    "google",
    "meta",
    "xai",
    "zai",
    "alibaba",
    "deepseek",
    "moonshot",
    "minimax",
)
CATALOG_DATE = date(2026, 7, 13)


def make_source(provider_id: str | None, page: str) -> SourceReference:
    host = provider_id or "benchmark"
    return SourceReference(
        title=f"{page.title()} source",
        publisher=provider_id.title() if provider_id else "Benchmark Organization",
        provider_id=provider_id,
        url=f"https://{host}.example.com/{page}",
        published_at=date(2026, 7, 1),
        verified_at=CATALOG_DATE,
    )


def make_reported_pricing(provider_id: str) -> ModelPricing:
    price = TokenPrice(status=PriceState.REPORTED, usd_per_million=1.0)
    return ModelPricing(
        status=PriceState.REPORTED,
        bands=(
            PricingBand(
                band_id="base",
                label="Standard",
                condition="Standard pay-as-you-go pricing",
                is_base=True,
                input=price,
                cached_input=price,
                output=price,
            ),
        ),
        source=make_source(provider_id, "pricing"),
    )


def make_valid_catalog() -> ModelBenchmarkCatalog:
    providers = tuple(
        ProviderRecord(
            id=provider_id,
            display_name=provider_id.title(),
            website=f"https://{provider_id}.example.com",
        )
        for provider_id in PROVIDER_IDS
    )
    models = tuple(
        ModelRecord(
            id=f"{provider_id}-{tier.value.replace('_', '-')}",
            display_name=f"{provider_id.title()} {tier.value.replace('_', ' ').title()}",
            api_model_id=f"{provider_id}-{tier.value}",
            provider_id=provider_id,
            tier=tier,
            tier_reason="Representative model for this capability tier",
            release_date=date(2026, 7, 1),
            context_window_tokens=128_000,
            input_modalities=(Modality.TEXT,),
            output_modalities=(Modality.TEXT,),
            weights_status=WeightsStatus.CLOSED,
            availability=Availability.OFFICIAL_API,
            pricing=ModelPricing(
                status=PriceState.NOT_REPORTED,
                source=make_source(provider_id, "pricing"),
            ),
            specification_source=make_source(provider_id, "model-card"),
            verified_at=CATALOG_DATE,
        )
        for provider_id in PROVIDER_IDS
        for tier in ModelTier
    )
    benchmark = BenchmarkDefinition(
        id="synthetic-reasoning",
        display_name="Synthetic Reasoning",
        track=BenchmarkTrack.TEXT_CODE,
        category=BenchmarkCategory.REASONING,
        dataset_edition="Synthetic v1",
        unit="percent",
        minimum=0.0,
        maximum=100.0,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        setup_variant="Official reported setup",
        info=BenchmarkInformation(
            meaning="Measures synthetic reasoning performance.",
            dataset_and_edition="Synthetic benchmark, edition v1.",
            scoring_method="Exact-match percentage.",
            interpretation="Higher values indicate stronger performance.",
            standard_conditions=("Official reported setup",),
            limitations=("Synthetic fixture data only",),
        ),
        official_source=make_source(None, "benchmark"),
    )
    scores = tuple(
        BenchmarkScore(
            model_id=model.id,
            benchmark_id=benchmark.id,
            value=75.0,
            setup=(SetupDetail(label="Prompting", value="Official default"),),
            source=make_source(model.provider_id, "benchmark-result"),
        )
        for model in models
    )
    return ModelBenchmarkCatalog(
        catalog_version="synthetic-v1",
        last_verified_at=CATALOG_DATE,
        providers=providers,
        models=models,
        benchmarks=(benchmark,),
        scores=scores,
    )
