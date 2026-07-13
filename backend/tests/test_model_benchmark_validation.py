from datetime import timedelta

import pytest

from app.model_benchmarks.types import (
    Availability,
    PriceState,
    PricingBand,
    TokenPrice,
    WeightsStatus,
)
from app.model_benchmarks.validation import APPROVED_PROVIDER_IDS, validate_catalog
from model_benchmark_fixtures import PROVIDER_IDS, make_reported_pricing, make_source, make_valid_catalog


def _replace_model(catalog, index, model):
    models = (*catalog.models[:index], model, *catalog.models[index + 1 :])
    return catalog.model_copy(update={"models": models})


def _replace_first_model_pricing(catalog, pricing):
    return _replace_model(catalog, 0, catalog.models[0].model_copy(update={"pricing": pricing}))


def test_accepts_the_valid_synthetic_catalog():
    catalog = make_valid_catalog()

    validate_catalog(catalog)

    assert {provider.id for provider in catalog.providers} == APPROVED_PROVIDER_IDS
    assert set(PROVIDER_IDS) == APPROVED_PROVIDER_IDS


def test_rejects_wrong_provider_set():
    catalog = make_valid_catalog()
    invalid_provider = catalog.providers[-1].model_copy(update={"id": "unapproved"})
    invalid = catalog.model_copy(update={"providers": (*catalog.providers[:-1], invalid_provider)})

    with pytest.raises(ValueError, match="approved provider IDs"):
        validate_catalog(invalid)


@pytest.mark.parametrize(
    ("name", "build_invalid", "message"),
    [
        (
            "provider",
            lambda catalog: catalog.model_copy(
                update={"providers": (catalog.providers[0], *catalog.providers)}
            ),
            "duplicate provider ID",
        ),
        (
            "model",
            lambda catalog: _replace_model(
                catalog,
                1,
                catalog.models[1].model_copy(update={"id": catalog.models[0].id}),
            ),
            "duplicate model ID",
        ),
        (
            "benchmark",
            lambda catalog: catalog.model_copy(
                update={"benchmarks": (catalog.benchmarks[0], catalog.benchmarks[0])}
            ),
            "duplicate benchmark ID",
        ),
        (
            "score key",
            lambda catalog: catalog.model_copy(update={"scores": (catalog.scores[0], *catalog.scores)}),
            "duplicate score key",
        ),
    ],
)
def test_rejects_duplicate_catalog_keys(name, build_invalid, message):
    invalid = build_invalid(make_valid_catalog())

    with pytest.raises(ValueError, match=message):
        validate_catalog(invalid)


def test_rejects_duplicate_benchmark_display_names():
    catalog = make_valid_catalog()
    duplicate_name = catalog.benchmarks[0].model_copy(
        update={"id": "synthetic-reasoning-alternate"}
    )
    invalid = catalog.model_copy(
        update={"benchmarks": (*catalog.benchmarks, duplicate_name)}
    )

    with pytest.raises(ValueError, match="duplicate benchmark display name"):
        validate_catalog(invalid)


def test_rejects_fewer_than_three_models_for_a_provider():
    catalog = make_valid_catalog()
    invalid = catalog.model_copy(
        update={"models": tuple(model for model in catalog.models if model.id != "openai-lite")}
    )

    with pytest.raises(ValueError, match="exactly one model per tier"):
        validate_catalog(invalid)


def test_rejects_more_than_three_models_for_a_provider():
    catalog = make_valid_catalog()
    extra_model = catalog.models[0].model_copy(update={"id": "openai-extra"})
    invalid = catalog.model_copy(update={"models": (*catalog.models, extra_model)})

    with pytest.raises(ValueError, match="exactly one model per tier"):
        validate_catalog(invalid)


def test_rejects_repeated_tier_for_a_provider():
    catalog = make_valid_catalog()
    repeated_tier = catalog.models[1].model_copy(update={"tier": catalog.models[0].tier})
    invalid = _replace_model(catalog, 1, repeated_tier)

    with pytest.raises(ValueError, match="exactly one model per tier"):
        validate_catalog(invalid)


def test_rejects_a_model_reused_for_two_tier_records():
    catalog = make_valid_catalog()
    reused_model = catalog.models[1].model_copy(
        update={"id": catalog.models[0].id, "tier": catalog.models[1].tier}
    )
    invalid = _replace_model(catalog, 1, reused_model)

    with pytest.raises(ValueError, match="duplicate model ID"):
        validate_catalog(invalid)


@pytest.mark.parametrize("field", ["display_name", "tier_reason"])
def test_rejects_blank_model_identifying_text(field):
    catalog = make_valid_catalog()
    invalid_model = catalog.models[0].model_copy(update={field: " "})
    invalid = _replace_model(catalog, 0, invalid_model)

    with pytest.raises(ValueError, match="must not be blank"):
        validate_catalog(invalid)


def test_rejects_model_released_after_catalog_verification():
    catalog = make_valid_catalog()
    future_model = catalog.models[0].model_copy(
        update={"release_date": catalog.last_verified_at + timedelta(days=1)}
    )
    invalid = _replace_model(catalog, 0, future_model)

    with pytest.raises(ValueError, match="release date"):
        validate_catalog(invalid)


@pytest.mark.parametrize(
    ("name", "build_invalid", "message"),
    [
        (
            "provider",
            lambda catalog: _replace_model(
                catalog,
                0,
                catalog.models[0].model_copy(update={"provider_id": "unknown"}),
            ),
            "unknown provider",
        ),
        (
            "model",
            lambda catalog: catalog.model_copy(
                update={
                    "scores": (
                        catalog.scores[0].model_copy(update={"model_id": "unknown"}),
                        *catalog.scores[1:],
                    )
                }
            ),
            "unknown model",
        ),
        (
            "benchmark",
            lambda catalog: catalog.model_copy(
                update={
                    "scores": (
                        catalog.scores[0].model_copy(update={"benchmark_id": "unknown"}),
                        *catalog.scores[1:],
                    )
                }
            ),
            "unknown benchmark",
        ),
    ],
)
def test_rejects_unknown_catalog_references(name, build_invalid, message):
    invalid = build_invalid(make_valid_catalog())

    with pytest.raises(ValueError, match=message):
        validate_catalog(invalid)


def test_rejects_score_outside_its_benchmark_range():
    catalog = make_valid_catalog()
    invalid_score = catalog.scores[0].model_copy(update={"value": 100.1})
    invalid = catalog.model_copy(update={"scores": (invalid_score, *catalog.scores[1:])})

    with pytest.raises(ValueError, match="outside benchmark range"):
        validate_catalog(invalid)


def test_rejects_score_from_a_competitor_source():
    catalog = make_valid_catalog()
    score = catalog.scores[0]
    invalid_source = score.source.model_copy(update={"provider_id": "anthropic"})
    invalid_score = score.model_copy(update={"source": invalid_source})
    invalid = catalog.model_copy(update={"scores": (invalid_score, *catalog.scores[1:])})

    with pytest.raises(ValueError, match="score source provider"):
        validate_catalog(invalid)


def test_rejects_score_without_a_source_as_a_value_error():
    catalog = make_valid_catalog()
    invalid_score = catalog.scores[0].model_copy(update={"source": None})
    invalid = catalog.model_copy(update={"scores": (invalid_score, *catalog.scores[1:])})

    with pytest.raises(ValueError, match="score source is required"):
        validate_catalog(invalid)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("meaning", " ", "benchmark information"),
        ("dataset_and_edition", " ", "benchmark information"),
        ("scoring_method", " ", "benchmark information"),
        ("interpretation", " ", "benchmark information"),
        ("standard_conditions", (), "standard conditions"),
        ("limitations", (), "limitations"),
    ],
)
def test_rejects_incomplete_benchmark_information(field, value, message):
    catalog = make_valid_catalog()
    invalid_info = catalog.benchmarks[0].info.model_copy(update={field: value})
    invalid_benchmark = catalog.benchmarks[0].model_copy(update={"info": invalid_info})
    invalid = catalog.model_copy(update={"benchmarks": (invalid_benchmark,)})

    with pytest.raises(ValueError, match=message):
        validate_catalog(invalid)


@pytest.mark.parametrize("field", ["published_at", "verified_at"])
def test_rejects_source_dates_after_catalog_verification(field):
    catalog = make_valid_catalog()
    invalid_source = catalog.scores[0].source.model_copy(
        update={field: catalog.last_verified_at + timedelta(days=1)}
    )
    invalid_score = catalog.scores[0].model_copy(update={"source": invalid_source})
    invalid = catalog.model_copy(update={"scores": (invalid_score, *catalog.scores[1:])})

    with pytest.raises(ValueError, match="source .* date"):
        validate_catalog(invalid)


def test_rejects_weights_only_model_without_not_applicable_pricing():
    catalog = make_valid_catalog()
    invalid_model = catalog.models[0].model_copy(
        update={"availability": Availability.OFFICIAL_WEIGHTS}
    )
    invalid = _replace_model(catalog, 0, invalid_model)

    with pytest.raises(ValueError, match="weights-only.*not_applicable"):
        validate_catalog(invalid)


def test_accepts_weights_only_model_with_not_applicable_pricing():
    catalog = make_valid_catalog()
    not_applicable_pricing = catalog.models[0].pricing.model_copy(
        update={"status": PriceState.NOT_APPLICABLE}
    )
    valid_model = catalog.models[0].model_copy(
        update={
            "weights_status": WeightsStatus.OPEN_WEIGHT,
            "availability": Availability.OFFICIAL_WEIGHTS,
            "pricing": not_applicable_pricing,
        }
    )
    valid = _replace_model(catalog, 0, valid_model)

    validate_catalog(valid)


def test_accepts_open_weight_api_and_weights_model_with_reported_pricing():
    catalog = make_valid_catalog()
    valid_model = catalog.models[0].model_copy(
        update={
            "weights_status": WeightsStatus.OPEN_WEIGHT,
            "availability": Availability.OFFICIAL_API_AND_WEIGHTS,
            "pricing": make_reported_pricing("openai"),
        }
    )
    valid = _replace_model(catalog, 0, valid_model)

    validate_catalog(valid)


def test_accepts_open_weight_api_and_weights_model_with_not_reported_pricing():
    catalog = make_valid_catalog()
    valid_model = catalog.models[0].model_copy(
        update={
            "weights_status": WeightsStatus.OPEN_WEIGHT,
            "availability": Availability.OFFICIAL_API_AND_WEIGHTS,
        }
    )
    valid = _replace_model(catalog, 0, valid_model)

    validate_catalog(valid)


@pytest.mark.parametrize(
    "availability",
    [Availability.OFFICIAL_API, Availability.OFFICIAL_API_AND_WEIGHTS],
)
def test_rejects_not_applicable_pricing_for_api_capable_model(availability):
    catalog = make_valid_catalog()
    not_applicable_pricing = catalog.models[0].pricing.model_copy(
        update={"status": PriceState.NOT_APPLICABLE}
    )
    invalid_model = catalog.models[0].model_copy(
        update={"availability": availability, "pricing": not_applicable_pricing}
    )
    invalid = _replace_model(catalog, 0, invalid_model)

    with pytest.raises(ValueError, match="not_applicable pricing.*weights-only"):
        validate_catalog(invalid)


@pytest.mark.parametrize("status", [PriceState.NOT_REPORTED, PriceState.NOT_APPLICABLE])
def test_rejects_non_reported_pricing_bands(status):
    catalog = make_valid_catalog()
    price = TokenPrice(status=status)
    band = PricingBand(
        band_id="unexpected",
        label="Unexpected",
        condition="Synthetic invalid pricing",
        input=price,
        cached_input=price,
        output=price,
    )
    invalid_pricing = catalog.models[0].pricing.model_copy(
        update={"status": status, "bands": (band,)}
    )
    invalid_model = catalog.models[0].model_copy(
        update={
            "availability": (
                Availability.OFFICIAL_WEIGHTS
                if status is PriceState.NOT_APPLICABLE
                else catalog.models[0].availability
            ),
            "pricing": invalid_pricing,
        }
    )
    invalid = _replace_model(catalog, 0, invalid_model)

    with pytest.raises(ValueError, match="must not define price bands"):
        validate_catalog(invalid)


@pytest.mark.parametrize("status", [PriceState.NOT_REPORTED, PriceState.NOT_APPLICABLE])
@pytest.mark.parametrize(
    "metadata",
    [{"source_currency": "USD"}, {"source_amount_per_million": 0.9}],
)
def test_rejects_non_reported_price_with_conversion_metadata(status, metadata):
    catalog = make_valid_catalog()
    pricing = make_reported_pricing("openai")
    non_reported_price = TokenPrice(status=status, **metadata)
    invalid_band = pricing.bands[0].model_copy(update={"cached_input": non_reported_price})
    invalid = _replace_first_model_pricing(catalog, pricing.model_copy(update={"bands": (invalid_band,)}))

    with pytest.raises(ValueError, match="not-reported price"):
        validate_catalog(invalid)


def test_rejects_specification_source_from_a_different_provider():
    catalog = make_valid_catalog()
    invalid_source = catalog.models[0].specification_source.model_copy(
        update={"provider_id": "anthropic"}
    )
    invalid_model = catalog.models[0].model_copy(update={"specification_source": invalid_source})
    invalid = _replace_model(catalog, 0, invalid_model)

    with pytest.raises(ValueError, match="specification source provider"):
        validate_catalog(invalid)


def test_rejects_pricing_source_from_a_different_provider():
    catalog = make_valid_catalog()
    invalid_source = catalog.models[0].pricing.source.model_copy(update={"provider_id": "anthropic"})
    invalid_pricing = catalog.models[0].pricing.model_copy(update={"source": invalid_source})
    invalid = _replace_first_model_pricing(catalog, invalid_pricing)

    with pytest.raises(ValueError, match="pricing source provider"):
        validate_catalog(invalid)


@pytest.mark.parametrize("status", [PriceState.NOT_REPORTED, PriceState.NOT_APPLICABLE])
def test_rejects_non_reported_price_with_a_numeric_value(status):
    catalog = make_valid_catalog()
    pricing = make_reported_pricing("openai")
    non_reported_price = TokenPrice(status=status, usd_per_million=1.0)
    invalid_band = pricing.bands[0].model_copy(update={"cached_input": non_reported_price})
    invalid = _replace_first_model_pricing(catalog, pricing.model_copy(update={"bands": (invalid_band,)}))

    with pytest.raises(ValueError, match="not-reported price"):
        validate_catalog(invalid)


def test_accepts_complete_reported_pricing():
    catalog = make_valid_catalog()
    valid = _replace_first_model_pricing(catalog, make_reported_pricing("openai"))

    validate_catalog(valid)


def test_accepts_complete_non_usd_conversion():
    catalog = make_valid_catalog()
    pricing = make_reported_pricing("openai")
    converted_price = TokenPrice(
        status=PriceState.REPORTED,
        usd_per_million=1.0,
        source_amount_per_million=0.9,
        source_currency="EUR",
    )
    converted_band = pricing.bands[0].model_copy(update={"input": converted_price})
    converted_pricing = pricing.model_copy(
        update={
            "bands": (converted_band,),
            "exchange_rate_source": make_source("openai", "exchange-rate"),
        }
    )
    valid = _replace_first_model_pricing(catalog, converted_pricing)

    validate_catalog(valid)


def test_rejects_reported_pricing_without_a_source():
    catalog = make_valid_catalog()
    invalid_pricing = make_reported_pricing("openai").model_copy(update={"source": None})
    invalid = _replace_first_model_pricing(catalog, invalid_pricing)

    with pytest.raises(ValueError, match="reported pricing source"):
        validate_catalog(invalid)


def test_rejects_reported_pricing_without_bands():
    catalog = make_valid_catalog()
    invalid_pricing = make_reported_pricing("openai").model_copy(update={"bands": ()})
    invalid = _replace_first_model_pricing(catalog, invalid_pricing)

    with pytest.raises(ValueError, match="reported pricing bands"):
        validate_catalog(invalid)


@pytest.mark.parametrize(
    ("base_flags", "message"),
    [((False,), "exactly one base band"), ((True, True), "exactly one base band")],
)
def test_rejects_reported_pricing_without_exactly_one_base_band(base_flags, message):
    catalog = make_valid_catalog()
    pricing = make_reported_pricing("openai")
    base_band = pricing.bands[0]
    bands = tuple(
        base_band.model_copy(update={"band_id": f"band-{index}", "is_base": is_base})
        for index, is_base in enumerate(base_flags)
    )
    invalid = _replace_first_model_pricing(catalog, pricing.model_copy(update={"bands": bands}))

    with pytest.raises(ValueError, match=message):
        validate_catalog(invalid)


@pytest.mark.parametrize("field", ["input", "output"])
def test_rejects_reported_pricing_without_reported_input_or_output(field):
    catalog = make_valid_catalog()
    pricing = make_reported_pricing("openai")
    invalid_band = pricing.bands[0].model_copy(
        update={field: TokenPrice(status=PriceState.NOT_REPORTED)}
    )
    invalid = _replace_first_model_pricing(catalog, pricing.model_copy(update={"bands": (invalid_band,)}))

    with pytest.raises(ValueError, match=f"reported {field} price"):
        validate_catalog(invalid)


def test_rejects_duplicate_pricing_band_ids():
    catalog = make_valid_catalog()
    pricing = make_reported_pricing("openai")
    duplicate_band = pricing.bands[0].model_copy(update={"is_base": False})
    invalid = _replace_first_model_pricing(
        catalog,
        pricing.model_copy(update={"bands": (pricing.bands[0], duplicate_band)}),
    )

    with pytest.raises(ValueError, match="duplicate pricing band ID"):
        validate_catalog(invalid)


def test_rejects_blank_pricing_band_conditions():
    catalog = make_valid_catalog()
    pricing = make_reported_pricing("openai")
    invalid_band = pricing.bands[0].model_copy(update={"condition": " "})
    invalid = _replace_first_model_pricing(catalog, pricing.model_copy(update={"bands": (invalid_band,)}))

    with pytest.raises(ValueError, match="pricing band condition"):
        validate_catalog(invalid)


def test_rejects_non_usd_conversion_without_original_amount():
    catalog = make_valid_catalog()
    pricing = make_reported_pricing("openai")
    converted_price = TokenPrice(
        status=PriceState.REPORTED,
        usd_per_million=1.0,
        source_currency="EUR",
    )
    invalid_band = pricing.bands[0].model_copy(update={"input": converted_price})
    invalid = _replace_first_model_pricing(catalog, pricing.model_copy(update={"bands": (invalid_band,)}))

    with pytest.raises(ValueError, match="original currency and amount"):
        validate_catalog(invalid)


def test_rejects_non_usd_conversion_without_exchange_rate_source():
    catalog = make_valid_catalog()
    pricing = make_reported_pricing("openai")
    converted_price = TokenPrice(
        status=PriceState.REPORTED,
        usd_per_million=1.0,
        source_amount_per_million=0.9,
        source_currency="EUR",
    )
    invalid_band = pricing.bands[0].model_copy(update={"input": converted_price})
    invalid = _replace_first_model_pricing(catalog, pricing.model_copy(update={"bands": (invalid_band,)}))

    with pytest.raises(ValueError, match="exchange-rate source"):
        validate_catalog(invalid)
