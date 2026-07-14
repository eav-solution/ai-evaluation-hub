"use client";

import {useState} from "react";

import type {Metric} from "@/lib/types";

type SchemaProperty = {
  type?: string;
  title?: string;
  description?: string;
  minimum?: number;
  maximum?: number;
  enum?: string[];
  items?: SchemaProperty;
  anyOf?: SchemaProperty[];
};

function resolvedProperty(property: SchemaProperty): SchemaProperty {
  if (property.type) return property;
  const concrete = property.anyOf?.find((option) => option.type !== "null");
  return concrete ? {...property, ...concrete, anyOf: property.anyOf} : property;
}

function fieldLabel(name: string, property: SchemaProperty) {
  return property.title ?? name.replaceAll("_", " ").replace(/^./, (value) => value.toUpperCase());
}

export function MetricConfigForm({
  metric,
  value,
  onChange,
  onValidityChange,
}: {
  metric: Metric;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  onValidityChange: (valid: boolean) => void;
}) {
  const schema = metric.config_schema as {
    properties?: Record<string, SchemaProperty>;
  };
  const properties = schema.properties ?? {};
  const [jsonDrafts, setJsonDrafts] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(properties)
        .filter(([, property]) => resolvedProperty(property).type === "object")
        .map(([name]) => [name, JSON.stringify(value[name] ?? {}, null, 2)]),
    ),
  );
  const [jsonErrors, setJsonErrors] = useState<Record<string, boolean>>({});

  function update(name: string, next: unknown) {
    onChange({...value, [name]: next});
  }

  return (
    <div className="metric-config-form">
      {Object.entries(properties).map(([name, rawProperty]) => {
        const property = resolvedProperty(rawProperty);
        const label = fieldLabel(name, property);
        if (property.type === "boolean") {
          return (
            <label className="config-checkbox" key={name}>
              <input
                type="checkbox"
                checked={Boolean(value[name])}
                onChange={(event) => update(name, event.target.checked)}
              />
              {label}
            </label>
          );
        }
        if (property.type === "number" || property.type === "integer") {
          return (
            <label key={name}>
              {label}
              <input
                type="number"
                min={property.minimum}
                max={property.maximum}
                step={property.type === "integer" ? 1 : "any"}
                value={value[name] === undefined || value[name] === null ? "" : String(value[name])}
                onChange={(event) =>
                  update(name, event.target.value === "" ? undefined : Number(event.target.value))
                }
              />
            </label>
          );
        }
        if (property.type === "array" && property.items?.enum) {
          return (
            <label key={name}>
              {label}
              <select
                multiple
                value={(value[name] as string[] | undefined) ?? []}
                onChange={(event) =>
                  update(
                    name,
                    Array.from(event.target.selectedOptions, (option) => option.value),
                  )
                }
              >
                {property.items.enum.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          );
        }
        if (property.type === "array") {
          return (
            <label key={name}>
              {label}
              <textarea
                value={((value[name] as string[] | undefined) ?? []).join("\n")}
                onChange={(event) =>
                  update(
                    name,
                    event.target.value
                      .split("\n")
                      .map((item) => item.trim())
                      .filter(Boolean),
                  )
                }
              />
            </label>
          );
        }
        if (property.type === "object") {
          return (
            <label key={name}>
              {label} <small>Advanced JSON</small>
              <textarea
                aria-label={`${label} Advanced JSON`}
                value={jsonDrafts[name] ?? "{}"}
                onChange={(event) => {
                  const draft = event.target.value;
                  setJsonDrafts((current) => ({...current, [name]: draft}));
                  try {
                    const parsed = JSON.parse(draft);
                    const nextErrors = {...jsonErrors, [name]: false};
                    setJsonErrors(nextErrors);
                    onValidityChange(!Object.values(nextErrors).some(Boolean));
                    update(name, parsed);
                  } catch {
                    const nextErrors = {...jsonErrors, [name]: true};
                    setJsonErrors(nextErrors);
                    onValidityChange(false);
                  }
                }}
              />
              {jsonErrors[name] && <span className="config-error">Enter valid JSON.</span>}
            </label>
          );
        }
        return (
          <label key={name}>
            {label}
            <input
              value={String(value[name] ?? "")}
              onChange={(event) => update(name, event.target.value)}
            />
          </label>
        );
      })}
    </div>
  );
}
