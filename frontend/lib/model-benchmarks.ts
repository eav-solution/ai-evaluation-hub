export type BenchmarkView = "text_code" | "multimodal" | "specs";
export type SortOrder = "asc" | "desc";
export type ModelTier = "frontier" | "mid_range" | "lite";
export type PriceState = "reported" | "not_reported" | "not_applicable";
export type BenchmarkTrack = "text_code" | "multimodal";
export type BenchmarkCategory =
  | "general_knowledge"
  | "reasoning"
  | "mathematics"
  | "coding"
  | "instruction_following"
  | "long_context"
  | "multimodal_understanding";
export type ScoreDirection = "higher_is_better" | "lower_is_better";
export type WeightsStatus = "open_weight" | "closed";
export type Availability = "official_api" | "official_weights" | "official_api_and_weights";
export type Modality = "text" | "image" | "audio" | "video" | "pdf";

export type SourceReference = {
  title: string;
  publisher: string;
  provider_id: string | null;
  url: string;
  published_at: string | null;
  verified_at: string;
};

export type TokenPrice = {
  status: PriceState;
  usd_per_million: number | null;
  source_amount_per_million: number | null;
  source_currency: string | null;
};

export type PricingBand = {
  band_id: string;
  label: string;
  condition: string;
  is_base: boolean;
  input: TokenPrice;
  cached_input: TokenPrice;
  output: TokenPrice;
};

export type ModelPricing = {
  status: PriceState;
  bands: PricingBand[];
  source: SourceReference;
  exchange_rate_source: SourceReference | null;
  note: string | null;
};

export type ProviderRecord = {
  id: string;
  display_name: string;
  website: string;
};

export type ModelRecord = {
  id: string;
  display_name: string;
  api_model_id: string | null;
  provider_id: string;
  tier: ModelTier;
  tier_reason: string;
  release_date: string;
  context_window_tokens: number;
  input_modalities: Modality[];
  output_modalities: Modality[];
  weights_status: WeightsStatus;
  availability: Availability;
  pricing: ModelPricing;
  specification_source: SourceReference;
  verified_at: string;
};

export type BenchmarkInformation = {
  meaning: string;
  dataset_and_edition: string;
  scoring_method: string;
  interpretation: string;
  standard_conditions: string[];
  limitations: string[];
};

export type BenchmarkDefinition = {
  id: string;
  display_name: string;
  track: BenchmarkTrack;
  category: BenchmarkCategory;
  dataset_edition: string;
  unit: string;
  minimum: number;
  maximum: number;
  direction: ScoreDirection;
  setup_variant: string;
  info: BenchmarkInformation;
  official_source: SourceReference;
};

export type SetupDetail = {
  label: string;
  value: string;
};

export type BenchmarkScore = {
  model_id: string;
  benchmark_id: string;
  value: number;
  setup: SetupDetail[];
  source: SourceReference;
};

export type ModelBenchmarkCatalogPayload = {
  catalog_version: string;
  last_verified_at: string;
  providers: ProviderRecord[];
  models: ModelRecord[];
  benchmarks: BenchmarkDefinition[];
  scores: BenchmarkScore[];
};

export type ModelFilters = {
  tier: ModelTier | "all";
  providerId: string;
  query: string;
};

export function filterModels(models: ModelRecord[], filters: ModelFilters): ModelRecord[] {
  const query = filters.query.trim().toLowerCase();

  return models.filter((model) => {
    const matchesProvider = !filters.providerId || filters.providerId === "all" || model.provider_id === filters.providerId;
    const matchesTier = filters.tier === "all" || model.tier === filters.tier;
    const matchesQuery = !query || model.display_name.toLowerCase().includes(query);

    return matchesProvider && matchesTier && matchesQuery;
  });
}

export function sortModelsByScore(
  models: ModelRecord[],
  scores: BenchmarkScore[],
  benchmarkId: string,
  order: SortOrder,
): ModelRecord[] {
  const scoreByModelId = new Map<string, number>();
  for (const score of scores) {
    if (score.benchmark_id === benchmarkId) scoreByModelId.set(score.model_id, score.value);
  }

  return [...models].sort((left, right) => {
    const leftScore = scoreByModelId.get(left.id);
    const rightScore = scoreByModelId.get(right.id);

    if (leftScore === undefined && rightScore === undefined) return compareDisplayNames(left, right);
    if (leftScore === undefined) return 1;
    if (rightScore === undefined) return -1;

    const scoreComparison = order === "asc" ? leftScore - rightScore : rightScore - leftScore;
    return scoreComparison || compareDisplayNames(left, right);
  });
}

export function isReviewNeeded(verifiedAt: string, now = new Date()): boolean {
  const verifiedDay = parseUtcCalendarDate(verifiedAt);
  if (verifiedDay === null) return false;

  const nowDay = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const ageInDays = (nowDay - verifiedDay) / (24 * 60 * 60 * 1000);
  return ageInDays > 90;
}

export function formatTokenPrice(price: TokenPrice): string {
  if (price.status === "not_applicable") return "Not applicable";
  if (price.status === "not_reported" || price.usd_per_million === null) return "Not reported";

  const amount = price.usd_per_million.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  });
  return `$${amount} / 1M tokens`;
}

function compareDisplayNames(left: ModelRecord, right: ModelRecord): number {
  return left.display_name.localeCompare(right.display_name);
}

function parseUtcCalendarDate(value: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const timestamp = Date.UTC(year, month - 1, day);
  const date = new Date(timestamp);
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return null;
  }
  return timestamp;
}
