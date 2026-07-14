import {render, screen, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {describe, expect, it, vi} from "vitest";

import {ColumnMapper} from "@/components/DatasetUpload";

describe("ColumnMapper", () => {
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
