"use client";

import Link from "next/link";
import {useParams} from "next/navigation";
import {useEffect, useMemo, useState} from "react";

import {DatasetUpload} from "@/components/DatasetUpload";
import {api} from "@/lib/api";
import {
  compatibleMetricCount,
  datasetCapabilities,
  type DatasetCapability,
} from "@/lib/dataset-capabilities";
import type {Dataset, Metric} from "@/lib/types";

const tabs = ["all", "rag", "agentic", "general"] as const;
const labels = {all: "All", rag: "RAG", agentic: "Agentic", general: "General"};

export default function DatasetsPage() {
  const {workspace} = useParams<{workspace: string}>();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>("all");
  const [error, setError] = useState("");

  async function refresh() {
    try {
      setDatasets(await api<Dataset[]>(`/api/workspaces/${workspace}/datasets`));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load datasets");
    }
  }
  useEffect(() => {
    refresh();
    api<Metric[]>("/api/metrics")
      .then(setMetrics)
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "Could not load metrics"),
      );
  }, [workspace]);

  const visibleDatasets = useMemo(
    () =>
      activeTab === "all"
        ? datasets
        : datasets.filter((dataset) =>
            datasetCapabilities(dataset).includes(activeTab as DatasetCapability),
          ),
    [activeTab, datasets],
  );

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">Data foundation</p>
          <h1>Datasets</h1>
          <p className="muted">
            Upload examples once, then reuse them across evaluation runs. Generated records
            from a job? Download its CSV, add answers, then upload it here.
          </p>
        </div>
        <Link className="primary" href={`/w/${workspace}/datasets/generate`}>
          Generate from documents
        </Link>
      </header>
      {error && <p className="notice error">{error}</p>}
      <section className="panel">
        <DatasetUpload workspaceId={workspace} onComplete={() => refresh()} />
      </section>
      <section className="panel">
        <div className="dataset-list-header">
          <h2>Your datasets</h2>
          <div
            className="capability-tabs"
            role="tablist"
            aria-label="Dataset capabilities"
          >
            {tabs.map((tab) => (
              <button
                type="button"
                key={tab}
                aria-pressed={activeTab === tab}
                onClick={() => setActiveTab(tab)}
              >
                {labels[tab]}
              </button>
            ))}
          </div>
        </div>
        <div className="item-list">
          {visibleDatasets.map((dataset) => {
            const capabilities = datasetCapabilities(dataset);
            const compatibleCount = compatibleMetricCount(dataset, metrics);
            return (
              <div className="list-row dataset-row" key={dataset.id}>
                <div className="dataset-row-main">
                  <div className="dataset-row-title">
                    <strong>{dataset.name}</strong>
                    <span className="dataset-badges">
                      {capabilities.map((capability) => (
                        <span className="capability-badge" key={capability}>
                          {labels[capability]}
                        </span>
                      ))}
                    </span>
                  </div>
                  <small>
                    {dataset.format.toUpperCase()} · {dataset.row_count} rows ·{" "}
                    {Object.keys(dataset.schema_map).length} mappings ·{" "}
                    <span>
                      {compatibleCount} compatible metric
                      {compatibleCount === 1 ? "" : "s"}
                    </span>
                  </small>
                </div>
                <button
                  className="ghost"
                  onClick={async () => {
                    await api(`/api/workspaces/${workspace}/datasets/${dataset.id}`, {
                      method: "DELETE",
                    });
                    refresh();
                  }}
                >
                  Delete
                </button>
              </div>
            );
          })}
          {!visibleDatasets.length && (
            <p className="empty">
              {datasets.length
                ? `No ${labels[activeTab]} datasets.`
                : "No datasets yet. Your first upload can be tiny."}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
