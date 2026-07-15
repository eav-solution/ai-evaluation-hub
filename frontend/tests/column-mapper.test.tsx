import {render, screen, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {describe, expect, it, vi} from "vitest";

import {ColumnMapper} from "@/components/DatasetUpload";

describe("ColumnMapper", () => {
  it("groups compact Common and RAG mappings and selects the legacy contexts alias", () => {
    render(
      <ColumnMapper
        dataset={{
          id: "dataset-legacy",
          name: "Legacy RAG",
          format: "jsonl",
          row_count: 1,
          storage_path: "hidden",
          schema_map: {contexts: "documents"},
          preview: [{question: "Hi", answer: "Hello", documents: ["Greeting"]}],
        }}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByRole("group", {name: "Common / RAG"})).toBeInTheDocument();
    expect(screen.getByLabelText("Input")).toBeInTheDocument();
    expect(screen.getByLabelText("Actual output")).toBeInTheDocument();
    expect(screen.getByLabelText("Expected output")).toBeInTheDocument();
    expect(screen.getByLabelText("Retrieval contexts")).toHaveValue("documents");
    expect(screen.getByLabelText("Trusted context")).toBeInTheDocument();
  });

  it("offers columns that appear after the first preview row", () => {
    render(
      <ColumnMapper
        dataset={{
          id: "dataset-1",
          name: "Sparse answers",
          format: "jsonl",
          row_count: 2,
          storage_path: "hidden",
          schema_map: {},
          preview: [
            {question: "Hi"},
            {question: "Bye", answer: "Goodbye", contexts: ["Greeting"]},
          ],
        }}
        onSave={vi.fn()}
      />,
    );

    const actualOutput = screen.getByLabelText("Actual output");
    expect(actualOutput).toHaveDisplayValue("Not mapped");
    expect(within(actualOutput).getByRole("option", {name: "answer"})).toBeInTheDocument();
    expect(within(actualOutput).getByRole("option", {name: "contexts"})).toBeInTheDocument();
  });

  it("adds one compact Agentic mapping group", () => {
    render(
      <ColumnMapper
        dataset={{
          id: "dataset-agent",
          name: "Agent traces",
          format: "jsonl",
          row_count: 1,
          storage_path: "hidden",
          schema_map: {},
          preview: [
            {
              prompt: "Book a flight",
              answer: "Booked",
              trace: [{type: "tool", name: "book"}],
              called: [{name: "book"}],
              expected: ["book"],
            },
          ],
        }}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByRole("group", {name: "Agentic"})).toBeInTheDocument();
    expect(screen.getByLabelText("Agent trace")).toBeInTheDocument();
    expect(screen.getByLabelText("Tools called")).toBeInTheDocument();
    expect(screen.getByLabelText("Expected tools")).toBeInTheDocument();
  });

  it("maps a conversation dataset without single-turn columns", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(
      <ColumnMapper
        dataset={{
          id: "dataset-conversation",
          name: "Support chats",
          format: "jsonl",
          row_count: 1,
          storage_path: "hidden",
          schema_map: {},
          preview: [{history: [{role: "user", content: "Hi"}]}],
        }}
        onSave={onSave}
      />,
    );

    expect(
      screen.getByRole("group", {name: "Conversational / MCP"}),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Turns")).toBeInTheDocument();
    expect(screen.getByLabelText("Chatbot role")).toBeInTheDocument();
    expect(screen.getByLabelText("Conversation context")).toBeInTheDocument();
    expect(screen.getByLabelText("MCP metadata")).toBeInTheDocument();
    expect(screen.getByLabelText("MCP events")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Turns"), "history");
    await user.click(screen.getByRole("button", {name: "Save mapping"}));

    expect(onSave).toHaveBeenCalledWith({turns: "history"});
  });

  it("saves semantic fields mapped to uploaded columns", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(
      <ColumnMapper
        dataset={{
          id: "dataset-1",
          name: "Answers",
          format: "csv",
          row_count: 1,
          storage_path: "hidden",
          schema_map: {},
          preview: [{question: "Hi", answer: "Hello"}],
        }}
        onSave={onSave}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Input"), "question");
    await user.selectOptions(screen.getByLabelText("Actual output"), "answer");
    await user.click(screen.getByRole("button", {name: "Save mapping"}));

    expect(onSave).toHaveBeenCalledWith({
      input: "question",
      actual_output: "answer",
    });
  });
});
