# Dataset Upload Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fake single-file upload form with a real drag-and-drop, multi-file/folder staged upload that counts records client-side, prefills dataset names, uploads sequentially, and auto-maps columns matching schema fields.

**Architecture:** Pure staging logic (format detection, record counting, folder traversal, auto-mapping) lives in a new `frontend/lib/dataset-staging.ts` module with DOM-free unit tests. `DatasetUpload.tsx` consumes it and manages a staged-file list through three phases (`staging → uploading → done`), reusing the existing `ColumnMapper` inline for datasets that auto-mapping couldn't finish. Backend untouched: one `POST` per file plus an optional `PATCH …/schema-map`.

**Tech Stack:** Next.js 16, React 19, TypeScript, vitest + @testing-library/react + userEvent (jsdom).

**Spec:** `docs/superpowers/specs/2026-07-15-dataset-upload-redesign-design.md`

## Global Constraints

- Run all frontend commands from `frontend/` (`npm test` = `vitest run`).
- No backend changes. Upload stays `POST /api/workspaces/{id}/datasets` with FormData fields `name` and `file`; mapping stays `PATCH /api/workspaces/{id}/datasets/{datasetId}/schema-map` with body `{schema_map}`.
- `DatasetUpload` keeps its public props `{workspaceId: string; onComplete: (dataset: Dataset) => void}`. `ColumnMapper` internals unchanged.
- Row limit constant: 5,000 records per file (server enforces the same in `backend/app/datasets.py`).
- Supported extensions: `.csv`, `.json`, `.jsonl`, case-insensitive.
- UI copy in English, sentence case, no exclamation marks (matches the rest of the app).
- Every commit message ends with the two trailers used in this repo:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` then `Authored-By: EaV Solution`.
- Commits require the user's standing approval for this plan's execution — confirm it once before Task 1's first commit.

---

### Task 1: Staging helpers (format, record counting, auto-map)

**Files:**
- Create: `frontend/lib/dataset-staging.ts`
- Test: `frontend/tests/dataset-staging.test.ts`

**Interfaces:**
- Consumes: nothing (pure functions).
- Produces:
  - `type StagedFormat = "csv" | "json" | "jsonl"`
  - `MAX_ROWS = 5000`
  - `detectFormat(filename: string): StagedFormat | null`
  - `isSupportedFile(filename: string): boolean`
  - `stripExtension(filename: string): string`
  - `countRecords(text: string, format: StagedFormat): number` (throws on invalid JSON / non-array JSON root)
  - `autoMapColumns(columns: string[]): Record<string, string>`

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/dataset-staging.test.ts`:

```ts
import {describe, expect, it} from "vitest";

import {
  autoMapColumns,
  countRecords,
  detectFormat,
  isSupportedFile,
  stripExtension,
} from "@/lib/dataset-staging";

describe("detectFormat / isSupportedFile", () => {
  it("detects supported extensions case-insensitively", () => {
    expect(detectFormat("a.csv")).toBe("csv");
    expect(detectFormat("b.JSON")).toBe("json");
    expect(detectFormat("c.JsonL")).toBe("jsonl");
  });

  it("rejects unsupported files and dotfiles", () => {
    expect(detectFormat("notes.txt")).toBeNull();
    expect(detectFormat(".DS_Store")).toBeNull();
    expect(detectFormat("no-extension")).toBeNull();
    expect(isSupportedFile("x.csv")).toBe(true);
    expect(isSupportedFile("x.txt")).toBe(false);
  });
});

describe("stripExtension", () => {
  it("drops the final extension only", () => {
    expect(stripExtension("ragas_faithfulness.csv")).toBe("ragas_faithfulness");
    expect(stripExtension("multi.part.jsonl")).toBe("multi.part");
    expect(stripExtension("no-extension")).toBe("no-extension");
  });
});

describe("countRecords", () => {
  it("counts csv data rows excluding the header", () => {
    expect(countRecords("a,b\n1,2\n3,4\n", "csv")).toBe(2);
  });

  it("does not split quoted multi-line csv cells", () => {
    const text = 'a,b\n1,"line one\nline two"\n2,plain\n';
    expect(countRecords(text, "csv")).toBe(2);
  });

  it("ignores trailing blank csv lines and a header-only file counts zero", () => {
    expect(countRecords("a,b\n1,2\n\n\n", "csv")).toBe(1);
    expect(countRecords("a,b\n", "csv")).toBe(0);
  });

  it("counts json array length and rejects non-arrays", () => {
    expect(countRecords('[{"x":1},{"x":2}]', "json")).toBe(2);
    expect(() => countRecords('{"x":1}', "json")).toThrow();
    expect(() => countRecords("not json", "json")).toThrow();
  });

  it("counts non-empty jsonl lines", () => {
    expect(countRecords('{"x":1}\n\n{"x":2}\n', "jsonl")).toBe(2);
  });
});

describe("autoMapColumns", () => {
  it("maps columns whose names match schema fields exactly", () => {
    expect(autoMapColumns(["input", "actual_output", "case", "note"])).toEqual({
      input: "input",
      actual_output: "actual_output",
    });
  });

  it("maps legacy contexts to retrieval_contexts unless the real key exists", () => {
    expect(autoMapColumns(["input", "contexts"])).toEqual({
      input: "input",
      retrieval_contexts: "contexts",
    });
    expect(autoMapColumns(["input", "contexts", "retrieval_contexts"])).toEqual({
      input: "input",
      retrieval_contexts: "retrieval_contexts",
    });
  });

  it("returns an empty mapping when nothing matches", () => {
    expect(autoMapColumns(["question", "answer"])).toEqual({});
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run tests/dataset-staging.test.ts`
Expected: FAIL — cannot resolve `@/lib/dataset-staging`.

- [ ] **Step 3: Implement the module**

Create `frontend/lib/dataset-staging.ts`:

```ts
export type StagedFormat = "csv" | "json" | "jsonl";

export const MAX_ROWS = 5000;

const EXTENSION_FORMATS: Record<string, StagedFormat> = {
  ".csv": "csv",
  ".json": "json",
  ".jsonl": "jsonl",
};

const SCHEMA_FIELDS = [
  "input",
  "actual_output",
  "expected_output",
  "retrieval_contexts",
  "context",
  "agent_trace",
  "tools_called",
  "expected_tools",
  "turns",
  "chatbot_role",
  "conversation_context",
  "mcp_metadata",
  "mcp_events",
] as const;

export function detectFormat(filename: string): StagedFormat | null {
  const match = /\.[^.]+$/.exec(filename.toLowerCase());
  if (!match || match.index === 0) return null;
  return EXTENSION_FORMATS[match[0]] ?? null;
}

export function isSupportedFile(filename: string): boolean {
  return detectFormat(filename) !== null;
}

export function stripExtension(filename: string): string {
  const match = /\.[^.]+$/.exec(filename);
  return match && match.index > 0 ? filename.slice(0, match.index) : filename;
}

function countCsvRows(text: string): number {
  let rows = 0;
  let inQuotes = false;
  let lineStart = 0;
  const flush = (end: number) => {
    if (text.slice(lineStart, end).trim() !== "") rows += 1;
  };
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') inQuotes = !inQuotes;
    else if (char === "\n" && !inQuotes) {
      flush(index);
      lineStart = index + 1;
    }
  }
  flush(text.length);
  return rows;
}

export function countRecords(text: string, format: StagedFormat): number {
  if (format === "json") {
    const parsed: unknown = JSON.parse(text);
    if (!Array.isArray(parsed)) throw new Error("JSON root must be an array");
    return parsed.length;
  }
  if (format === "jsonl") {
    return text.split("\n").filter((line) => line.trim() !== "").length;
  }
  return Math.max(0, countCsvRows(text) - 1);
}

export function autoMapColumns(columns: string[]): Record<string, string> {
  const mapping: Record<string, string> = {};
  for (const column of columns) {
    if ((SCHEMA_FIELDS as readonly string[]).includes(column)) {
      mapping[column] = column;
    }
  }
  if (!mapping.retrieval_contexts && columns.includes("contexts")) {
    mapping.retrieval_contexts = "contexts";
  }
  return mapping;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run tests/dataset-staging.test.ts`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/dataset-staging.ts frontend/tests/dataset-staging.test.ts
git commit -m "feat(datasets): add staging helpers for client-side upload validation"
```

---

### Task 2: Folder traversal for drag-and-drop

**Files:**
- Modify: `frontend/lib/dataset-staging.ts` (append)
- Test: `frontend/tests/dataset-staging.test.ts` (append)

**Interfaces:**
- Consumes: nothing from Task 1 (independent addition to the same module).
- Produces:
  - `collectFilesFromDataTransfer(items: DataTransferItemList): Promise<File[]>` — resolves every file in the drop, walking directories recursively via `webkitGetAsEntry()`; falls back to `getAsFile()` when the entry API is unavailable. Returns files unfiltered (the component filters by extension).

**Background for the implementer:** `DataTransferItem.webkitGetAsEntry()` returns a `FileSystemEntry`. Directory readers return entries in batches (Chrome caps at 100 per `readEntries` call), so you must call `readEntries` in a loop until it returns an empty batch. jsdom implements none of this — tests use hand-rolled fake entries, which is why the implementation types entries structurally instead of using DOM lib types.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/tests/dataset-staging.test.ts`:

```ts
import {collectFilesFromDataTransfer} from "@/lib/dataset-staging";

type FakeEntry = {
  isFile: boolean;
  isDirectory: boolean;
  file?: (resolve: (file: File) => void, reject?: (error: unknown) => void) => void;
  createReader?: () => {
    readEntries: (
      resolve: (entries: FakeEntry[]) => void,
      reject?: (error: unknown) => void,
    ) => void;
  };
};

function fakeFileEntry(name: string): FakeEntry {
  return {
    isFile: true,
    isDirectory: false,
    file: (resolve) => resolve(new File(["a,b\n1,2\n"], name, {type: "text/csv"})),
  };
}

function fakeDirectoryEntry(children: FakeEntry[], batchSize = 2): FakeEntry {
  let cursor = 0;
  return {
    isFile: false,
    isDirectory: true,
    createReader: () => ({
      readEntries: (resolve) => {
        const batch = children.slice(cursor, cursor + batchSize);
        cursor += batch.length;
        resolve(batch);
      },
    }),
  };
}

function fakeDataTransferItems(entries: (FakeEntry | null)[], files: (File | null)[] = []) {
  const items = entries.map((entry, index) => ({
    webkitGetAsEntry: () => entry,
    getAsFile: () => files[index] ?? null,
  }));
  return items as unknown as DataTransferItemList;
}

describe("collectFilesFromDataTransfer", () => {
  it("collects plain file drops", async () => {
    const items = fakeDataTransferItems([fakeFileEntry("a.csv"), fakeFileEntry("b.jsonl")]);
    const files = await collectFilesFromDataTransfer(items);
    expect(files.map((file) => file.name)).toEqual(["a.csv", "b.jsonl"]);
  });

  it("walks directories recursively across readEntries batches", async () => {
    const nested = fakeDirectoryEntry([fakeFileEntry("deep.csv")]);
    const root = fakeDirectoryEntry(
      [fakeFileEntry("one.csv"), fakeFileEntry("two.csv"), fakeFileEntry("three.csv"), nested],
      2,
    );
    const files = await collectFilesFromDataTransfer(fakeDataTransferItems([root]));
    expect(files.map((file) => file.name).sort()).toEqual(
      ["deep.csv", "one.csv", "three.csv", "two.csv"],
    );
  });

  it("falls back to getAsFile when the entry API is unavailable", async () => {
    const fallback = new File(["x"], "fallback.csv", {type: "text/csv"});
    const files = await collectFilesFromDataTransfer(fakeDataTransferItems([null], [fallback]));
    expect(files.map((file) => file.name)).toEqual(["fallback.csv"]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run tests/dataset-staging.test.ts`
Expected: FAIL — `collectFilesFromDataTransfer` is not exported.

- [ ] **Step 3: Implement traversal**

Append to `frontend/lib/dataset-staging.ts`:

```ts
type EntryLike = {
  isFile: boolean;
  isDirectory: boolean;
  file?: (resolve: (file: File) => void, reject?: (error: unknown) => void) => void;
  createReader?: () => {
    readEntries: (
      resolve: (entries: EntryLike[]) => void,
      reject?: (error: unknown) => void,
    ) => void;
  };
};

function entryFile(entry: EntryLike): Promise<File | null> {
  return new Promise((resolve) => {
    if (!entry.file) return resolve(null);
    entry.file(resolve, () => resolve(null));
  });
}

function readBatch(reader: ReturnType<NonNullable<EntryLike["createReader"]>>): Promise<EntryLike[]> {
  return new Promise((resolve) => {
    reader.readEntries(resolve, () => resolve([]));
  });
}

async function walkEntry(entry: EntryLike): Promise<File[]> {
  if (entry.isFile) {
    const file = await entryFile(entry);
    return file ? [file] : [];
  }
  if (!entry.isDirectory || !entry.createReader) return [];
  const reader = entry.createReader();
  const files: File[] = [];
  for (;;) {
    const batch = await readBatch(reader);
    if (!batch.length) break;
    for (const child of batch) files.push(...(await walkEntry(child)));
  }
  return files;
}

export async function collectFilesFromDataTransfer(
  items: DataTransferItemList,
): Promise<File[]> {
  const collected: File[] = [];
  const walks: Promise<File[]>[] = [];
  for (const item of Array.from(items)) {
    const entry = (
      item as DataTransferItem & {webkitGetAsEntry?: () => EntryLike | null}
    ).webkitGetAsEntry?.();
    if (entry) walks.push(walkEntry(entry));
    else {
      const file = item.getAsFile?.();
      if (file) collected.push(file);
    }
  }
  for (const files of await Promise.all(walks)) collected.push(...files);
  return collected;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run tests/dataset-staging.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/dataset-staging.ts frontend/tests/dataset-staging.test.ts
git commit -m "feat(datasets): walk dropped folders recursively for batch staging"
```

---

### Task 3: Staged-list intake UI

**Files:**
- Modify: `frontend/components/DatasetUpload.tsx` (replace the `DatasetUpload` function; keep `ColumnMapper` and its imports untouched)
- Modify: `frontend/app/globals.css` (upload section, lines ~109-119)
- Test: `frontend/tests/dataset-upload.test.tsx` (new)

**Interfaces:**
- Consumes: everything exported by `frontend/lib/dataset-staging.ts` (Tasks 1-2).
- Produces: the internal `StagedRow` shape Tasks 4-5 extend —

```ts
type StagedRow = {
  id: string;
  file: File;
  format: StagedFormat;
  name: string;
  records: number | null;
  error: string | null;
  status: "staged" | "uploading" | "uploaded" | "failed";
  dataset?: Dataset;
  mappedCount?: number;
  needsMapping?: boolean;
};
```

Component-level state: `rows: StagedRow[]`, `skipped: number`, `phase: "staging" | "uploading" | "done"`, `error: string`. In this task the Upload button is wired but its handler is a stub (`console.error` placeholder is NOT acceptable — wire it to an empty `async function uploadAll() {}` implemented in Task 4).

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/dataset-upload.test.tsx`:

```tsx
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
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run tests/dataset-upload.test.tsx`
Expected: FAIL — current component renders the old single-file form (no "Add dataset files" label).

- [ ] **Step 3: Replace the `DatasetUpload` function**

In `frontend/components/DatasetUpload.tsx`, keep the imports, field constants, and `ColumnMapper` as they are; replace the entire `DatasetUpload` function (currently lines 115-180) with:

```tsx
type StagedRow = {
  id: string;
  file: File;
  format: StagedFormat;
  name: string;
  records: number | null;
  error: string | null;
  status: "staged" | "uploading" | "uploaded" | "failed";
  dataset?: Dataset;
  mappedCount?: number;
  needsMapping?: boolean;
};

const folderInputProps = {
  webkitdirectory: "",
} as React.InputHTMLAttributes<HTMLInputElement>;

export function DatasetUpload({
  workspaceId,
  onComplete,
}: {
  workspaceId: string;
  onComplete: (dataset: Dataset) => void;
}) {
  const [rows, setRows] = useState<StagedRow[]>([]);
  const [skipped, setSkipped] = useState(0);
  const [phase, setPhase] = useState<"staging" | "uploading" | "done">("staging");
  const [notice, setNotice] = useState("");
  const [dragover, setDragover] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const prevent = (event: DragEvent) => event.preventDefault();
    window.addEventListener("dragover", prevent);
    window.addEventListener("drop", prevent);
    return () => {
      window.removeEventListener("dragover", prevent);
      window.removeEventListener("drop", prevent);
    };
  }, []);

  function patchRow(id: string, patch: Partial<StagedRow>) {
    setRows((current) =>
      current.map((row) => (row.id === id ? {...row, ...patch} : row)),
    );
  }

  function addFiles(incoming: File[]) {
    const supported = incoming.filter((file) => isSupportedFile(file.name));
    setNotice(
      incoming.length > 0 && supported.length === 0
        ? "No CSV/JSON/JSONL files found"
        : "",
    );
    setSkipped((count) => count + (incoming.length - supported.length));
    setRows((current) => {
      const fresh = supported.filter(
        (file) =>
          !current.some(
            (row) => row.file.name === file.name && row.file.size === file.size,
          ),
      );
      const added = fresh.map<StagedRow>((file) => ({
        id: crypto.randomUUID(),
        file,
        format: detectFormat(file.name) as StagedFormat,
        name: stripExtension(file.name),
        records: null,
        error: null,
        status: "staged",
      }));
      for (const row of added) {
        row.file
          .text()
          .then((text) => {
            const records = countRecords(text, row.format);
            patchRow(row.id, {
              records,
              error: records > MAX_ROWS ? "Exceeds 5,000 rows" : null,
            });
          })
          .catch(() => patchRow(row.id, {error: "Could not read this file"}));
      }
      return [...current, ...added];
    });
  }

  async function onDrop(event: React.DragEvent) {
    event.preventDefault();
    setDragover(false);
    addFiles(await collectFilesFromDataTransfer(event.dataTransfer.items));
  }

  function openFilePicker() {
    fileInputRef.current?.click();
  }

  const uploadable = rows.filter((row) => row.status === "staged" && !row.error);
  const canUpload =
    phase === "staging" &&
    uploadable.length > 0 &&
    uploadable.every((row) => row.name.trim() !== "");

  async function uploadAll() {}

  return (
    <div className="upload-zone">
      <div
        className={`upload-drop${dragover ? " dragover" : ""}`}
        role="button"
        tabIndex={0}
        aria-label="Add dataset files or folders"
        onClick={openFilePicker}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openFilePicker();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setDragover(true);
        }}
        onDragLeave={() => setDragover(false)}
        onDrop={onDrop}
      >
        <span className="upload-icon" aria-hidden="true">↑</span>
        <strong>Drag and drop files or folders</strong>
        <p className="muted">or click to browse · CSV, JSON, JSONL · up to 5,000 rows each</p>
      </div>
      <input
        ref={fileInputRef}
        className="sr-only"
        type="file"
        multiple
        accept=".csv,.json,.jsonl"
        aria-label="Add dataset files"
        onChange={(event) => {
          addFiles(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
      <input
        ref={folderInputRef}
        className="sr-only"
        type="file"
        aria-label="Add a dataset folder"
        {...folderInputProps}
        onChange={(event) => {
          addFiles(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
      {notice && <p className="notice error">{notice}</p>}
      {skipped > 0 && (
        <p className="muted skip-note">
          Skipped {skipped} unsupported file{skipped === 1 ? "" : "s"}
        </p>
      )}
      {rows.length > 0 && (
        <ul className="staged-list">
          {rows.map((row) => (
            <li className="staged-row" key={row.id}>
              <span className="staged-file">
                <strong>{row.file.name}</strong>
                <small>
                  {row.error ??
                    (row.records === null
                      ? "Counting records…"
                      : `${row.records} record${row.records === 1 ? "" : "s"}`)}
                </small>
              </span>
              <input
                aria-label="Dataset name"
                value={row.name}
                disabled={phase !== "staging"}
                onChange={(event) => patchRow(row.id, {name: event.target.value})}
              />
              <button
                type="button"
                className="ghost"
                aria-label={`Remove ${row.file.name}`}
                disabled={phase === "uploading"}
                onClick={() =>
                  setRows((current) => current.filter((item) => item.id !== row.id))
                }
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="upload-actions">
        <button type="button" onClick={() => folderInputRef.current?.click()}>
          Choose folder
        </button>
        <button
          type="button"
          className="primary"
          disabled={!canUpload}
          onClick={uploadAll}
        >
          Upload {uploadable.length} file{uploadable.length === 1 ? "" : "s"}
        </button>
      </div>
    </div>
  );
}
```

Adjust the imports at the top of the file:

```tsx
import {useEffect, useMemo, useRef, useState} from "react";

import {api} from "@/lib/api";
import {
  collectFilesFromDataTransfer,
  countRecords,
  detectFormat,
  isSupportedFile,
  MAX_ROWS,
  stripExtension,
  type StagedFormat,
} from "@/lib/dataset-staging";
import type {Dataset} from "@/lib/types";
```

(`FormEvent` is no longer imported; `useMemo` stays for `ColumnMapper`. `api` becomes unused until Task 4 — leave the import, Task 4 uses it, and vitest does not lint unused imports.)

- [ ] **Step 4: Update the CSS**

In `frontend/app/globals.css`, replace the block from `.upload-zone` through `.file-picker:focus-within` (lines ~109-119) with:

```css
.upload-zone { display: grid; gap: 10px; }
.upload-drop { display: grid; place-items: center; gap: 7px; border: 1.5px dashed #d5d5e6; border-radius: 11px; background: #fbfbfe; padding: 26px 20px; text-align: center; cursor: pointer; }
.upload-drop:focus-visible { border-color: var(--primary); box-shadow: 0 0 0 3px #deddfd; outline: none; }
.upload-drop.dragover { border-color: var(--primary); background: var(--soft); }
.upload-drop strong { font-size: 14px; }
.upload-drop p { margin: 0; font-size: 12.5px; }
.upload-icon { display: grid; width: 36px; height: 36px; place-items: center; border-radius: 999px; background: var(--soft); color: var(--primary-dark); font-size: 16px; font-weight: 800; }
.skip-note { margin: 0; font-size: 12.5px; }
.staged-list { display: grid; margin: 0; padding: 0; list-style: none; }
.staged-row { display: flex; align-items: center; gap: 12px; border-bottom: 1px solid #eef0f6; padding: 10px 2px; }
.staged-row:last-child { border-bottom: 0; }
.staged-file { display: grid; flex: 1; min-width: 0; gap: 2px; }
.staged-file strong { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.staged-file small { color: var(--subtle); }
.staged-row input { width: 220px; }
.upload-actions { display: flex; justify-content: flex-end; gap: 8px; }
```

Before deleting `.file-picker`, verify nothing else uses it:

Run: `grep -rn "file-picker" frontend --include="*.tsx"`
Expected: no matches outside `DatasetUpload.tsx` (which no longer renders it). If another component uses it, keep the `.file-picker` rules and delete only the upload-grid rules.

- [ ] **Step 5: Run the new tests and the whole suite**

Run: `cd frontend && npx vitest run tests/dataset-upload.test.tsx && npm test`
Expected: new file PASS; `datasets-page.test.tsx` still PASS (its only test doesn't touch the upload form).

- [ ] **Step 6: Commit**

```bash
git add frontend/components/DatasetUpload.tsx frontend/app/globals.css frontend/tests/dataset-upload.test.tsx
git commit -m "feat(datasets): stage multi-file and folder uploads with record counts"
```

---

### Task 4: Sequential batch upload with auto-mapping

**Files:**
- Modify: `frontend/components/DatasetUpload.tsx` (fill in `uploadAll`)
- Test: `frontend/tests/dataset-upload.test.tsx` (append)

**Interfaces:**
- Consumes: `StagedRow`, `patchRow`, `uploadable` from Task 3; `autoMapColumns` from Task 1; `api` from `@/lib/api`.
- Produces: rows in status `uploaded` (with `dataset`, `mappedCount`, `needsMapping`) or `failed` (with `error`), `phase === "done"`, and a progress counter `progress: {done: number; total: number}` state that Task 5's results panel reads.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/tests/dataset-upload.test.tsx`:

```tsx
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
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run tests/dataset-upload.test.tsx`
Expected: the two new tests FAIL (uploadAll is empty; "columns mapped" never appears).

- [ ] **Step 3: Implement `uploadAll`**

In `DatasetUpload`, add a progress state next to the others:

```tsx
const [progress, setProgress] = useState({done: 0, total: 0});
```

Replace the `async function uploadAll() {}` stub with:

```tsx
async function uploadAll() {
  const queue = uploadable;
  setPhase("uploading");
  setProgress({done: 0, total: queue.length});
  for (const row of queue) {
    patchRow(row.id, {status: "uploading"});
    try {
      const form = new FormData();
      form.append("name", row.name.trim());
      form.append("file", row.file);
      const created = await api<Dataset>(`/api/workspaces/${workspaceId}/datasets`, {
        method: "POST",
        body: form,
      });
      const columns = Array.from(
        new Set((created.preview ?? []).flatMap((record) => Object.keys(record))),
      );
      const mapping = autoMapColumns(columns);
      let saved = created;
      if (Object.keys(mapping).length > 0) {
        saved = await api<Dataset>(
          `/api/workspaces/${workspaceId}/datasets/${created.id}/schema-map`,
          {method: "PATCH", body: JSON.stringify({schema_map: mapping})},
        );
      }
      patchRow(row.id, {
        status: "uploaded",
        dataset: saved,
        mappedCount: Object.keys(saved.schema_map).length,
        needsMapping: !saved.schema_map.input && !saved.schema_map.turns,
      });
      onComplete(saved);
    } catch (reason) {
      patchRow(row.id, {
        status: "failed",
        error: reason instanceof Error ? reason.message : "Upload failed",
      });
    }
    setProgress((current) => ({...current, done: current.done + 1}));
  }
  setPhase("done");
}
```

Add `autoMapColumns` to the `@/lib/dataset-staging` import list.

Update the staged-row `<small>` so uploaded/failed rows report status (replace the existing `<small>` element):

```tsx
<small>
  {row.status === "uploaded"
    ? `${row.mappedCount} column${row.mappedCount === 1 ? "" : "s"} mapped`
    : row.error ??
      (row.records === null
        ? "Counting records…"
        : `${row.records} record${row.records === 1 ? "" : "s"}`)}
</small>
```

Update the Upload button to show progress while uploading (replace the button element):

```tsx
<button
  type="button"
  className="primary"
  disabled={!canUpload}
  aria-busy={phase === "uploading"}
  onClick={uploadAll}
>
  {phase === "uploading"
    ? `Uploading ${Math.min(progress.done + 1, progress.total)}/${progress.total}…`
    : `Upload ${uploadable.length} file${uploadable.length === 1 ? "" : "s"}`}
</button>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run tests/dataset-upload.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/DatasetUpload.tsx frontend/tests/dataset-upload.test.tsx
git commit -m "feat(datasets): upload staged files sequentially with column auto-map"
```

---

### Task 5: Results panel with inline mapper and reset

**Files:**
- Modify: `frontend/components/DatasetUpload.tsx`
- Test: `frontend/tests/dataset-upload.test.tsx` (append)

**Interfaces:**
- Consumes: `phase === "done"`, row statuses/`dataset`/`needsMapping` from Task 4; `ColumnMapper` (unchanged, same file).
- Produces: final component behavior — nothing downstream consumes internals.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/tests/dataset-upload.test.tsx`:

```tsx
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
```

Note: `ColumnMapper`'s selects are labeled by their visible text ("Input", …) via the wrapping `<label>`; "Common / RAG" is the first `<legend>`, so it proves the mapper rendered.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run tests/dataset-upload.test.tsx`
Expected: the two new tests FAIL (no "Needs mapping" badge, no Map/Done buttons).

- [ ] **Step 3: Implement the results panel**

In `DatasetUpload`, add state for the open mapper:

```tsx
const [mapperRowId, setMapperRowId] = useState<string | null>(null);
```

Add a reset helper:

```tsx
function reset() {
  setRows([]);
  setSkipped(0);
  setNotice("");
  setPhase("staging");
  setProgress({done: 0, total: 0});
  setMapperRowId(null);
}
```

Extend each staged row: after the remove button (inside the `<li>`), append status affordances so the full `<li>` body becomes:

```tsx
<li className="staged-row" key={row.id}>
  <span className="staged-file">
    <strong>{row.status === "uploaded" ? row.dataset?.name : row.file.name}</strong>
    <small>
      {row.status === "uploaded"
        ? `${row.mappedCount} column${row.mappedCount === 1 ? "" : "s"} mapped`
        : row.error ??
          (row.records === null
            ? "Counting records…"
            : `${row.records} record${row.records === 1 ? "" : "s"}`)}
    </small>
  </span>
  {row.status === "uploaded" && row.needsMapping && (
    <span className="capability-badge">Needs mapping</span>
  )}
  {row.status === "uploaded" && row.needsMapping && row.dataset && (
    <button
      type="button"
      onClick={() =>
        setMapperRowId((current) => (current === row.id ? null : row.id))
      }
    >
      Map
    </button>
  )}
  {phase === "staging" && (
    <>
      <input
        aria-label="Dataset name"
        value={row.name}
        onChange={(event) => patchRow(row.id, {name: event.target.value})}
      />
      <button
        type="button"
        className="ghost"
        aria-label={`Remove ${row.file.name}`}
        onClick={() =>
          setRows((current) => current.filter((item) => item.id !== row.id))
        }
      >
        ×
      </button>
    </>
  )}
</li>
```

After the `</ul>` closing the staged list, render the inline mapper for the open row:

```tsx
{mapperRowId &&
  (() => {
    const row = rows.find((item) => item.id === mapperRowId);
    if (!row?.dataset) return null;
    return (
      <ColumnMapper
        dataset={row.dataset}
        onSave={async (schema_map) => {
          const saved = await api<Dataset>(
            `/api/workspaces/${workspaceId}/datasets/${row.dataset!.id}/schema-map`,
            {method: "PATCH", body: JSON.stringify({schema_map})},
          );
          patchRow(row.id, {
            dataset: saved,
            mappedCount: Object.keys(saved.schema_map).length,
            needsMapping: !saved.schema_map.input && !saved.schema_map.turns,
          });
          setMapperRowId(null);
          onComplete(saved);
        }}
      />
    );
  })()}
```

Replace the actions row so `done` phase shows Done instead of upload controls:

```tsx
<div className="upload-actions">
  {phase === "done" ? (
    <button type="button" onClick={reset}>
      Done
    </button>
  ) : (
    <>
      <button
        type="button"
        disabled={phase === "uploading"}
        onClick={() => folderInputRef.current?.click()}
      >
        Choose folder
      </button>
      <button
        type="button"
        className="primary"
        disabled={!canUpload}
        aria-busy={phase === "uploading"}
        onClick={uploadAll}
      >
        {phase === "uploading"
          ? `Uploading ${Math.min(progress.done + 1, progress.total)}/${progress.total}…`
          : `Upload ${uploadable.length} file${uploadable.length === 1 ? "" : "s"}`}
      </button>
    </>
  )}
</div>
```

Hide the dropzone outside the staging phase by wrapping it (and both hidden inputs plus the skip note stay as they are):

```tsx
{phase === "staging" && (
  <div
    className={`upload-drop${dragover ? " dragover" : ""}`}
    ...unchanged props...
  >
    ...unchanged children...
  </div>
)}
```

- [ ] **Step 4: Run the component tests**

Run: `cd frontend && npx vitest run tests/dataset-upload.test.tsx`
Expected: PASS (all describes).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/DatasetUpload.tsx frontend/tests/dataset-upload.test.tsx
git commit -m "feat(datasets): report batch results with inline mapper and reset"
```

---

### Task 6: Full verification

**Files:**
- Modify: none expected (fixes only if verification fails)

**Interfaces:** none.

- [ ] **Step 1: Run the entire frontend suite**

Run: `cd frontend && npm test`
Expected: all files PASS, including the untouched `datasets-page.test.tsx`.

- [ ] **Step 2: Type-check / build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no type errors, build succeeds. (`webkitdirectory` passes through the `folderInputProps` cast — if tsc complains, the cast in Task 3 is wrong.)

- [ ] **Step 3: Manual smoke test in the app**

With the dev stack running (`docker-compose up` from the repo root or `npm run dev` in `frontend/` with the backend up), on `/w/<workspace>/datasets`:

1. Drag `sample_datasets/rag/generation` (folder) onto the dropzone → rows appear with record counts (3 each), names prefilled, unsupported files skipped.
2. Click "Upload N files" → progress counts up, rows flip to "N columns mapped", dataset list below refreshes incrementally.
3. Confirm sample datasets need no manual mapping (no "Needs mapping" badges), and a CSV with quirky column names gets the badge, Map opens the mapper inline, saving clears the badge.
4. Click Done → panel returns to the idle dropzone.

Expected: all four behaviors as described; no browser console errors.

- [ ] **Step 4: Fix anything found, re-run, commit fixes**

```bash
git add -A
git commit -m "fix(datasets): address upload redesign verification findings"
```

(Skip this commit when verification found nothing.)
