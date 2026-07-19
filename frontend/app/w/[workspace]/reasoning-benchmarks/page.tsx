import {ReasoningBenchmarkCatalog} from "@/components/ReasoningBenchmarkCatalog";

export default function ReasoningBenchmarksPage() {
  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">Harness-level evidence</p>
          <h1>Reasoning benchmarks</h1>
          <p className="muted">Hand-scored comparisons of model reasoning across harnesses, one test at a time.</p>
        </div>
      </header>
      <ReasoningBenchmarkCatalog />
    </div>
  );
}
