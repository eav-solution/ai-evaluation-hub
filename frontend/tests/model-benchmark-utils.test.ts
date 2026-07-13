import {describe, expect, it} from "vitest";

import {
  filterModels,
  formatTokenPrice,
  isReviewNeeded,
  sortModelsByScore,
} from "@/lib/model-benchmarks";
import {catalog, notApplicablePrice, notReportedPrice, reportedPrice} from "./model-benchmark-fixture";

describe("model benchmark utilities", () => {
  it("composes provider, tier, and case-insensitive full-name filters", () => {
    expect(
      filterModels(catalog.models, {
        providerId: "openai",
        tier: "frontier",
        query: "  gPt  ",
      }).map((model) => model.display_name),
    ).toEqual(["GPT Test Frontier"]);
  });

  it("sorts numeric scores and always leaves missing scores last", () => {
    const descending = sortModelsByScore(catalog.models, catalog.scores, "mmlu-pro", "desc");
    const ascending = sortModelsByScore(catalog.models, catalog.scores, "mmlu-pro", "asc");

    expect(descending.map((model) => model.id)).toEqual([
      "claude-test-frontier",
      "gpt-test-frontier",
      "gpt-test-lite",
      "model-without-score",
    ]);
    expect(ascending.map((model) => model.id)).toEqual([
      "gpt-test-lite",
      "claude-test-frontier",
      "gpt-test-frontier",
      "model-without-score",
    ]);
    expect(descending.at(-1)?.id).toBe("model-without-score");
    expect(ascending.at(-1)?.id).toBe("model-without-score");
  });

  it("marks entries only after ninety full days", () => {
    const now = new Date("2026-07-13T12:00:00Z");

    expect(isReviewNeeded("2026-04-13", now)).toBe(true);
    expect(isReviewNeeded("2026-04-14", now)).toBe(false);
  });

  it("formats reported, unavailable, and inapplicable prices distinctly", () => {
    expect(formatTokenPrice(reportedPrice)).toBe("$2.50 / 1M tokens");
    expect(formatTokenPrice(notReportedPrice)).toBe("Not reported");
    expect(formatTokenPrice(notApplicablePrice)).toBe("Not applicable");
  });
});
