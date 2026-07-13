import {ModelBenchmarkCatalog} from "@/components/ModelBenchmarkCatalog";

export default function ModelBenchmarksPage() {
  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">Provider-reported evidence</p>
          <h1>Model benchmarks</h1>
          <p className="muted">Compare one public benchmark at a time, with source and setup details.</p>
        </div>
      </header>
      <ModelBenchmarkCatalog />
    </div>
  );
}
