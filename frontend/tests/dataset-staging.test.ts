import {describe, expect, it} from "vitest";

import {
  autoMapColumns,
  collectFilesFromDataTransfer,
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
