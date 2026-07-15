import {render, screen, waitFor, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {beforeEach, describe, expect, it, vi} from "vitest";

import DatasetsPage from "@/app/w/[workspace]/datasets/page";
import {api} from "@/lib/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({workspace: "workspace-1"}),
}));

vi.mock("@/lib/api", () => ({api: vi.fn()}));

const mockedApi = vi.mocked(api);

describe("DatasetsPage", () => {
  beforeEach(() => {
    mockedApi.mockImplementation(async (path: string) => {
      if (path === "/api/metrics") {
        return [
          {
            key: "deepeval.contextual_relevancy",
            category: "rag",
            sample_kind: "single_turn",
            requires: ["retrieval_contexts"],
          },
          {
            key: "deepeval.bias",
            category: "general",
            sample_kind: "single_turn",
            requires: [],
          },
          {
            key: "deepeval.answer_relevancy",
            category: "rag",
            sample_kind: "single_turn",
            requires: [],
          },
          {
            key: "deepeval.agent_loop_detection",
            category: "agentic",
            sample_kind: "agent_trace",
            requires: ["agent_trace"],
          },
          {
            key: "deepeval.tool_correctness",
            category: "agentic",
            sample_kind: "agent_trace",
            requires: ["tools_called", "expected_tools"],
          },
        ] as never;
      }
      if (path === "/api/workspaces/workspace-1/datasets") {
        return [
          {
            id: "rag-data",
            name: "RAG examples",
            format: "jsonl",
            row_count: 5,
            storage_path: "hidden",
            schema_map: {input: "question", contexts: "documents"},
          },
          {
            id: "general-data",
            name: "General outputs",
            format: "csv",
            row_count: 3,
            storage_path: "hidden",
            schema_map: {input: "prompt", actual_output: "answer"},
          },
          {
            id: "agent-data",
            name: "Agent traces",
            format: "jsonl",
            row_count: 2,
            storage_path: "hidden",
            schema_map: {
              input: "prompt",
              actual_output: "answer",
              agent_trace: "trace",
              tools_called: "called",
              expected_tools: "expected",
            },
          },
        ] as never;
      }
      return undefined as never;
    });
  });

  it("filters upgraded rows by inferred capability without losing datasets", async () => {
    const user = userEvent.setup();
    render(<DatasetsPage />);

    expect(await screen.findByText("RAG examples")).toBeInTheDocument();
    expect(screen.getByText("General outputs")).toBeInTheDocument();
    expect(screen.getByText("Agent traces")).toBeInTheDocument();
    const ragRow = screen.getByText("RAG examples").closest(".dataset-row");
    const generalRow = screen.getByText("General outputs").closest(".dataset-row");
    expect(ragRow).not.toBeNull();
    expect(generalRow).not.toBeNull();
    expect(within(ragRow as HTMLElement).getByText("RAG")).toBeInTheDocument();
    expect(within(ragRow as HTMLElement).getByText("3 compatible metrics")).toBeInTheDocument();
    expect(within(generalRow as HTMLElement).getByText("General")).toBeInTheDocument();
    expect(within(generalRow as HTMLElement).getByText("2 compatible metrics")).toBeInTheDocument();
    const agentRow = screen.getByText("Agent traces").closest(".dataset-row");
    expect(agentRow).not.toBeNull();
    expect(within(agentRow as HTMLElement).getByText("Agentic")).toBeInTheDocument();
    expect(within(agentRow as HTMLElement).getByText("General")).toBeInTheDocument();
    expect(within(agentRow as HTMLElement).getByText("4 compatible metrics")).toBeInTheDocument();

    await user.click(screen.getByRole("button", {name: "RAG"}));
    expect(screen.getByText("RAG examples")).toBeInTheDocument();
    expect(screen.queryByText("General outputs")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", {name: "General"}));
    expect(screen.queryByText("RAG examples")).not.toBeInTheDocument();
    expect(screen.getByText("General outputs")).toBeInTheDocument();

    await user.click(screen.getByRole("button", {name: "Agentic"}));
    expect(screen.getByText("Agent traces")).toBeInTheDocument();
    expect(screen.queryByText("General outputs")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", {name: "All"}));
    await waitFor(() => {
      expect(screen.getByText("RAG examples")).toBeInTheDocument();
      expect(screen.getByText("General outputs")).toBeInTheDocument();
    });
  });
});
