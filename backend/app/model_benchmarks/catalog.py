"""Curated, provider-published model benchmark catalog.

The catalog is deliberately static: it is an audited product record, not a
runtime scraper.  Every URL below is an official first-party source checked on
2026-07-13.  A missing provider disclosure stays missing rather than becoming
an inferred score or a third-party hosting price.
"""

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
from app.model_benchmarks.validation import validate_catalog


CATALOG_VERSION = "2026-07-13"
LAST_VERIFIED_AT = date(2026, 7, 13)


def _source(
    title: str,
    publisher: str,
    provider_id: str | None,
    url: str,
    published_at: date | None,
) -> SourceReference:
    return SourceReference(
        title=title,
        publisher=publisher,
        provider_id=provider_id,
        url=url,
        published_at=published_at,
        verified_at=LAST_VERIFIED_AT,
    )


SWE_BENCH_PRO_SOURCE = _source(
    "SWE-bench Pro public leaderboard",
    "Scale Labs",
    None,
    "https://labs.scale.com/leaderboard/swe_bench_pro_public",
    None,
)
TERMINAL_BENCH_21_SOURCE = _source(
    "Terminal-Bench 2.1",
    "Terminal-Bench",
    None,
    "https://www.tbench.ai/news/terminal-bench-2-1",
    None,
)
MMMU_PRO_SOURCE = _source(
    "MMMU-Pro benchmark",
    "MMMU Benchmark",
    None,
    "https://github.com/MMMU-Benchmark/MMMU",
    None,
)
CHARXIV_SOURCE = _source(
    "CharXiv benchmark",
    "CharXiv",
    None,
    "https://charxiv.github.io/",
    None,
)


def _reported_pricing(
    source: SourceReference,
    input_price: float,
    cached_input_price: float | None,
    output_price: float,
    condition: str = "Standard direct API price per 1 million tokens",
) -> ModelPricing:
    return ModelPricing(
        status=PriceState.REPORTED,
        source=source,
        bands=(
            PricingBand(
                band_id="standard",
                label="Standard",
                condition=condition,
                is_base=True,
                input=TokenPrice(
                    status=PriceState.REPORTED, usd_per_million=input_price
                ),
                cached_input=(
                    TokenPrice(status=PriceState.REPORTED, usd_per_million=cached_input_price)
                    if cached_input_price is not None
                    else TokenPrice(status=PriceState.NOT_REPORTED)
                ),
                output=TokenPrice(
                    status=PriceState.REPORTED, usd_per_million=output_price
                ),
            ),
        ),
    )


def _not_reported_pricing(source: SourceReference, note: str) -> ModelPricing:
    return ModelPricing(status=PriceState.NOT_REPORTED, source=source, note=note)


def _not_applicable_pricing(source: SourceReference, note: str) -> ModelPricing:
    return ModelPricing(status=PriceState.NOT_APPLICABLE, source=source, note=note)


def _reported_pricing_bands(
    source: SourceReference, bands: tuple[PricingBand, ...]
) -> ModelPricing:
    return ModelPricing(status=PriceState.REPORTED, source=source, bands=bands)


def _reported_band(
    band_id: str,
    label: str,
    condition: str,
    input_price: float,
    cached_input_price: float,
    output_price: float,
    *,
    is_base: bool = False,
) -> PricingBand:
    return PricingBand(
        band_id=band_id,
        label=label,
        condition=condition,
        is_base=is_base,
        input=TokenPrice(status=PriceState.REPORTED, usd_per_million=input_price),
        cached_input=TokenPrice(
            status=PriceState.REPORTED, usd_per_million=cached_input_price
        ),
        output=TokenPrice(status=PriceState.REPORTED, usd_per_million=output_price),
    )


# OpenAI
OPENAI_GPT_56 = _source(
    "GPT-5.6: Frontier intelligence that scales with your ambition",
    "OpenAI",
    "openai",
    "https://openai.com/index/gpt-5-6/",
    date(2026, 7, 9),
)
OPENAI_MODELS = _source(
    "OpenAI API model documentation",
    "OpenAI",
    "openai",
    "https://developers.openai.com/api/docs/models",
    None,
)

# Anthropic
ANTHROPIC_OPUS_48 = _source(
    "Claude Opus 4.8",
    "Anthropic",
    "anthropic",
    "https://www.anthropic.com/claude/opus",
    date(2026, 5, 28),
)
ANTHROPIC_SONNET_5 = _source(
    "Introducing Claude Sonnet 5",
    "Anthropic",
    "anthropic",
    "https://www.anthropic.com/news/claude-sonnet-5",
    date(2026, 6, 30),
)
ANTHROPIC_HAIKU_45 = _source(
    "Introducing Claude Haiku 4.5",
    "Anthropic",
    "anthropic",
    "https://www.anthropic.com/news/claude-haiku-4-5",
    date(2025, 10, 15),
)
ANTHROPIC_API_PRICING = _source(
    "Claude API model pricing",
    "Anthropic",
    "anthropic",
    "https://platform.claude.com/docs/en/about-claude/pricing",
    None,
)

# Google
GOOGLE_GEMINI_31_PRO = _source(
    "Gemini 3.1 Pro model card",
    "Google DeepMind",
    "google",
    "https://deepmind.google/models/model-cards/gemini-3-1-pro/",
    date(2026, 2, 19),
)
GOOGLE_GEMINI_35_FLASH = _source(
    "Gemini 3.5 Flash model card",
    "Google DeepMind",
    "google",
    "https://deepmind.google/models/model-cards/gemini-3-5-flash/",
    date(2026, 5, 19),
)
GOOGLE_GEMINI_31_FLASH_LITE = _source(
    "Gemini 3.1 Flash-Lite model card",
    "Google DeepMind",
    "google",
    "https://deepmind.google/models/model-cards/gemini-3-1-flash-lite/",
    date(2026, 3, 3),
)
GOOGLE_GEMINI_OVERVIEW = _source(
    "Gemini model overview and evaluations",
    "Google DeepMind",
    "google",
    "https://deepmind.google/models/gemini/",
    None,
)
GOOGLE_API_PRICING = _source(
    "Gemini Developer API pricing",
    "Google",
    "google",
    "https://ai.google.dev/gemini-api/docs/pricing",
    None,
)

# Meta
META_LLAMA_4 = _source(
    "The Llama 4 herd: natively multimodal AI innovation",
    "Meta",
    "meta",
    "https://ai.meta.com/blog/llama-4-multimodal-intelligence/",
    date(2025, 4, 5),
)
META_LLAMA_32 = _source(
    "Llama 3.2: Revolutionizing edge AI and vision with open, customizable models",
    "Meta",
    "meta",
    "https://ai.meta.com/blog/llama-3-2-connect-2024-vision-edge-mobile-devices/",
    date(2024, 9, 25),
)

# xAI
XAI_GROK_45 = _source(
    "Introducing Grok 4.5",
    "xAI",
    "xai",
    "https://x.ai/news/grok-4-5",
    date(2026, 7, 8),
)
XAI_GROK_43 = _source(
    "Grok model documentation",
    "xAI",
    "xai",
    "https://docs.x.ai/developers/models",
    None,
)
XAI_GROK_420 = _source(
    "Grok 4.20 system card",
    "xAI",
    "xai",
    "https://data.x.ai/2026-04-07-grok-4-20-model-card.pdf",
    date(2026, 4, 7),
)
XAI_PRICING = _source(
    "xAI API pricing",
    "xAI",
    "xai",
    "https://docs.x.ai/developers/pricing",
    None,
)

# Z.AI
ZAI_GLM_52 = _source(
    "GLM-5.2: Built for Long-Horizon Tasks",
    "Z.AI",
    "zai",
    "https://z.ai/blog/glm-5.2",
    date(2026, 6, 16),
)
ZAI_GLM_51 = _source(
    "GLM-5.1 release notes",
    "Z.AI",
    "zai",
    "https://docs.z.ai/release-notes/new-released",
    None,
)
ZAI_GLM_45_AIR = _source(
    "GLM-4.5-Air developer documentation",
    "Z.AI",
    "zai",
    "https://docs.z.ai/guides/overview/pricing",
    None,
)
ZAI_PRICING = _source(
    "Z.AI API pricing",
    "Z.AI",
    "zai",
    "https://docs.z.ai/guides/overview/pricing",
    None,
)

# Alibaba / Qwen
ALIBABA_MODELS = _source(
    "Alibaba Cloud Model Studio recommended models",
    "Alibaba Cloud",
    "alibaba",
    "https://www.alibabacloud.com/help/en/model-studio/models",
    date(2026, 7, 2),
)
ALIBABA_PRICING = _source(
    "Alibaba Cloud Model Studio model pricing and Context Cache",
    "Alibaba Cloud",
    "alibaba",
    "https://www.alibabacloud.com/help/en/model-studio/model-pricing",
    date(2026, 7, 8),
)

# DeepSeek
DEEPSEEK_V4 = _source(
    "DeepSeek V4 preview release",
    "DeepSeek",
    "deepseek",
    "https://api-docs.deepseek.com/news/news260424/",
    date(2026, 4, 24),
)
DEEPSEEK_V32 = _source(
    "DeepSeek API change log: DeepSeek-V3.2",
    "DeepSeek",
    "deepseek",
    "https://api-docs.deepseek.com/updates",
    date(2025, 12, 1),
)
DEEPSEEK_PRICING = _source(
    "DeepSeek API pricing",
    "DeepSeek",
    "deepseek",
    "https://api-docs.deepseek.com/quick_start/pricing",
    None,
)

# Moonshot AI / Kimi
MOONSHOT_K27 = _source(
    "Here comes Kimi K2.7 Code: Better Coding with more efficiency",
    "Moonshot AI",
    "moonshot",
    "https://forum.moonshot.ai/t/here-comes-kimi-k2-7-code-better-coding-with-more-efficiency/441",
    date(2026, 6, 16),
)
MOONSHOT_K26 = _source(
    "Meet Kimi K2.6: Advancing Open-Source Coding",
    "Moonshot AI",
    "moonshot",
    "https://forum.moonshot.ai/t/meet-kimi-k2-6-advancing-open-source-coding/369",
    date(2026, 4, 21),
)
MOONSHOT_K25 = _source(
    "Kimi K2.5 API is now available",
    "Moonshot AI",
    "moonshot",
    "https://forum.moonshot.ai/t/kimi-k2-5-api-is-now-available/218",
    date(2026, 2, 4),
)
MOONSHOT_K27_PRICING = _source(
    "Kimi K2.7 Code API pricing",
    "Moonshot AI",
    "moonshot",
    "https://platform.kimi.ai/docs/pricing/chat-k27-code",
    None,
)
MOONSHOT_K26_PRICING = _source(
    "Kimi K2.6 API pricing",
    "Moonshot AI",
    "moonshot",
    "https://platform.kimi.ai/docs/pricing/chat-k26",
    None,
)
MOONSHOT_K25_PRICING = _source(
    "Kimi API Platform model pricing",
    "Moonshot AI",
    "moonshot",
    "https://platform.kimi.ai/",
    None,
)

# MiniMax
MINIMAX_M3 = _source(
    "MiniMax M3",
    "MiniMax",
    "minimax",
    "https://www.minimax.io/models/text/m3",
    date(2026, 6, 1),
)
MINIMAX_MODEL_FAMILY = _source(
    "MiniMax model family",
    "MiniMax",
    "minimax",
    "https://www.minimax.io/about",
    None,
)
MINIMAX_M27 = _source(
    "MiniMax M2.7",
    "MiniMax",
    "minimax",
    "https://www.minimax.io/models/text/m27",
    None,
)
MINIMAX_M25 = _source(
    "MiniMax M2.5",
    "MiniMax",
    "minimax",
    "https://www.minimax.io/models/text",
    None,
)
MINIMAX_PRICING = _source(
    "MiniMax API token plan and pricing",
    "MiniMax",
    "minimax",
    "https://platform.minimax.io/subscribe/token-plan?tab=api-enterprise",
    None,
)
MINIMAX_PAYGO_PRICING = _source(
    "MiniMax pay-as-you-go pricing",
    "MiniMax",
    "minimax",
    "https://platform.minimax.io/docs/guides/pricing-paygo",
    None,
)


PROVIDERS = (
    ProviderRecord(id="openai", display_name="OpenAI", website="https://openai.com/"),
    ProviderRecord(
        id="anthropic", display_name="Anthropic", website="https://www.anthropic.com/"
    ),
    ProviderRecord(id="google", display_name="Google", website="https://deepmind.google/"),
    ProviderRecord(id="meta", display_name="Meta", website="https://ai.meta.com/"),
    ProviderRecord(id="xai", display_name="xAI", website="https://x.ai/"),
    ProviderRecord(id="zai", display_name="Z.AI", website="https://z.ai/"),
    ProviderRecord(
        id="alibaba", display_name="Alibaba / Qwen", website="https://www.alibabacloud.com/"
    ),
    ProviderRecord(
        id="deepseek", display_name="DeepSeek", website="https://www.deepseek.com/"
    ),
    ProviderRecord(
        id="moonshot", display_name="Moonshot AI / Kimi", website="https://www.moonshot.ai/"
    ),
    ProviderRecord(id="minimax", display_name="MiniMax", website="https://www.minimax.io/"),
)


MODELS = (
    ModelRecord(
        id="gpt-5-6-sol",
        display_name="GPT-5.6 Sol",
        api_model_id="gpt-5.6-sol",
        provider_id="openai",
        tier=ModelTier.FRONTIER,
        tier_reason="OpenAI positions Sol as the GPT-5.6 flagship for its hardest work.",
        release_date=date(2026, 7, 9),
        context_window_tokens=1_050_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(OPENAI_GPT_56, 5.0, 0.5, 30.0),
        specification_source=OPENAI_MODELS,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="gpt-5-6-terra",
        display_name="GPT-5.6 Terra",
        api_model_id="gpt-5.6-terra",
        provider_id="openai",
        tier=ModelTier.MID_RANGE,
        tier_reason="OpenAI positions Terra as the balanced GPT-5.6 model for everyday work.",
        release_date=date(2026, 7, 9),
        context_window_tokens=1_050_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(OPENAI_GPT_56, 2.5, 0.25, 15.0),
        specification_source=OPENAI_MODELS,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="gpt-5-6-luna",
        display_name="GPT-5.6 Luna",
        api_model_id="gpt-5.6-luna",
        provider_id="openai",
        tier=ModelTier.LITE,
        tier_reason="OpenAI positions Luna as the fastest and most affordable GPT-5.6 model.",
        release_date=date(2026, 7, 9),
        context_window_tokens=1_050_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(OPENAI_GPT_56, 1.0, 0.1, 6.0),
        specification_source=OPENAI_MODELS,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="claude-opus-4-8",
        display_name="Claude Opus 4.8",
        api_model_id="claude-opus-4-8",
        provider_id="anthropic",
        tier=ModelTier.FRONTIER,
        tier_reason="Anthropic's Opus line is its highest-capability model class.",
        release_date=date(2026, 5, 28),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(
            ANTHROPIC_API_PRICING,
            5.0,
            0.5,
            25.0,
            "Standard direct Claude API pricing; prompt-cache hit or refresh rate",
        ),
        specification_source=ANTHROPIC_OPUS_48,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="claude-sonnet-5",
        display_name="Claude Sonnet 5",
        api_model_id="claude-sonnet-5",
        provider_id="anthropic",
        tier=ModelTier.MID_RANGE,
        tier_reason="Anthropic positions Sonnet 5 for frontier work at scale.",
        release_date=date(2026, 6, 30),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing_bands(
            ANTHROPIC_API_PRICING,
            (
                _reported_band(
                    "introductory-through-2026-08-31",
                    "Introductory through August 31, 2026",
                    "Direct Claude API pricing through August 31, 2026; prompt-cache hit or refresh rate",
                    2.0,
                    0.2,
                    10.0,
                    is_base=True,
                ),
                _reported_band(
                    "standard-from-2026-09-01",
                    "Standard from September 1, 2026",
                    "Direct Claude API pricing starting September 1, 2026; prompt-cache hit or refresh rate",
                    3.0,
                    0.3,
                    15.0,
                ),
            ),
        ),
        specification_source=ANTHROPIC_SONNET_5,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="claude-haiku-4-5",
        display_name="Claude Haiku 4.5",
        api_model_id="claude-haiku-4-5",
        provider_id="anthropic",
        tier=ModelTier.LITE,
        tier_reason="Anthropic positions Haiku 4.5 as its economical, low-latency model.",
        release_date=date(2025, 10, 15),
        context_window_tokens=200_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(
            ANTHROPIC_API_PRICING,
            1.0,
            0.1,
            5.0,
            "Standard direct Claude API pricing; prompt-cache hit or refresh rate",
        ),
        specification_source=ANTHROPIC_HAIKU_45,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="gemini-3-1-pro",
        display_name="Gemini 3.1 Pro",
        api_model_id="gemini-3.1-pro-preview",
        provider_id="google",
        tier=ModelTier.FRONTIER,
        tier_reason="Google positions Gemini 3.1 Pro for complex tasks and creative work.",
        release_date=date(2026, 2, 19),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE, Modality.AUDIO, Modality.VIDEO, Modality.PDF),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing_bands(
            GOOGLE_API_PRICING,
            (
                _reported_band(
                    "standard-le-200k",
                    "Standard up to 200K",
                    "Standard paid Gemini API price for prompts up to 200K tokens",
                    2.0,
                    0.2,
                    12.0,
                    is_base=True,
                ),
                _reported_band(
                    "standard-gt-200k",
                    "Standard over 200K",
                    "Standard paid Gemini API price for prompts over 200K tokens",
                    4.0,
                    0.4,
                    18.0,
                ),
            ),
        ),
        specification_source=GOOGLE_GEMINI_31_PRO,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="gemini-3-5-flash",
        display_name="Gemini 3.5 Flash",
        api_model_id="gemini-3.5-flash",
        provider_id="google",
        tier=ModelTier.MID_RANGE,
        tier_reason="Google positions Gemini 3.5 Flash for frontier agents and coding.",
        release_date=date(2026, 5, 19),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE, Modality.AUDIO, Modality.VIDEO, Modality.PDF),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(
            GOOGLE_API_PRICING,
            1.5,
            0.15,
            9.0,
            "Standard paid Gemini API price per 1 million tokens",
        ),
        specification_source=GOOGLE_GEMINI_35_FLASH,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="gemini-3-1-flash-lite",
        display_name="Gemini 3.1 Flash-Lite",
        api_model_id="gemini-3.1-flash-lite",
        provider_id="google",
        tier=ModelTier.LITE,
        tier_reason="Google positions Flash-Lite for efficient, high-volume tasks.",
        release_date=date(2026, 3, 3),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE, Modality.AUDIO, Modality.VIDEO, Modality.PDF),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(
            GOOGLE_API_PRICING,
            0.25,
            0.025,
            1.5,
            "Standard paid Gemini API price for text, image, and video input per 1 million tokens",
        ),
        specification_source=GOOGLE_GEMINI_31_FLASH_LITE,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="llama-4-maverick",
        display_name="Llama 4 Maverick",
        provider_id="meta",
        tier=ModelTier.FRONTIER,
        tier_reason="Meta's larger Llama 4 release is its high-quality multimodal general model.",
        release_date=date(2025, 4, 5),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.OPEN_WEIGHT,
        availability=Availability.OFFICIAL_WEIGHTS,
        pricing=_not_applicable_pricing(META_LLAMA_4, "Meta supplies official weights; no direct Meta token price is mixed in."),
        specification_source=META_LLAMA_4,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="llama-4-scout",
        display_name="Llama 4 Scout",
        provider_id="meta",
        tier=ModelTier.MID_RANGE,
        tier_reason="Meta positions Scout for efficient long-context multimodal use on one H100 GPU.",
        release_date=date(2025, 4, 5),
        context_window_tokens=10_000_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.OPEN_WEIGHT,
        availability=Availability.OFFICIAL_WEIGHTS,
        pricing=_not_applicable_pricing(META_LLAMA_4, "Meta supplies official weights; no direct Meta token price is mixed in."),
        specification_source=META_LLAMA_4,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="llama-3-2-3b-instruct",
        display_name="Llama 3.2 3B Instruct",
        provider_id="meta",
        tier=ModelTier.LITE,
        tier_reason="Meta released this small instruction model for on-device and edge use.",
        release_date=date(2024, 9, 25),
        context_window_tokens=128_000,
        input_modalities=(Modality.TEXT,),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.OPEN_WEIGHT,
        availability=Availability.OFFICIAL_WEIGHTS,
        pricing=_not_applicable_pricing(META_LLAMA_32, "Meta supplies official weights; no direct Meta token price is mixed in."),
        specification_source=META_LLAMA_32,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="grok-4-5",
        display_name="Grok 4.5",
        api_model_id="grok-4.5",
        provider_id="xai",
        tier=ModelTier.FRONTIER,
        tier_reason="xAI describes Grok 4.5 as its smartest model and strongest model ever.",
        release_date=date(2026, 7, 8),
        context_window_tokens=500_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(XAI_PRICING, 2.0, 0.5, 6.0),
        specification_source=XAI_GROK_45,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="grok-4-3",
        display_name="Grok 4.3",
        api_model_id="grok-4.3",
        provider_id="xai",
        tier=ModelTier.MID_RANGE,
        tier_reason="xAI documents Grok 4.3 as a current direct API model below Grok 4.5.",
        release_date=date(2026, 5, 1),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(XAI_PRICING, 1.25, 0.2, 2.5),
        specification_source=XAI_GROK_43,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="grok-4-20-multi-agent",
        display_name="Grok 4.20 Multi-Agent",
        api_model_id="grok-4.20-multi-agent-0309",
        provider_id="xai",
        tier=ModelTier.LITE,
        tier_reason="Editorial placement: the released Grok 4.20 model card represents xAI's closest smaller current family option.",
        release_date=date(2026, 4, 7),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(XAI_PRICING, 1.25, 0.2, 2.5),
        specification_source=XAI_GROK_420,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="glm-5-2",
        display_name="GLM-5.2",
        api_model_id="GLM-5.2",
        provider_id="zai",
        tier=ModelTier.FRONTIER,
        tier_reason="Z.AI calls GLM-5.2 its latest flagship for long-horizon tasks.",
        release_date=date(2026, 6, 16),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT,),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.OPEN_WEIGHT,
        availability=Availability.OFFICIAL_API_AND_WEIGHTS,
        pricing=_reported_pricing(ZAI_PRICING, 1.4, 0.26, 4.4),
        specification_source=ZAI_GLM_52,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="glm-5-1",
        display_name="GLM-5.1",
        api_model_id="glm-5.1",
        provider_id="zai",
        tier=ModelTier.MID_RANGE,
        tier_reason="Z.AI positions GLM-5.1 as a high-capability API model below GLM-5.2.",
        release_date=date(2026, 4, 27),
        context_window_tokens=200_000,
        input_modalities=(Modality.TEXT,),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(ZAI_PRICING, 1.4, 0.26, 4.4),
        specification_source=ZAI_GLM_51,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="glm-4-5-air",
        display_name="GLM-4.5-Air",
        api_model_id="glm-4.5-air",
        provider_id="zai",
        tier=ModelTier.LITE,
        tier_reason="Z.AI positions GLM-4.5-Air as the efficient member of the GLM 4.5 line.",
        release_date=date(2025, 7, 28),
        context_window_tokens=128_000,
        input_modalities=(Modality.TEXT,),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.OPEN_WEIGHT,
        availability=Availability.OFFICIAL_API_AND_WEIGHTS,
        pricing=_reported_pricing(ZAI_PRICING, 0.2, 0.03, 1.1),
        specification_source=ZAI_GLM_45_AIR,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="qwen3-7-max",
        display_name="Qwen3.7-Max",
        api_model_id="qwen3.7-max",
        provider_id="alibaba",
        tier=ModelTier.FRONTIER,
        tier_reason="Alibaba Cloud lists Qwen3.7-Max as the most capable current Qwen text model.",
        release_date=date(2026, 5, 20),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT,),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing_bands(
            ALIBABA_PRICING,
            (
                _reported_band(
                    "explicit-cache",
                    "Explicit cache",
                    "International deployment, input up to 1M; explicit context-cache hit billed at 10% of the standard input price",
                    2.5,
                    0.25,
                    7.5,
                    is_base=True,
                ),
                _reported_band(
                    "implicit-cache",
                    "Implicit cache",
                    "International deployment, input up to 1M; implicit context-cache hit billed at 20% of the standard input price",
                    2.5,
                    0.5,
                    7.5,
                ),
            ),
        ),
        specification_source=ALIBABA_MODELS,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="qwen3-6-plus",
        display_name="Qwen3.6-Plus",
        api_model_id="qwen3.6-plus-2026-04-02",
        provider_id="alibaba",
        tier=ModelTier.MID_RANGE,
        tier_reason="Alibaba Cloud positions the Plus line between Max and Flash for capable general use.",
        release_date=date(2026, 4, 2),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing_bands(
            ALIBABA_PRICING,
            (
                _reported_band(
                    "explicit-cache-le-256k",
                    "Explicit cache, up to 256K",
                    "International deployment, input up to 256K; explicit context-cache hit billed at 10% of the standard input price",
                    0.276,
                    0.0276,
                    1.651,
                    is_base=True,
                ),
                _reported_band(
                    "implicit-cache-le-256k",
                    "Implicit cache, up to 256K",
                    "International deployment, input up to 256K; implicit context-cache hit billed at 20% of the standard input price",
                    0.276,
                    0.0552,
                    1.651,
                ),
                _reported_band(
                    "explicit-cache-gt-256k",
                    "Explicit cache, over 256K",
                    "International deployment, input over 256K through 1M; explicit context-cache hit billed at 10% of the standard input price",
                    1.101,
                    0.1101,
                    6.602,
                ),
                _reported_band(
                    "implicit-cache-gt-256k",
                    "Implicit cache, over 256K",
                    "International deployment, input over 256K through 1M; implicit context-cache hit billed at 20% of the standard input price",
                    1.101,
                    0.2202,
                    6.602,
                ),
            ),
        ),
        specification_source=ALIBABA_MODELS,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="qwen3-6-flash",
        display_name="Qwen3.6-Flash",
        api_model_id="qwen3.6-flash-2026-04-16",
        provider_id="alibaba",
        tier=ModelTier.LITE,
        tier_reason="Alibaba Cloud positions Qwen3.6-Flash as the cost-effective Qwen text model.",
        release_date=date(2026, 4, 16),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT,),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing_bands(
            ALIBABA_PRICING,
            (
                _reported_band(
                    "explicit-cache-le-256k",
                    "Explicit cache, up to 256K",
                    "International deployment, input up to 256K; explicit context-cache hit billed at 10% of the standard input price",
                    0.25,
                    0.025,
                    1.5,
                    is_base=True,
                ),
                _reported_band(
                    "implicit-cache-le-256k",
                    "Implicit cache, up to 256K",
                    "International deployment, input up to 256K; implicit context-cache hit billed at 20% of the standard input price",
                    0.25,
                    0.05,
                    1.5,
                ),
                _reported_band(
                    "explicit-cache-gt-256k",
                    "Explicit cache, over 256K",
                    "International deployment, input over 256K through 1M; explicit context-cache hit billed at 10% of the standard input price",
                    1.0,
                    0.1,
                    4.0,
                ),
                _reported_band(
                    "implicit-cache-gt-256k",
                    "Implicit cache, over 256K",
                    "International deployment, input over 256K through 1M; implicit context-cache hit billed at 20% of the standard input price",
                    1.0,
                    0.2,
                    4.0,
                ),
            ),
        ),
        specification_source=ALIBABA_MODELS,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="deepseek-v4-pro",
        display_name="DeepSeek-V4-Pro",
        api_model_id="deepseek-v4-pro",
        provider_id="deepseek",
        tier=ModelTier.FRONTIER,
        tier_reason="DeepSeek's V4-Pro is the larger current V4 API option.",
        release_date=date(2026, 4, 24),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT,),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.OPEN_WEIGHT,
        availability=Availability.OFFICIAL_API_AND_WEIGHTS,
        pricing=_reported_pricing(DEEPSEEK_PRICING, 0.435, 0.003625, 0.87),
        specification_source=DEEPSEEK_V4,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="deepseek-v4-flash",
        display_name="DeepSeek-V4-Flash",
        api_model_id="deepseek-v4-flash",
        provider_id="deepseek",
        tier=ModelTier.MID_RANGE,
        tier_reason="DeepSeek positions V4-Flash as the efficient current V4 API option.",
        release_date=date(2026, 4, 24),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT,),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.OPEN_WEIGHT,
        availability=Availability.OFFICIAL_API_AND_WEIGHTS,
        pricing=_reported_pricing(DEEPSEEK_PRICING, 0.14, 0.0028, 0.28),
        specification_source=DEEPSEEK_V4,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="deepseek-v3-2",
        display_name="DeepSeek-V3.2",
        api_model_id="deepseek-v3.2",
        provider_id="deepseek",
        tier=ModelTier.LITE,
        tier_reason="Editorial placement: V3.2 is the closest earlier released DeepSeek API generation for the lite tier.",
        release_date=date(2025, 12, 1),
        context_window_tokens=128_000,
        input_modalities=(Modality.TEXT,),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.OPEN_WEIGHT,
        availability=Availability.OFFICIAL_API_AND_WEIGHTS,
        pricing=_not_reported_pricing(
            DEEPSEEK_PRICING,
            "The current official pricing page lists DeepSeek-V4-Flash and DeepSeek-V4-Pro, not a DeepSeek-V3.2 rate.",
        ),
        specification_source=DEEPSEEK_V32,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="kimi-k2-7-code",
        display_name="Kimi K2.7 Code",
        api_model_id="kimi-k2.7-code",
        provider_id="moonshot",
        tier=ModelTier.FRONTIER,
        tier_reason="Moonshot presents K2.7 Code as its newer, more efficient coding model.",
        release_date=date(2026, 6, 16),
        context_window_tokens=256_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.OPEN_WEIGHT,
        availability=Availability.OFFICIAL_API_AND_WEIGHTS,
        pricing=_reported_pricing(MOONSHOT_K27_PRICING, 0.95, 0.19, 4.0),
        specification_source=MOONSHOT_K27,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="kimi-k2-6",
        display_name="Kimi K2.6",
        api_model_id="kimi-k2.6",
        provider_id="moonshot",
        tier=ModelTier.MID_RANGE,
        tier_reason="Moonshot's K2.6 is the released open-source model below K2.7 Code.",
        release_date=date(2026, 4, 21),
        context_window_tokens=256_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.OPEN_WEIGHT,
        availability=Availability.OFFICIAL_API_AND_WEIGHTS,
        pricing=_reported_pricing(MOONSHOT_K26_PRICING, 0.95, 0.16, 4.0),
        specification_source=MOONSHOT_K26,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="kimi-k2-5",
        display_name="Kimi K2.5",
        api_model_id="kimi-k2.5",
        provider_id="moonshot",
        tier=ModelTier.LITE,
        tier_reason="Editorial placement: K2.5 is Moonshot's earlier released API option for the lite tier.",
        release_date=date(2026, 2, 4),
        context_window_tokens=256_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(MOONSHOT_K25_PRICING, 0.6, 0.1, 3.0),
        specification_source=MOONSHOT_K25,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="minimax-m3",
        display_name="MiniMax M3",
        api_model_id="MiniMax-M3",
        provider_id="minimax",
        tier=ModelTier.FRONTIER,
        tier_reason="MiniMax positions M3 for coding and agentic work with 1M context and native multimodality.",
        release_date=date(2026, 6, 1),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE, Modality.VIDEO),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.OPEN_WEIGHT,
        availability=Availability.OFFICIAL_API_AND_WEIGHTS,
        pricing=_reported_pricing_bands(
            MINIMAX_PAYGO_PRICING,
            (
                _reported_band(
                    "standard-le-512k",
                    "Standard up to 512K",
                    "Standard pay-as-you-go price after the published permanent 50% discount for input up to 512K tokens",
                    0.3,
                    0.06,
                    1.2,
                    is_base=True,
                ),
                _reported_band(
                    "standard-gt-512k",
                    "Standard over 512K",
                    "Standard pay-as-you-go price after the published permanent 50% discount for input over 512K tokens",
                    0.6,
                    0.12,
                    2.4,
                ),
            ),
        ),
        specification_source=MINIMAX_M3,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="minimax-m2-7",
        display_name="MiniMax M2.7",
        api_model_id="MiniMax-M2.7",
        provider_id="minimax",
        tier=ModelTier.MID_RANGE,
        tier_reason="MiniMax lists M2.7 as the current balanced model below M3.",
        release_date=date(2026, 3, 18),
        context_window_tokens=1_000_000,
        input_modalities=(Modality.TEXT, Modality.IMAGE, Modality.VIDEO),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.CLOSED,
        availability=Availability.OFFICIAL_API,
        pricing=_reported_pricing(MINIMAX_PAYGO_PRICING, 0.3, 0.06, 1.2),
        specification_source=MINIMAX_M27,
        verified_at=LAST_VERIFIED_AT,
    ),
    ModelRecord(
        id="minimax-m2-5",
        display_name="MiniMax M2.5",
        api_model_id="MiniMax-M2.5",
        provider_id="minimax",
        tier=ModelTier.LITE,
        tier_reason="Editorial placement: M2.5 is MiniMax's closest earlier released efficient text model.",
        release_date=date(2026, 2, 1),
        context_window_tokens=204_800,
        input_modalities=(Modality.TEXT,),
        output_modalities=(Modality.TEXT,),
        weights_status=WeightsStatus.OPEN_WEIGHT,
        availability=Availability.OFFICIAL_API_AND_WEIGHTS,
        pricing=_reported_pricing(MINIMAX_PAYGO_PRICING, 0.3, 0.03, 1.2),
        specification_source=MINIMAX_M25,
        verified_at=LAST_VERIFIED_AT,
    ),
)


def _info(
    meaning: str,
    dataset: str,
    scoring: str,
    interpretation: str,
    conditions: tuple[str, ...],
    limitations: tuple[str, ...],
) -> BenchmarkInformation:
    return BenchmarkInformation(
        meaning=meaning,
        dataset_and_edition=dataset,
        scoring_method=scoring,
        interpretation=interpretation,
        standard_conditions=conditions,
        limitations=limitations,
    )


BENCHMARKS = (
    BenchmarkDefinition(
        id="gpqa-diamond",
        display_name="GPQA Diamond",
        track=BenchmarkTrack.TEXT_CODE,
        category=BenchmarkCategory.GENERAL_KNOWLEDGE,
        dataset_edition="GPQA Diamond",
        unit="percent",
        minimum=0,
        maximum=100,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        setup_variant="Provider-reported text evaluation",
        info=_info(
            "Graduate-level, expert-written multiple-choice science questions designed to resist lookup.",
            "GPQA Diamond expert-validated subset.",
            "Exact-answer accuracy reported as a percentage.",
            "Higher scores indicate stronger difficult scientific question answering.",
            ("Text-only questions unless a provider explicitly states otherwise.",),
            ("Provider reports may use different sampling budgets.", "This does not measure tool use or real-world task completion."),
        ),
        official_source=ZAI_GLM_52,
    ),
    BenchmarkDefinition(
        id="aime-2026",
        display_name="AIME 2026",
        track=BenchmarkTrack.TEXT_CODE,
        category=BenchmarkCategory.MATHEMATICS,
        dataset_edition="American Invitational Mathematics Examination 2026",
        unit="percent",
        minimum=0,
        maximum=100,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        setup_variant="Provider-reported answer accuracy",
        info=_info(
            "Competition mathematics problems requiring exact integer answers.",
            "AIME 2026 problem set.",
            "Exact final-answer accuracy reported as a percentage.",
            "Higher scores indicate stronger contest-math problem solving.",
            ("Provider-disclosed sampling and answer-format instruction apply.",),
            ("A single contest set can be saturated.", "Reasoning-token budgets differ across providers."),
        ),
        official_source=ZAI_GLM_52,
    ),
    BenchmarkDefinition(
        id="swe-bench-pro",
        display_name="SWE-bench Pro",
        track=BenchmarkTrack.TEXT_CODE,
        category=BenchmarkCategory.CODING,
        dataset_edition="SWE-bench Pro public suite",
        unit="percent",
        minimum=0,
        maximum=100,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        setup_variant="Provider-reported setup; see score details",
        info=_info(
            "Software-engineering issues evaluated by whether generated patches resolve repository tests.",
            "SWE-bench Pro public suite.",
            "Resolved-task rate reported as a percentage.",
            "Higher scores indicate more repository issues resolved under each reported setup.",
            ("Use the provider-reported harness and conditions recorded in score details.",),
            (
                "Harnesses, tools, prompts, attempt policies, and time limits can materially affect results.",
                "Cross-provider ordering is a reference comparison and is not strictly apples-to-apples.",
            ),
        ),
        official_source=SWE_BENCH_PRO_SOURCE,
    ),
    BenchmarkDefinition(
        id="terminal-bench-2-1",
        display_name="Terminal-Bench 2.1",
        track=BenchmarkTrack.TEXT_CODE,
        category=BenchmarkCategory.CODING,
        dataset_edition="Terminal-Bench 2.1",
        unit="percent",
        minimum=0,
        maximum=100,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        setup_variant="Provider-reported setup; see score details",
        info=_info(
            "Long-horizon terminal tasks that require operating a real command-line environment.",
            "Terminal-Bench 2.1.",
            "Task success rate reported as a percentage.",
            "Higher scores indicate more terminal tasks completed under each reported setup.",
            ("Use the provider-reported harness and resource limits recorded in score details.",),
            (
                "Harnesses, tools, prompts, resource limits, and time limits can materially affect results.",
                "Cross-provider ordering is a reference comparison and is not strictly apples-to-apples.",
            ),
        ),
        official_source=TERMINAL_BENCH_21_SOURCE,
    ),
    BenchmarkDefinition(
        id="swe-bench-verified-anthropic-scaffold",
        display_name="SWE-bench Verified",
        track=BenchmarkTrack.TEXT_CODE,
        category=BenchmarkCategory.CODING,
        dataset_edition="SWE-bench Verified, full 500-problem set",
        unit="percent",
        minimum=0,
        maximum=100,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        setup_variant="Anthropic two-tool scaffold",
        info=_info(
            "Real GitHub issue resolution evaluated through repository tests.",
            "SWE-bench Verified full 500-problem dataset.",
            "Resolved-task rate averaged over provider-disclosed trials.",
            "Higher scores indicate more verified software issues resolved with this scaffold.",
            ("Anthropic's disclosed bash and file-editing scaffold is part of this variant.",),
            ("Not comparable to scores with other scaffolds.", "Reasoning budget and prompt changes can change outcomes."),
        ),
        official_source=ANTHROPIC_HAIKU_45,
    ),
    BenchmarkDefinition(
        id="deep-swe-1-0",
        display_name="DeepSWE 1.0",
        track=BenchmarkTrack.TEXT_CODE,
        category=BenchmarkCategory.CODING,
        dataset_edition="DeepSWE 1.0",
        unit="percent",
        minimum=0,
        maximum=100,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        setup_variant="Datacurve evaluation; provider harnesses run by Artificial Analysis",
        info=_info(
            "Long-horizon software-engineering tasks assessed by an objective task-success signal.",
            "DeepSWE 1.0, as evaluated by Datacurve.",
            "Task success rate reported as a percentage.",
            "Higher scores indicate more tasks completed under each provider's harness.",
            (
                "Evaluation created by Datacurve and run with each model provider's harnesses by Artificial Analysis.",
            ),
            (
                "Cross-provider harness differences limit direct comparison.",
                "It measures agentic engineering, not standalone code generation.",
            ),
        ),
        official_source=XAI_GROK_45,
    ),
    BenchmarkDefinition(
        id="deep-swe-1-1-openai-release-table",
        display_name="DeepSWE v1.1",
        track=BenchmarkTrack.TEXT_CODE,
        category=BenchmarkCategory.CODING,
        dataset_edition="DeepSWE v1.1",
        unit="percent",
        minimum=0,
        maximum=100,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        setup_variant="OpenAI release table; harness not further disclosed",
        info=_info(
            "Long-horizon software-engineering tasks assessed by an objective task-success signal.",
            "DeepSWE v1.1, as reported in OpenAI's GPT-5.6 release table.",
            "Task success rate reported as a percentage.",
            "Higher scores indicate more tasks completed in OpenAI's release-table configuration.",
            (
                "OpenAI reports this release-table result without a further harness disclosure.",
            ),
            (
                "Not comparable to DeepSWE 1.0 or other harness-specific variants.",
                "Prompting, tool permissions, time limits, and agent harness details can materially affect results.",
            ),
        ),
        official_source=OPENAI_GPT_56,
    ),
    BenchmarkDefinition(
        id="mmmu-pro",
        display_name="MMMU-Pro",
        track=BenchmarkTrack.MULTIMODAL,
        category=BenchmarkCategory.MULTIMODAL_UNDERSTANDING,
        dataset_edition="MMMU-Pro",
        unit="percent",
        minimum=0,
        maximum=100,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        setup_variant="No tools",
        info=_info(
            "Multidisciplinary multimodal understanding and reasoning across image-and-text questions.",
            "MMMU-Pro benchmark.",
            "Exact-answer accuracy reported as a percentage.",
            "Higher scores indicate stronger multimodal expert-question answering without tools.",
            ("No external tools are available.",),
            ("Prompting and image preprocessing can affect results.", "It does not measure image generation quality."),
        ),
        official_source=MMMU_PRO_SOURCE,
    ),
    BenchmarkDefinition(
        id="mmmu-pro-tools",
        display_name="MMMU-Pro (Tools)",
        track=BenchmarkTrack.MULTIMODAL,
        category=BenchmarkCategory.MULTIMODAL_UNDERSTANDING,
        dataset_edition="MMMU-Pro",
        unit="percent",
        minimum=0,
        maximum=100,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        setup_variant="With tools",
        info=_info(
            "Multidisciplinary multimodal understanding and reasoning across image-and-text questions.",
            "MMMU-Pro benchmark.",
            "Exact-answer accuracy reported as a percentage.",
            "Higher scores indicate stronger multimodal expert-question answering with tools.",
            ("Provider evaluation provides tools to the model.",),
            (
                "Not comparable to MMMU-Pro results without tools.",
                "Prompting, tool availability, and image preprocessing can affect results.",
            ),
        ),
        official_source=MMMU_PRO_SOURCE,
    ),
    BenchmarkDefinition(
        id="charxiv",
        display_name="CharXiv",
        track=BenchmarkTrack.MULTIMODAL,
        category=BenchmarkCategory.MULTIMODAL_UNDERSTANDING,
        dataset_edition="CharXiv reasoning",
        unit="percent",
        minimum=0,
        maximum=100,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        setup_variant="Provider-reported setup; see score details",
        info=_info(
            "Understanding and reasoning over complex scientific charts and figures.",
            "CharXiv reasoning benchmark.",
            "Exact-answer accuracy reported as a percentage.",
            "Higher scores indicate stronger chart-grounded multimodal reasoning under each reported setup.",
            ("Use the tool availability and conditions recorded in score details.",),
            (
                "No-tool and Python-assisted results share this reference column.",
                "Tool access, chart rendering, and prompt format can materially affect results; scores are not strictly apples-to-apples.",
            ),
        ),
        official_source=CHARXIV_SOURCE,
    ),
)


SCORES = (
    BenchmarkScore(
        model_id="gpt-5-6-sol",
        benchmark_id="swe-bench-pro",
        value=64.6,
        setup=(
            SetupDetail(
                label="Evaluation",
                value="OpenAI release table; harness not further disclosed",
            ),
        ),
        source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-terra",
        benchmark_id="swe-bench-pro",
        value=63.4,
        setup=(
            SetupDetail(
                label="Evaluation",
                value="OpenAI release table; harness not further disclosed",
            ),
        ),
        source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-luna",
        benchmark_id="swe-bench-pro",
        value=62.7,
        setup=(
            SetupDetail(
                label="Evaluation",
                value="OpenAI release table; harness not further disclosed",
            ),
        ),
        source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-sol",
        benchmark_id="deep-swe-1-1-openai-release-table",
        value=72.7,
        setup=(),
        source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-terra",
        benchmark_id="deep-swe-1-1-openai-release-table",
        value=69.6,
        setup=(),
        source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-luna",
        benchmark_id="deep-swe-1-1-openai-release-table",
        value=67.2,
        setup=(),
        source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-sol",
        benchmark_id="terminal-bench-2-1",
        value=88.8,
        setup=(
            SetupDetail(
                label="Evaluation",
                value="OpenAI release table; harness not further disclosed",
            ),
        ),
        source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-terra",
        benchmark_id="terminal-bench-2-1",
        value=87.4,
        setup=(
            SetupDetail(
                label="Evaluation",
                value="OpenAI release table; harness not further disclosed",
            ),
        ),
        source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-luna",
        benchmark_id="terminal-bench-2-1",
        value=84.7,
        setup=(
            SetupDetail(
                label="Evaluation",
                value="OpenAI release table; harness not further disclosed",
            ),
        ),
        source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-sol", benchmark_id="gpqa-diamond", value=94.6,
        setup=(), source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-terra", benchmark_id="gpqa-diamond", value=92.9,
        setup=(), source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-luna", benchmark_id="gpqa-diamond", value=92.3,
        setup=(), source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-sol", benchmark_id="mmmu-pro", value=83.0,
        setup=(SetupDetail(label="Tools", value="No tools"),), source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-terra", benchmark_id="mmmu-pro", value=80.7,
        setup=(SetupDetail(label="Tools", value="No tools"),), source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-luna", benchmark_id="mmmu-pro", value=78.4,
        setup=(SetupDetail(label="Tools", value="No tools"),), source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-sol", benchmark_id="mmmu-pro-tools", value=84.6,
        setup=(SetupDetail(label="Tools", value="Available"),), source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-terra", benchmark_id="mmmu-pro-tools", value=82.0,
        setup=(SetupDetail(label="Tools", value="Available"),), source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="gpt-5-6-luna", benchmark_id="mmmu-pro-tools", value=79.5,
        setup=(SetupDetail(label="Tools", value="Available"),), source=OPENAI_GPT_56,
    ),
    BenchmarkScore(
        model_id="glm-5-2", benchmark_id="gpqa-diamond", value=91.2, setup=(), source=ZAI_GLM_52
    ),
    BenchmarkScore(
        model_id="glm-5-2", benchmark_id="aime-2026", value=99.2,
        setup=(SetupDetail(label="Evaluation", value="Provider-disclosed answer-format prompt and sampling"),),
        source=ZAI_GLM_52,
    ),
    BenchmarkScore(
        model_id="glm-5-2", benchmark_id="swe-bench-pro", value=62.1,
        setup=(SetupDetail(label="Harness", value="OpenHands with provider-disclosed settings"),),
        source=ZAI_GLM_52,
    ),
    BenchmarkScore(
        model_id="glm-5-2", benchmark_id="terminal-bench-2-1", value=81.0,
        setup=(SetupDetail(label="Harness", value="Terminus-2"),), source=ZAI_GLM_52,
    ),
    BenchmarkScore(
        model_id="gemini-3-5-flash", benchmark_id="swe-bench-pro", value=55.1,
        setup=(SetupDetail(label="Attempts", value="Single attempt"),), source=GOOGLE_GEMINI_OVERVIEW,
    ),
    BenchmarkScore(
        model_id="gemini-3-5-flash", benchmark_id="terminal-bench-2-1", value=76.2,
        setup=(SetupDetail(label="Harness", value="Terminus-2"),), source=GOOGLE_GEMINI_OVERVIEW,
    ),
    BenchmarkScore(
        model_id="gemini-3-1-pro", benchmark_id="swe-bench-pro", value=54.2,
        setup=(SetupDetail(label="Attempts", value="Single attempt"),), source=GOOGLE_GEMINI_OVERVIEW,
    ),
    BenchmarkScore(
        model_id="gemini-3-1-pro", benchmark_id="terminal-bench-2-1", value=70.3,
        setup=(SetupDetail(label="Harness", value="Terminus-2"),), source=GOOGLE_GEMINI_OVERVIEW,
    ),
    BenchmarkScore(
        model_id="gemini-3-5-flash", benchmark_id="mmmu-pro", value=83.6,
        setup=(SetupDetail(label="Tools", value="No tools"),), source=GOOGLE_GEMINI_OVERVIEW,
    ),
    BenchmarkScore(
        model_id="gemini-3-1-pro", benchmark_id="charxiv", value=83.3,
        setup=(SetupDetail(label="Tools", value="No tools"),), source=GOOGLE_GEMINI_OVERVIEW,
    ),
    BenchmarkScore(
        model_id="claude-haiku-4-5", benchmark_id="swe-bench-verified-anthropic-scaffold", value=73.3,
        setup=(SetupDetail(label="Thinking budget", value="128K"), SetupDetail(label="Trials", value="50")),
        source=ANTHROPIC_HAIKU_45,
    ),
    BenchmarkScore(
        model_id="grok-4-5", benchmark_id="swe-bench-pro", value=64.7,
        setup=(SetupDetail(label="Evaluation", value="Provider-reported release evaluation"),), source=XAI_GROK_45,
    ),
    BenchmarkScore(
        model_id="grok-4-5", benchmark_id="deep-swe-1-0", value=62.0,
        setup=(
            SetupDetail(
                label="Evaluation",
                value="Created by Datacurve; run with provider harnesses by Artificial Analysis",
            ),
        ),
        source=XAI_GROK_45,
    ),
    BenchmarkScore(
        model_id="kimi-k2-6", benchmark_id="swe-bench-pro", value=58.6,
        setup=(SetupDetail(label="Tools", value="Tools available"),), source=MOONSHOT_K26,
    ),
    BenchmarkScore(
        model_id="kimi-k2-6", benchmark_id="charxiv", value=86.7,
        setup=(SetupDetail(label="Tools", value="Python tool available"),), source=MOONSHOT_K26,
    ),
)


CATALOG = ModelBenchmarkCatalog(
    catalog_version=CATALOG_VERSION,
    last_verified_at=LAST_VERIFIED_AT,
    providers=PROVIDERS,
    models=MODELS,
    benchmarks=BENCHMARKS,
    scores=SCORES,
)

validate_catalog(CATALOG)
