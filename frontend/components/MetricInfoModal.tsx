"use client";

import {useEffect, useRef} from "react";

import type {Metric} from "@/lib/types";

export function MetricInfoButton({
  metric,
  onOpen,
}: {
  metric: Metric;
  onOpen: (metric: Metric) => void;
}) {
  return (
    <button
      type="button"
      className="metric-info-trigger"
      aria-label={`About ${metric.display_name}`}
      onClick={() => onOpen(metric)}
    >
      i
    </button>
  );
}

export function MetricInfoModal({
  metric,
  onClose,
}: {
  metric: Metric | null;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (metric && !dialog.open) {
      returnFocusRef.current = document.activeElement as HTMLElement | null;
      dialog.showModal();
    } else if (!metric && dialog.open) {
      dialog.close();
    }
  }, [metric]);

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
      className="metric-info-modal"
      aria-labelledby="metric-info-title"
      onClose={handleClosed}
      onCancel={(event) => {
        event.preventDefault();
        closeDialog();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) closeDialog();
      }}
    >
      {metric && (
        <article className="metric-info-content">
          <header className="metric-info-header">
            <span className="metric-info-framework">{metric.framework} metric</span>
            <h2 id="metric-info-title">{metric.display_name}</h2>
            <span className="metric-info-direction">
              {metric.info.score_direction === "higher_is_better"
                ? "Higher scores are better"
                : "Lower scores are better"}
            </span>
            <button
              type="button"
              className="metric-info-close"
              aria-label="Close metric information"
              onClick={closeDialog}
            >
              ×
            </button>
          </header>
          <div className="metric-info-body">
            <section className="metric-info-section">
              <h3>What it means</h3>
              <p>{metric.info.meaning}</p>
            </section>
            <section className="metric-info-section">
              <h3>How it's calculated</h3>
              <ol className="metric-info-calculation">
                {metric.info.calculation_steps.map((step, index) => (
                  <li
                    className="metric-info-calculation-step"
                    aria-label={`Calculation step ${index + 1}`}
                    key={step}
                  >
                    <span>{index + 1}</span><p>{step}</p>
                  </li>
                ))}
              </ol>
              <div className="metric-info-formula">
                <small>Formula</small>{metric.info.formula}
              </div>
            </section>
            <section className="metric-info-section">
              <h3>Examples</h3>
              <div className="metric-info-examples">
                {metric.info.examples.map((example) => (
                  <article className="metric-info-example" key={example.title}>
                    <h4>{example.title}</h4>
                    {example.inputs.map((input) => (
                      <p key={input.label}><strong>{input.label}:</strong> {input.value}</p>
                    ))}
                    <ul>
                      {example.checks.map((check) => (
                        <li key={check.text}>
                          <span aria-hidden="true">
                            {check.outcome === "pass" ? "✓" : check.outcome === "fail" ? "×" : "•"}
                          </span>
                          <span className="sr-only">{check.outcome}: </span>{check.text}
                        </li>
                      ))}
                    </ul>
                    <strong className="metric-info-example-result">{example.result}</strong>
                  </article>
                ))}
              </div>
            </section>
            <section className="metric-info-section">
              <h3>{metric.category === "rag" ? "How to improve your RAG" : "How to improve"}</h3>
              <ul className="metric-info-tips">
                {metric.info.improvement_tips.map((tip) => (
                  <li key={`${tip.area}:${tip.text}`}><strong>{tip.area}</strong><span>{tip.text}</span></li>
                ))}
              </ul>
            </section>
            <section className="metric-info-section">
              <h3>Required data</h3>
              <div className="metric-info-required">
                {metric.info.required_data.map((field) => <code key={field}>{field}</code>)}
              </div>
            </section>
          </div>
        </article>
      )}
    </dialog>
  );
}
