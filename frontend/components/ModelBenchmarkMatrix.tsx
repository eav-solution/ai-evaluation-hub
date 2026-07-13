"use client";

import type {ReactNode} from "react";

import {BenchmarkInfoButton} from "@/components/BenchmarkInfoModal";
import type {DetailSelection} from "@/components/ModelBenchmarkDetails";
import {
  formatTokenPrice,
  type BenchmarkDefinition,
  type BenchmarkScore,
  type BenchmarkView,
  type ModelRecord,
  type ProviderRecord,
  type SortOrder,
  type TokenPrice,
} from "@/lib/model-benchmarks";

export type MatrixSort = {benchmarkId: string; order: SortOrder} | null;

export function ModelBenchmarkMatrix({
  view,
  models,
  providers,
  benchmarks,
  scores,
  sort,
  onSort,
  onOpenInfo,
  onSelectScore,
  onSelectModel,
}: {
  view: BenchmarkView;
  models: ModelRecord[];
  providers: ProviderRecord[];
  benchmarks: BenchmarkDefinition[];
  scores: BenchmarkScore[];
  sort: MatrixSort;
  onSort: (benchmark: BenchmarkDefinition) => void;
  onOpenInfo: (benchmark: BenchmarkDefinition) => void;
  onSelectScore: (selection: Extract<DetailSelection, {kind: "score"}>) => void;
  onSelectModel: (selection: Extract<DetailSelection, {kind: "model"}>) => void;
}): ReactNode {
  const providerById = new Map(providers.map((provider) => [provider.id, provider]));
  const scoreByKey = new Map(scores.map((score) => [`${score.model_id}:${score.benchmark_id}`, score]));
  const trackBenchmarks = view === "specs" ? [] : benchmarks.filter((benchmark) => benchmark.track === view);

  return (
    <div className="model-benchmark-matrix">
      <table>
        <thead>
          <tr>
            <th scope="col">Model</th>
            {view === "specs" ? <SpecificationHeaders /> : trackBenchmarks.map((benchmark) => (
              <BenchmarkHeader
                key={benchmark.id}
                benchmark={benchmark}
                sort={sort}
                onSort={onSort}
                onOpenInfo={onOpenInfo}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {models.map((model) => {
            const provider = providerById.get(model.provider_id) ?? unknownProvider(model.provider_id);
            return (
              <tr key={model.id}>
                <th scope="row">
                  <button
                    type="button"
                    className="model-benchmark-model-button"
                    aria-label={`View details for ${model.display_name}`}
                    onClick={() => onSelectModel({kind: "model", model, provider})}
                  >
                    {model.display_name}
                  </button>
                  <span>{provider.display_name}</span>
                  <span>{formatTier(model.tier)}</span>
                  <span>{formatWeights(model.weights_status)}</span>
                  {model.pricing.bands.length > 1 && <span>Additional pricing bands available</span>}
                </th>
                {view === "specs" ? <SpecificationCells model={model} /> : trackBenchmarks.map((benchmark) => {
                  const score = scoreByKey.get(`${model.id}:${benchmark.id}`);
                  return (
                    <td key={benchmark.id}>
                      {score ? (
                        <button
                          type="button"
                          className="model-benchmark-score-button"
                          aria-label={`View ${benchmark.display_name} score for ${model.display_name}`}
                          onClick={() => onSelectScore({kind: "score", model, provider, benchmark, score})}
                        >
                          {score.value} {benchmark.unit}
                        </button>
                      ) : "Not reported"}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function BenchmarkHeader({
  benchmark,
  sort,
  onSort,
  onOpenInfo,
}: {
  benchmark: BenchmarkDefinition;
  sort: MatrixSort;
  onSort: (benchmark: BenchmarkDefinition) => void;
  onOpenInfo: (benchmark: BenchmarkDefinition) => void;
}) {
  const ariaSort = sort?.benchmarkId === benchmark.id
    ? sort.order === "asc" ? "ascending" : "descending"
    : undefined;
  const sortTitle = sort?.benchmarkId === benchmark.id
    ? `Sort by ${benchmark.display_name} (${sort.order === "asc" ? "ascending" : "descending"})`
    : `Sort by ${benchmark.display_name}`;

  return (
    <th scope="col" aria-sort={ariaSort}>
      <span>{benchmark.display_name}</span>
      <button
        type="button"
        className="model-benchmark-sort-button"
        aria-label={`Sort by ${benchmark.display_name}`}
        title={sortTitle}
        onClick={() => onSort(benchmark)}
      >
        <span aria-hidden="true">{sortIcon(sort, benchmark.id)}</span>
      </button>
      <BenchmarkInfoButton benchmark={benchmark} onOpen={onOpenInfo} />
    </th>
  );
}

function sortIcon(sort: MatrixSort, benchmarkId: string): "↕" | "↑" | "↓" {
  if (sort?.benchmarkId !== benchmarkId) return "↕";
  return sort.order === "asc" ? "↑" : "↓";
}

function SpecificationHeaders() {
  return <>
    <th scope="col">Release date</th>
    <th scope="col">Context window</th>
    <th scope="col">Input modalities</th>
    <th scope="col">Output modalities</th>
    <th scope="col">Weights</th>
    <th scope="col">Input</th>
    <th scope="col">Cached input</th>
    <th scope="col">Output</th>
  </>;
}

function SpecificationCells({model}: {model: ModelRecord}) {
  const baseBand = model.pricing.bands.find((band) => band.is_base);
  return <>
    <td>{model.release_date}</td>
    <td>{model.context_window_tokens.toLocaleString("en-US")} tokens</td>
    <td>{formatModalities(model.input_modalities)}</td>
    <td>{formatModalities(model.output_modalities)}</td>
    <td>{formatWeights(model.weights_status)}</td>
    <td>{formatTokenPrice(baseBand?.input ?? unavailablePrice(model))}</td>
    <td>{formatTokenPrice(baseBand?.cached_input ?? unavailablePrice(model))}</td>
    <td>{formatTokenPrice(baseBand?.output ?? unavailablePrice(model))}</td>
  </>;
}

function unavailablePrice(model: ModelRecord): TokenPrice {
  return {
    status: model.pricing.status,
    usd_per_million: null,
    source_amount_per_million: null,
    source_currency: null,
  };
}

function unknownProvider(providerId: string): ProviderRecord {
  return {id: providerId, display_name: "Not reported", website: ""};
}

function formatTier(tier: ModelRecord["tier"]): string {
  return tier === "mid_range" ? "Mid-range" : tier[0].toUpperCase() + tier.slice(1);
}

function formatWeights(weights: ModelRecord["weights_status"]): string {
  return weights === "open_weight" ? "Open weights" : "Closed weights";
}

function formatModalities(modalities: ModelRecord["input_modalities"]): string {
  return modalities.map((modality) => modality[0].toUpperCase() + modality.slice(1)).join(", ");
}
