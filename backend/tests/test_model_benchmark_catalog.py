from app.model_benchmarks.catalog import (
    CATALOG,
    GOOGLE_GEMINI_OVERVIEW,
    MOONSHOT_K26,
    OPENAI_GPT_56,
    XAI_GROK_45,
    ZAI_GLM_52,
)
from app.model_benchmarks.types import (
    Availability,
    BenchmarkTrack,
    ModelTier,
    Modality,
    PriceState,
    WeightsStatus,
)
from app.model_benchmarks.validation import APPROVED_PROVIDER_IDS, validate_catalog


CANONICAL_BENCHMARKS = {
    "swe-bench-pro": (
        "SWE-bench Pro",
        "https://labs.scale.com/leaderboard/swe_bench_pro_public",
    ),
    "terminal-bench-2-1": (
        "Terminal-Bench 2.1",
        "https://www.tbench.ai/news/terminal-bench-2-1",
    ),
    "charxiv": ("CharXiv", "https://charxiv.github.io/"),
    "mmmu-pro": ("MMMU-Pro", "https://github.com/MMMU-Benchmark/MMMU"),
    "mmmu-pro-tools": (
        "MMMU-Pro (Tools)",
        "https://github.com/MMMU-Benchmark/MMMU",
    ),
}

CANONICAL_SCORE_VALUES = {
    ("gpt-5-6-sol", "swe-bench-pro"): 64.6,
    ("gpt-5-6-terra", "swe-bench-pro"): 63.4,
    ("gpt-5-6-luna", "swe-bench-pro"): 62.7,
    ("glm-5-2", "swe-bench-pro"): 62.1,
    ("gemini-3-5-flash", "swe-bench-pro"): 55.1,
    ("gemini-3-1-pro", "swe-bench-pro"): 54.2,
    ("grok-4-5", "swe-bench-pro"): 64.7,
    ("kimi-k2-6", "swe-bench-pro"): 58.6,
    ("gpt-5-6-sol", "terminal-bench-2-1"): 88.8,
    ("gpt-5-6-terra", "terminal-bench-2-1"): 87.4,
    ("gpt-5-6-luna", "terminal-bench-2-1"): 84.7,
    ("glm-5-2", "terminal-bench-2-1"): 81.0,
    ("gemini-3-5-flash", "terminal-bench-2-1"): 76.2,
    ("gemini-3-1-pro", "terminal-bench-2-1"): 70.3,
    ("gemini-3-1-pro", "charxiv"): 83.3,
    ("kimi-k2-6", "charxiv"): 86.7,
    ("gpt-5-6-sol", "mmmu-pro"): 83.0,
    ("gpt-5-6-terra", "mmmu-pro"): 80.7,
    ("gpt-5-6-luna", "mmmu-pro"): 78.4,
    ("gemini-3-5-flash", "mmmu-pro"): 83.6,
    ("gpt-5-6-sol", "mmmu-pro-tools"): 84.6,
    ("gpt-5-6-terra", "mmmu-pro-tools"): 82.0,
    ("gpt-5-6-luna", "mmmu-pro-tools"): 79.5,
}


def test_shipped_catalog_uses_canonical_benchmark_columns_and_official_sources():
    benchmarks = {
        benchmark.id: benchmark
        for benchmark in CATALOG.benchmarks
        if benchmark.id in CANONICAL_BENCHMARKS
    }

    assert {
        benchmark_id: (benchmark.display_name, str(benchmark.official_source.url))
        for benchmark_id, benchmark in benchmarks.items()
    } == CANONICAL_BENCHMARKS
    assert all(benchmark.official_source.provider_id is None for benchmark in benchmarks.values())
    for benchmark_id in ("swe-bench-pro", "terminal-bench-2-1", "charxiv"):
        assert any(
            "not strictly apples-to-apples" in limitation
            for limitation in benchmarks[benchmark_id].info.limitations
        )


def test_canonical_metric_scores_preserve_values_sources_and_setups():
    scores = {
        (score.model_id, score.benchmark_id): score
        for score in CATALOG.scores
        if score.benchmark_id in CANONICAL_BENCHMARKS
    }
    expected_sources = {
        "gpt-5-6-sol": OPENAI_GPT_56,
        "gpt-5-6-terra": OPENAI_GPT_56,
        "gpt-5-6-luna": OPENAI_GPT_56,
        "glm-5-2": ZAI_GLM_52,
        "gemini-3-5-flash": GOOGLE_GEMINI_OVERVIEW,
        "gemini-3-1-pro": GOOGLE_GEMINI_OVERVIEW,
        "grok-4-5": XAI_GROK_45,
        "kimi-k2-6": MOONSHOT_K26,
    }

    assert {key: score.value for key, score in scores.items()} == CANONICAL_SCORE_VALUES
    for (model_id, _benchmark_id), score in scores.items():
        assert score.source is expected_sources[model_id]
        assert score.setup


def test_shipped_catalog_has_exact_approved_roster():
    validate_catalog(CATALOG)

    assert {provider.id for provider in CATALOG.providers} == APPROVED_PROVIDER_IDS
    assert len(CATALOG.models) == 30
    for provider_id in APPROVED_PROVIDER_IDS:
        models = [model for model in CATALOG.models if model.provider_id == provider_id]
        assert {model.tier for model in models} == set(ModelTier)
        assert len({model.id for model in models}) == 3


def test_shipped_scores_use_own_provider_sources():
    models = {model.id: model for model in CATALOG.models}

    for score in CATALOG.scores:
        assert score.source.provider_id == models[score.model_id].provider_id


def test_weights_only_models_never_use_third_party_prices():
    for model in CATALOG.models:
        if model.availability is Availability.OFFICIAL_WEIGHTS:
            assert model.pricing.status is PriceState.NOT_APPLICABLE


def test_api_and_weights_models_use_direct_api_prices_or_honest_missing_state():
    api_and_weights_models = [
        model
        for model in CATALOG.models
        if model.availability is Availability.OFFICIAL_API_AND_WEIGHTS
    ]

    assert api_and_weights_models
    assert all(model.pricing.status is not PriceState.NOT_APPLICABLE for model in api_and_weights_models)
    assert {
        model.id for model in api_and_weights_models if model.pricing.status is PriceState.NOT_REPORTED
    } == {"deepseek-v3-2"}


def test_deepseek_v4_direct_api_prices_match_the_official_pricing_page():
    models = {model.id: model for model in CATALOG.models}

    assert str(models["deepseek-v4-pro"].pricing.source.url) == "https://api-docs.deepseek.com/quick_start/pricing"
    assert str(models["deepseek-v4-flash"].pricing.source.url) == "https://api-docs.deepseek.com/quick_start/pricing"
    assert [
        (
            band.cached_input.usd_per_million,
            band.input.usd_per_million,
            band.output.usd_per_million,
        )
        for band in models["deepseek-v4-flash"].pricing.bands
    ] == [(0.0028, 0.14, 0.28)]
    assert [
        (
            band.cached_input.usd_per_million,
            band.input.usd_per_million,
            band.output.usd_per_million,
        )
        for band in models["deepseek-v4-pro"].pricing.bands
    ] == [(0.003625, 0.435, 0.87)]


def test_shipped_benchmarks_cover_both_tracks_and_have_scores():
    score_counts = {benchmark.id: 0 for benchmark in CATALOG.benchmarks}
    for score in CATALOG.scores:
        score_counts[score.benchmark_id] += 1

    assert {benchmark.track for benchmark in CATALOG.benchmarks} == set(BenchmarkTrack)
    assert all(score_counts.values())


def test_shipped_catalog_uses_https_sources_and_full_model_names():
    generic_names = {"Frontier", "Mid-range", "Lite"}
    sources = [
        *(model.specification_source for model in CATALOG.models),
        *(model.pricing.source for model in CATALOG.models),
        *(benchmark.official_source for benchmark in CATALOG.benchmarks),
        *(score.source for score in CATALOG.scores),
    ]

    assert all(str(provider.website).startswith("https://") for provider in CATALOG.providers)
    assert all(str(source.url).startswith("https://") for source in sources)
    assert all(model.display_name not in generic_names for model in CATALOG.models)


def test_openai_gpt_5_6_rows_include_official_gpqa_and_mmmu_scores():
    scores = {(score.model_id, score.benchmark_id): score.value for score in CATALOG.scores}

    assert scores[("gpt-5-6-sol", "gpqa-diamond")] == 94.6
    assert scores[("gpt-5-6-terra", "gpqa-diamond")] == 92.9
    assert scores[("gpt-5-6-luna", "gpqa-diamond")] == 92.3
    assert scores[("gpt-5-6-sol", "mmmu-pro")] == 83.0
    assert scores[("gpt-5-6-terra", "mmmu-pro")] == 80.7
    assert scores[("gpt-5-6-luna", "mmmu-pro")] == 78.4
    assert scores[("gpt-5-6-sol", "mmmu-pro-tools")] == 84.6
    assert scores[("gpt-5-6-terra", "mmmu-pro-tools")] == 82.0
    assert scores[("gpt-5-6-luna", "mmmu-pro-tools")] == 79.5


def test_openai_deep_swe_release_table_rows_remain_versioned():
    benchmarks = {benchmark.id: benchmark for benchmark in CATALOG.benchmarks}
    benchmark = benchmarks["deep-swe-1-1-openai-release-table"]
    scores = [
        score
        for score in CATALOG.scores
        if score.benchmark_id == "deep-swe-1-1-openai-release-table"
    ]

    assert benchmark.track is BenchmarkTrack.TEXT_CODE
    assert benchmark.setup_variant == "OpenAI release table; harness not further disclosed"
    assert benchmark.dataset_edition == "DeepSWE v1.1"
    assert benchmark.info.dataset_and_edition == (
        "DeepSWE v1.1, as reported in OpenAI's GPT-5.6 release table."
    )
    assert benchmark.official_source is OPENAI_GPT_56
    assert {score.model_id: score.value for score in scores} == {
        "gpt-5-6-sol": 72.7,
        "gpt-5-6-terra": 69.6,
        "gpt-5-6-luna": 67.2,
    }
    assert all(score.setup == () and score.source is OPENAI_GPT_56 for score in scores)
    assert benchmarks["deep-swe-1-0"].info.dataset_and_edition == (
        "DeepSWE 1.0, as evaluated by Datacurve."
    )


def test_google_rows_use_direct_standard_api_pricing():
    models = {model.id: model for model in CATALOG.models}
    pro = models["gemini-3-1-pro"].pricing
    flash = models["gemini-3-5-flash"].pricing
    flash_lite = models["gemini-3-1-flash-lite"].pricing

    assert str(pro.source.url) == "https://ai.google.dev/gemini-api/docs/pricing"
    assert [(band.input.usd_per_million, band.cached_input.usd_per_million, band.output.usd_per_million) for band in pro.bands] == [
        (2.0, 0.2, 12.0),
        (4.0, 0.4, 18.0),
    ]
    assert [(band.input.usd_per_million, band.cached_input.usd_per_million, band.output.usd_per_million) for band in flash.bands] == [
        (1.5, 0.15, 9.0)
    ]
    assert [(band.input.usd_per_million, band.cached_input.usd_per_million, band.output.usd_per_million) for band in flash_lite.bands] == [
        (0.25, 0.025, 1.5)
    ]


def test_anthropic_direct_api_prices_include_official_cache_hit_rates():
    models = {model.id: model for model in CATALOG.models}

    assert str(models["claude-opus-4-8"].pricing.source.url) == "https://platform.claude.com/docs/en/about-claude/pricing"
    assert [
        (band.input.usd_per_million, band.cached_input.usd_per_million, band.output.usd_per_million)
        for band in models["claude-opus-4-8"].pricing.bands
    ] == [(5.0, 0.5, 25.0)]
    assert [
        (band.input.usd_per_million, band.cached_input.usd_per_million, band.output.usd_per_million)
        for band in models["claude-sonnet-5"].pricing.bands
    ] == [(2.0, 0.2, 10.0), (3.0, 0.3, 15.0)]
    assert [
        (band.input.usd_per_million, band.cached_input.usd_per_million, band.output.usd_per_million)
        for band in models["claude-haiku-4-5"].pricing.bands
    ] == [(1.0, 0.1, 5.0)]


def test_kimi_k2_5_uses_direct_official_api_pricing():
    pricing = next(model.pricing for model in CATALOG.models if model.id == "kimi-k2-5")

    assert str(pricing.source.url) == "https://platform.kimi.ai/"
    assert [
        (band.input.usd_per_million, band.cached_input.usd_per_million, band.output.usd_per_million)
        for band in pricing.bands
    ] == [(0.6, 0.1, 3.0)]


def test_qwen_3_6_prices_preserve_context_tiers_and_cache_modes():
    models = {model.id: model for model in CATALOG.models}

    for model_id, expected_bands in {
        "qwen3-6-plus": [
            (0.276, 0.0276, 1.651),
            (0.276, 0.0552, 1.651),
            (1.101, 0.1101, 6.602),
            (1.101, 0.2202, 6.602),
        ],
        "qwen3-6-flash": [
            (0.25, 0.025, 1.5),
            (0.25, 0.05, 1.5),
            (1.0, 0.1, 4.0),
            (1.0, 0.2, 4.0),
        ],
    }.items():
        bands = models[model_id].pricing.bands
        assert len(bands) == 4
        assert sum(band.is_base for band in bands) == 1
        assert [
            (band.input.usd_per_million, band.cached_input.usd_per_million, band.output.usd_per_million)
            for band in bands
        ] == expected_bands
        assert {"explicit", "implicit"} <= {mode for band in bands for mode in band.label.lower().split()}
        assert all("cache hit" in band.condition.lower() for band in bands)


def test_qwen_3_7_max_preserves_its_official_cache_modes():
    pricing = next(model.pricing for model in CATALOG.models if model.id == "qwen3-7-max")

    assert pricing.status is PriceState.REPORTED
    assert sum(band.is_base for band in pricing.bands) == 1
    assert [
        (band.input.usd_per_million, band.cached_input.usd_per_million, band.output.usd_per_million)
        for band in pricing.bands
    ] == [(2.5, 0.25, 7.5), (2.5, 0.5, 7.5)]
    assert {"explicit", "implicit"} <= {
        mode for band in pricing.bands for mode in band.label.lower().split()
    }
    assert all("cache hit" in band.condition.lower() for band in pricing.bands)


def test_minimax_m3_matches_its_official_multimodal_context_specification():
    m3 = next(model for model in CATALOG.models if model.id == "minimax-m3")

    assert m3.context_window_tokens == 1_000_000
    assert {Modality.TEXT, Modality.IMAGE, Modality.VIDEO} <= set(m3.input_modalities)
    assert m3.weights_status is WeightsStatus.OPEN_WEIGHT
    assert m3.availability is Availability.OFFICIAL_API_AND_WEIGHTS
    assert m3.pricing.status is PriceState.REPORTED


def test_deep_swe_source_discloses_external_evaluator_and_provider_harness():
    score = next(
        score
        for score in CATALOG.scores
        if score.model_id == "grok-4-5" and score.benchmark_id == "deep-swe-1-0"
    )

    assert {detail.label: detail.value for detail in score.setup} == {
        "Evaluation": "Created by Datacurve; run with provider harnesses by Artificial Analysis"
    }
