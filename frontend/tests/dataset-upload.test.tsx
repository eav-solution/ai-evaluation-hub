import {StrictMode} from "react";

import {render, screen, waitFor, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {beforeEach, describe, expect, it, vi} from "vitest";

import {DatasetUpload} from "@/components/DatasetUpload";
import {api} from "@/lib/api";

vi.mock("@/lib/api", () => ({api: vi.fn()}));

const mockedApi = vi.mocked(api);

function csvFile(name: string, rows: number): File {
  const body = ["input,actual_output"];
  for (let index = 0; index < rows; index += 1) body.push(`q${index},a${index}`);
  return new File([body.join("\n")], name, {type: "text/csv"});
}

function filePicker(): HTMLInputElement {
  return screen.getByLabelText("Add dataset files") as HTMLInputElement;
}

describe("DatasetUpload staging", () => {
  beforeEach(() => {
    mockedApi.mockReset();
  });

  it("stages picked files with record count and a prefilled editable name", async () => {
    const user = userEvent.setup();
    render(<DatasetUpload workspaceId="w1" onComplete={() => {}} />);

    await user.upload(filePicker(), csvFile("ragas_faithfulness.csv", 3));

    const row = (await screen.findByText("ragas_faithfulness.csv")).closest(
      ".staged-row",
    ) as HTMLElement;
    await within(row).findByText("3 records");
    const nameInput = within(row).getByLabelText("Dataset name") as HTMLInputElement;
    expect(nameInput.value).toBe("ragas_faithfulness");

    await user.clear(nameInput);
    await user.type(nameInput, "my set");
    expect(nameInput.value).toBe("my set");
    expect(screen.getByRole("button", {name: "Upload 1 file"})).toBeEnabled();
  });

  it("removes a staged row and returns to the idle hint", async () => {
    const user = userEvent.setup();
    render(<DatasetUpload workspaceId="w1" onComplete={() => {}} />);

    await user.upload(filePicker(), csvFile("a.csv", 1));
    await screen.findByText("1 record");
    await user.click(screen.getByRole("button", {name: "Remove a.csv"}));

    expect(screen.queryByText("a.csv")).toBeNull();
    expect(screen.getByText(/drag and drop files or folders/i)).toBeInTheDocument();
  });

  it("flags files over the row limit and excludes them from the upload count", async () => {
    const user = userEvent.setup();
    render(<DatasetUpload workspaceId="w1" onComplete={() => {}} />);

    await user.upload(filePicker(), [csvFile("big.csv", 5001), csvFile("ok.csv", 2)]);

    const bigRow = (await screen.findByText("big.csv")).closest(".staged-row") as HTMLElement;
    await within(bigRow).findByText("Exceeds 5,000 rows");
    await screen.findByRole("button", {name: "Upload 1 file"});
  });

  it("counts skipped unsupported files instead of staging them", async () => {
    const user = userEvent.setup();
    render(<DatasetUpload workspaceId="w1" onComplete={() => {}} />);

    const picker = filePicker();
    picker.removeAttribute("accept");
    await user.upload(picker, [
      csvFile("good.csv", 1),
      new File(["hi"], "notes.txt", {type: "text/plain"}),
    ]);

    await screen.findByText("good.csv");
    expect(screen.getByText("Skipped 1 unsupported file")).toBeInTheDocument();
    expect(screen.queryByText("notes.txt")).toBeNull();
  });

  it("shows a notice when an intake contains no supported files at all", async () => {
    const user = userEvent.setup();
    render(<DatasetUpload workspaceId="w1" onComplete={() => {}} />);

    const picker = filePicker();
    picker.removeAttribute("accept");
    await user.upload(picker, [new File(["hi"], "notes.txt", {type: "text/plain"})]);

    expect(await screen.findByText("No CSV/JSON/JSONL files found")).toBeInTheDocument();

    await user.upload(picker, csvFile("good.csv", 1));
    await screen.findByText("good.csv");
    expect(screen.queryByText("No CSV/JSON/JSONL files found")).toBeNull();
  });

  it("ignores a duplicate of an already-staged file", async () => {
    const user = userEvent.setup();
    render(<DatasetUpload workspaceId="w1" onComplete={() => {}} />);

    const first = csvFile("a.csv", 2);
    await user.upload(filePicker(), first);
    await screen.findByText("2 records");
    await user.upload(filePicker(), csvFile("a.csv", 2));

    expect(screen.getAllByText("a.csv")).toHaveLength(1);
  });

  it("counts records exactly once under React StrictMode's double-invoke", async () => {
    const user = userEvent.setup();
    render(
      <StrictMode>
        <DatasetUpload workspaceId="w1" onComplete={() => {}} />
      </StrictMode>,
    );

    await user.upload(filePicker(), csvFile("strict.csv", 3));

    expect(await screen.findByText("3 records")).toBeInTheDocument();
    expect(screen.getAllByText(/records$/)).toHaveLength(1);
  });
});
