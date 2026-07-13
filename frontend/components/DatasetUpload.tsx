"use client";

import {FormEvent, useMemo, useState} from "react";

import {api} from "@/lib/api";
import type {Dataset} from "@/lib/types";

const fields = [
  ["input", "Input"],
  ["expected_output", "Expected output"],
  ["contexts", "Contexts"],
  ["actual_output", "Actual output"],
] as const;

export function ColumnMapper({
  dataset,
  onSave,
}: {
  dataset: Dataset;
  onSave: (mapping: Record<string, string>) => void | Promise<void>;
}) {
  const columns = useMemo(
    () => Object.keys(dataset.preview?.[0] ?? {}),
    [dataset.preview],
  );
  const [mapping, setMapping] = useState<Record<string, string>>(dataset.schema_map);
  return (
    <div className="mapper">
      <div className="mapping-grid">
        {fields.map(([key, label]) => (
          <label key={key}>
            {label}
            <select
              value={mapping[key] ?? ""}
              onChange={(event) =>
                setMapping((current) => {
                  const next = {...current};
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
        ))}
      </div>
      <button className="primary" onClick={() => onSave(mapping)} disabled={!mapping.input}>
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

export function DatasetUpload({
  workspaceId,
  onComplete,
}: {
  workspaceId: string;
  onComplete: (dataset: Dataset) => void;
}) {
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      setDataset(
        await api<Dataset>(`/api/workspaces/${workspaceId}/datasets`, {
          method: "POST",
          body: form,
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  if (dataset) {
    return (
      <ColumnMapper
        dataset={dataset}
        onSave={async (schema_map) => {
          const saved = await api<Dataset>(
            `/api/workspaces/${workspaceId}/datasets/${dataset.id}/schema-map`,
            {method: "PATCH", body: JSON.stringify({schema_map})},
          );
          onComplete(saved);
          setDataset(null);
        }}
      />
    );
  }

  return (
    <form className="upload-zone" onSubmit={upload}>
      <div className="upload-drop">
        <span className="upload-icon" aria-hidden="true">↑</span>
        <strong>Drop in a dataset</strong>
        <p className="muted">CSV, JSON, or JSONL · up to 5,000 rows</p>
      </div>
      <label className="upload-name">
        <span className="sr-only">Dataset name</span>
        <input name="name" placeholder="Dataset name" required />
      </label>
      <label className="file-picker">
        <span>Choose file</span>
        <input name="file" type="file" accept=".csv,.json,.jsonl" required />
      </label>
      {error && <p className="notice error">{error}</p>}
      <button className="primary" disabled={busy}>{busy ? "Uploading…" : "Upload"}</button>
    </form>
  );
}
