import {readFileSync} from "node:fs";
import {resolve} from "node:path";

import {StrictMode} from "react";
import {fireEvent, render, screen, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

import {ModelBenchmarkCatalog} from "@/components/ModelBenchmarkCatalog";
import {api} from "@/lib/api";
import type {ModelBenchmarkCatalogPayload} from "@/lib/model-benchmarks";
import {catalog} from "./model-benchmark-fixture";

vi.mock("@/lib/api", () => ({api: vi.fn()}));

beforeEach(() => {
  vi.mocked(api).mockResolvedValue(catalog);
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value: vi.fn(function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    }),
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value: vi.fn(function (this: HTMLDialogElement) {
      this.removeAttribute("open");
      this.dispatchEvent(new Event("close"));
    }),
  });
});

afterEach(() => {
  vi.resetAllMocks();
});

function staleCatalog(): ModelBenchmarkCatalogPayload {
  return {
    ...catalog,
    last_verified_at: "2026-04-01",
    models: [{...catalog.models[0], verified_at: "2026-04-01"}, ...catalog.models.slice(1)],
  };
}

describe("ModelBenchmarkCatalog", () => {
  it("keeps dense benchmark matrices usable on desktop and narrow screens", () => {
    // jsdom does not compute sticky layout or media queries, so this verifies
    // the stylesheet source with whitespace-tolerant patterns.
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");

    expect(css).toMatch(/\.model-benchmark-tier-sections\s*\{[^}]*display:\s*grid[^}]*gap:\s*24px/);
    expect(css).toMatch(/\.model-benchmark-tier-section\s*\{[^}]*display:\s*grid[^}]*gap:\s*10px/);
    expect(css).toMatch(/\.model-benchmark-matrix\s*\{[^}]*max-width:\s*100%[^}]*overflow-x:\s*auto/);
    expect(css).not.toMatch(/\.model-benchmark-matrix\s*\{[^}]*max-height:/);
    expect(css).not.toMatch(/\.model-benchmark-matrix\s*\{[^}]*overflow:\s*auto/);
    expect(css).toMatch(/\.model-benchmark-matrix\s+thead\s+th[^}]*position:\s*sticky[^}]*top:\s*0/);
    expect(css).toMatch(/\.model-benchmark-matrix\s+th:first-child[^}]*position:\s*sticky[^}]*left:\s*0/);
    expect(css).toMatch(/\.model-benchmark-matrix\s+thead\s+th:first-child[^}]*z-index:\s*[4-9]/);
    expect(css).not.toMatch(/\.benchmark-table-wrap|\.benchmark-model-column/);
    expect(css).toMatch(/\.benchmark-info-trigger\s*\{[^}]*min-height:\s*26px[^}]*margin:\s*5px\s+4px\s+0\s+0[^}]*border-color:\s*transparent[^}]*background:\s*transparent[^}]*box-shadow:\s*none[^}]*font-size:\s*10\.5px[^}]*padding:\s*3px\s+0/);
    expect(css).toMatch(/\.model-benchmark-score-button:focus-visible[\s\S]*?\.benchmark-info-trigger:focus-visible[\s\S]*?\.model-benchmark-view-tabs\s+button:focus-visible[\s\S]*?\.benchmark-details-close:focus-visible/);
    expect(css).toMatch(/@media \(max-width:\s*760px\)[\s\S]*?\.sidebar nav\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
    expect(css).toMatch(/dialog\.benchmark-info-modal\s*\{[^}]*max-height:\s*90dvh/);
    expect(css).toMatch(/@media \(max-width:\s*760px\)[\s\S]*?\.model-benchmark-controls\s*\{[^}]*grid-template-columns:\s*1fr/);
  });

  it("shows loading until its one catalog request resolves, then renders full model names", async () => {
    let resolveCatalog: (value: ModelBenchmarkCatalogPayload) => void;
    vi.mocked(api).mockImplementationOnce(() => new Promise<ModelBenchmarkCatalogPayload>((resolve) => {
      resolveCatalog = resolve;
    }));

    render(<ModelBenchmarkCatalog />);

    expect(screen.getByText("Loading model benchmarks…")).toBeInTheDocument();
    expect(api).toHaveBeenCalledOnce();
    expect(api).toHaveBeenCalledWith("/api/model-benchmarks");

    resolveCatalog!(catalog);

    expect(await screen.findByRole("button", {name: "View details for GPT Test Frontier"})).toBeInTheDocument();
  });

  it("does not duplicate its initial request when effects are replayed", async () => {
    render(<StrictMode><ModelBenchmarkCatalog /></StrictMode>);

    await screen.findByText("GPT Test Frontier");

    expect(api).toHaveBeenCalledOnce();
  });

  it("renders permanent ordered tier tables and applies provider/search filters to all of them", async () => {
    const user = userEvent.setup();
    render(<ModelBenchmarkCatalog />);
    await screen.findByText("GPT Test Frontier");

    expect(screen.getAllByRole("heading", {level: 2}).map((heading) => heading.textContent)).toEqual([
      "Frontier",
      "Mid-range",
      "Lite",
    ]);
    expect(screen.queryByLabelText("Tier")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Provider"), "openai");
    await user.type(screen.getByLabelText("Search full model name"), "gpt");

    expect(within(screen.getByRole("region", {name: "Frontier models"})).getByText("GPT Test Frontier")).toBeInTheDocument();
    expect(within(screen.getByRole("region", {name: "Lite models"})).getByText("GPT Test Lite")).toBeInTheDocument();
    expect(screen.getByText("No Mid-range models match these filters")).toBeInTheDocument();
  });

  it("renders each canonical benchmark column once in every tier table", async () => {
    const user = userEvent.setup();
    render(<ModelBenchmarkCatalog />);
    await screen.findByText("GPT Test Frontier");

    for (const tier of ["Frontier", "Mid-range", "Lite"]) {
      const region = within(screen.getByRole("region", {name: `${tier} models`}));
      for (const benchmark of ["SWE-bench Pro", "Terminal-Bench 2.1"]) {
        expect(region.getAllByRole("button", {name: `Sort by ${benchmark}`})).toHaveLength(1);
      }
    }

    await user.click(screen.getByRole("button", {name: "Multimodal"}));

    for (const tier of ["Frontier", "Mid-range", "Lite"]) {
      const region = within(screen.getByRole("region", {name: `${tier} models`}));
      for (const benchmark of ["CharXiv", "MMMU-Pro", "MMMU-Pro (Tools)"]) {
        expect(region.getAllByRole("button", {name: `Sort by ${benchmark}`})).toHaveLength(1);
      }
    }
  });

  it("shares score sorting across tier tables and keeps Specs & Pricing alphabetized within each tier", async () => {
    const user = userEvent.setup();
    render(<ModelBenchmarkCatalog />);
    await screen.findByText("GPT Test Frontier");

    const sort = screen.getAllByRole("button", {name: "Sort by MMLU-Pro"})[0];
    await user.click(sort);
    for (const tier of ["Frontier", "Mid-range", "Lite"]) {
      expect(within(screen.getByRole("region", {name: `${tier} models`})).getByRole("columnheader", {name: /MMLU-Pro/}))
        .toHaveAttribute("aria-sort", "descending");
    }

    await user.click(screen.getByRole("button", {name: "Specs & Pricing"}));
    expect(modelOrder(screen.getByRole("region", {name: "Frontier models"}))).toEqual([
      "Claude Test Frontier",
      "GPT Test Frontier",
    ]);
  });

  it("starts a lower-is-better benchmark in ascending order", async () => {
    vi.mocked(api).mockResolvedValueOnce({
      ...catalog,
      benchmarks: [{...catalog.benchmarks[0], direction: "lower_is_better"}, ...catalog.benchmarks.slice(1)],
    });
    const user = userEvent.setup();
    render(<ModelBenchmarkCatalog />);
    await screen.findByText("GPT Test Frontier");

    await user.click(screen.getAllByRole("button", {name: "Sort by MMLU-Pro"})[0]);

    for (const header of screen.getAllByRole("columnheader", {name: /MMLU-Pro/})) {
      expect(header).toHaveAttribute("aria-sort", "ascending");
    }
  });

  it("clears a score sort outside its track and keeps specs in full-name order", async () => {
    const user = userEvent.setup();
    render(<ModelBenchmarkCatalog />);
    await screen.findByText("GPT Test Frontier");

    await user.click(screen.getAllByRole("button", {name: "Sort by MMLU-Pro"})[0]);
    await user.click(screen.getByRole("button", {name: "Multimodal"}));
    await user.click(screen.getByRole("button", {name: "Text & Code"}));
    for (const header of screen.getAllByRole("columnheader", {name: /MMLU-Pro/})) {
      expect(header).not.toHaveAttribute("aria-sort");
    }

    await user.click(screen.getByRole("button", {name: "Specs & Pricing"}));
    expect(modelOrder(screen.getByRole("region", {name: "Frontier models"}))).toEqual([
      "Claude Test Frontier",
      "GPT Test Frontier",
    ]);
  });

  it("keeps filters and sorting intact when benchmark information opens and closes", async () => {
    const user = userEvent.setup();
    render(<ModelBenchmarkCatalog />);
    await screen.findByText("GPT Test Frontier");

    await user.selectOptions(screen.getByLabelText("Provider"), "openai");
    await user.click(screen.getAllByRole("button", {name: "Sort by MMLU-Pro"})[0]);
    await user.click(screen.getAllByRole("button", {name: "About MMLU-Pro"})[0]);
    expect(screen.getByRole("dialog", {name: "MMLU-Pro"})).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name: "Close MMLU-Pro benchmark information"}));

    expect(screen.getByLabelText("Provider")).toHaveValue("openai");
    for (const tier of ["Frontier", "Lite"]) {
      expect(within(screen.getByRole("region", {name: `${tier} models`})).getByRole("columnheader", {name: /MMLU-Pro/}))
        .toHaveAttribute("aria-sort", "descending");
    }
    expect(screen.queryByRole("button", {name: "View details for Claude Test Frontier"})).not.toBeInTheDocument();
  });

  it("opens score provenance and model detail selections without changing the current view", async () => {
    const user = userEvent.setup();
    render(<ModelBenchmarkCatalog />);
    await screen.findByText("GPT Test Frontier");

    await user.click(screen.getByRole("button", {name: "View MMLU-Pro score for GPT Test Frontier"}));
    const scoreDetails = screen.getByRole("complementary", {name: "Benchmark details"});
    expect(within(scoreDetails).getByText("Source provenance")).toBeInTheDocument();
    expect(within(scoreDetails).getByText("GPT Test Frontier")).toBeInTheDocument();
    await user.click(within(scoreDetails).getByRole("button", {name: "Close benchmark details"}));

    await user.click(screen.getByRole("button", {name: "View details for GPT Test Frontier"}));
    const modelDetails = screen.getByRole("complementary", {name: "Benchmark details"});
    expect(within(modelDetails).getByText("Model specification")).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "Text & Code"})).toHaveAttribute("aria-pressed", "true");
  });

  it("marks stale catalog and selected model entries as needing review", async () => {
    vi.mocked(api).mockResolvedValueOnce(staleCatalog());
    const user = userEvent.setup();
    render(<ModelBenchmarkCatalog />);
    await screen.findByText("GPT Test Frontier");

    expect(screen.getAllByText("Review needed").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", {name: "View details for GPT Test Frontier"}));
    expect(within(screen.getByRole("complementary", {name: "Benchmark details"})).getAllByText("Review needed").length).toBeGreaterThan(0);
  });

  it("shows a descriptive empty state for each tier with no model matches", async () => {
    const user = userEvent.setup();
    render(<ModelBenchmarkCatalog />);
    await screen.findByText("GPT Test Frontier");

    await user.type(screen.getByLabelText("Search full model name"), "does not exist");

    expect(screen.getByText("No Frontier models match these filters")).toBeInTheDocument();
    expect(screen.getByText("No Mid-range models match these filters")).toBeInTheDocument();
    expect(screen.getByText("No Lite models match these filters")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("retries a failed catalog request and renders the recovered catalog without an overall score or rank", async () => {
    vi.mocked(api)
      .mockRejectedValueOnce(new Error("Catalog unavailable"))
      .mockResolvedValueOnce(catalog);
    const user = userEvent.setup();
    render(<ModelBenchmarkCatalog />);

    expect(await screen.findByText("Catalog unavailable")).toBeInTheDocument();
    await user.click(screen.getByRole("button", {name: "Retry"}));

    expect(await screen.findByText("GPT Test Frontier")).toBeInTheDocument();
    expect(api).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/overall (score|rank)/i)).not.toBeInTheDocument();
  });
});

function modelOrder(region: HTMLElement): string[] {
  return within(region).getAllByRole("button", {name: /^View details for /}).map((button) => button.textContent ?? "");
}
