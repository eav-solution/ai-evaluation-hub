import {render, screen} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {describe, expect, it, vi} from "vitest";

import {ColumnMapper} from "@/components/DatasetUpload";

describe("ColumnMapper", () => {
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
