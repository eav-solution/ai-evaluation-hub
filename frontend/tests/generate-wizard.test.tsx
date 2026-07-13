import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GenerateWizard } from "@/components/GenerateWizard";
import { computeMaxCount } from "@/lib/generation";
import type { DocumentFile, GenerationJob, GenerationRecord } from "@/lib/types";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const documentFile: DocumentFile = {
  id: "doc-1",
  filename: "guide.md",
  format: "md",
  size_bytes: 100,
  char_count: 80,
  chunk_count: 2,
  created_at: "2026-07-11T00:00:00Z",
};

const completedJob: GenerationJob = {
  id: "job-1",
  name: "Generated dataset",
  document_ids: [documentFile.id],
  mode: "chunk",
  requested_count: 2,
  max_count: 6,
  generator_config: { provider: "openai", model: "gpt-4.1-mini" },
  options: { questions_per_chunk: 3, language: null },
  status: "completed",
  progress_done: 2,
  progress_total: 2,
  generated_count: 1,
  error: null,
  unit_errors: [],
  dataset_id: null,
  dataset_created: false,
  created_at: "2026-07-11T00:00:00Z",
  finished_at: "2026-07-11T00:01:00Z",
};

const runningJob: GenerationJob = {
  ...completedJob,
  status: "running",
  progress_done: 0,
  progress_total: 2,
  generated_count: 0,
  finished_at: null,
};

const generatedRecord: GenerationRecord = {
  id: "record-1",
  record_index: 0,
  question: "Original question",
  answer: "Original answer",
  contexts: ["Original context"],
  source: { document_id: documentFile.id, chunk_index: 0 },
  deleted: false,
};

describe("computeMaxCount", () => {
  it("multiplies total chunks by questions per chunk", () => {
    expect(computeMaxCount([2, 3], 3)).toBe(15);
  });
  it("clamps to the dataset row cap", () => {
    expect(computeMaxCount([4000], 3)).toBe(5000);
  });
  it("is zero with no documents", () => {
    expect(computeMaxCount([], 3)).toBe(0);
  });
});

describe("GenerateWizard", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("[]", {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
  });

  it("renders the source and configuration sections", async () => {
    render(<GenerateWizard workspaceId="ws-1" />);
    await waitFor(() => {
      expect(screen.getByText("1 · Source documents")).toBeDefined();
    });
    expect(screen.getByText("2 · Configure generation")).toBeDefined();
    expect(screen.getByText(/Number of records/i)).toBeDefined();
  });

  it("shows full-name selectable file cards and grouped settings", async () => {
    const longDocument = {
      ...documentFile,
      filename: "system-design-guide-for-evaluation-platform-v2-final.html",
      format: "html",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([longDocument]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([]);
        throw new Error(`Unexpected request: GET ${path}`);
      }),
    );

    const { container } = render(<GenerateWizard workspaceId="ws-1" />);
    const filename = await screen.findByText(longDocument.filename);

    expect(filename).toHaveClass("document-name");
    expect(container.querySelector(".document-grid")).toBeInTheDocument();
    expect(screen.queryByText(/HTML ·/)).toBeNull();
    expect(screen.getByText("Content settings")).toBeInTheDocument();
    expect(screen.getByText("AI model")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${longDocument.filename}` }));
    expect(filename.closest(".document-card")).toHaveClass("selected");
  });

  it("deletes a finished job after confirmation and refreshes the list", async () => {
    let jobs = [completedJob];
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([]);
        if (path.endsWith("/generation-jobs") && !init?.method) return jsonResponse(jobs);
        if (path.endsWith(`/generation-jobs/${completedJob.id}`) && init?.method === "DELETE") {
          jobs = [];
          return new Response(null, { status: 204 });
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete generation job Generated dataset" }));

    expect(confirm).toHaveBeenCalledWith('Delete generation job "Generated dataset"?');
    await waitFor(() => {
      expect(screen.queryByText("Generated dataset")).not.toBeInTheDocument();
    });
    confirm.mockRestore();
  });

  it("shows a deletion error and keeps the finished job", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([]);
        if (path.endsWith("/generation-jobs") && !init?.method) return jsonResponse([completedJob]);
        if (path.endsWith(`/generation-jobs/${completedJob.id}`) && init?.method === "DELETE") {
          return jsonResponse({ detail: "Delete failed" }, 503);
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete generation job Generated dataset" }));

    expect(await screen.findByText("Delete failed")).toBeInTheDocument();
    expect(screen.getByText("Generated dataset")).toBeInTheDocument();
    confirm.mockRestore();
  });

  it("shows View progress and Cancel, but not Delete, for an active job", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([runningJob]);
        throw new Error(`Unexpected request: GET ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    expect(await screen.findByRole("button", { name: "View progress" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete generation job/ })).not.toBeInTheDocument();
  });

  it("waits for an in-flight edit before saving", async () => {
    let resolvePatch!: (response: Response) => void;
    const patchResponse = new Promise<Response>((resolve) => {
      resolvePatch = resolve;
    });
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([completedJob]);
        if (path.includes("/records?") && !init?.method) {
          return jsonResponse({ records: [generatedRecord], page: 1, page_size: 50, total: 1 });
        }
        if (init?.method === "PATCH") {
          calls.push("patch");
          return patchResponse;
        }
        if (path.endsWith("/dataset") && init?.method === "POST") {
          calls.push("save");
          return jsonResponse({ id: "dataset-1", name: completedJob.name });
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    const question = await screen.findByDisplayValue(generatedRecord.question);
    fireEvent.change(question, { target: { value: "Edited question" } });
    fireEvent.blur(question);

    const save = screen.getByRole("button", { name: "Save as dataset" });
    expect(save).toBeDisabled();
    fireEvent.submit(screen.getByRole("form", { name: "Save dataset" }));
    expect(calls).toEqual(["patch"]);

    await act(async () => {
      resolvePatch(jsonResponse({ ...generatedRecord, question: "Edited question" }));
      await patchResponse;
    });

    await waitFor(() => expect(calls).toEqual(["patch", "save"]));
  });

  it("clamps fractional and oversized launch values in the payload", async () => {
    let payload: Record<string, unknown> | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([documentFile]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs") && !init?.method) return jsonResponse([]);
        if (path.endsWith("/generation-jobs") && init?.method === "POST") {
          payload = JSON.parse(String(init.body));
          return jsonResponse({ ...completedJob, status: "pending", finished_at: null });
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("checkbox", { name: /guide\.md/ }));
    fireEvent.change(screen.getByLabelText("Job name"), { target: { value: "Job" } });
    fireEvent.click(screen.getByLabelText("LLM Model"));
    fireEvent.click(screen.getByRole("option", { name: "gpt-4.1-mini" }));
    fireEvent.change(screen.getByLabelText("Questions per chunk"), { target: { value: "9.8" } });
    fireEvent.change(screen.getByLabelText(/Number of records/), { target: { value: "12.9" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate .* records/ }));

    await waitFor(() => expect(payload).toBeDefined());
    expect(payload?.requested_count).toBe(10);
    expect(payload?.options).toEqual({ questions_per_chunk: 5, language: null });
  });

  it("normalizes empty and negative launch values in the payload", async () => {
    let payload: Record<string, unknown> | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([documentFile]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs") && !init?.method) return jsonResponse([]);
        if (path.endsWith("/generation-jobs") && init?.method === "POST") {
          payload = JSON.parse(String(init.body));
          return jsonResponse({ ...completedJob, status: "pending", finished_at: null });
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("checkbox", { name: /guide\.md/ }));
    fireEvent.change(screen.getByLabelText("Job name"), { target: { value: "Job" } });
    fireEvent.click(screen.getByLabelText("LLM Model"));
    fireEvent.click(screen.getByRole("option", { name: "gpt-4.1-mini" }));
    fireEvent.change(screen.getByLabelText("Questions per chunk"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText(/Number of records/), { target: { value: "-3" } });
    fireEvent.click(screen.getByRole("button", { name: /Generate .* records/ }));

    await waitFor(() => expect(payload).toBeDefined());
    expect(payload?.requested_count).toBe(1);
    expect(payload?.options).toEqual({ questions_per_chunk: 1, language: null });
  });

  it("shows polling errors and clears them after a later successful tick", async () => {
    let polls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([runningJob]);
        if (path.endsWith(`/generation-jobs/${runningJob.id}`)) {
          polls += 1;
          return polls === 1
            ? jsonResponse({ detail: "Polling failed" }, 503)
            : jsonResponse({ ...runningJob, progress_done: 1 });
        }
        throw new Error(`Unexpected request: GET ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    const viewProgress = await screen.findByRole("button", { name: "View progress" });
    vi.useFakeTimers();
    fireEvent.click(viewProgress);

    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(screen.getByText("Polling failed")).toBeInTheDocument();

    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(polls).toBe(2);
    expect(screen.queryByText("Polling failed")).not.toBeInTheDocument();
  });

  it("never overlaps generation polling requests", async () => {
    let resolveFirst!: (response: Response) => void;
    const firstPoll = new Promise<Response>((resolve) => {
      resolveFirst = resolve;
    });
    let polls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([runningJob]);
        if (path.endsWith(`/generation-jobs/${runningJob.id}`)) {
          polls += 1;
          return polls === 1 ? firstPoll : jsonResponse(runningJob);
        }
        throw new Error(`Unexpected request: GET ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    const viewProgress = await screen.findByRole("button", { name: "View progress" });
    vi.useFakeTimers();
    fireEvent.click(viewProgress);

    await act(async () => vi.advanceTimersByTimeAsync(6000));
    expect(polls).toBe(1);
    await act(async () => resolveFirst(jsonResponse(runningJob)));
    await act(async () => vi.advanceTimersByTimeAsync(1999));
    expect(polls).toBe(1);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(polls).toBe(2);
  });

  it("shows cancel failures without leaving progress", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([runningJob]);
        if (path.endsWith("/cancel") && init?.method === "POST") {
          return jsonResponse({ detail: "Cancel failed" }, 503);
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "View progress" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(await screen.findByText("Cancel failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("shows document delete failures and keeps the document", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([documentFile]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([]);
        if (path.endsWith(`/documents/${documentFile.id}`) && init?.method === "DELETE") {
          return jsonResponse({ detail: "Delete failed" }, 503);
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete guide.md" }));

    expect(await screen.findByText("Delete failed")).toBeInTheDocument();
    expect(screen.getByText(documentFile.filename)).toBeInTheDocument();
  });

  it("renders a cancelled progress state with a Back action", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([runningJob]);
        if (path.endsWith(`/generation-jobs/${runningJob.id}`)) {
          return jsonResponse({ ...runningJob, status: "cancelled" });
        }
        throw new Error(`Unexpected request: GET ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    const viewProgress = await screen.findByRole("button", { name: "View progress" });
    vi.useFakeTimers();
    fireEvent.click(viewProgress);
    expect(screen.getByRole("progressbar", { name: "Generation progress" })).toBeInTheDocument();

    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(screen.getByRole("heading", { name: "Generation cancelled" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
  });

  it("shows per-unit failures and accessible review controls", async () => {
    const job = {
      ...completedJob,
      unit_errors: [
        { unit: 3, error: "Invalid JSON" },
        { unit: 7, error: "Rate limited" },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([job]);
        if (path.includes("/records?")) {
          return jsonResponse({ records: [generatedRecord], page: 1, page_size: 50, total: 1 });
        }
        throw new Error(`Unexpected request: GET ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));

    expect(await screen.findByText("Unit 3: Invalid JSON")).toBeInTheDocument();
    expect(screen.getByText("Unit 7: Rate limited")).toBeInTheDocument();
    expect(screen.getByLabelText("Question 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Answer 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Contexts 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Dataset name")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete record 1" })).toBeInTheDocument();
  });

  it("shows per-unit errors on a failed generation job", async () => {
    const failedJob: GenerationJob = {
      ...runningJob,
      status: "failed",
      progress_done: 2,
      generated_count: 0,
      error: "All generation units failed",
      unit_errors: [
        { unit: 0, error: "Generator returned invalid JSON. Response excerpt: bad output" },
        { unit: 1, error: "Gateway timed out" },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([runningJob]);
        if (path.endsWith(`/generation-jobs/${runningJob.id}`)) return jsonResponse(failedJob);
        throw new Error(`Unexpected request: GET ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    const viewProgress = await screen.findByRole("button", { name: "View progress" });
    vi.useFakeTimers();
    fireEvent.click(viewProgress);
    await act(async () => vi.advanceTimersByTimeAsync(2000));

    expect(screen.getByRole("heading", { name: "Generation failed" })).toBeInTheDocument();
    expect(screen.getByText("Unit 0: Generator returned invalid JSON. Response excerpt: bad output")).toBeInTheDocument();
    expect(screen.getByText("Unit 1: Gateway timed out")).toBeInTheDocument();
  });

  it("ignores stale record-page responses", async () => {
    const pending = new Map<number, (response: Response) => void>();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([completedJob]);
        const match = path.match(/records\?page=(\d+)/);
        if (match) {
          const page = Number(match[1]);
          if (page === 1 && !pending.has(1)) {
            pending.set(1, () => undefined);
            return jsonResponse({ records: [generatedRecord], page: 1, page_size: 50, total: 101 });
          }
          return new Promise<Response>((resolve) => pending.set(page, resolve));
        }
        throw new Error(`Unexpected request: GET ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    expect(await screen.findByText("Page 1 / 3")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await act(async () => pending.get(2)?.(jsonResponse({ records: [], page: 2, page_size: 50, total: 101 })));
    expect(await screen.findByText("Page 2 / 3")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await act(async () => pending.get(1)?.(jsonResponse({ records: [generatedRecord], page: 1, page_size: 50, total: 101 })));
    expect(await screen.findByText("Page 1 / 3")).toBeInTheDocument();
    await act(async () => pending.get(3)?.(jsonResponse({ records: [], page: 3, page_size: 50, total: 101 })));
    expect(screen.getByText("Page 1 / 3")).toBeInTheDocument();
  });

  it("labels upload and separates document selection from deletion", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([documentFile]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([]);
        throw new Error(`Unexpected request: GET ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    expect(await screen.findByLabelText("Upload documents")).toHaveAttribute("type", "file");
    const checkbox = screen.getByRole("checkbox", { name: /guide\.md/ });
    expect(checkbox.closest("label")?.querySelector("button")).toBeNull();
    expect(screen.getByRole("button", { name: "Delete guide.md" })).toBeInTheDocument();
  });

  it("keeps a failed edit blocking save after another edit succeeds", async () => {
    let saveCalls = 0;
    let answerSaved = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([completedJob]);
        if (path.includes("/records?") && !init?.method) {
          return jsonResponse({ records: [generatedRecord], page: 1, page_size: 50, total: 1 });
        }
        if (init?.method === "PATCH") {
          const body = JSON.parse(String(init.body));
          if (body.question) return jsonResponse({ detail: "Edit failed" }, 503);
          answerSaved = true;
          return jsonResponse({ ...generatedRecord, answer: body.answer });
        }
        if (path.endsWith("/dataset") && init?.method === "POST") {
          saveCalls += 1;
          return jsonResponse({ id: "dataset-1", name: completedJob.name });
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    const question = await screen.findByDisplayValue(generatedRecord.question);
    fireEvent.change(question, { target: { value: "Edited question" } });
    fireEvent.blur(question);
    expect(await screen.findByText("Edit failed")).toBeInTheDocument();

    const answer = screen.getByDisplayValue(generatedRecord.answer);
    fireEvent.change(answer, { target: { value: "Edited answer" } });
    fireEvent.blur(answer);
    await waitFor(() => expect(answerSaved).toBe(true));

    fireEvent.submit(screen.getByRole("form", { name: "Save dataset" }));
    await act(async () => Promise.resolve());
    expect(saveCalls).toBe(0);
    expect(screen.getByRole("button", { name: "Save as dataset" })).toBeDisabled();
  });

  it("locks review mutations once dataset saving begins", async () => {
    let resolveSave!: (response: Response) => void;
    const saveResponse = new Promise<Response>((resolve) => {
      resolveSave = resolve;
    });
    let patchCalls = 0;
    let saveCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([completedJob]);
        if (path.includes("/records?") && !init?.method) {
          return jsonResponse({ records: [generatedRecord], page: 1, page_size: 50, total: 51 });
        }
        if (init?.method === "PATCH") {
          patchCalls += 1;
          return jsonResponse(generatedRecord);
        }
        if (path.endsWith("/dataset") && init?.method === "POST") {
          saveCalls += 1;
          return saveResponse;
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    const question = await screen.findByLabelText("Question 1");
    fireEvent.change(question, { target: { value: "Late edit" } });
    fireEvent.submit(screen.getByRole("form", { name: "Save dataset" }));
    await waitFor(() => expect(saveCalls).toBe(1));

    expect(question).toBeDisabled();
    expect(screen.getByLabelText("Answer 1")).toBeDisabled();
    expect(screen.getByLabelText("Contexts 1")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete record 1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByLabelText("Dataset name")).toBeDisabled();

    fireEvent.blur(question);
    await act(async () => Promise.resolve());
    expect(patchCalls).toBe(0);

    await act(async () => {
      resolveSave(jsonResponse({ id: "dataset-1", name: completedJob.name }));
      await saveResponse;
    });
    expect(await screen.findByRole("heading", { name: "Dataset saved" })).toBeInTheDocument();
  });

  it("serializes same-field edits in server order", async () => {
    const requests: { body: Record<string, unknown>; resolve: (response: Response) => void }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([completedJob]);
        if (path.includes("/records?") && !init?.method) {
          return jsonResponse({ records: [generatedRecord], page: 1, page_size: 50, total: 1 });
        }
        if (init?.method === "PATCH") {
          return new Promise<Response>((resolve) => {
            requests.push({ body: JSON.parse(String(init.body)), resolve });
          });
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    const question = await screen.findByLabelText("Question 1");
    fireEvent.change(question, { target: { value: "First edit" } });
    fireEvent.blur(question);
    fireEvent.change(question, { target: { value: "Second edit" } });
    fireEvent.blur(question);
    expect(requests.map((request) => request.body)).toEqual([{ question: "First edit" }]);

    await act(async () => {
      requests[0].resolve(jsonResponse({ ...generatedRecord, question: "First edit" }));
    });
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[1].body).toEqual({ question: "Second edit" });
    await act(async () => {
      requests[1].resolve(jsonResponse({ ...generatedRecord, question: "Second edit" }));
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save as dataset" })).toBeEnabled();
    });
  });

  it("queues a server-value revert behind an in-flight edit", async () => {
    const requests: { body: Record<string, unknown>; resolve: (response: Response) => void }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([completedJob]);
        if (path.includes("/records?") && !init?.method) {
          return jsonResponse({ records: [generatedRecord], page: 1, page_size: 50, total: 1 });
        }
        if (init?.method === "PATCH") {
          return new Promise<Response>((resolve) => {
            requests.push({ body: JSON.parse(String(init.body)), resolve });
          });
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));
    const question = await screen.findByLabelText("Question 1");
    fireEvent.change(question, { target: { value: "Temporary edit" } });
    fireEvent.blur(question);
    fireEvent.change(question, { target: { value: generatedRecord.question } });
    fireEvent.blur(question);
    expect(requests.map((request) => request.body)).toEqual([{ question: "Temporary edit" }]);

    await act(async () => {
      requests[0].resolve(jsonResponse({ ...generatedRecord, question: "Temporary edit" }));
    });
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[1].body).toEqual({ question: generatedRecord.question });
    await act(async () => {
      requests[1].resolve(jsonResponse(generatedRecord));
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save as dataset" })).toBeEnabled();
    });
  });

  it("clears text and context failures when reverted to server values", async () => {
    let patchCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/provider-connections")) return jsonResponse([{ id: "conn-openai", name: "OpenAI", connection_type: "openai", base_url: null, has_key: true, key_hint: "…key" }]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([completedJob]);
        if (path.includes("/records?") && !init?.method) {
          return jsonResponse({ records: [generatedRecord], page: 1, page_size: 50, total: 1 });
        }
        if (init?.method === "PATCH") {
          patchCalls += 1;
          return jsonResponse({ detail: "Edit failed" }, 503);
        }
        throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Review" }));

    const question = await screen.findByLabelText("Question 1");
    fireEvent.change(question, { target: { value: "Bad question edit" } });
    fireEvent.blur(question);
    expect(await screen.findByText("Edit failed")).toBeInTheDocument();
    fireEvent.change(question, { target: { value: generatedRecord.question } });
    fireEvent.blur(question);
    expect(screen.queryByText("Edit failed")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save as dataset" })).toBeEnabled();

    const contexts = screen.getByLabelText("Contexts 1");
    fireEvent.change(contexts, { target: { value: "Bad context edit" } });
    fireEvent.blur(contexts);
    expect(await screen.findByText("Edit failed")).toBeInTheDocument();
    fireEvent.change(contexts, { target: { value: generatedRecord.contexts.join("\n") } });
    fireEvent.blur(contexts);

    expect(screen.queryByText("Edit failed")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save as dataset" })).toBeEnabled();
    expect(patchCalls).toBe(2);
  });

  it("shows a searchable model selector for a custom connection", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const path = String(input);
        if (path.endsWith("/documents")) return jsonResponse([]);
        if (path.endsWith("/generation-jobs")) return jsonResponse([]);
        if (path.endsWith("/provider-connections"))
          return jsonResponse([
            { id: "conn-custom", name: "Gateway", connection_type: "openai_compatible", base_url: "http://gateway/v1", has_key: false, key_hint: null },
          ]);
        if (path.endsWith("/models"))
          return jsonResponse({ models: ["chat-a", "chat-b"] });
        throw new Error(`Unexpected request: GET ${path}`);
      }),
    );

    render(<GenerateWizard workspaceId="ws-1" />);
    fireEvent.click(await screen.findByLabelText("LLM Model"));
    expect(screen.getByRole("searchbox", { name: "Search models" })).toBeInTheDocument();
  });

});
