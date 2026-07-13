"use client";

import Link from "next/link";
import {useParams} from "next/navigation";
import {useEffect, useState} from "react";

import {api} from "@/lib/api";
import type {Run} from "@/lib/types";

export default function RunsPage() {
  const {workspace} = useParams<{workspace: string}>();
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    async function refresh() {
      try {
        const rows = await api<Run[]>(`/api/workspaces/${workspace}/runs`);
        if (stopped) return;
        setRuns(rows);
        if (rows.some((run) => ["pending", "running"].includes(run.status))) {
          timer = setTimeout(refresh, 2000);
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Could not load runs");
      }
    }
    refresh();
    return () => { stopped = true; clearTimeout(timer); };
  }, [workspace]);

  return (
    <div className="stack">
      <header className="page-header">
        <div><p className="eyebrow">Evidence, not vibes</p><h1>Evaluation runs</h1><p className="muted">Track quality, failures, and judge explanations.</p></div>
        <Link className="button primary" href={`/w/${workspace}/runs/new`}>New evaluation</Link>
      </header>
      {error && <p className="notice error">{error}</p>}
      <section className="panel run-list">
        {runs.map((run) => (
          <Link className="run-row" href={`/w/${workspace}/runs/${run.id}`} key={run.id}>
            <span><strong>{run.name}</strong><small>{run.mode} · {new Date(run.created_at).toLocaleString()}</small></span>
            <div className="run-progress">
              <span className={`status ${run.status}`}>{run.status}</span>
              <div className="progress"><span style={{width: `${run.progress_total ? run.progress_done / run.progress_total * 100 : 0}%`}} /></div>
              <small>{run.progress_done}/{run.progress_total}</small>
            </div>
          </Link>
        ))}
        {!runs.length && <div className="empty"><h2>No runs yet</h2><p>Pick a dataset and launch a baseline.</p></div>}
      </section>
    </div>
  );
}
