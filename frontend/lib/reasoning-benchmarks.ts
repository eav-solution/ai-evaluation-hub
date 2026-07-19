export type ScoreDirection = "higher_is_better" | "lower_is_better";

export type HarnessRecord = {
  id: string;
  display_name: string;
  description: string;
};

export type ReasoningModelRecord = {
  id: string;
  display_name: string;
  developer: string;
};

export type CriterionDefinition = {
  id: string;
  display_name: string;
  description: string;
  minimum: number;
  maximum: number;
  direction: ScoreDirection;
};

export type CriterionScore = {
  criterion_id: string;
  value: number;
  evidence: string | null;
};

export type TestEntry = {
  model_id: string;
  harness_id: string;
  summary: string;
  scores: CriterionScore[];
};

export type ReasoningTest = {
  id: string;
  display_name: string;
  category: string;
  series_id: string | null;
  conducted_at: string;
  task_summary: string;
  methodology: string;
  source_reference: string;
  criteria: CriterionDefinition[];
  entries: TestEntry[];
  findings: string[];
  limitations: string[];
};

export type ReasoningBenchmarkCatalogPayload = {
  catalog_version: string;
  last_updated_at: string;
  harnesses: HarnessRecord[];
  models: ReasoningModelRecord[];
  tests: ReasoningTest[];
};

export type RankedEntry = {
  entry: TestEntry;
  average: number;
  rank: number;
};

export function formatScore(value: number): string {
  return String(Math.round(value * 10) / 10);
}

export function entryAverage(entry: TestEntry): number {
  if (entry.scores.length === 0) return 0;
  const total = entry.scores.reduce((sum, score) => sum + score.value, 0);
  return total / entry.scores.length;
}

export function rankEntries(
  test: ReasoningTest,
  modelsById: Map<string, ReasoningModelRecord>,
): RankedEntry[] {
  const displayName = (entry: TestEntry) =>
    modelsById.get(entry.model_id)?.display_name ?? entry.model_id;
  return test.entries
    .map((entry) => ({entry, average: entryAverage(entry)}))
    .sort(
      (left, right) =>
        right.average - left.average ||
        displayName(left.entry).localeCompare(displayName(right.entry)),
    )
    .map((item, index) => ({...item, rank: index + 1}));
}

export function bestValueByCriterion(test: ReasoningTest): Map<string, number> {
  const best = new Map<string, number>();
  for (const criterion of test.criteria) {
    const values = test.entries.flatMap((entry) =>
      entry.scores
        .filter((score) => score.criterion_id === criterion.id)
        .map((score) => score.value),
    );
    if (values.length === 0) continue;
    best.set(
      criterion.id,
      criterion.direction === "lower_is_better" ? Math.min(...values) : Math.max(...values),
    );
  }
  return best;
}
