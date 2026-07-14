"use client";

import {useEffect, useMemo, useState} from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {api, download} from "@/lib/api";
import {MetricInfoButton, MetricInfoModal} from "@/components/MetricInfoModal";
import type {Metric, Run, RunResult} from "@/lib/types";

export function metricLabel(metricsByKey: Map<string, Metric>, key: string): string {
  return metricsByKey.get(key)?.display_name ?? key;
}

export function RunReport({
  workspaceId,
  runId,
}: {
  workspaceId: string;
  runId: string;
}) {
  const [run, setRun] = useState<Run | null>(null);
  const [results, setResults] = useState<RunResult[]>([]);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [activeMetric, setActiveMetric] = useState<Metric | null>(null);
  const [failuresOnly, setFailuresOnly] = useState(false);
  const [sortMetric, setSortMetric] = useState("");
  const [error, setError] = useState("");
  const base = `/api/workspaces/${workspaceId}/runs/${runId}`;

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    async function load() {
      try {
        const nextRun = await api<Run>(base);
        if (stopped) return;
        setRun(nextRun);
        setResults(await api<RunResult[]>(`${base}/results`));
        if (["pending", "running"].includes(nextRun.status)) {
          timer = setTimeout(load, 2000);
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Could not load run");
      }
    }
    load();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [base]);

  useEffect(() => {
    let cancelled = false;
    api<Metric[]>("/api/metrics")
      .then((catalog) => {
        if (!cancelled) setMetrics(catalog);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const metricKeys = run?.metric_config.metrics.map((item) => item.key) ?? [];
  const metricsByKey = useMemo(
    () => new Map(metrics.map((metric) => [metric.key, metric])),
    [metrics],
  );
  const rows = useMemo(() => {
    const filtered = failuresOnly
      ? results.filter(
          (row) =>
            row.error ||
            Object.values(row.scores).some((score) => score.error || score.passed === false),
        )
      : results;
    if (!sortMetric) return filtered;
    return [...filtered].sort(
      (a, b) =>
        (b.scores[sortMetric]?.score ?? -1) - (a.scores[sortMetric]?.score ?? -1),
    );
  }, [failuresOnly, results, sortMetric]);

  const histogram = useMemo(() => {
    const buckets = [
      {range: "0–.2", min: 0, max: 0.2, count: 0},
      {range: ".2–.4", min: 0.2, max: 0.4, count: 0},
      {range: ".4–.6", min: 0.4, max: 0.6, count: 0},
      {range: ".6–.8", min: 0.6, max: 0.8, count: 0},
      {range: ".8–1", min: 0.8, max: 1.01, count: 0},
    ];
    results.flatMap((row) => Object.values(row.scores)).forEach((score) => {
      if (score.score === null) return;
      buckets.find((bucket) => score.score! >= bucket.min && score.score! < bucket.max)!.count += 1;
    });
    return buckets;
  }, [results]);

  if (error) return <p className="notice error">{error}</p>;
  if (!run) return <div className="loading">Loading evaluation…</div>;

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">{run.mode} evaluation</p>
          <h1>{run.name}</h1>
          <div className="status-line">
            <span className={`status ${run.status}`}>{run.status}</span>
            <span>{run.progress_done}/{run.progress_total} rows</span>
          </div>
        </div>
        <div className="actions">
          {["pending", "running"].includes(run.status) && (
            <button
              className="danger"
              onClick={async () => setRun(await api<Run>(`${base}/cancel`, {method: "POST"}))}
            >
              Cancel
            </button>
          )}
          <button onClick={() => download(`${base}/report.html`, `${run.name}.html`)}>HTML</button>
          <button onClick={() => download(`${base}/results.csv`, `${run.name}.csv`)}>CSV</button>
          <button onClick={() => download(`${base}/results.json`, `${run.name}.json`)}>JSON</button>
        </div>
      </header>

      {["pending", "running"].includes(run.status) && (
        <div className="progress"><span style={{width: `${run.progress_total ? run.progress_done / run.progress_total * 100 : 2}%`}} /></div>
      )}
      {run.error && <p className="notice error">{run.error}</p>}

      <div className="summary-grid">
        {run.summaries.map((summary) => (
          <article className="summary-card" key={summary.metric_key}>
            <small>{summary.metric_key}</small>
            {metricsByKey.get(summary.metric_key) && (
              <MetricInfoButton
                metric={metricsByKey.get(summary.metric_key)!}
                onOpen={setActiveMetric}
              />
            )}
            <strong>{summary.mean.toFixed(3)}</strong>
            <span>{summary.pass_rate === null ? "No threshold" : `${(summary.pass_rate * 100).toFixed(0)}% pass`}</span>
          </article>
        ))}
      </div>

      <MetricInfoModal metric={activeMetric} onClose={() => setActiveMetric(null)} />

      <div className="chart-grid">
        <section className="panel chart-panel">
          <h2>Mean by metric</h2>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={run.summaries} layout="vertical" margin={{left: 24, right: 12}}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" domain={[0, 1]} />
              <YAxis
                type="category"
                dataKey="metric_key"
                width={140}
                tickFormatter={(key: string) => metricLabel(metricsByKey, key)}
              />
              <Tooltip />
              <Bar dataKey="mean" fill="#635bff" radius={[0, 7, 7, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </section>
        <section className="panel chart-panel">
          <h2>Score distribution</h2>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={histogram}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="range" label={{value: "Score range", position: "insideBottom", offset: -4}} />
              <YAxis allowDecimals={false} label={{value: "Count", angle: -90, position: "insideLeft"}} />
              <Tooltip />
              <Bar dataKey="count" fill="#1ca58b" radius={[7, 7, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </section>
        {run.summaries.length > 2 && (
          <section className="panel chart-panel">
            <h2>Metric profile</h2>
            <ResponsiveContainer width="100%" height={260}>
              <RadarChart data={run.summaries} outerRadius="70%" margin={{top: 8, right: 64, bottom: 8, left: 64}}>
                <PolarGrid />
                <PolarAngleAxis
                  dataKey="metric_key"
                  tickFormatter={(key: string) => metricLabel(metricsByKey, key)}
                />
                <PolarRadiusAxis domain={[0, 1]} tick={false} axisLine={false} />
                <Tooltip labelFormatter={(key) => metricLabel(metricsByKey, String(key))} />
                <Radar dataKey="mean" stroke="#635bff" fill="#635bff" fillOpacity={0.3} />
              </RadarChart>
            </ResponsiveContainer>
          </section>
        )}
      </div>

      <section className="panel">
        <div className="table-controls">
          <h2>Row results <span className="muted">({rows.length})</span></h2>
          <label className="check"><input type="checkbox" checked={failuresOnly} onChange={(event) => setFailuresOnly(event.target.checked)} /> Failures only</label>
          <label>Sort by<select value={sortMetric} onChange={(event) => setSortMetric(event.target.value)}><option value="">Dataset order</option>{metricKeys.map((key) => <option key={key}>{key}</option>)}</select></label>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>Input / output</th>{metricKeys.map((key) => <th key={key}>{key}</th>)}<th>Latency</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.row_index}</td>
                  <td className="copy-cell">
                    <strong>{row.input}</strong>
                    <p>{row.actual}</p>
                    {row.error && <span className="error">{row.error}</span>}
                    {row.contexts && <details><summary>Contexts</summary><pre>{JSON.stringify(row.contexts, null, 2)}</pre></details>}
                  </td>
                  {metricKeys.map((key) => {
                    const score = row.scores[key];
                    return (
                      <td key={key}>
                        <span className={`score ${score?.passed === false ? "bad" : "good"}`}>
                          {score?.score?.toFixed(3) ?? "—"}
                        </span>
                        {(score?.reason || score?.error) && <details><summary>Details</summary><p>{score.reason ?? score.error}</p></details>}
                      </td>
                    );
                  })}
                  <td>{row.latency_ms === null ? "—" : `${row.latency_ms} ms`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
