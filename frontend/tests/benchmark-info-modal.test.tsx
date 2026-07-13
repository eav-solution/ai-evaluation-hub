import {fireEvent, render, screen, within} from "@testing-library/react";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

import {
  BenchmarkInfoButton,
  BenchmarkInfoModal,
} from "@/components/BenchmarkInfoModal";
import {
  ModelBenchmarkDetails,
  type DetailSelection,
} from "@/components/ModelBenchmarkDetails";
import {catalog} from "./model-benchmark-fixture";

const benchmark = catalog.benchmarks[0];
const model = catalog.models[0];
const provider = catalog.providers[0];
const score = catalog.scores[0];

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

afterEach(() => {
  vi.useRealTimers();
});

describe("BenchmarkInfoModal", () => {
  it("renders benchmark information in the approved order with an official source", () => {
    render(<BenchmarkInfoModal benchmark={benchmark} onClose={vi.fn()} />);

    const dialog = screen.getByRole("dialog", {name: benchmark.display_name});
    const headings = within(dialog).getAllByRole("heading").map((item) => item.textContent);
    expect(headings).toEqual([
      benchmark.display_name,
      "What it measures",
      "Dataset and edition",
      "Scoring",
      "How to read the score",
      "Standard conditions",
      "Limitations",
    ]);
    expect(within(dialog).getByText("Higher scores are better")).toBeInTheDocument();

    const source = within(dialog).getByRole("link", {name: `Official source: ${benchmark.official_source.title}`});
    expect(source).toHaveAttribute("href", benchmark.official_source.url);
    expect(source).toHaveAttribute("target", "_blank");
    expect(source).toHaveAttribute("rel", "noreferrer noopener");
  });

  it("uses a benchmark-specific trigger label", () => {
    const onOpen = vi.fn();
    render(<BenchmarkInfoButton benchmark={benchmark} onOpen={onOpen} />);

    const opener = screen.getByRole("button", {name: `About ${benchmark.display_name}`});
    fireEvent.click(opener);
    expect(onOpen).toHaveBeenCalledWith(benchmark);
  });

  it("restores focus to the opener after closing", () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    render(<BenchmarkInfoModal benchmark={benchmark} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", {name: `Close ${benchmark.display_name} benchmark information`}));
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("closes on cancel and backdrop click", () => {
    const onClose = vi.fn();
    const first = render(<BenchmarkInfoModal benchmark={benchmark} onClose={onClose} />);
    const dialog = screen.getByRole("dialog");
    fireEvent(dialog, new Event("cancel", {cancelable: true}));
    expect(onClose).toHaveBeenCalledOnce();

    first.unmount();
    render(<BenchmarkInfoModal benchmark={benchmark} onClose={onClose} />);
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe("ModelBenchmarkDetails", () => {
  it("shows complete score provenance and returns focus after close", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-13T12:00:00Z"));
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const onClose = vi.fn();
    const selection: DetailSelection = {kind: "score", model, provider, benchmark, score};

    render(<ModelBenchmarkDetails selection={selection} onClose={onClose} />);

    const panel = screen.getByRole("complementary", {name: "Benchmark details"});
    expect(screen.getByRole("heading", {name: "Benchmark details"})).toHaveFocus();
    expect(within(panel).getByText(model.display_name)).toBeInTheDocument();
    expect(within(panel).getByText(provider.display_name)).toBeInTheDocument();
    expect(within(panel).getByText(`${score.value} ${benchmark.unit}`)).toBeInTheDocument();
    expect(within(panel).getByText(score.setup[0].label)).toBeInTheDocument();
    expect(within(panel).getByText(score.setup[0].value)).toBeInTheDocument();
    expect(within(panel).getByRole("link", {name: score.source.title})).toHaveAttribute("href", score.source.url);
    expect(within(panel).getAllByText("Review needed")).toHaveLength(2);

    fireEvent.click(within(panel).getByRole("button", {name: "Close benchmark details"}));
    expect(onClose).toHaveBeenCalledOnce();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("moves focus and restores the latest trigger when the selection changes while open", () => {
    const openerA = document.createElement("button");
    const openerB = document.createElement("button");
    document.body.append(openerA, openerB);
    openerA.focus();
    const onClose = vi.fn();
    const selectionA: DetailSelection = {kind: "score", model, provider, benchmark, score};
    const selectionB: DetailSelection = {kind: "model", model: catalog.models[1], provider};
    const view = render(<ModelBenchmarkDetails selection={selectionA} onClose={onClose} />);

    expect(screen.getByRole("heading", {name: "Benchmark details"})).toHaveFocus();

    openerB.focus();
    view.rerender(<ModelBenchmarkDetails selection={selectionB} onClose={onClose} />);

    const panel = screen.getByRole("complementary", {name: "Benchmark details"});
    expect(screen.getByRole("heading", {name: "Benchmark details"})).toHaveFocus();
    fireEvent.click(within(panel).getByRole("button", {name: "Close benchmark details"}));
    expect(onClose).toHaveBeenCalledOnce();
    expect(openerB).toHaveFocus();
    openerA.remove();
    openerB.remove();
  });

  it("keeps the original trigger for a logically identical selection rerender", () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const onClose = vi.fn();
    const selectionA: DetailSelection = {kind: "score", model, provider, benchmark, score};
    const view = render(<ModelBenchmarkDetails selection={selectionA} onClose={onClose} />);

    view.rerender(
      <ModelBenchmarkDetails
        selection={{kind: "score", model, provider, benchmark, score: {...score}}}
        onClose={onClose}
      />,
    );

    fireEvent.click(screen.getByRole("button", {name: "Close benchmark details"}));
    expect(onClose).toHaveBeenCalledOnce();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("shows every pricing band and official model metadata", () => {
    const selection: DetailSelection = {kind: "model", model, provider};
    render(<ModelBenchmarkDetails selection={selection} onClose={vi.fn()} />);

    const panel = screen.getByRole("complementary", {name: "Benchmark details"});
    expect(within(panel).getAllByText(model.release_date).length).toBeGreaterThan(0);
    expect(within(panel).getByText("1,000,000 tokens")).toBeInTheDocument();
    expect(within(panel).getByText("Text, Image")).toBeInTheDocument();
    expect(within(panel).getByText("Closed weights")).toBeInTheDocument();
    expect(within(panel).getByText("Official API")).toBeInTheDocument();
    expect(within(panel).getByRole("heading", {level: 4, name: "Standard (base)"})).toBeInTheDocument();
    expect(within(panel).getByText("Standard direct API price per 1 million tokens")).toBeInTheDocument();
    expect(within(panel).getAllByText("$2.50 / 1M tokens")).toHaveLength(3);
    expect(within(panel).getAllByRole("link", {name: model.pricing.source.title})[0]).toHaveAttribute("href", model.pricing.source.url);
  });
});
