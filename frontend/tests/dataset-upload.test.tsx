import {StrictMode} from "react";

import {act, render, screen, waitFor, within} from "@testing-library/react";
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
    const errorText = await within(bigRow).findByText("Exceeds 5,000 rows");
    expect(errorText).toHaveClass("staged-error");
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

function mockUploadApi() {
  mockedApi.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      const form = init.body as FormData;
      const name = String(form.get("name"));
      if (name === "fails") throw new Error("Server rejected this file");
      return {
        id: `ds-${name}`,
        name,
        format: "csv",
        row_count: 2,
        storage_path: "",
        schema_map: {},
        preview: [{input: "q", actual_output: "a", note: "n"}],
      };
    }
    if (init?.method === "PATCH") {
      const body = JSON.parse(String(init.body)) as {schema_map: Record<string, string>};
      const id = path.split("/").slice(-2)[0];
      return {
        id,
        name: id,
        format: "csv",
        row_count: 2,
        storage_path: "",
        schema_map: body.schema_map,
        preview: [{input: "q", actual_output: "a", note: "n"}],
      };
    }
    throw new Error(`Unexpected call: ${path}`);
  });
}

describe("DatasetUpload batch upload", () => {
  beforeEach(() => {
    mockedApi.mockReset();
  });

  it("uploads sequentially, auto-maps matching columns, and reports per row", async () => {
    mockUploadApi();
    const onComplete = vi.fn();
    const user = userEvent.setup();
    render(<DatasetUpload workspaceId="w1" onComplete={onComplete} />);

    await user.upload(filePicker(), [csvFile("one.csv", 2), csvFile("two.csv", 2)]);
    await screen.findByRole("button", {name: "Upload 2 files"});
    await user.click(screen.getByRole("button", {name: "Upload 2 files"}));

    await waitFor(() => expect(screen.getAllByText("2 columns mapped")).toHaveLength(2));

    const postCalls = mockedApi.mock.calls.filter(([, init]) => init?.method === "POST");
    const patchCalls = mockedApi.mock.calls.filter(([, init]) => init?.method === "PATCH");
    expect(postCalls.map(([path]) => path)).toEqual([
      "/api/workspaces/w1/datasets",
      "/api/workspaces/w1/datasets",
    ]);
    expect(patchCalls.map(([path]) => path)).toEqual([
      "/api/workspaces/w1/datasets/ds-one/schema-map",
      "/api/workspaces/w1/datasets/ds-two/schema-map",
    ]);
    expect(JSON.parse(String(patchCalls[0][1]?.body))).toEqual({
      schema_map: {input: "input", actual_output: "actual_output"},
    });
    expect(onComplete).toHaveBeenCalledTimes(2);
  });

  it("keeps uploading after a failed file and shows the error on its row", async () => {
    mockUploadApi();
    const user = userEvent.setup();
    render(<DatasetUpload workspaceId="w1" onComplete={() => {}} />);

    await user.upload(filePicker(), [csvFile("fails.csv", 1), csvFile("ok.csv", 1)]);
    await screen.findByRole("button", {name: "Upload 2 files"});
    await user.click(screen.getByRole("button", {name: "Upload 2 files"}));

    await screen.findByText("Server rejected this file");
    await screen.findByText("2 columns mapped");
    expect(
      mockedApi.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(2);
  });

  it("keeps a failed upload's error after its record count resolves late", async () => {
    mockedApi.mockRejectedValue(new Error("Server rejected this file"));
    const user = userEvent.setup();
    render(<DatasetUpload workspaceId="w1" onComplete={() => {}} />);

    // Give this file a `.text()` we control, so its record count stays
    // pending until we resolve it ourselves — after the upload has failed.
    let resolveText!: (value: string) => void;
    const deferred = {
      promise: new Promise<string>((resolve) => {
        resolveText = resolve;
      }),
    };
    const file = csvFile("slow.csv", 1);
    Object.defineProperty(file, "text", {value: () => deferred.promise});

    await user.upload(filePicker(), file);

    // The count never resolves, but a staged row with records===null and no
    // error still counts as uploadable, so the button is enabled.
    const uploadButton = await screen.findByRole("button", {name: "Upload 1 file"});
    expect(uploadButton).toBeEnabled();
    await user.click(uploadButton);

    const row = (await screen.findByText("slow.csv")).closest(".staged-row") as HTMLElement;
    await within(row).findByText("Server rejected this file");

    // NOW let the record count resolve, well after the row has failed.
    await act(async () => {
      resolveText("input,actual_output\nq,a\n");
    });

    expect(within(row).getByText("Server rejected this file")).toBeInTheDocument();
    expect(within(row).queryByText(/record/)).toBeNull();
  });
});

describe("DatasetUpload results", () => {
  beforeEach(() => {
    mockedApi.mockReset();
  });

  it("badges datasets that still need mapping and opens the mapper inline", async () => {
    mockedApi.mockImplementation(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return {
          id: "ds-1",
          name: "quirky",
          format: "csv",
          row_count: 1,
          storage_path: "",
          schema_map: {},
          preview: [{question: "q", answer: "a"}],
        };
      }
      if (init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as {schema_map: Record<string, string>};
        return {
          id: "ds-1",
          name: "quirky",
          format: "csv",
          row_count: 1,
          storage_path: "",
          schema_map: body.schema_map,
          preview: [{question: "q", answer: "a"}],
        };
      }
      throw new Error(`Unexpected call: ${path}`);
    });
    const user = userEvent.setup();
    render(<DatasetUpload workspaceId="w1" onComplete={() => {}} />);

    const quirky = new File(["question,answer\nq,a"], "quirky.csv", {type: "text/csv"});
    await user.upload(filePicker(), quirky);
    await user.click(await screen.findByRole("button", {name: "Upload 1 file"}));

    await screen.findByText("Needs mapping");
    await user.click(screen.getByRole("button", {name: "Map"}));
    expect(await screen.findByText("Common / RAG")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Input"), "question");
    await user.click(screen.getByRole("button", {name: "Save mapping"}));

    await waitFor(() => expect(screen.queryByText("Needs mapping")).toBeNull());
    expect(screen.queryByText("Common / RAG")).toBeNull();
  });

  it("resets the inline mapper's selection when switching to a different row's mapper", async () => {
    mockedApi.mockImplementation(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const form = init.body as FormData;
        const name = String(form.get("name"));
        if (name === "a") {
          return {
            id: "ds-a",
            name: "a",
            format: "csv",
            row_count: 1,
            storage_path: "",
            schema_map: {},
            preview: [{alpha: "x"}],
          };
        }
        return {
          id: "ds-b",
          name: "b",
          format: "csv",
          row_count: 1,
          storage_path: "",
          schema_map: {},
          preview: [{beta: "y"}],
        };
      }
      throw new Error(`Unexpected call: ${path}`);
    });
    const user = userEvent.setup();
    render(<DatasetUpload workspaceId="w1" onComplete={vi.fn()} />);

    await user.upload(filePicker(), [csvFile("a.csv", 1), csvFile("b.csv", 1)]);
    await screen.findByRole("button", {name: "Upload 2 files"});
    await user.click(screen.getByRole("button", {name: "Upload 2 files"}));

    await waitFor(() => expect(screen.getAllByText("Needs mapping")).toHaveLength(2));

    await user.click(screen.getAllByRole("button", {name: "Map"})[0]);
    await user.selectOptions(screen.getByLabelText("Input"), "alpha");
    expect(screen.getByLabelText<HTMLSelectElement>("Input").value).toBe("alpha");

    // Switch to the second row's mapper WITHOUT saving row one's selection.
    await user.click(screen.getAllByRole("button", {name: "Map"})[1]);

    const reopenedInput = screen.getByLabelText<HTMLSelectElement>("Input");
    expect(reopenedInput.value).toBe("");
    expect(within(reopenedInput).getByRole("option", {name: "beta"})).toBeInTheDocument();
    expect(within(reopenedInput).queryByRole("option", {name: "alpha"})).toBeNull();
    // The real proof: if `mapping` state had leaked over from row one, `mapping.input`
    // would still be the truthy stale value "alpha" (even though no <option> named
    // "alpha" exists here to display it), which would leave Save mapping enabled.
    // A properly reset mapper has a fresh, empty mapping, so Save stays disabled.
    expect(screen.getByRole("button", {name: "Save mapping"})).toBeDisabled();
  });

  it("resets to idle after Done", async () => {
    mockUploadApi();
    const user = userEvent.setup();
    render(<DatasetUpload workspaceId="w1" onComplete={() => {}} />);

    await user.upload(filePicker(), csvFile("one.csv", 1));
    await user.click(await screen.findByRole("button", {name: "Upload 1 file"}));
    await user.click(await screen.findByRole("button", {name: "Done"}));

    expect(screen.queryByText("one.csv")).toBeNull();
    expect(screen.getByText(/drag and drop files or folders/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", {name: "Done"})).toBeNull();
  });
});
