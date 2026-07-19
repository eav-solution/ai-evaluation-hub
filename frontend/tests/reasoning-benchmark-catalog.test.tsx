import {render, screen, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

import {ReasoningBenchmarkCatalog} from "@/components/ReasoningBenchmarkCatalog";
import {api} from "@/lib/api";
import {catalog} from "./reasoning-benchmark-fixture";

vi.mock("@/lib/api", () => ({api: vi.fn()}));

beforeEach(() => {
  vi.mocked(api).mockResolvedValue(catalog);
});

afterEach(() => {
  vi.resetAllMocks();
});

describe("ReasoningBenchmarkCatalog", () => {
  it("loads once and renders the matrix with harness badges, averages and rank", async () => {
    render(<ReasoningBenchmarkCatalog />);

    expect(screen.getByText("Loading reasoning benchmarks…")).toBeInTheDocument();

    const table = await screen.findByRole("table");
    expect(api).toHaveBeenCalledOnce();
    expect(api).toHaveBeenCalledWith("/api/reasoning-benchmarks");

    expect(within(table).getByText("Claude Opus 4.8")).toBeInTheDocument();
    expect(within(table).getByText("Claude Fable 5")).toBeInTheDocument();
    expect(within(table).getByText("Qwen 27B")).toBeInTheDocument();
    expect(within(table).getAllByText("Claude Code")).toHaveLength(3);

    expect(within(table).getByText("Goal understanding")).toBeInTheDocument();
    expect(within(table).getByText("Average")).toBeInTheDocument();
    expect(within(table).getByText("Rank")).toBeInTheDocument();

    const bestCells = table.querySelectorAll("td.reasoning-score-best");
    expect(bestCells.length).toBeGreaterThan(0);
  });

  it("computes averages and ranks entries by average score", async () => {
    render(<ReasoningBenchmarkCatalog />);
    const table = await screen.findByRole("table");

    const averageRow = within(table).getByText("Average").closest("tr");
    expect(averageRow).not.toBeNull();
    const averages = within(averageRow as HTMLElement)
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    expect(averages).toEqual(["10", "9.8", "3"]);

    const rankRow = within(table).getByText("Rank").closest("tr");
    const ranks = within(rankRow as HTMLElement)
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    expect(ranks).toEqual(["1", "2", "3"]);
  });

  it("shows test metadata, findings and limitations for the selected test", async () => {
    render(<ReasoningBenchmarkCatalog />);
    await screen.findByRole("table");

    expect(screen.getByText(/Conducted 2026-07-18/)).toBeInTheDocument();
    expect(screen.getByText("Findings")).toBeInTheDocument();
    expect(screen.getByText("Goal inference separated the groups.")).toBeInTheDocument();
    expect(screen.getByText("Limitations")).toBeInTheDocument();
    expect(screen.getByText("Single run per model.")).toBeInTheDocument();
    expect(screen.getByText("Methodology")).toBeInTheDocument();
  });

  it("switches tests via the selector", async () => {
    render(<ReasoningBenchmarkCatalog />);
    await screen.findByRole("table");

    const selector = screen.getByLabelText("Reasoning test");
    await userEvent.selectOptions(selector, "debugging-2026-08");

    const table = screen.getByRole("table");
    expect(within(table).getByText("Root-cause accuracy")).toBeInTheDocument();
    expect(within(table).getByText("Codex 5.6 Sol")).toBeInTheDocument();
    expect(within(table).getByText("Codex CLI")).toBeInTheDocument();
    expect(screen.queryByText("Goal understanding")).not.toBeInTheDocument();
  });

  it("shows the error notice and retries the request", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("boom"));

    render(<ReasoningBenchmarkCatalog />);

    expect(await screen.findByText("boom")).toBeInTheDocument();

    vi.mocked(api).mockResolvedValueOnce(catalog);
    await userEvent.click(screen.getByRole("button", {name: "Retry"}));

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(api).toHaveBeenCalledTimes(2);
  });
});
