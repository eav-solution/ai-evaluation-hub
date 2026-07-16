"use client";

import {useEffect, useMemo, useRef, useState} from "react";

import {api} from "@/lib/api";
import {
  autoMapColumns,
  collectFilesFromDataTransfer,
  countRecords,
  detectFormat,
  isSupportedFile,
  MAX_ROWS,
  stripExtension,
  type StagedFormat,
} from "@/lib/dataset-staging";
import type {Dataset} from "@/lib/types";

const commonFields = [
  ["input", "Input"],
  ["actual_output", "Actual output"],
  ["expected_output", "Expected output"],
  ["retrieval_contexts", "Retrieval contexts"],
  ["context", "Trusted context"],
] as const;

const agentFields = [
  ["agent_trace", "Agent trace"],
  ["tools_called", "Tools called"],
  ["expected_tools", "Expected tools"],
] as const;

const conversationFields = [
  ["turns", "Turns"],
  ["chatbot_role", "Chatbot role"],
  ["conversation_context", "Conversation context"],
  ["mcp_metadata", "MCP metadata"],
  ["mcp_events", "MCP events"],
] as const;

export function ColumnMapper({
  dataset,
  onSave,
}: {
  dataset: Dataset;
  onSave: (mapping: Record<string, string>) => void | Promise<void>;
}) {
  const columns = useMemo(
    () => Array.from(new Set((dataset.preview ?? []).flatMap((row) => Object.keys(row)))),
    [dataset.preview],
  );
  const [mapping, setMapping] = useState<Record<string, string>>(dataset.schema_map);
  function mappingFields(
    groupFields: readonly (readonly [string, string])[],
  ) {
    return groupFields.map(([key, label]) => (
      <label key={key}>
        {label}
        <select
          value={
            key === "retrieval_contexts"
              ? mapping.retrieval_contexts ?? mapping.contexts ?? ""
              : mapping[key] ?? ""
          }
          onChange={(event) =>
            setMapping((current) => {
              const next = {...current};
              if (key === "retrieval_contexts") delete next.contexts;
              if (event.target.value) next[key] = event.target.value;
              else delete next[key];
              return next;
            })
          }
        >
          <option value="">Not mapped</option>
          {columns.map((column) => (
            <option value={column} key={column}>{column}</option>
          ))}
        </select>
      </label>
    ));
  }
  return (
    <div className="mapper">
      <fieldset className="mapping-group">
        <legend>Common / RAG</legend>
        <div className="mapping-grid">
          {mappingFields(commonFields)}
        </div>
      </fieldset>
      <fieldset className="mapping-group">
        <legend>Agentic</legend>
        <div className="mapping-grid">
          {mappingFields(agentFields)}
        </div>
      </fieldset>
      <fieldset className="mapping-group">
        <legend>Conversational / MCP</legend>
        <div className="mapping-grid">
          {mappingFields(conversationFields)}
        </div>
      </fieldset>
      <button
        className="primary"
        onClick={() => onSave(mapping)}
        disabled={!mapping.input && !mapping.turns}
      >
        Save mapping
      </button>
      <div className="table-wrap">
        <table>
          <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
          <tbody>
            {dataset.preview?.slice(0, 5).map((row, index) => (
              <tr key={index}>
                {columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

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
  const [progress, setProgress] = useState({done: 0, total: 0});
  const [notice, setNotice] = useState("");
  const [dragover, setDragover] = useState(false);
  const [mapperRowId, setMapperRowId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const countingStarted = useRef<Set<string>>(new Set());

  function reset() {
    setRows([]);
    setSkipped(0);
    setNotice("");
    setPhase("staging");
    setProgress({done: 0, total: 0});
    setMapperRowId(null);
  }

  useEffect(() => {
    const prevent = (event: DragEvent) => event.preventDefault();
    window.addEventListener("dragover", prevent);
    window.addEventListener("drop", prevent);
    return () => {
      window.removeEventListener("dragover", prevent);
      window.removeEventListener("drop", prevent);
    };
  }, []);

  useEffect(() => {
    const pending = rows.filter(
      (row) =>
        row.records === null &&
        !row.error &&
        row.status === "staged" &&
        !countingStarted.current.has(row.id),
    );
    for (const row of pending) {
      countingStarted.current.add(row.id);
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
  }, [rows]);

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

  return (
    <div className="upload-zone">
      {phase === "staging" && (
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
      )}
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
          ))}
        </ul>
      )}
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
    </div>
  );
}
