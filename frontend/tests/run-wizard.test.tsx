import {readFileSync} from "node:fs";
import {resolve} from "node:path";

import {fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const deepAnswerRelevancy: Metric = {
  ...answerRelevancy,
  key: "deepeval.answer_relevancy",
  framework: "deepeval",
  resources: ["judge"],
  default_config: {threshold: 0.5, include_reason: true, strict_mode: false},
};

const faithfulness: Metric = {
  ...deepAnswerRelevancy,
  key: "deepeval.faithfulness",
  display_name: "Faithfulness",
  description: "Grounded in retrieved evidence",
  requires: ["retrieval_contexts"],
};

const contextualRelevancy: Metric = {
  ...deepAnswerRelevancy,
  key: "deepeval.contextual_relevancy",
  family: "retrieval",
  display_name: "Contextual Relevancy",
  description: "Relevant retrieved evidence",
  requires: ["retrieval_contexts"],
};

const gevalMetric = {
  ...biasMetric,
  key: "deepeval.geval",
  display_name: "G-Eval",
  description: "Custom criteria",
  requires: [],
  requirement_rule: {
    config_field: "evaluation_fields",
    exclude: ["input", "actual_output"],
  },
  requirement_aliases: {},
  config_schema: {
    type: "object",
    properties: {
      evaluation_fields: {
        type: "array",
        title: "Evaluation fields",
        items: {
          type: "string",
          enum: ["input", "actual_output", "context", "retrieval_contexts"],
        },
      },
    },
  },
  default_config: {evaluation_fields: ["input", "actual_output"]},
} as unknown as Metric;

const ragLivePreset = {
  id: "rag_live",
  display_name: "RAG live",
  description: "Core live checks",
  category: "rag" as const,
  mode_hint: "endpoint" as const,
  metric_keys: [
    deepAnswerRelevancy.key,
    faithfulness.key,
    contextualRelevancy.key,
  ],
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
    if (path === "/api/metrics/presets") return Promise.resolve([]) as never;
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
    expect(screen.getByText("Needs mapping: contexts")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name: "General"}));
    expect(screen.getByLabelText("Bias")).toBeEnabled();
  });

  it("recomputes G-Eval requirements from the live adapter config", async () => {
    const user = userEvent.setup();
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[
          {...dataset, schema_map: {input: "prompt", actual_output: "answer"}},
        ]}
        initialMetrics={[gevalMetric]}
        initialConnections={[nativeConnection]}
      />,
    );

    fireEvent.click(screen.getByLabelText("G-Eval"));
    const fields = screen.getByLabelText("Evaluation fields");
    await user.selectOptions(fields, ["input", "context"]);

    expect(screen.getByText("Needs mapping: context")).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "Launch evaluation"})).toBeDisabled();
  });

  it("organizes cards by capability, family, then framework and preserves selection", () => {
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[dataset]}
        initialMetrics={[
          deepAnswerRelevancy,
          {...answerRelevancy, resources: ["judge"]},
          contextualRelevancy,
          biasMetric,
        ]}
        initialConnections={[nativeConnection]}
      />,
    );

    expect(screen.getByRole("button", {name: "RAG"})).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", {name: "Agentic"})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "General"})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "Generation"})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "Retrieval"})).toBeInTheDocument();
    expect(screen.getAllByRole("group", {name: "deepeval"})).toHaveLength(2);
    expect(screen.getByRole("group", {name: "ragas"})).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("deepeval.answer_relevancy"));
    fireEvent.click(screen.getByRole("button", {name: "Retrieval"}));
    expect(screen.queryByLabelText("deepeval.answer_relevancy")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Contextual Relevancy")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {name: "All families"}));
    expect(screen.getByLabelText("deepeval.answer_relevancy")).toBeChecked();

    fireEvent.change(screen.getByLabelText("Search metrics"), {
      target: {value: "retrieved evidence"},
    });
    expect(screen.getByLabelText("Contextual Relevancy")).toBeInTheDocument();
    expect(screen.queryByLabelText("deepeval.answer_relevancy")).not.toBeInTheDocument();
  });

  it("enables the RAG live preset after an endpoint retrieval mapping is configured", async () => {
    mockedApi.mockImplementation((path: string) => {
      if (path === "/api/metrics/presets") return Promise.resolve([ragLivePreset]) as never;
      return Promise.resolve({id: "run-1"}) as never;
    });
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[{...dataset, schema_map: {input: "prompt"}}]}
        initialMetrics={[deepAnswerRelevancy, faithfulness, contextualRelevancy]}
        initialConnections={[nativeConnection]}
      />,
    );

    const preset = await screen.findByRole("button", {name: "RAG live"});
    expect(preset).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Live endpoint"));
    fireEvent.change(screen.getByLabelText("Retrieval contexts JSONPath"), {
      target: {value: "$.documents"},
    });
    expect(preset).toBeEnabled();
    fireEvent.click(preset);

    const picker = screen.getByTestId("metric-picker");
    expect(within(picker).getByLabelText("Answer Relevancy")).toBeChecked();
    expect(within(picker).getByLabelText("Faithfulness")).toBeChecked();
    expect(within(picker).getByLabelText("Contextual Relevancy")).toBeChecked();
    expect(within(picker).getAllByRole("checkbox", {checked: true})).toHaveLength(3);
  });

  it("submits generated metric config and named endpoint response mappings", async () => {
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[{...dataset, schema_map: {input: "prompt"}}]}
        initialMetrics={[biasMetric]}
        initialConnections={[nativeConnection]}
      />,
    );
    fireEvent.click(screen.getByLabelText("Bias"));
    fireEvent.click(screen.getByLabelText("Live endpoint"));
    fireEvent.change(screen.getByLabelText("URL"), {
      target: {value: "https://example.test/chat"},
    });
    fireEvent.change(screen.getByLabelText("Actual output JSONPath"), {
      target: {value: "$.answer"},
    });
    fireEvent.change(screen.getByLabelText("Trusted context JSONPath"), {
      target: {value: "$.facts"},
    });
    fireEvent.change(screen.getByLabelText("Retrieval contexts JSONPath"), {
      target: {value: "$.documents"},
    });
    fireEvent.click(screen.getByLabelText("LLM Model"));
    fireEvent.click(screen.getByRole("option", {name: "gpt-4.1-mini"}));
    fireEvent.click(screen.getByRole("button", {name: "Launch evaluation"}));

    await waitFor(() => {
      const launchCall = mockedApi.mock.calls.find(
        ([path, init]) => path === "/api/workspaces/workspace-1/runs" && init,
      );
      expect(launchCall).toBeDefined();
      const payload = JSON.parse(String(launchCall?.[1]?.body));
      expect(payload.metrics).toEqual([{key: "deepeval.bias", config: {threshold: 0.5}}]);
      expect(payload.endpoint_config.response_mappings).toEqual({
        actual_output: "$.answer",
        context: "$.facts",
        retrieval_contexts: "$.documents",
      });
      expect(payload.endpoint_config).not.toHaveProperty("response_jsonpath");
    });
  });

  it("prevents launch while an Advanced JSON config is invalid", () => {
    const jsonMetric: Metric = {
      ...biasMetric,
      key: "deepeval.json_correctness",
      display_name: "JSON Correctness",
      config_schema: {
        type: "object",
        properties: {
          threshold: {type: "number", title: "Threshold"},
          expected_schema: {type: "object", title: "Expected schema"},
        },
      },
      default_config: {
        threshold: 0.5,
        expected_schema: {type: "object", properties: {}},
      },
    };
    render(
      <RunWizard
        workspaceId="workspace-1"
        initialDatasets={[dataset]}
        initialMetrics={[jsonMetric]}
        initialConnections={[nativeConnection]}
      />,
    );

    fireEvent.click(screen.getByLabelText("JSON Correctness"));
    fireEvent.click(screen.getByLabelText("LLM Model"));
    fireEvent.click(screen.getByRole("option", {name: "gpt-4.1-mini"}));
    const launch = screen.getByRole("button", {name: "Launch evaluation"});
    expect(launch).toBeEnabled();

    fireEvent.change(screen.getByLabelText("Expected schema Advanced JSON"), {
      target: {value: "{"},
    });
    expect(launch).toBeDisabled();
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
    mockedApi.mockImplementation((path: string) => {
      if (path.includes("/models")) return pendingModels as never;
      if (path === "/api/metrics/presets") return Promise.resolve([]) as never;
      return Promise.resolve({id: "run-1"}) as never;
    });
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
