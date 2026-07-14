import type {PropsWithChildren} from "react";
import {fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {beforeEach, describe, expect, it, vi} from "vitest";

import {RunReport, metricLabel} from "@/components/RunReport";
import {api} from "@/lib/api";
import type {Metric, Run, RunResult} from "@/lib/types";

vi.mock("@/lib/api", () => ({api: vi.fn(), download: vi.fn()}));
vi.mock("recharts", () => {
  const Box = ({children}: PropsWithChildren) => <div>{children}</div>;
  const Chart = ({children, data}: PropsWithChildren<{data?: unknown}>) => (
    <div data-testid="bar-chart" data-points={JSON.stringify(data ?? [])}>{children}</div>
  );
  const Empty = () => null;
  return {
    ResponsiveContainer: Box,
    BarChart: Chart,
    RadarChart: Chart,
    Bar: Empty,
    CartesianGrid: Empty,
    PolarAngleAxis: Empty,
    PolarGrid: Empty,
    PolarRadiusAxis: Empty,
    Radar: Empty,
    Tooltip: Empty,
    XAxis: Empty,
    YAxis: Empty,
  };
});

const mockedApi = vi.mocked(api);
const metric: Metric = {
  key: "ragas.faithfulness",
  revision: "1",
  framework: "ragas",
  category: "rag",
  family: "generation",
  display_name: "Faithfulness",
  description: "Groundedness",
  sample_kind: "single_turn",
  requires: ["contexts"],
  resources: ["judge"],
  config_schema: {type: "object"},
  default_config: {threshold: null},
  recommended: true,
  info: {
    meaning: "Claims must be grounded.",
    score_direction: "higher_is_better",
    calculation_steps: ["Extract claims.", "Verify claims."],
    formula: "supported / total",
    examples: [
      {title: "Good", inputs: [{label: "Answer", value: "Good"}], checks: [{outcome: "pass", text: "Supported"}], result: "1.00"},
      {title: "Bad", inputs: [{label: "Answer", value: "Bad"}], checks: [{outcome: "fail", text: "Unsupported"}], result: "0.00"},
    ],
    improvement_tips: [{area: "Generation", text: "Ground the answer."}],
    required_data: ["input", "actual_output", "contexts"],
  },
};

const run: Run = {
  id: "run-1",
  dataset_id: "dataset-1",
  name: "RAG benchmark",
  mode: "static",
  metric_config: {metrics: [{key: metric.key, threshold: 0.5}]},
  judge_config: {model: "judge"},
  status: "completed",
  progress_done: 1,
  progress_total: 1,
  error: null,
  created_at: "2026-07-13T00:00:00Z",
  finished_at: "2026-07-13T00:01:00Z",
  summaries: [{metric_key: metric.key, mean: 0.8, min: 0.8, max: 0.8, p50: 0.8, pass_rate: 1, threshold: 0.5}],
};

beforeEach(() => {
  mockedApi.mockReset();
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

function mockReportApi(
  catalog: Promise<Metric[]>,
  nextRun: Run = run,
  results: RunResult[] = [],
) {
  mockedApi.mockImplementation((path: string) => {
    if (path === "/api/metrics") return catalog as never;
    if (path.endsWith("/results")) return Promise.resolve(results) as never;
    return Promise.resolve(nextRun) as never;
  });
}

const toxicity: Metric = {
  ...metric,
  key: "deepeval.toxicity",
  framework: "deepeval",
  display_name: "Toxicity",
  info: {...metric.info, score_direction: "lower_is_better"},
};

function result(row_index: number, input: string, score: number | null): RunResult {
  return {
    id: `result-${row_index}`,
    row_index,
    input,
    expected: null,
    actual: "answer",
    contexts: null,
    scores: {
      [toxicity.key]: {score, reason: null, passed: score === null ? null : score < 0.5, error: null},
    },
    error: null,
    latency_ms: 10,
    details: null,
    usage: null,
    estimated_cost: null,
  };
}

describe("metricLabel", () => {
  it("prefers the catalog display name", () => {
    const map = new Map<string, Metric>([[metric.key, metric]]);
    expect(metricLabel(map, metric.key)).toBe("Faithfulness");
  });

  it("falls back to the raw key when the metric is missing", () => {
    expect(metricLabel(new Map(), "ragas.faithfulness")).toBe("ragas.faithfulness");
  });
});

describe("RunReport metric information", () => {
  it("opens catalog information from a summary card", async () => {
    mockReportApi(Promise.resolve([metric]));
    render(<RunReport workspaceId="workspace-1" runId="run-1" />);

    await screen.findByText("RAG benchmark");
    fireEvent.click(await screen.findByRole("button", {name: "About Faithfulness"}));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Claims must be grounded.")).toBeInTheDocument();
  });

  it("sorts lower-is-better scores while keeping missing values last", async () => {
    const toxicityRun: Run = {
      ...run,
      metric_config: {metrics: [{key: toxicity.key, threshold: 0.5}]},
      progress_done: 3,
      progress_total: 3,
      summaries: [
        {metric_key: toxicity.key, mean: 0.1, min: 0.1, max: 0.8, p50: 0.1, pass_rate: 0.5, threshold: 0.5},
      ],
    };
    mockReportApi(Promise.resolve([toxicity]), toxicityRun, [
      result(0, "missing", null),
      result(1, "high", 0.8),
      result(2, "low", 0.1),
    ]);
    render(<RunReport workspaceId="workspace-1" runId="run-1" />);

    await screen.findByText("RAG benchmark");
    fireEvent.change(screen.getByLabelText("Sort by"), {target: {value: toxicity.key}});
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("low")).toBeInTheDocument();
    expect(within(rows[1]).getByText("high")).toBeInTheDocument();
    expect(within(rows[2]).getByText("missing")).toBeInTheDocument();
    expect(screen.getByText("Lower is better")).toBeInTheDocument();
    const comparison = JSON.parse(
      screen.getAllByTestId("bar-chart")[0].getAttribute("data-points")!,
    );
    expect(comparison[0]).toMatchObject({raw_mean: 0.1, comparison_score: 0.9});
    expect(screen.getAllByText("0.100")).toHaveLength(2);
  });

  it("shows unknown direction without normalizing historical metrics", async () => {
    mockReportApi(Promise.resolve([]));
    render(<RunReport workspaceId="workspace-1" runId="run-1" />);

    await screen.findByText("RAG benchmark");
    expect(screen.getByText("Direction unavailable")).toBeInTheDocument();
    const comparison = JSON.parse(
      screen.getAllByTestId("bar-chart")[0].getAttribute("data-points")!,
    );
    expect(comparison).toEqual([]);
  });

  it("keeps report results usable when the catalog fails", async () => {
    mockReportApi(Promise.reject(new Error("catalog unavailable")));
    render(<RunReport workspaceId="workspace-1" runId="run-1" />);

    expect(await screen.findByText("RAG benchmark")).toBeInTheDocument();
    expect(screen.getByText("0.800")).toBeInTheDocument();
    await waitFor(() => expect(mockedApi).toHaveBeenCalledWith("/api/metrics"));
    expect(screen.queryByRole("button", {name: "About Faithfulness"})).not.toBeInTheDocument();
    expect(screen.queryByText("catalog unavailable")).not.toBeInTheDocument();
  });

  it("omits information for a historical metric missing from the catalog", async () => {
    mockReportApi(Promise.resolve([]));
    render(<RunReport workspaceId="workspace-1" runId="run-1" />);

    expect(await screen.findByText("RAG benchmark")).toBeInTheDocument();
    await waitFor(() => expect(mockedApi).toHaveBeenCalledWith("/api/metrics"));
    expect(screen.queryByRole("button", {name: "About Faithfulness"})).not.toBeInTheDocument();
  });
});
