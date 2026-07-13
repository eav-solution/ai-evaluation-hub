import {fireEvent, render, screen, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {describe, expect, it, vi} from "vitest";

import {ModelBenchmarkMatrix, type MatrixSort} from "@/components/ModelBenchmarkMatrix";
import type {BenchmarkView} from "@/lib/model-benchmarks";
import {catalog} from "./model-benchmark-fixture";

function renderMatrix(view: BenchmarkView, sort: MatrixSort = null) {
  const onSort = vi.fn();
  const onOpenInfo = vi.fn();
  const onSelectScore = vi.fn();
  const onSelectModel = vi.fn();

  render(
    <ModelBenchmarkMatrix
      view={view}
      models={catalog.models}
      providers={catalog.providers}
      benchmarks={catalog.benchmarks}
      scores={catalog.scores}
      sort={sort}
      onSort={onSort}
      onOpenInfo={onOpenInfo}
      onSelectScore={onSelectScore}
      onSelectModel={onSelectModel}
    />,
  );

  return {onSort, onOpenInfo, onSelectScore, onSelectModel};
}

describe("ModelBenchmarkMatrix", () => {
  it("renders only text and code benchmark columns in the text and code view", () => {
    renderMatrix("text_code");

    expect(screen.getByRole("button", {name: "Sort by MMLU-Pro"})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "Sort by SWE-bench Pro"})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "Sort by Terminal-Bench 2.1"})).toBeInTheDocument();
    expect(screen.queryByRole("button", {name: "Sort by MMMU-Pro"})).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {name: "Sort by MMMU-Pro (Tools)"})).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {name: "Sort by CharXiv"})).not.toBeInTheDocument();
  });

  it("renders only multimodal benchmark columns in the multimodal view", () => {
    renderMatrix("multimodal");

    expect(screen.getByRole("button", {name: "Sort by MMMU-Pro"})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "Sort by MMMU-Pro (Tools)"})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "Sort by CharXiv"})).toBeInTheDocument();
    expect(screen.queryByRole("button", {name: "Sort by MMLU-Pro"})).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {name: "Sort by SWE-bench Pro"})).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {name: "Sort by Terminal-Bench 2.1"})).not.toBeInTheDocument();
  });

  it("renders specifications and base pricing without benchmark score columns", () => {
    renderMatrix("specs");

    for (const heading of [
      "Release date",
      "Context window",
      "Input modalities",
      "Output modalities",
      "Weights",
      "Input",
      "Cached input",
      "Output",
    ]) {
      expect(screen.getByRole("columnheader", {name: heading})).toBeInTheDocument();
    }

    for (const benchmark of [
      "MMLU-Pro",
      "SWE-bench Pro",
      "Terminal-Bench 2.1",
      "MMMU-Pro",
      "MMMU-Pro (Tools)",
      "CharXiv",
    ]) {
      expect(screen.queryByRole("button", {name: `Sort by ${benchmark}`})).not.toBeInTheDocument();
    }
    expect(screen.getAllByText("$2.50 / 1M tokens")).toHaveLength(6);
    expect(screen.getAllByText("Not reported")).toHaveLength(3);
    expect(screen.getAllByText("Not applicable")).toHaveLength(3);
  });

  it("renders the full model identity and weight status in every row", () => {
    renderMatrix("text_code");

    for (const model of catalog.models) {
      const modelButton = screen.getByRole("button", {name: `View details for ${model.display_name}`});
      const row = modelButton.closest("tr");
      expect(row).not.toBeNull();
      expect(within(row!).getByText(model.display_name)).toBeInTheDocument();
      expect(within(row!).getByText(model.provider_id === "openai" ? "OpenAI" : "Anthropic")).toBeInTheDocument();
      expect(within(row!).getByText(model.tier === "mid_range" ? "Mid-range" : model.tier[0].toUpperCase() + model.tier.slice(1))).toBeInTheDocument();
      expect(within(row!).getByText(model.weights_status === "open_weight" ? "Open weights" : "Closed weights")).toBeInTheDocument();
    }
  });

  it("renders keyboard-operable score and model buttons with their detail selections", async () => {
    const {onSelectModel, onSelectScore} = renderMatrix("text_code");
    const model = catalog.models[0];
    const benchmark = catalog.benchmarks[0];
    const score = catalog.scores[0];

    const scoreButton = screen.getByRole("button", {name: `View ${benchmark.display_name} score for ${model.display_name}`});
    scoreButton.focus();
    await userEvent.keyboard("{Enter}");
    expect(onSelectScore).toHaveBeenCalledWith({
      kind: "score",
      model,
      provider: catalog.providers[0],
      benchmark,
      score,
    });

    fireEvent.click(screen.getByRole("button", {name: `View details for ${model.display_name}`}));
    expect(onSelectModel).toHaveBeenCalledWith({kind: "model", model, provider: catalog.providers[0]});
    expect(screen.getAllByText("Not reported").length).toBeGreaterThan(0);
  });

  it("provides separate sort and information controls and marks the active sort direction", () => {
    const benchmark = catalog.benchmarks[0];
    const {onOpenInfo, onSort} = renderMatrix("text_code", {benchmarkId: benchmark.id, order: "desc"});
    const header = screen.getByRole("columnheader", {name: /MMLU-Pro/});

    expect(header).toHaveAttribute("aria-sort", "descending");
    const sortButton = within(header).getByRole("button", {name: `Sort by ${benchmark.display_name}`});
    expect(sortButton).toHaveAttribute("title", "Sort by MMLU-Pro (descending)");
    expect(sortButton).toHaveTextContent("↓");
    expect(sortButton).not.toHaveTextContent("Sort");
    fireEvent.click(sortButton);
    fireEvent.click(within(header).getByRole("button", {name: `About ${benchmark.display_name}`}));

    expect(onSort).toHaveBeenCalledWith(benchmark);
    expect(onOpenInfo).toHaveBeenCalledWith(benchmark);
  });

  it("shows an inactive sort icon when the benchmark is not selected", () => {
    const benchmark = catalog.benchmarks[0];
    renderMatrix("text_code", null);

    const header = screen.getByRole("columnheader", {name: /MMLU-Pro/});
    const sortButton = within(header).getByRole("button", {name: `Sort by ${benchmark.display_name}`});

    expect(sortButton).toHaveAttribute("title", "Sort by MMLU-Pro");
    expect(sortButton).toHaveTextContent("↕");
  });

  it("shows an ascending sort icon when the benchmark is selected", () => {
    const benchmark = catalog.benchmarks[0];
    renderMatrix("text_code", {benchmarkId: benchmark.id, order: "asc"});

    const header = screen.getByRole("columnheader", {name: /MMLU-Pro/});
    const sortButton = within(header).getByRole("button", {name: `Sort by ${benchmark.display_name}`});

    expect(sortButton).toHaveAttribute("title", "Sort by MMLU-Pro (ascending)");
    expect(sortButton).toHaveTextContent("↑");
  });
});
