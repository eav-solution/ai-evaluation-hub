"use client";

import Link from "next/link";
import {useParams} from "next/navigation";
import {useEffect, useState} from "react";

import {DatasetUpload} from "@/components/DatasetUpload";
import {api} from "@/lib/api";
import type {Dataset} from "@/lib/types";

export default function DatasetsPage() {
  const {workspace} = useParams<{workspace: string}>();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      setDatasets(await api<Dataset[]>(`/api/workspaces/${workspace}/datasets`));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load datasets");
    }
  }
  useEffect(() => { refresh(); }, [workspace]);

  return (
    <div className="stack">
      <header className="page-header">
        <div><p className="eyebrow">Data foundation</p><h1>Datasets</h1><p className="muted">Upload examples once, then reuse them across evaluation runs. Generated records from a job? Download its CSV, add answers, then upload it here.</p></div>
        <Link className="primary" href={`/w/${workspace}/datasets/generate`}>Generate from documents</Link>
      </header>
      {error && <p className="notice error">{error}</p>}
      <section className="panel">
        <DatasetUpload workspaceId={workspace} onComplete={() => refresh()} />
      </section>
      <section className="panel">
        <h2>Your datasets</h2>
        <div className="item-list">
          {datasets.map((dataset) => (
            <div className="list-row" key={dataset.id}>
              <span>
                <strong>{dataset.name}</strong>
                <small>{dataset.format.toUpperCase()} · {dataset.row_count} rows · {Object.keys(dataset.schema_map).length} mappings</small>
              </span>
              <button className="ghost" onClick={async () => {
                await api(`/api/workspaces/${workspace}/datasets/${dataset.id}`, {method: "DELETE"});
                refresh();
              }}>Delete</button>
            </div>
          ))}
          {!datasets.length && <p className="empty">No datasets yet. Your first upload can be tiny.</p>}
        </div>
      </section>
    </div>
  );
}
