from collections.abc import Iterable

from app.model_benchmarks.types import (
    Availability,
    ModelBenchmarkCatalog,
    ModelPricing,
    ModelTier,
    PriceState,
    SourceReference,
    TokenPrice,
)


APPROVED_PROVIDER_IDS: frozenset[str] = frozenset(
    {
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
    }
)


def validate_catalog(catalog: ModelBenchmarkCatalog) -> None:
    """Raise ValueError when catalog-wide data invariants are unsafe."""
    _validate_unique_ids(catalog)
    _validate_provider_roster(catalog)
    _validate_model_roster(catalog)
    _validate_benchmarks(catalog)
    _validate_scores(catalog)
    _validate_pricing(catalog)
    _validate_source_dates(catalog)


def _validate_unique_ids(catalog: ModelBenchmarkCatalog) -> None:
    _validate_unique_values("provider ID", (provider.id for provider in catalog.providers))
    _validate_unique_values("model ID", (model.id for model in catalog.models))
    _validate_unique_values("benchmark ID", (benchmark.id for benchmark in catalog.benchmarks))
    _validate_unique_values(
        "benchmark display name",
        (benchmark.display_name for benchmark in catalog.benchmarks),
    )
    _validate_unique_values(
        "score key",
        ((score.model_id, score.benchmark_id) for score in catalog.scores),
    )


def _validate_unique_values(label: str, values: Iterable[object]) -> None:
    seen: set[object] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value!r}")
        seen.add(value)


def _validate_provider_roster(catalog: ModelBenchmarkCatalog) -> None:
    provider_ids = {provider.id for provider in catalog.providers}
    if provider_ids != APPROVED_PROVIDER_IDS:
        missing = ", ".join(sorted(APPROVED_PROVIDER_IDS - provider_ids)) or "none"
        unexpected = ", ".join(sorted(provider_ids - APPROVED_PROVIDER_IDS)) or "none"
        raise ValueError(
            "catalog provider IDs must equal approved provider IDs "
            f"(missing: {missing}; unexpected: {unexpected})"
        )


def _validate_model_roster(catalog: ModelBenchmarkCatalog) -> None:
    provider_ids = {provider.id for provider in catalog.providers}
    for model in catalog.models:
        if model.provider_id not in provider_ids:
            raise ValueError(
                f"model {model.id!r} references unknown provider {model.provider_id!r}"
            )
        _validate_non_empty(f"model {model.id!r} display name", model.display_name)
        _validate_non_empty(f"model {model.id!r} tier reason", model.tier_reason)
        if model.release_date > catalog.last_verified_at:
            raise ValueError(
                f"model {model.id!r} release date is after catalog verification date"
            )
        if model.verified_at > catalog.last_verified_at:
            raise ValueError(
                f"model {model.id!r} verification date is after catalog verification date"
            )
        if model.specification_source is None:
            raise ValueError(f"model {model.id!r} specification source is required")
        if model.specification_source.provider_id != model.provider_id:
            raise ValueError(
                f"model {model.id!r} specification source provider "
                f"{model.specification_source.provider_id!r} does not match "
                f"model provider {model.provider_id!r}"
            )

    expected_tiers = set(ModelTier)
    for provider_id in sorted(provider_ids):
        provider_models = [model for model in catalog.models if model.provider_id == provider_id]
        tier_counts = {tier: 0 for tier in ModelTier}
        for model in provider_models:
            tier_counts[model.tier] += 1
        if len(provider_models) != len(ModelTier) or any(
            count != 1 for count in tier_counts.values()
        ):
            tiers = ", ".join(tier.value for tier in sorted(expected_tiers, key=str))
            raise ValueError(
                f"provider {provider_id!r} must have exactly one model per tier "
                f"({tiers})"
            )


def _validate_benchmarks(catalog: ModelBenchmarkCatalog) -> None:
    for benchmark in catalog.benchmarks:
        if benchmark.minimum > benchmark.maximum:
            raise ValueError(
                f"benchmark {benchmark.id!r} minimum must not exceed its maximum"
            )
        info = benchmark.info
        for field, value in (
            ("meaning", info.meaning),
            ("dataset and edition", info.dataset_and_edition),
            ("scoring method", info.scoring_method),
            ("interpretation", info.interpretation),
        ):
            _validate_non_empty(f"benchmark information {field}", value)
        _validate_non_empty_collection(
            f"benchmark {benchmark.id!r} standard conditions", info.standard_conditions
        )
        _validate_non_empty_collection(
            f"benchmark {benchmark.id!r} limitations", info.limitations
        )


def _validate_scores(catalog: ModelBenchmarkCatalog) -> None:
    models = {model.id: model for model in catalog.models}
    benchmarks = {benchmark.id: benchmark for benchmark in catalog.benchmarks}
    for score in catalog.scores:
        model = models.get(score.model_id)
        if model is None:
            raise ValueError(f"score references unknown model {score.model_id!r}")
        benchmark = benchmarks.get(score.benchmark_id)
        if benchmark is None:
            raise ValueError(f"score references unknown benchmark {score.benchmark_id!r}")
        if not benchmark.minimum <= score.value <= benchmark.maximum:
            raise ValueError(
                f"score for model {score.model_id!r} on benchmark {score.benchmark_id!r} "
                f"is outside benchmark range {benchmark.minimum}..{benchmark.maximum}"
            )
        if score.source is None:
            raise ValueError(
                f"score for model {score.model_id!r} on benchmark {score.benchmark_id!r} "
                "score source is required"
            )
        if score.source.provider_id != model.provider_id:
            raise ValueError(
                f"score source provider {score.source.provider_id!r} does not match "
                f"scored model provider {model.provider_id!r}"
            )


def _validate_pricing(catalog: ModelBenchmarkCatalog) -> None:
    for model in catalog.models:
        pricing = model.pricing
        if pricing.source is None:
            if pricing.status is PriceState.REPORTED:
                raise ValueError(f"model {model.id!r} reported pricing source is required")
            raise ValueError(f"model {model.id!r} pricing source is required")
        if pricing.source.provider_id != model.provider_id:
            raise ValueError(
                f"model {model.id!r} pricing source provider "
                f"{pricing.source.provider_id!r} does not match model provider "
                f"{model.provider_id!r}"
            )
        if (
            model.availability is Availability.OFFICIAL_WEIGHTS
            and pricing.status is not PriceState.NOT_APPLICABLE
        ):
            raise ValueError(
                f"weights-only model {model.id!r} must use not_applicable pricing"
            )
        if (
            pricing.status is PriceState.NOT_APPLICABLE
            and model.availability is not Availability.OFFICIAL_WEIGHTS
        ):
            raise ValueError(
                f"not_applicable pricing for model {model.id!r} is only permitted "
                "for weights-only availability"
            )
        if pricing.status is not PriceState.REPORTED:
            if pricing.bands:
                raise ValueError(
                    f"model {model.id!r} non-reported pricing must not define price bands"
                )
            continue
        _validate_pricing_bands(model.id, pricing)
        if not pricing.bands:
            raise ValueError(f"model {model.id!r} reported pricing bands are required")
        base_band_count = sum(band.is_base for band in pricing.bands)
        if base_band_count != 1:
            raise ValueError(
                f"model {model.id!r} reported pricing requires exactly one base band"
            )
        for band in pricing.bands:
            _validate_reported_price(model.id, band.band_id, "input", band.input)
            _validate_reported_price(model.id, band.band_id, "output", band.output)


def _validate_pricing_bands(model_id: str, pricing: ModelPricing) -> None:
    _validate_unique_values("pricing band ID", (band.band_id for band in pricing.bands))
    for band in pricing.bands:
        _validate_non_empty(
            f"model {model_id!r} pricing band condition for {band.band_id!r}",
            band.condition,
        )
        for label, price in (
            ("input", band.input),
            ("cached input", band.cached_input),
            ("output", band.output),
        ):
            _validate_price_point(model_id, band.band_id, label, price, pricing)


def _validate_reported_price(
    model_id: str, band_id: str, label: str, price: TokenPrice
) -> None:
    if price.status is not PriceState.REPORTED or price.usd_per_million is None:
        raise ValueError(
            f"model {model_id!r} reported {label} price in band {band_id!r} is required"
        )


def _validate_price_point(
    model_id: str,
    band_id: str,
    label: str,
    price: TokenPrice,
    pricing: ModelPricing,
) -> None:
    location = f"model {model_id!r} {label} price in band {band_id!r}"
    if price.status is PriceState.REPORTED:
        if price.usd_per_million is None:
            raise ValueError(f"{location} reported price requires a USD amount")
    elif (
        price.usd_per_million is not None
        or price.source_amount_per_million is not None
        or price.source_currency is not None
    ):
        raise ValueError(f"{location} not-reported price must not carry a numeric value")

    if price.source_currency and price.source_currency.upper() != "USD":
        if price.source_amount_per_million is None:
            raise ValueError(f"{location} requires original currency and amount for non-USD conversion")
        if pricing.exchange_rate_source is None:
            raise ValueError(f"{location} requires an exchange-rate source for non-USD conversion")


def _validate_source_dates(catalog: ModelBenchmarkCatalog) -> None:
    for location, source in _iter_sources(catalog):
        if source is None:
            raise ValueError(f"{location} source is required")
        _validate_non_empty(f"{location} source title", source.title)
        _validate_non_empty(f"{location} source publisher", source.publisher)
        if source.published_at is not None and source.published_at > catalog.last_verified_at:
            raise ValueError(f"{location} source published date is after catalog verification date")
        if source.verified_at > catalog.last_verified_at:
            raise ValueError(f"{location} source verification date is after catalog verification date")


def _iter_sources(catalog: ModelBenchmarkCatalog) -> Iterable[tuple[str, SourceReference | None]]:
    for model in catalog.models:
        yield (f"model {model.id!r} specification", model.specification_source)
        yield (f"model {model.id!r} pricing", model.pricing.source)
        if model.pricing.exchange_rate_source is not None:
            yield (f"model {model.id!r} exchange rate", model.pricing.exchange_rate_source)
    for benchmark in catalog.benchmarks:
        yield (f"benchmark {benchmark.id!r}", benchmark.official_source)
    for score in catalog.scores:
        yield (
            f"score for model {score.model_id!r} on benchmark {score.benchmark_id!r}",
            score.source,
        )


def _validate_non_empty(label: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be blank")


def _validate_non_empty_collection(label: str, values: tuple[str, ...]) -> None:
    if not values:
        raise ValueError(f"{label} must not be empty")
    for value in values:
        _validate_non_empty(label, value)
