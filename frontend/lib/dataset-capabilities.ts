import type {Dataset, Metric} from "@/lib/types";
import {missingMetricRequirements} from "@/lib/metric-requirements";

export type DatasetCapability = "rag" | "agentic" | "general";

function availableFields(dataset: Dataset) {
  const fields = new Set(Object.keys(dataset.schema_map));
  if (fields.has("contexts")) {
    fields.add("retrieval_contexts");
  }
  return fields;
}

export function datasetCapabilities(dataset: Dataset): DatasetCapability[] {
  const fields = availableFields(dataset);
  const capabilities: DatasetCapability[] = [];
  if (fields.has("retrieval_contexts")) capabilities.push("rag");
  if (
    fields.has("input") &&
    fields.has("actual_output") &&
    fields.has("agent_trace")
  ) {
    capabilities.push("agentic");
  }
  if (fields.has("input") && fields.has("actual_output")) capabilities.push("general");
  return capabilities;
}

export function compatibleMetricCount(dataset: Dataset, metrics: Metric[]) {
  const fields = availableFields(dataset);
  const capabilities = new Set(datasetCapabilities(dataset));
  return metrics.filter(
    (metric) =>
      (metric.sample_kind === "single_turn" ||
        (metric.sample_kind === "agent_trace" && capabilities.has("agentic"))) &&
      missingMetricRequirements(metric, fields).length === 0,
  ).length;
}
