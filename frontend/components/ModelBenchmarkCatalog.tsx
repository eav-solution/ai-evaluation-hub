"use client";

import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import type {ReactNode} from "react";

import {BenchmarkInfoModal} from "@/components/BenchmarkInfoModal";
import {ModelBenchmarkDetails, type DetailSelection} from "@/components/ModelBenchmarkDetails";
import {ModelBenchmarkMatrix, type MatrixSort} from "@/components/ModelBenchmarkMatrix";
import {api} from "@/lib/api";
import {
  filterModels,
  isReviewNeeded,
  sortModelsByScore,
  type BenchmarkDefinition,
  type BenchmarkView,
  type ModelBenchmarkCatalogPayload,
  type ModelFilters,
} from "@/lib/model-benchmarks";

const views: Array<{id: BenchmarkView; label: string}> = [
  {id: "text_code", label: "Text & Code"},
  {id: "multimodal", label: "Multimodal"},
  {id: "specs", label: "Specs & Pricing"},
];

const tierSections = [
  {id: "frontier", label: "Frontier"},
  {id: "mid_range", label: "Mid-range"},
  {id: "lite", label: "Lite"},
] as const;

const initialFilters: ModelFilters = {tier: "all", providerId: "all", query: ""};

export function ModelBenchmarkCatalog(): ReactNode {
  const [catalog, setCatalog] = useState<ModelBenchmarkCatalogPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState<BenchmarkView>("text_code");
  const [filters, setFilters] = useState<ModelFilters>(initialFilters);
  const [sort, setSort] = useState<MatrixSort>(null);
  const [infoBenchmark, setInfoBenchmark] = useState<BenchmarkDefinition | null>(null);
  const [detailSelection, setDetailSelection] = useState<DetailSelection | null>(null);
  const mountedRef = useRef(true);
  const initialLoadRef = useRef(false);

  const loadCatalog = useCallback(async () => {
    if (mountedRef.current) {
      setLoading(true);
      setError("");
    }

    try {
      const nextCatalog = await api<ModelBenchmarkCatalogPayload>("/api/model-benchmarks");
      if (mountedRef.current) setCatalog(nextCatalog);
    } catch (reason) {
      if (mountedRef.current) {
        setError(reason instanceof Error ? reason.message : "Could not load model benchmarks");
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

  const models = useMemo(() => {
    if (!catalog) return [];

    const filtered = filterModels(catalog.models, {...filters, tier: "all"});
    if (view === "specs") {
      return [...filtered].sort((left, right) => left.display_name.localeCompare(right.display_name));
    }
    if (!sort) return filtered;
    return sortModelsByScore(filtered, catalog.scores, sort.benchmarkId, sort.order);
  }, [catalog, filters, sort, view]);

  function selectView(nextView: BenchmarkView) {
    setView(nextView);
    setSort((currentSort) => {
      if (!currentSort || nextView === "specs") return null;
      const benchmarkIsAvailable = catalog?.benchmarks.some(
        (benchmark) => benchmark.id === currentSort.benchmarkId && benchmark.track === nextView,
      );
      return benchmarkIsAvailable ? currentSort : null;
    });
  }

  function updateSort(benchmark: BenchmarkDefinition) {
    setSort((currentSort) => {
      if (currentSort?.benchmarkId === benchmark.id) {
        return {...currentSort, order: currentSort.order === "desc" ? "asc" : "desc"};
      }
      return {
        benchmarkId: benchmark.id,
        order: benchmark.direction === "higher_is_better" ? "desc" : "asc",
      };
    });
  }

  if (loading) return <p className="notice">Loading model benchmarks…</p>;

  if (error) {
    return (
      <section className="notice error" aria-live="polite">
        <p>{error}</p>
        <button type="button" onClick={() => void loadCatalog()}>Retry</button>
      </section>
    );
  }

  if (!catalog) return null;

  return (
    <section className="model-benchmark-catalog" aria-label="Model benchmarks">
      <div className="model-benchmark-controls">
        <div className="model-benchmark-catalog-meta">
          <span>Catalog version: {catalog.catalog_version}</span>
          <span>Last verified: {catalog.last_verified_at}</span>
          {isReviewNeeded(catalog.last_verified_at) && <span className="benchmark-review-needed">Review needed</span>}
        </div>
        <div className="model-benchmark-view-tabs" role="group" aria-label="Benchmark view">
          {views.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-pressed={view === item.id}
              onClick={() => selectView(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="model-benchmark-filters">
          <label>
            Provider
            <select
              value={filters.providerId}
              onChange={(event) => setFilters((current) => ({...current, providerId: event.target.value}))}
            >
              <option value="all">All providers</option>
              {catalog.providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.display_name}</option>)}
            </select>
          </label>
          <label>
            Search full model name
            <input
              type="search"
              value={filters.query}
              onChange={(event) => setFilters((current) => ({...current, query: event.target.value}))}
            />
          </label>
        </div>
      </div>

      <div className="model-benchmark-tier-sections">
        {tierSections.map((tier) => {
          const tierModels = models.filter((model) => model.tier === tier.id);
          return (
            <section
              key={tier.id}
              className="model-benchmark-tier-section"
              aria-label={`${tier.label} models`}
            >
              <h2>{tier.label}</h2>
              {tierModels.length === 0 ? (
                <p className="model-benchmark-tier-empty" role="status">
                  No {tier.label} models match these filters
                </p>
              ) : (
                <ModelBenchmarkMatrix
                  view={view}
                  models={tierModels}
                  providers={catalog.providers}
                  benchmarks={catalog.benchmarks}
                  scores={catalog.scores}
                  sort={sort}
                  onSort={updateSort}
                  onOpenInfo={setInfoBenchmark}
                  onSelectScore={setDetailSelection}
                  onSelectModel={setDetailSelection}
                />
              )}
            </section>
          );
        })}
      </div>
      <ModelBenchmarkDetails selection={detailSelection} onClose={() => setDetailSelection(null)} />
      <BenchmarkInfoModal benchmark={infoBenchmark} onClose={() => setInfoBenchmark(null)} />
    </section>
  );
}
