"use client";

import {useEffect, useRef} from "react";
import type {ReactNode} from "react";

import {
  formatTokenPrice,
  isReviewNeeded,
  type BenchmarkDefinition,
  type BenchmarkScore,
  type ModelRecord,
  type ProviderRecord,
  type SourceReference,
  type TokenPrice,
} from "@/lib/model-benchmarks";

export type DetailSelection =
  | {
    kind: "score";
    model: ModelRecord;
    provider: ProviderRecord;
    benchmark: BenchmarkDefinition;
    score: BenchmarkScore;
  }
  | {kind: "model"; model: ModelRecord; provider: ProviderRecord};

export function ModelBenchmarkDetails({
  selection,
  onClose,
}: {
  selection: DetailSelection | null;
  onClose: () => void;
}): ReactNode {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const isOpenRef = useRef(false);
  const selectionKey = selection ? getSelectionKey(selection) : null;

  useEffect(() => {
    if (selectionKey !== null) {
      isOpenRef.current = true;
      returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      headingRef.current?.focus();
      return;
    }

    if (isOpenRef.current) {
      isOpenRef.current = false;
      returnFocusRef.current?.focus();
    }
  }, [selectionKey]);

  function closeDetails() {
    onClose();
    if (isOpenRef.current) {
      isOpenRef.current = false;
      returnFocusRef.current?.focus();
    }
  }

  if (!selection) return null;

  return (
    <aside className="model-benchmark-details" aria-labelledby="benchmark-details-title" tabIndex={-1}>
      <header className="model-benchmark-details-header">
        <h2 id="benchmark-details-title" ref={headingRef} tabIndex={-1}>Benchmark details</h2>
        <button type="button" className="benchmark-details-close" onClick={closeDetails} aria-label="Close benchmark details">
          Close
        </button>
      </header>
      {selection.kind === "score" ? <ScoreDetails selection={selection} /> : <ModelDetails selection={selection} />}
    </aside>
  );
}

function getSelectionKey(selection: DetailSelection): string {
  if (selection.kind === "model") return `model:${selection.model.id}`;
  return `score:${selection.model.id}:${selection.benchmark.id}`;
}

function ScoreDetails({selection}: {selection: Extract<DetailSelection, {kind: "score"}>}) {
  const {benchmark, model, provider, score} = selection;
  return (
    <div className="benchmark-detail-sections">
      <DetailSection heading="Score result">
        <DetailList rows={[
          ["Model", model.display_name],
          ["Provider", provider.display_name],
          ["Benchmark", benchmark.display_name],
          ["Dataset and edition", benchmark.dataset_edition],
          ["Setup variant", benchmark.setup_variant],
          ["Score", `${score.value} ${benchmark.unit}`],
          ["Model verified", <VerifiedDate date={model.verified_at} />],
        ]} />
      </DetailSection>
      <DetailSection heading="Disclosed setup">
        {score.setup.length === 0 ? <p>Not reported</p> : <DetailList rows={score.setup.map(({label, value}) => [label, value])} />}
      </DetailSection>
      <SourceDetails heading="Source provenance" source={score.source} />
    </div>
  );
}

function ModelDetails({selection}: {selection: Extract<DetailSelection, {kind: "model"}>}) {
  const {model, provider} = selection;
  const conversionDetails = model.pricing.bands.flatMap((band) => [
    [band.label, "Input", band.input],
    [band.label, "Cached input", band.cached_input],
    [band.label, "Output", band.output],
  ] as const).filter(([, , price]) => price.source_amount_per_million !== null && price.source_currency !== null);

  return (
    <div className="benchmark-detail-sections">
      <DetailSection heading="Model specification">
        <DetailList rows={[
          ["Model", model.display_name],
          ["Provider", provider.display_name],
          ["Tier", `${formatTier(model.tier)} — ${model.tier_reason}`],
          ["Release date", model.release_date],
          ["Context window", `${model.context_window_tokens.toLocaleString("en-US")} tokens`],
          ["Input modalities", formatModalities(model.input_modalities)],
          ["Output modalities", formatModalities(model.output_modalities)],
          ["Weights", formatWeights(model.weights_status)],
          ["Availability", formatAvailability(model.availability)],
          ["Model verified", <VerifiedDate date={model.verified_at} />],
        ]} />
      </DetailSection>
      <SourceDetails heading="Specification source" source={model.specification_source} />
      <DetailSection heading="Pricing">
        <p><strong>Pricing status:</strong> {formatPricingStatus(model.pricing.status)}</p>
        {model.pricing.bands.length === 0 ? <p>{formatPricingStatus(model.pricing.status)}</p> : model.pricing.bands.map((band) => (
          <section className="benchmark-pricing-band" key={band.band_id}>
            <h4>{band.label}{band.is_base ? " (base)" : ""}</h4>
            <p>{band.condition}</p>
            <DetailList rows={[
              ["Input", <PriceValue price={band.input} />],
              ["Cached input", <PriceValue price={band.cached_input} />],
              ["Output", <PriceValue price={band.output} />],
            ]} />
          </section>
        ))}
      </DetailSection>
      <SourceDetails heading="Official pricing source" source={model.pricing.source} />
      {(conversionDetails.length > 0 || model.pricing.exchange_rate_source) && (
        <DetailSection heading="Conversion details">
          {conversionDetails.length > 0 && <DetailList rows={conversionDetails.map(([bandLabel, priceLabel, price]) => [
            `${bandLabel} ${priceLabel}`,
            `${price.source_amount_per_million} ${price.source_currency} / 1M tokens`,
          ])} />}
          {model.pricing.exchange_rate_source && <SourceDetails heading="Exchange-rate source" source={model.pricing.exchange_rate_source} />}
        </DetailSection>
      )}
      {model.pricing.note && <DetailSection heading="Notes"><p>{model.pricing.note}</p></DetailSection>}
    </div>
  );
}

function DetailSection({heading, children}: {heading: string; children: ReactNode}) {
  return <section className="benchmark-detail-section"><h3>{heading}</h3>{children}</section>;
}

function DetailList({rows}: {rows: Array<[string, ReactNode]>}) {
  return (
    <dl className="benchmark-detail-list">
      {rows.map(([label, value], index) => (
        <div key={`${label}-${index}`}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function SourceDetails({heading, source}: {heading: string; source: SourceReference}) {
  return (
    <DetailSection heading={heading}>
      <DetailList rows={[
        ["Source", <ExternalSourceLink source={source} />],
        ["Publisher", source.publisher],
        ...(source.published_at ? [["Published", source.published_at] as [string, ReactNode]] : []),
        ["Verified", <VerifiedDate date={source.verified_at} />],
      ]} />
    </DetailSection>
  );
}

function ExternalSourceLink({source}: {source: SourceReference}) {
  return <a href={source.url} target="_blank" rel="noreferrer noopener">{source.title}</a>;
}

function VerifiedDate({date}: {date: string}) {
  return <>{date}{isReviewNeeded(date) && <span className="benchmark-review-needed">Review needed</span>}</>;
}

function PriceValue({price}: {price: TokenPrice}) {
  return <>{formatTokenPrice(price)} <span className="sr-only">({formatPricingStatus(price.status)})</span></>;
}

function formatTier(tier: ModelRecord["tier"]): string {
  return tier === "mid_range" ? "Mid-range" : tier[0].toUpperCase() + tier.slice(1);
}

function formatModalities(modalities: ModelRecord["input_modalities"]): string {
  return modalities.map((modality) => modality[0].toUpperCase() + modality.slice(1)).join(", ");
}

function formatWeights(weights: ModelRecord["weights_status"]): string {
  return weights === "open_weight" ? "Open weights" : "Closed weights";
}

function formatAvailability(availability: ModelRecord["availability"]): string {
  if (availability === "official_api") return "Official API";
  if (availability === "official_weights") return "Official weights";
  return "Official API and weights";
}

function formatPricingStatus(status: TokenPrice["status"]): string {
  if (status === "not_applicable") return "Not applicable";
  if (status === "not_reported") return "Not reported";
  return "Reported";
}
