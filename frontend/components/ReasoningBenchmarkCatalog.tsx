"use client";

import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import type {ReactNode} from "react";

import {api} from "@/lib/api";
import {
  bestValueByCriterion,
  formatScore,
  rankEntries,
  type ReasoningBenchmarkCatalogPayload,
  type ReasoningTest,
} from "@/lib/reasoning-benchmarks";

function testsByCategory(tests: ReasoningTest[]): Map<string, ReasoningTest[]> {
  const groups = new Map<string, ReasoningTest[]>();
  for (const test of tests) {
    const group = groups.get(test.category) ?? [];
    group.push(test);
    groups.set(test.category, group);
  }
  return groups;
}

export function ReasoningBenchmarkCatalog(): ReactNode {
  const [catalog, setCatalog] = useState<ReasoningBenchmarkCatalogPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedTestId, setSelectedTestId] = useState("");
  const mountedRef = useRef(true);
  const initialLoadRef = useRef(false);

  const loadCatalog = useCallback(async () => {
    if (mountedRef.current) {
      setLoading(true);
      setError("");
    }

    try {
      const nextCatalog = await api<ReasoningBenchmarkCatalogPayload>("/api/reasoning-benchmarks");
      if (mountedRef.current) setCatalog(nextCatalog);
    } catch (reason) {
      if (mountedRef.current) {
        setError(reason instanceof Error ? reason.message : "Could not load reasoning benchmarks");
      }
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    if (!initialLoadRef.current) {
      initialLoadRef.current = true;
      void loadCatalog();
    }
    return () => {
      mountedRef.current = false;
    };
  }, [loadCatalog]);

  const activeTest = useMemo(() => {
    if (!catalog || catalog.tests.length === 0) return null;
    return catalog.tests.find((test) => test.id === selectedTestId) ?? catalog.tests[0];
  }, [catalog, selectedTestId]);

  const modelsById = useMemo(
    () => new Map((catalog?.models ?? []).map((model) => [model.id, model])),
    [catalog],
  );
  const harnessesById = useMemo(
    () => new Map((catalog?.harnesses ?? []).map((harness) => [harness.id, harness])),
    [catalog],
  );
  const ranked = useMemo(
    () => (activeTest ? rankEntries(activeTest, modelsById) : []),
    [activeTest, modelsById],
  );
  const bestValues = useMemo(
    () => (activeTest ? bestValueByCriterion(activeTest) : new Map<string, number>()),
    [activeTest],
  );

  if (loading) return <p className="notice">Loading reasoning benchmarks…</p>;

  if (error) {
    return (
      <section className="notice error" aria-live="polite">
        <p>{error}</p>
        <button type="button" onClick={() => void loadCatalog()}>Retry</button>
      </section>
    );
  }

  if (!catalog || !activeTest) return null;

  const groups = testsByCategory(catalog.tests);
  const testOptions = (tests: ReasoningTest[]) =>
    tests.map((test) => (
      <option key={test.id} value={test.id}>
        {test.display_name}
      </option>
    ));

  return (
    <section className="reasoning-benchmark-catalog" aria-label="Reasoning benchmarks">
      <div className="reasoning-benchmark-controls">
        <label className="reasoning-benchmark-picker">
          <span>Test</span>
          <select
            aria-label="Reasoning test"
            value={activeTest.id}
            onChange={(event) => setSelectedTestId(event.target.value)}
          >
            {groups.size > 1
              ? [...groups.entries()].map(([category, tests]) => (
                  <optgroup key={category} label={category}>
                    {testOptions(tests)}
                  </optgroup>
                ))
              : testOptions(catalog.tests)}
          </select>
        </label>
        <div className="reasoning-benchmark-meta">
          <span>Conducted {activeTest.conducted_at}</span>
          <span>Category: {activeTest.category}</span>
          <span>Catalog version: {catalog.catalog_version}</span>
        </div>
      </div>

      <p className="muted">{activeTest.task_summary}</p>

      <div className="reasoning-benchmark-matrix">
        <table>
          <thead>
            <tr>
              <th scope="col">Criterion</th>
              {ranked.map(({entry}) => (
                <th scope="col" key={`${entry.model_id}:${entry.harness_id}`}>
                  <span className="reasoning-model-name">
                    {modelsById.get(entry.model_id)?.display_name ?? entry.model_id}
                  </span>
                  <span className="reasoning-harness-badge">
                    {harnessesById.get(entry.harness_id)?.display_name ?? entry.harness_id}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {activeTest.criteria.map((criterion) => (
              <tr key={criterion.id}>
                <th scope="row">
                  <span className="reasoning-criterion-name" title={criterion.description}>
                    {criterion.display_name}
                  </span>
                  <span className="reasoning-criterion-scale">
                    {formatScore(criterion.minimum)}–{formatScore(criterion.maximum)}
                    {criterion.direction === "lower_is_better" ? " (lower is better)" : ""}
                  </span>
                </th>
                {ranked.map(({entry}) => {
                  const score = entry.scores.find((item) => item.criterion_id === criterion.id);
                  const isBest = score !== undefined && bestValues.get(criterion.id) === score.value;
                  return (
                    <td
                      key={`${entry.model_id}:${entry.harness_id}:${criterion.id}`}
                      className={isBest ? "reasoning-score-best" : undefined}
                      title={score?.evidence ?? undefined}
                    >
                      {score ? formatScore(score.value) : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Average</th>
              {ranked.map(({entry, average}) => (
                <td key={`${entry.model_id}:${entry.harness_id}:avg`}>{formatScore(average)}</td>
              ))}
            </tr>
            <tr>
              <th scope="row">Rank</th>
              {ranked.map(({entry, rank}) => (
                <td key={`${entry.model_id}:${entry.harness_id}:rank`}>{rank}</td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>

      <ul className="reasoning-entry-summaries">
        {ranked.map(({entry}) => (
          <li key={`${entry.model_id}:${entry.harness_id}`}>
            <strong>{modelsById.get(entry.model_id)?.display_name ?? entry.model_id}</strong>
            {" — "}
            {entry.summary}
          </li>
        ))}
      </ul>

      {activeTest.findings.length > 0 && (
        <section className="reasoning-benchmark-section">
          <h2>Findings</h2>
          <ul>
            {activeTest.findings.map((finding) => (
              <li key={finding}>{finding}</li>
            ))}
          </ul>
        </section>
      )}

      {activeTest.limitations.length > 0 && (
        <section className="reasoning-benchmark-section">
          <h2>Limitations</h2>
          <ul>
            {activeTest.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="reasoning-benchmark-section">
        <h2>Methodology</h2>
        <p>{activeTest.methodology}</p>
        <p className="muted">Source: {activeTest.source_reference}</p>
      </section>
    </section>
  );
}
