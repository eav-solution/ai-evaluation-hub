import {readFileSync} from "node:fs";
import {resolve} from "node:path";

import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {beforeEach, describe, expect, it, vi} from "vitest";

import {RunWizard} from "@/components/RunWizard";
import {api} from "@/lib/api";
import type {Metric, ProviderConnection} from "@/lib/types";

const metricInfo: Metric["info"] = {
  meaning: "Explains the metric.",
  score_direction: "higher_is_better",
  calculation_steps: ["First step.", "Second step."],
  formula: "score = good / total",
  examples: [
    {title: "Good", inputs: [{label: "Answer", value: "Good"}], checks: [{outcome: "pass", text: "Pass"}], result: "1.00"},
    {title: "Bad", inputs: [{label: "Answer", value: "Bad"}], checks: [{outcome: "fail", text: "Fail"}], result: "0.00"},
  ],
  improvement_tips: [{area: "Generation", text: "Improve the prompt."}],
  required_data: ["input", "actual_output"],
};

vi.mock("next/navigation", () => ({
  useRouter: () => ({push: vi.fn()}),
}));

vi.mock("@/lib/api", () => ({api: vi.fn()}));

const mockedApi = vi.mocked(api);

const dataset = {
  id: "dataset-1",
  name: "Answers",
  format: "json",
  row_count: 2,
  storage_path: "hidden",
  schema_map: {input: "prompt", actual_output: "answer", contexts: "contexts"},
};

const nativeConnection: ProviderConnection = {
  id: "conn-openai",
  name: "OpenAI",
  connection_type: "openai",
  base_url: null,
  has_key: true,
  key_hint: "…key",
};

const customConnection: ProviderConnection = {
  id: "conn-custom",
  name: "Gateway",
  connection_type: "openai_compatible",
  base_url: "http://gateway/v1",
  has_key: false,
  key_hint: null,
};

const biasMetric: Metric = {
  key: "deepeval.bias",
  revision: "1",
  framework: "deepeval",
  category: "general",
  family: "text_safety",
  display_name: "Bias",
  description: "Bias",
  sample_kind: "single_turn",
  requires: [],
  resources: ["judge"],
  config_schema: {type: "object"},
  default_config: {threshold: 0.5},
  recommended: true,
  info: metricInfo,
};

const answerRelevancy: Metric = {
  ...biasMetric,
  key: "ragas.answer_relevancy",
  framework: "ragas",
  category: "rag",
  family: "generation",
  display_name: "Answer Relevancy",
  description: "Relevancy",
  resources: ["judge", "embedding"],
  default_config: {threshold: null},
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
  mockedApi.mockImplementation((path: string) => {
    if (path.includes("/models")) {
      return Promise.resolve({models: ["chat-a", "chat-b", "embed-x"]}) as never;
    }
    return Promise.resolve({id: "run-1"}) as never;
  });
});

describe("RunWizard", () => {
  it("keeps every metric framework on a fixed five-column grid", () => {
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");

    expect(css).toMatch(
      /\.metric-grid\s*\{[^}]*grid-template-columns:\s*repeat\(5,\s*minmax\(0,\s*1fr\)\)/,
    );
  });

  it("opens metric information without toggling selection", () => {
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[dataset]}
        initialMetrics={[biasMetric]}
        initialConnections={[nativeConnection]}
      />,
    );

    const checkbox = screen.getByLabelText("Bias");
    expect(checkbox).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", {name: "About Bias"}));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Explains the metric.")).toBeInTheDocument();
    expect(checkbox).not.toBeChecked();
  });

  it("uses consistent LLM and embedding field labels", () => {
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[dataset]}
        initialMetrics={[answerRelevancy]}
        initialConnections={[nativeConnection]}
      />,
    );

    fireEvent.click(screen.getByLabelText("Answer Relevancy"));

    expect(screen.getByLabelText("LLM Connection")).toBeDefined();
    expect(screen.getByLabelText("LLM Model")).toBeDefined();
    expect(screen.getByLabelText("Embedding Connection")).toBeDefined();
    expect(screen.getByLabelText("Embedding Model")).toBeDefined();
  });

  it("discovers embedding requirements from metric resource metadata", () => {
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[dataset]}
        initialMetrics={[
          {
            ...biasMetric,
            key: "test.embedding",
            display_name: "Metadata embedding",
            resources: ["judge", "embedding"],
          },
        ]}
        initialConnections={[nativeConnection]}
      />,
    );

    fireEvent.click(screen.getByLabelText("Metadata embedding"));

    expect(screen.getByLabelText("Embedding Connection")).toBeDefined();
    expect(screen.getByLabelText("Embedding Model")).toBeDefined();
  });

  it("disables metrics whose required columns are not mapped", () => {
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[{...dataset, schema_map: {input: "prompt", actual_output: "answer"}}]}
        initialMetrics={[
          {
            ...biasMetric,
            key: "ragas.faithfulness",
            framework: "ragas",
            category: "rag",
            family: "generation",
            display_name: "Faithfulness",
            description: "Groundedness",
            requires: ["contexts"],
            resources: ["judge"],
            info: metricInfo,
          },
          biasMetric,
        ]}
        initialConnections={[nativeConnection]}
      />,
    );

    expect(screen.getByLabelText("Faithfulness")).toBeDisabled();
    expect(screen.getByLabelText("Bias")).toBeEnabled();
    expect(screen.getByText("Needs mapping: contexts")).toBeInTheDocument();
  });

  it("offers curated model options for a native connection", () => {
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[dataset]}
        initialMetrics={[biasMetric]}
        initialConnections={[nativeConnection]}
      />,
    );
    const model = screen.getByLabelText("LLM Model");
    expect(model).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(model);
    expect(screen.getByRole("searchbox", {name: "Search models"})).toBeDefined();
    expect(screen.getByRole("option", {name: "gpt-4.1-mini"})).toBeDefined();
  });

  it("shows a searchable model selector for a custom connection", async () => {
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[dataset]}
        initialMetrics={[biasMetric]}
        initialConnections={[customConnection]}
      />,
    );
    await waitFor(() => expect(screen.getByLabelText("LLM Model")).toBeDefined());
    fireEvent.click(screen.getByLabelText("LLM Model"));
    expect(screen.getByRole("searchbox", {name: "Search models"})).toBeDefined();
  });

  it("enables the native picker after leaving a loading custom connection", async () => {
    const pendingModels = new Promise<{models: string[]}>(() => {});
    mockedApi.mockImplementation((path: string) =>
      path.includes("/models") ? pendingModels as never : Promise.resolve({id: "run-1"}) as never,
    );
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[dataset]}
        initialMetrics={[biasMetric]}
        initialConnections={[customConnection, nativeConnection]}
      />,
    );

    await waitFor(() => expect(screen.getByLabelText("LLM Model")).toBeDisabled());
    fireEvent.change(screen.getByLabelText("LLM Connection"), {
      target: {value: nativeConnection.id},
    });
    expect(screen.getByLabelText("LLM Model")).not.toBeDisabled();
  });

  it("requires a separate embedding connection for embedding metrics", async () => {
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[dataset]}
        initialMetrics={[answerRelevancy]}
        initialConnections={[nativeConnection, customConnection]}
      />,
    );
    // select the embedding-dependent metric
    fireEvent.click(screen.getByLabelText("Answer Relevancy"));

    const launch = screen.getByRole("button", {name: /Launch evaluation/i});
    expect(launch).toBeDisabled();

    fireEvent.click(screen.getByLabelText("LLM Model"));
    fireEvent.click(screen.getByRole("option", {name: "gpt-4.1-mini"}));

    // an embedding connection picker appears; pick the custom one
    fireEvent.change(screen.getByLabelText("Embedding Connection"), {
      target: {value: customConnection.id},
    });
    await waitFor(() => expect(screen.getByLabelText("Embedding Model")).toBeDefined());
    fireEvent.click(screen.getByLabelText("Embedding Model"));
    fireEvent.change(screen.getByRole("searchbox", {name: "Search models"}), {
      target: {value: "embed"},
    });
    fireEvent.click(screen.getByRole("option", {name: "embed-x"}));
    expect(launch).toBeEnabled();
  });

  it("offers curated options for a native embedding connection", async () => {
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[dataset]}
        initialMetrics={[answerRelevancy]}
        initialConnections={[nativeConnection]}
      />,
    );
    fireEvent.click(screen.getByLabelText("Answer Relevancy"));
    fireEvent.click(screen.getByLabelText("LLM Model"));
    fireEvent.click(screen.getByRole("option", {name: "gpt-4.1-mini"}));
    fireEvent.change(screen.getByLabelText("Embedding Connection"), {
      target: {value: nativeConnection.id},
    });
    fireEvent.click(screen.getByLabelText("Embedding Model"));
    fireEvent.click(screen.getByRole("option", {name: "text-embedding-3-small"}));
    expect(screen.getByRole("button", {name: /Launch evaluation/i})).toBeEnabled();
  });
});
