import {readFileSync} from "node:fs";
import {resolve} from "node:path";

import {fireEvent, render, screen, within} from "@testing-library/react";
import {beforeEach, describe, expect, it, vi} from "vitest";

import {MetricInfoModal} from "@/components/MetricInfoModal";
import type {Metric} from "@/lib/types";

const metric: Metric = {
  key: "ragas.faithfulness",
  framework: "ragas",
  display_name: "Faithfulness",
  description: "Groundedness",
  requires: ["contexts"],
  info: {
    meaning: "Claims must be supported by retrieved contexts.",
    score_direction: "higher_is_better",
    calculation_steps: ["Extract claims.", "Verify claims.", "Calculate the score."],
    formula: "Faithfulness = supported claims / total claims",
    examples: [
      {
        title: "Fully supported",
        inputs: [{label: "Answer", value: "Paris is the capital."}],
        checks: [{outcome: "pass", text: "Capital claim supported."}],
        result: "1 / 1 = 1.00",
      },
      {
        title: "Unsupported claim",
        inputs: [{label: "Answer", value: "Paris hosted the 2012 Olympics."}],
        checks: [{outcome: "fail", text: "Olympics claim unsupported."}],
        result: "0 / 1 = 0.00",
      },
    ],
    improvement_tips: [{area: "Generation", text: "Answer only from context."}],
    required_data: ["input", "actual_output", "contexts"],
  },
};

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value: vi.fn(function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    }),
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value: vi.fn(function (this: HTMLDialogElement) {
      this.removeAttribute("open");
      this.dispatchEvent(new Event("close"));
    }),
  });
});

describe("MetricInfoModal", () => {
  it("renders the approved section order, steps, formula, and two examples", () => {
    render(<MetricInfoModal metric={metric} onClose={vi.fn()} />);

    const dialog = screen.getByRole("dialog");
    const headings = within(dialog).getAllByRole("heading").map((item) => item.textContent);
    expect(headings).toEqual([
      "Faithfulness",
      "What it means",
      "How it's calculated",
      "Examples",
      "Fully supported",
      "Unsupported claim",
      "How to improve your RAG",
      "Required data",
    ]);
    expect(within(dialog).getAllByRole("listitem", {name: /Calculation step/})).toHaveLength(3);
    expect(screen.getByText(metric.info.formula)).toHaveClass("metric-info-formula");
    expect(screen.getByText("Higher scores are better")).toBeInTheDocument();
  });

  it("closes with the button and returns focus to the opener", () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const onClose = vi.fn();
    render(<MetricInfoModal metric={metric} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", {name: "Close metric information"}));

    expect(onClose).toHaveBeenCalledOnce();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("closes on cancel and backdrop click", () => {
    const onClose = vi.fn();
    const first = render(<MetricInfoModal metric={metric} onClose={onClose} />);
    const dialog = screen.getByRole("dialog");
    // jsdom cannot synthesize Escape -> cancel on a native <dialog>; the browser
    // guarantees that step, so the cancel event is the correct test entry point.
    // fireEvent has no `cancel` shortcut, so dispatch the DOM event directly.
    fireEvent(dialog, new Event("cancel", {cancelable: true}));
    expect(onClose).toHaveBeenCalledOnce();

    first.unmount();
    render(<MetricInfoModal metric={metric} onClose={onClose} />);
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("keeps the dialog viewport-bound and stacks examples on narrow screens", () => {
    // jsdom does not compute layout or media queries, so assert the stylesheet
    // source with whitespace-tolerant patterns that survive reformatting.
    // Vitest runs from the frontend root, so resolve the sheet from cwd
    // (import.meta.url is not a file:// URL under the vite transform).
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");
    expect(css).toMatch(/dialog\.metric-info-modal\s*\{[^}]*max-height:\s*90dvh/);
    expect(css).toMatch(
      /@media \(max-width:\s*620px\)[\s\S]*?\.metric-info-examples\s*\{\s*grid-template-columns:\s*1fr;?\s*\}/,
    );
  });
});
