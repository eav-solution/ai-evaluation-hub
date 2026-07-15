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

function resultDetailView(details: Record<string, unknown> | null) {
  const sample = details?.sample;
  if (!sample || typeof sample !== "object" || Array.isArray(sample)) {
    return {
      trustedContext: null,
      agentTrace: null,
      toolsCalled: null,
      expectedTools: null,
      otherDetails: details && Object.keys(details).length ? details : null,
    };
  }

  const fields = sample as Record<string, unknown>;
  const trustedContext = fields.context ?? null;
  if (fields.kind !== "agent_trace") {
    return {
      trustedContext,
      agentTrace: null,
      toolsCalled: null,
      expectedTools: null,
      otherDetails: details,
    };
  }

  const otherDetails = {...details};
  const otherSample = {...fields};
  for (const key of [
    "kind",
    "context",
    "agent_trace",
    "tools_called",
    "expected_tools",
    "normalizer_revision",
  ]) {
    delete otherSample[key];
  }
  for (const key of ["metadata", "tags", "source"]) {
    if (!otherSample[key]) delete otherSample[key];
    else if (Array.isArray(otherSample[key]) && !otherSample[key].length) delete otherSample[key];
    else if (
      typeof otherSample[key] === "object" &&
      !Array.isArray(otherSample[key]) &&
      !Object.keys(otherSample[key] as object).length
    ) delete otherSample[key];
  }
  const source = otherSample.source;
  if (
    source &&
    typeof source === "object" &&
    !Array.isArray(source) &&
    !(source as Record<string, unknown>).event_id &&
    !(source as Record<string, unknown>).external_id
  ) delete otherSample.source;
  if (Object.keys(otherSample).length) otherDetails.sample = otherSample;
  else delete otherDetails.sample;

  return {
    trustedContext,
    agentTrace: fields.agent_trace ?? null,
    toolsCalled: fields.tools_called ?? null,
    expectedTools: fields.expected_tools ?? null,
    otherDetails: Object.keys(otherDetails).length ? otherDetails : null,
  };
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
  const comparisonSummaries = useMemo(
    () =>
      (run?.summaries ?? []).flatMap((summary) => {
        const direction = metricsByKey.get(summary.metric_key)?.info.score_direction;
        if (!direction) return [];
        return [{
          ...summary,
          raw_mean: summary.mean,
          comparison_score:
            direction === "lower_is_better" ? 1 - summary.mean : summary.mean,
          score_direction: direction,
        }];
      }),
    [metricsByKey, run],
  );
  const comparisonTooltip = (
    _value: unknown,
    _name: unknown,
    item: {payload?: {raw_mean: number; score_direction: string}},
  ) => {
    const point = item.payload;
    if (!point) return ["", "Comparable quality"];
    const direction = point.score_direction === "lower_is_better"
      ? "Lower is better"
      : "Higher is better";
    return [`Raw ${point.raw_mean.toFixed(3)} · ${direction}`, "Comparable quality"];
  };
  const rows = useMemo(() => {
    const filtered = failuresOnly
      ? results.filter(
          (row) =>
            row.error ||
            Object.values(row.scores).some((score) => score.error || score.passed === false),
        )
      : results;
    if (!sortMetric) return filtered;
    const direction = metricsByKey.get(sortMetric)?.info.score_direction;
    return [...filtered].sort((a, b) => {
      const left = a.scores[sortMetric]?.score;
      const right = b.scores[sortMetric]?.score;
      if (left === null || left === undefined) {
        return right === null || right === undefined ? a.row_index - b.row_index : 1;
      }
      if (right === null || right === undefined) return -1;
      if (direction === "lower_is_better") return left - right;
      if (direction === "higher_is_better") return right - left;
      return a.row_index - b.row_index;
    });
  }, [failuresOnly, metricsByKey, results, sortMetric]);

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
            <span>
              {metricsByKey.get(summary.metric_key)?.info.score_direction === "lower_is_better"
                ? "Lower is better"
                : metricsByKey.get(summary.metric_key)?.info.score_direction === "higher_is_better"
                  ? "Higher is better"
                  : "Direction unavailable"}
            </span>
          </article>
        ))}
      </div>

      <MetricInfoModal metric={activeMetric} onClose={() => setActiveMetric(null)} />

      <div className="chart-grid">
        <section className="panel chart-panel">
          <h2>Comparable quality</h2>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={comparisonSummaries} layout="vertical" margin={{left: 24, right: 12}}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" domain={[0, 1]} />
              <YAxis
                type="category"
                dataKey="metric_key"
                width={140}
                tickFormatter={(key: string) => metricLabel(metricsByKey, key)}
              />
              <Tooltip
                formatter={comparisonTooltip}
                labelFormatter={(key) => metricLabel(metricsByKey, String(key))}
              />
              <Bar dataKey="comparison_score" fill="#635bff" radius={[0, 7, 7, 0]} />
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
        {comparisonSummaries.length > 2 && (
          <section className="panel chart-panel">
            <h2>Metric profile</h2>
            <ResponsiveContainer width="100%" height={260}>
              <RadarChart data={comparisonSummaries} outerRadius="70%" margin={{top: 8, right: 64, bottom: 8, left: 64}}>
                <PolarGrid />
                <PolarAngleAxis
                  dataKey="metric_key"
                  tickFormatter={(key: string) => metricLabel(metricsByKey, key)}
                />
                <PolarRadiusAxis domain={[0, 1]} tick={false} axisLine={false} />
                <Tooltip
                  formatter={comparisonTooltip}
                  labelFormatter={(key) => metricLabel(metricsByKey, String(key))}
                />
                <Radar dataKey="comparison_score" stroke="#635bff" fill="#635bff" fillOpacity={0.3} />
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
              {rows.map((row) => {
                const detailView = resultDetailView(row.details);
                const hasMetadata =
                  detailView.trustedContext !== null ||
                  detailView.agentTrace !== null ||
                  detailView.toolsCalled !== null ||
                  detailView.expectedTools !== null ||
                  detailView.otherDetails !== null ||
                  row.usage !== null ||
                  row.estimated_cost !== null;
                return (
                  <tr key={row.id}>
                    <td>{row.row_index}</td>
                    <td className="copy-cell">
                      <strong>{row.input}</strong>
                      <p>{row.actual}</p>
                      {row.error && <span className="error">{row.error}</span>}
                      {row.contexts && (
                        <details>
                          <summary>Contexts</summary>
                          <pre>{JSON.stringify(row.contexts, null, 2)}</pre>
                        </details>
                      )}
                      {hasMetadata && (
                        <details className="result-metadata">
                          <summary>Result metadata</summary>
                          <div className="result-metadata-body">
                            {detailView.trustedContext !== null && (
                              <div>
                                <strong>Trusted context</strong>
                                <pre>{JSON.stringify(detailView.trustedContext, null, 2)}</pre>
                              </div>
                            )}
                            {detailView.agentTrace !== null && (
                              <div>
                                <strong>Agent trace</strong>
                                <pre>{JSON.stringify(detailView.agentTrace, null, 2)}</pre>
                              </div>
                            )}
                            {detailView.toolsCalled !== null && (
                              <div>
                                <strong>Tools called</strong>
                                <pre>{JSON.stringify(detailView.toolsCalled, null, 2)}</pre>
                              </div>
                            )}
                            {detailView.expectedTools !== null && (
                              <div>
                                <strong>Expected tools</strong>
                                <pre>{JSON.stringify(detailView.expectedTools, null, 2)}</pre>
                              </div>
                            )}
                            {detailView.otherDetails !== null && (
                              <div>
                                <strong>Details</strong>
                                <pre>{JSON.stringify(detailView.otherDetails, null, 2)}</pre>
                              </div>
                            )}
                            {row.usage !== null && (
                              <div>
                                <strong>Usage</strong>
                                <pre>{JSON.stringify(row.usage, null, 2)}</pre>
                              </div>
                            )}
                            {row.estimated_cost !== null && (
                              <div>
                                <strong>Estimated cost</strong>
                                <p>${row.estimated_cost.toFixed(6)}</p>
                              </div>
                            )}
                          </div>
                        </details>
                      )}
                    </td>
                    {metricKeys.map((key) => {
                      const score = row.scores[key];
                      return (
                        <td key={key}>
                          <span
                            className={`score ${score?.passed === false ? "bad" : "good"}`}
                          >
                            {score?.score?.toFixed(3) ?? "—"}
                          </span>
                          {(score?.reason || score?.error) && (
                            <details>
                              <summary>Details</summary>
                              <p>{score.reason ?? score.error}</p>
                            </details>
                          )}
                        </td>
                      );
                    })}
                    <td>{row.latency_ms === null ? "—" : `${row.latency_ms} ms`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
