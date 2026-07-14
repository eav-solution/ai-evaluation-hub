"use client";

import { useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";

import { api, download } from "@/lib/api";
import { computeMaxCount } from "@/lib/generation";
import { modelOptions } from "@/lib/model-options";
import { SearchableSelect } from "@/components/SearchableSelect";
import type {
  DocumentFile,
  GenerationJob,
  GenerationRecord,
  GenerationRecordPage,
  ProviderConnection,
} from "@/lib/types";

type Step = "configure" | "progress" | "review";

function finiteInteger(value: number, min: number, max: number) {
  const integer = Number.isFinite(value) ? Math.trunc(value) : min;
  return Math.min(Math.max(integer, min), max);
}

export function GenerateWizard({ workspaceId }: { workspaceId: string }) {
  const [step, setStep] = useState<Step>("configure");
  const [documents, setDocuments] = useState<DocumentFile[]>([]);
  const [jobs, setJobs] = useState<GenerationJob[]>([]);
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [name, setName] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [mode, setMode] = useState<"chunk" | "document">("chunk");
  const [count, setCount] = useState(20);
  const [questionsPerChunk, setQuestionsPerChunk] = useState(3);
  const [language, setLanguage] = useState("");
  const [connections, setConnections] = useState<ProviderConnection[]>([]);
  const [connectionId, setConnectionId] = useState("");
  const [model, setModel] = useState("");
  const [customModels, setCustomModels] = useState<string[]>([]);
  const [modelsError, setModelsError] = useState("");
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsReload, setModelsReload] = useState(0);

  const connection = connections.find((item) => item.id === connectionId);
  const isCustom = connection?.connection_type === "openai_compatible";
  const chatModelOptions = modelOptions(connection?.connection_type, customModels);

  async function refresh() {
    try {
      const [docs, jobList, connectionList] = await Promise.all([
        api<DocumentFile[]>(`/api/workspaces/${workspaceId}/documents`),
        api<GenerationJob[]>(`/api/workspaces/${workspaceId}/generation-jobs`),
        api<ProviderConnection[]>(`/api/workspaces/${workspaceId}/provider-connections`),
      ]);
      setDocuments(docs);
      setJobs(jobList);
      setConnections(connectionList);
      setConnectionId((current) => current || connectionList[0]?.id || "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load documents");
    }
  }
  useEffect(() => {
    refresh();
  }, [workspaceId]);

  // For a custom connection, load its live model list; reset for native ones.
  useEffect(() => {
    setModel("");
    setModelsError("");
    setCustomModels([]);
    setModelsLoading(false);
    if (!connection || connection.connection_type !== "openai_compatible") return;
    let cancelled = false;
    setModelsLoading(true);
    api<{ models: string[] }>(
      `/api/workspaces/${workspaceId}/provider-connections/${connection.id}/models`,
    )
      .then((result) => {
        if (!cancelled) setCustomModels(result.models);
      })
      .catch((reason) => {
        if (!cancelled) {
          setModelsError(reason instanceof Error ? reason.message : "Could not load models");
        }
      })
      .finally(() => {
        if (!cancelled) setModelsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [connection?.id, connection?.connection_type, workspaceId, modelsReload]);

  useEffect(() => {
    if (!job || (job.status !== "pending" && job.status !== "running")) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const fresh = await api<GenerationJob>(
          `/api/workspaces/${workspaceId}/generation-jobs/${job.id}`,
        );
        if (stopped) return;
        setError("");
        setJob(fresh);
        if (fresh.status === "completed") setStep("review");
      } catch (reason) {
        if (stopped) return;
        setError(reason instanceof Error ? reason.message : "Could not refresh generation");
      } finally {
        if (!stopped) timer = setTimeout(poll, 2000);
      }
    };
    timer = setTimeout(poll, 2000);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [job?.id, job?.status, workspaceId]);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    if (!event.target.files?.length) return;
    setBusy(true);
    setError("");
    const form = new FormData();
    for (const file of Array.from(event.target.files)) form.append("files", file);
    try {
      const uploaded = await api<DocumentFile[]>(
        `/api/workspaces/${workspaceId}/documents`,
        { method: "POST", body: form },
      );
      setDocuments((current) => [...uploaded, ...current]);
      setSelected((current) => [...current, ...uploaded.map((doc) => doc.id)]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed");
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  const selectedDocs = documents.filter((doc) => selected.includes(doc.id));
  const safeQuestionsPerChunk = finiteInteger(questionsPerChunk, 1, 5);
  const maxCount = computeMaxCount(
    selectedDocs.map((doc) => doc.chunk_count),
    safeQuestionsPerChunk,
  );
  const clampedCount = finiteInteger(count, 1, Math.max(maxCount, 1));

  async function launch() {
    const launchQuestions = finiteInteger(questionsPerChunk, 1, 5);
    const launchMaxCount = computeMaxCount(
      selectedDocs.map((doc) => doc.chunk_count),
      launchQuestions,
    );
    if (launchMaxCount < 1) {
      setError("Select at least one document with extracted chunks");
      return;
    }
    const requestedCount = finiteInteger(count, 1, launchMaxCount);
    setBusy(true);
    setError("");
    try {
      const created = await api<GenerationJob>(
        `/api/workspaces/${workspaceId}/generation-jobs`,
        {
          method: "POST",
          body: JSON.stringify({
            name,
            document_ids: selected,
            mode,
            requested_count: requestedCount,
            generator: { connection_id: connectionId, model },
            options: {
              questions_per_chunk: launchQuestions,
              language: language.trim() || null,
            },
          }),
        },
      );
      setJob(created);
      setStep("progress");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start generation");
    } finally {
      setBusy(false);
    }
  }

  async function cancelJob(item: GenerationJob) {
    setBusy(true);
    setError("");
    try {
      await api(`/api/workspaces/${workspaceId}/generation-jobs/${item.id}/cancel`, {
        method: "POST",
      });
      if (job?.id === item.id) {
        setStep("configure");
        setJob(null);
      }
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not cancel generation");
    } finally {
      setBusy(false);
    }
  }

  async function deleteJob(item: GenerationJob) {
    if (!window.confirm(`Delete generation job "${item.name}"?`)) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/workspaces/${workspaceId}/generation-jobs/${item.id}`, {
        method: "DELETE",
      });
      if (job?.id === item.id) {
        setStep("configure");
        setJob(null);
      }
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete generation job");
    } finally {
      setBusy(false);
    }
  }

  if (step === "progress" && job) {
    return (
      <section className="panel">
        <h2>
          {job.status === "cancelled"
            ? "Generation cancelled"
            : job.status === "failed"
              ? "Generation failed"
              : "Generating records…"}
        </h2>
        <p className="muted">
          {job.progress_done} / {job.progress_total || "…"} units · {job.generated_count} records
        </p>
        <progress
          aria-label="Generation progress"
          value={job.progress_done}
          max={job.progress_total || 1}
        />
        {job.status === "failed" && (
          <div className="notice error">
            <p>{job.error}</p>
            {job.unit_errors.length > 0 && (
              <ul>
                {job.unit_errors.map((unitError) => (
                  <li key={`${unitError.unit}-${unitError.error}`}>
                    Unit {unitError.unit}: {unitError.error}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {error && <p className="notice error">{error}</p>}
        {(job.status === "failed" || job.status === "cancelled") && (
          <button className="ghost" onClick={() => setStep("configure")}>Back</button>
        )}
        {(job.status === "pending" || job.status === "running") && (
          <button
            className="ghost"
            disabled={busy}
            onClick={() => cancelJob(job)}
          >
            Cancel
          </button>
        )}
      </section>
    );
  }

  if (step === "review" && job) {
    return <ReviewTable workspaceId={workspaceId} job={job} />;
  }

  return (
    <div className="stack">
      {error && <p className="notice error">{error}</p>}
      <section className="panel generation-source-panel">
        <div className="generation-section-header">
          <div>
            <h2>1 · Source documents</h2>
            <p className="muted">Choose one or more files to ground the generated records.</p>
          </div>
          {documents.length > 0 && (
            <span className="selection-count">
              {selectedDocs.length} of {documents.length} selected
            </span>
          )}
        </div>
        <div className="document-grid">
          {documents.map((doc) => (
            <article
              className={`document-card ${selected.includes(doc.id) ? "selected" : ""}`}
              key={doc.id}
            >
              <label className="document-select">
                <input
                  aria-label={`Select ${doc.filename}`}
                  type="checkbox"
                  checked={selected.includes(doc.id)}
                  onChange={(event) =>
                    setSelected((current) =>
                      event.target.checked
                        ? [...current, doc.id]
                        : current.filter((id) => id !== doc.id),
                    )
                  }
                />
                <span className="document-copy">
                  <strong className="document-name">{doc.filename}</strong>
                  <small>{doc.char_count.toLocaleString()} characters · {doc.chunk_count} chunks</small>
                </span>
              </label>
              <button
                aria-label={`Delete ${doc.filename}`}
                className="ghost document-remove"
                onClick={async () => {
                  setError("");
                  try {
                    await api(`/api/workspaces/${workspaceId}/documents/${doc.id}`, {
                      method: "DELETE",
                    });
                    setSelected((current) => current.filter((id) => id !== doc.id));
                    refresh();
                  } catch (reason) {
                    setError(reason instanceof Error ? reason.message : "Could not delete document");
                  }
                }}
              >
                ×
              </button>
            </article>
          ))}
          <label className="document-add-card">
            <span className="document-add-icon" aria-hidden="true">+</span>
            <span>
              <strong>Add documents</strong>
              <small>PDF, DOCX, TXT, MD, or HTML</small>
            </span>
            <input
              aria-label="Upload documents"
              type="file"
              multiple
              accept=".pdf,.docx,.txt,.md,.html"
              onChange={upload}
              disabled={busy}
            />
          </label>
        </div>
      </section>

      <section className="panel generation-config-panel">
        <h2>2 · Configure generation</h2>
        <div className="generation-config-layout">
          <div className="generation-settings-group">
            <p className="generation-group-title">Content settings</p>
            <div className="generation-content-grid">
              <label>
                Job name
                <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Dataset from docs" />
              </label>
              <label>
                Generation mode
                <select value={mode} onChange={(event) => setMode(event.target.value as "chunk" | "document")}>
                  <option value="chunk">Per chunk (broad coverage)</option>
                  <option value="document">Whole document (global questions)</option>
                </select>
              </label>
              <label>
                Number of records
                <input
                  type="number"
                  min={1}
                  max={Math.max(maxCount, 1)}
                  value={clampedCount}
                  onChange={(event) =>
                    setCount(
                      finiteInteger(Number(event.target.value), 1, Math.max(maxCount, 1)),
                    )
                  }
                />
                <small className="muted">
                  Max {maxCount} for the selected documents ({selectedDocs.length} selected)
                </small>
              </label>
              <label>
                Questions per chunk
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={safeQuestionsPerChunk}
                  onChange={(event) =>
                    setQuestionsPerChunk(finiteInteger(Number(event.target.value), 1, 5))
                  }
                />
              </label>
              <label className="wide">
                Language (optional)
                <input
                  value={language}
                  onChange={(event) => setLanguage(event.target.value)}
                  placeholder="Match document language"
                />
              </label>
            </div>
          </div>
          <div className="generation-model-settings">
            <p className="generation-group-title">AI model</p>
            <div className="generation-model-fields">
              <label>
                LLM Connection
                <select
                  value={connectionId}
                  onChange={(event) => setConnectionId(event.target.value)}
                >
                  {!connections.length && <option value="">No connections — add one in Settings</option>}
                  {connections.map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                LLM Model
                {modelsError ? (
                  <span className="notice error">
                    {modelsError}{" "}
                    <button type="button" className="ghost" onClick={() => setModelsReload((n) => n + 1)}>
                      Retry
                    </button>
                  </span>
                ) : (
                  <SearchableSelect
                    options={chatModelOptions}
                    value={model}
                    onChange={setModel}
                    placeholder={modelsLoading ? "Loading models…" : "Select a model"}
                    disabled={modelsLoading}
                  />
                )}
              </label>
            </div>
          </div>
        </div>
        <button
          className="primary generation-launch"
          disabled={
            busy ||
            !name ||
            !model ||
            !connectionId ||
            !selected.length ||
            maxCount === 0 ||
            (isCustom && Boolean(modelsError))
          }
          onClick={launch}
        >
          {busy ? "Starting…" : `Generate ${clampedCount} records`}
        </button>
      </section>

      {jobs.length > 0 && (
        <section className="panel">
          <h2>Generation jobs</h2>
          <div className="item-list">
            {jobs.map((item) => (
              <div className="list-row" key={item.id}>
                <span>
                  <strong>{item.name}</strong>
                  <small>
                    {item.status} · {item.generated_count}/{item.requested_count} records
                  </small>
                </span>
                <div className="actions">
                  {(item.status === "pending" || item.status === "running") && (
                    <>
                      <button
                        className="ghost"
                        disabled={busy}
                        onClick={() => { setJob(item); setStep("progress"); }}
                      >
                        View progress
                      </button>
                      <button className="ghost" disabled={busy} onClick={() => cancelJob(item)}>
                        Cancel
                      </button>
                    </>
                  )}
                  {item.status === "completed" && (
                    <>
                      <button className="ghost" disabled={busy} onClick={() => { setJob(item); setStep("review"); }}>
                        Review
                      </button>
                      <button
                        className="ghost"
                        disabled={busy}
                        onClick={() => download(
                          `/api/workspaces/${workspaceId}/generation-jobs/${item.id}/records.csv`,
                          `${item.name}.csv`,
                        )}
                      >
                        Download CSV
                      </button>
                    </>
                  )}
                  {["completed", "failed", "cancelled"].includes(item.status) && (
                    <button
                      aria-label={`Delete generation job ${item.name}`}
                      className="ghost"
                      disabled={busy}
                      onClick={() => deleteJob(item)}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function ReviewTable({
  workspaceId,
  job,
}: {
  workspaceId: string;
  job: GenerationJob;
}) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<GenerationRecordPage | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [hasEditFailure, setHasEditFailure] = useState(false);
  const pendingEdits = useRef(new Set<Promise<boolean>>());
  const failedEdits = useRef(new Set<string>());
  const editGenerations = useRef(new Map<string, number>());
  const editChains = useRef(new Map<string, Promise<boolean>>());
  const saving = useRef(false);
  const loadGeneration = useRef(0);

  async function load(target: number) {
    const generation = ++loadGeneration.current;
    try {
      const fresh = await api<GenerationRecordPage>(
        `/api/workspaces/${workspaceId}/generation-jobs/${job.id}/records?page=${target}`,
      );
      if (generation !== loadGeneration.current) return;
      setData(fresh);
      setPage(target);
    } catch (reason) {
      if (generation !== loadGeneration.current) return;
      setError(reason instanceof Error ? reason.message : "Could not load records");
    }
  }
  useEffect(() => {
    load(1);
    return () => {
      loadGeneration.current += 1;
    };
  }, [job.id]);

  function restoreOrClear(record: GenerationRecord, body: Partial<GenerationRecord>) {
    if (saving.current) return;
    const editKey = `${record.id}:${Object.keys(body).sort().join(",")}`;
    if (editChains.current.has(editKey)) {
      patch(record, body);
      return;
    }
    editGenerations.current.set(editKey, (editGenerations.current.get(editKey) ?? 0) + 1);
    failedEdits.current.delete(editKey);
    setHasEditFailure(failedEdits.current.size > 0);
    if (!failedEdits.current.size) setError("");
  }

  function patch(record: GenerationRecord, body: Partial<GenerationRecord>) {
    if (saving.current) return;
    const editKey = `${record.id}:${Object.keys(body).sort().join(",")}`;
    const generation = (editGenerations.current.get(editKey) ?? 0) + 1;
    editGenerations.current.set(editKey, generation);
    const previous = editChains.current.get(editKey);
    let request: Promise<boolean>;
    const run = () => api<GenerationRecord>(
      `/api/workspaces/${workspaceId}/generation-jobs/${job.id}/records/${record.id}`,
      { method: "PATCH", body: JSON.stringify(body) },
    )
      .then((fresh) => {
        if (editGenerations.current.get(editKey) !== generation) return true;
        failedEdits.current.delete(editKey);
        setHasEditFailure(failedEdits.current.size > 0);
        if (!failedEdits.current.size) setError("");
        setData((current) =>
          current
            ? {
              ...current,
              records: current.records.map((item) =>
                item.id === fresh.id ? fresh : item,
              ),
            }
            : current,
        );
        return true;
      })
      .catch((reason) => {
        if (editGenerations.current.get(editKey) !== generation) return true;
        failedEdits.current.add(editKey);
        setHasEditFailure(true);
        setError(reason instanceof Error ? reason.message : "Could not save the edit");
        return false;
      });
    request = (previous ? previous.then(run) : run())
      .finally(() => {
        pendingEdits.current.delete(request);
        if (editChains.current.get(editKey) === request) editChains.current.delete(editKey);
        setPendingCount(pendingEdits.current.size);
      });
    editChains.current.set(editKey, request);
    pendingEdits.current.add(request);
    setPendingCount(pendingEdits.current.size);
    return request;
  }

  async function downloadCsv() {
    if (saving.current) return;
    saving.current = true;
    setBusy(true);
    setError("");
    try {
      const edits = await Promise.all([...pendingEdits.current]);
      if (failedEdits.current.size || edits.some((succeeded) => !succeeded)) return;
      await download(
        `/api/workspaces/${workspaceId}/generation-jobs/${job.id}/records.csv`,
        `${job.name}.csv`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not download records");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="stack">
      <section className="panel">
        <h2>Review generated records</h2>
        <p className="muted">
          {job.generated_count} records generated · edit text, delete bad rows, then save.
        </p>
        {job.unit_errors.length > 0 && (
          <div className="notice error">
            <p>{job.unit_errors.length} generation unit(s) failed; the rest completed.</p>
            <ul>
              {job.unit_errors.map((unitError) => (
                <li key={`${unitError.unit}-${unitError.error}`}>
                  Unit {unitError.unit}: {unitError.error}
                </li>
              ))}
            </ul>
          </div>
        )}
        {error && <p className="notice error">{error}</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>#</th><th>Question</th><th>Answer</th><th>Contexts</th><th></th></tr>
            </thead>
            <tbody>
              {data?.records.map((record) => (
                <tr key={record.id} style={record.deleted ? { opacity: 0.4 } : undefined}>
                  <td>{record.record_index + 1}</td>
                  <td>
                    <textarea
                      aria-label={`Question ${record.record_index + 1}`}
                      defaultValue={record.question}
                      disabled={busy || record.deleted}
                      onBlur={(event) => {
                        const question = event.target.value;
                        if (!question.trim()) return;
                        if (question === record.question) {
                          restoreOrClear(record, { question: record.question });
                        } else patch(record, { question });
                      }}
                    />
                  </td>
                  <td>
                    <textarea
                      aria-label={`Answer ${record.record_index + 1}`}
                      defaultValue={record.answer}
                      disabled={busy || record.deleted}
                      onBlur={(event) => {
                        const answer = event.target.value;
                        if (!answer.trim()) return;
                        if (answer === record.answer) {
                          restoreOrClear(record, { answer: record.answer });
                        } else patch(record, { answer });
                      }}
                    />
                  </td>
                  <td>
                    <textarea
                      aria-label={`Contexts ${record.record_index + 1}`}
                      defaultValue={record.contexts.join("\n")}
                      disabled={busy || record.deleted}
                      onBlur={(event) => {
                        const contexts = event.target.value
                          .split("\n")
                          .map((line) => line.trim())
                          .filter(Boolean);
                        if (!contexts.length) return;
                        const unchanged = contexts.length === record.contexts.length
                          && contexts.every((context, index) => context === record.contexts[index]);
                        if (unchanged) restoreOrClear(record, { contexts: record.contexts });
                        else patch(record, { contexts });
                      }}
                    />
                  </td>
                  <td>
                    <button
                      aria-label={`${record.deleted ? "Restore" : "Delete"} record ${record.record_index + 1}`}
                      className="ghost"
                      disabled={busy}
                      onClick={() => patch(record, { deleted: !record.deleted })}
                    >
                      {record.deleted ? "Restore" : "Delete"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {totalPages > 1 && (
          <div className="list-row">
            <button className="ghost" disabled={busy || page <= 1} onClick={() => load(page - 1)}>
              Previous
            </button>
            <span>Page {page} / {totalPages}</span>
            <button className="ghost" disabled={busy || page >= totalPages} onClick={() => load(page + 1)}>
              Next
            </button>
          </div>
        )}
      </section>
      <section className="panel" aria-label="Download records">
        <h2>Download records</h2>
        <p className="muted">
          Download as CSV, fill in or correct answers offline, then upload it on the Datasets page.
        </p>
        <div className="list-row">
          <button
            className="primary"
            disabled={busy || pendingCount > 0 || hasEditFailure}
            onClick={downloadCsv}
          >
            {busy ? "Preparing…" : "Download CSV"}
          </button>
          <a className="ghost" href={`/w/${workspaceId}/datasets`}>Go to datasets</a>
        </div>
      </section>
    </div>
  );
}
