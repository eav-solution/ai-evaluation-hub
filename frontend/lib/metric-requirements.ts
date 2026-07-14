import type {Metric} from "@/lib/types";

export function metricRequirements(
  metric: Metric,
  config: Record<string, unknown> = metric.default_config,
) {
  const rule = metric.requirement_rule;
  const configured = rule ? config[rule.config_field] : undefined;
  if (rule && Array.isArray(configured)) {
    return configured.filter(
      (field): field is string =>
        typeof field === "string" && !rule.exclude.includes(field),
    );
  }
  return metric.requires;
}

export function missingMetricRequirements(
  metric: Metric,
  availableFields: Set<string>,
  config: Record<string, unknown> = metric.default_config,
) {
  const aliases = metric.requirement_aliases ?? {};
  return metricRequirements(metric, config).filter(
    (field) =>
      !availableFields.has(field) &&
      !(aliases[field] ?? []).some((alias) => availableFields.has(alias)),
  );
}
