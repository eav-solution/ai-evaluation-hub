"use client";

import {useEffect, useRef} from "react";
import type {ReactNode} from "react";

import type {BenchmarkDefinition, SourceReference} from "@/lib/model-benchmarks";

export function BenchmarkInfoButton({
  benchmark,
  onOpen,
}: {
  benchmark: BenchmarkDefinition;
  onOpen: (benchmark: BenchmarkDefinition) => void;
}): ReactNode {
  return (
    <button
      type="button"
      className="benchmark-info-trigger"
      aria-label={`About ${benchmark.display_name}`}
      onClick={() => onOpen(benchmark)}
    >
      i
    </button>
  );
}

export function BenchmarkInfoModal({
  benchmark,
  onClose,
}: {
  benchmark: BenchmarkDefinition | null;
  onClose: () => void;
}): ReactNode {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (benchmark && !dialog.open) {
      returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      dialog.showModal();
    } else if (!benchmark && dialog.open) {
      dialog.close();
    }
  }, [benchmark]);

  function closeDialog() {
    dialogRef.current?.close();
  }

  function handleClosed() {
    onClose();
    returnFocusRef.current?.focus();
  }

  return (
    <dialog
      ref={dialogRef}
      className="benchmark-info-modal"
      aria-labelledby="benchmark-info-title"
      onClose={handleClosed}
      onCancel={(event) => {
        event.preventDefault();
        closeDialog();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) closeDialog();
      }}
    >
      {benchmark && (
        <article className="benchmark-info-content">
          <header className="benchmark-info-header">
            <span className="benchmark-info-track">{formatTrack(benchmark.track)}</span>
            <h2 id="benchmark-info-title">{benchmark.display_name}</h2>
            <span className="benchmark-info-direction">{formatDirection(benchmark.direction)}</span>
            <button
              type="button"
              className="benchmark-info-close"
              aria-label={`Close ${benchmark.display_name} benchmark information`}
              onClick={closeDialog}
            >
              ×
            </button>
          </header>
          <div className="benchmark-info-body">
            <InfoSection heading="What it measures"><p>{benchmark.info.meaning}</p></InfoSection>
            <InfoSection heading="Dataset and edition">
              <p>{benchmark.info.dataset_and_edition}</p>
              <p><strong>Edition:</strong> {benchmark.dataset_edition}</p>
            </InfoSection>
            <InfoSection heading="Scoring">
              <p>{benchmark.info.scoring_method}</p>
              <p><strong>Range:</strong> {benchmark.minimum}–{benchmark.maximum} {benchmark.unit}</p>
            </InfoSection>
            <InfoSection heading="How to read the score"><p>{benchmark.info.interpretation}</p></InfoSection>
            <InfoSection heading="Standard conditions"><InfoList items={benchmark.info.standard_conditions} /></InfoSection>
            <InfoSection heading="Limitations"><InfoList items={benchmark.info.limitations} /></InfoSection>
            <p className="benchmark-info-source">
              <ExternalSourceLink source={benchmark.official_source} labelPrefix="Official source: " />
            </p>
          </div>
        </article>
      )}
    </dialog>
  );
}

function InfoSection({heading, children}: {heading: string; children: ReactNode}) {
  return (
    <section className="benchmark-info-section">
      <h3>{heading}</h3>
      {children}
    </section>
  );
}

function InfoList({items}: {items: string[]}) {
  if (items.length === 0) return <p>Not reported</p>;
  return <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>;
}

function ExternalSourceLink({source, labelPrefix = ""}: {source: SourceReference; labelPrefix?: string}) {
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noreferrer noopener"
    >
      {labelPrefix}{source.title}
    </a>
  );
}

function formatDirection(direction: BenchmarkDefinition["direction"]): string {
  return direction === "higher_is_better" ? "Higher scores are better" : "Lower scores are better";
}

function formatTrack(track: BenchmarkDefinition["track"]): string {
  return track === "text_code" ? "Text & Code benchmark" : "Multimodal benchmark";
}
