"use client";

import {useRouter} from "next/navigation";
import {FormEvent, useEffect, useMemo, useState} from "react";

import {api} from "@/lib/api";
import {missingMetricRequirements} from "@/lib/metric-requirements";
import {modelOptions} from "@/lib/model-options";
import {MetricConfigForm} from "@/components/MetricConfigForm";
import {MetricInfoButton, MetricInfoModal} from "@/components/MetricInfoModal";
import {SearchableSelect} from "@/components/SearchableSelect";
import type {Dataset, Metric, MetricPreset, ProviderConnection, Run} from "@/lib/types";

export function missingRequirements(
  metric: Metric,
  dataset?: Dataset,
  responseMappings: Record<string, string> = {},
  config: Record<string, unknown> = metric.default_config,
) {
  if (!dataset) return metric.requires;
  const fields = new Set(Object.keys(dataset.schema_map));
  if (fields.has("contexts")) {
    fields.add("retrieval_contexts");
  }
  Object.entries(responseMappings).forEach(([field, path]) => {
    if (path.trim()) fields.add(field);
  });
  return missingMetricRequirements(metric, fields, config);
}

const categoryLabels = {rag: "RAG", agentic: "Agentic", general: "General"};

function title(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function RunWizard({
  workspaceId,
  initialDatasets,
  initialMetrics,
  initialConnections,
}: {
  workspaceId: string;
  initialDatasets?: Dataset[];
  initialMetrics?: Metric[];
  initialConnections?: ProviderConnection[];
}) {
  const router = useRouter();
  const [datasets, setDatasets] = useState(initialDatasets ?? []);
  const [metrics, setMetrics] = useState(initialMetrics ?? []);
  const [datasetId, setDatasetId] = useState(initialDatasets?.[0]?.id ?? "");
  const [selected, setSelected] = useState<string[]>([]);
  const [metricConfigs, setMetricConfigs] = useState<Record<string, Record<string, unknown>>>({});
  const [configValidity, setConfigValidity] = useState<Record<string, boolean>>({});
  const [activeMetric, setActiveMetric] = useState<Metric | null>(null);
  const [presets, setPresets] = useState<MetricPreset[]>([]);
  const [activeCategory, setActiveCategory] = useState<Metric["category"]>(
    initialMetrics?.some((metric) => metric.category === "rag")
      ? "rag"
      : initialMetrics?.[0]?.category ?? "rag",
  );
  const [activeFamily, setActiveFamily] = useState("all");
  const [metricSearch, setMetricSearch] = useState("");
  const [mode, setMode] = useState<"static" | "endpoint">("static");
  const [name, setName] = useState("Evaluation run");
  const [connections, setConnections] = useState<ProviderConnection[]>(initialConnections ?? []);
  const [connectionId, setConnectionId] = useState(initialConnections?.[0]?.id ?? "");
  const [model, setModel] = useState("gpt-4.1-mini");
  const [customModels, setCustomModels] = useState<string[]>([]);
  const [modelsError, setModelsError] = useState("");
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsReload, setModelsReload] = useState(0);
  const [embeddingConnectionId, setEmbeddingConnectionId] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [embeddingModels, setEmbeddingModels] = useState<string[]>([]);
  const [embeddingModelsError, setEmbeddingModelsError] = useState("");
  const [embeddingModelsLoading, setEmbeddingModelsLoading] = useState(false);
  const [url, setUrl] = useState("");
  const [method, setMethod] = useState("POST");
  const [headers, setHeaders] = useState("{}");
  const [bodyTemplate, setBodyTemplate] = useState('{"input":"{{input}}"}');
  const [actualOutputJsonpath, setActualOutputJsonpath] = useState("$.answer");
  const [contextJsonpath, setContextJsonpath] = useState("");
  const [retrievalContextsJsonpath, setRetrievalContextsJsonpath] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!initialDatasets) {
      api<Dataset[]>(`/api/workspaces/${workspaceId}/datasets`).then((rows) => {
        setDatasets(rows);
        setDatasetId((current) => current || rows[0]?.id || "");
      }).catch((reason) => setError(String(reason)));
    }
    if (!initialMetrics) {
      api<Metric[]>("/api/metrics").then(setMetrics).catch((reason) => setError(String(reason)));
    }
    api<MetricPreset[]>("/api/metrics/presets")
      .then((rows) => setPresets(Array.isArray(rows) ? rows : []))
      .catch((reason) => setError(String(reason)));
    if (!initialConnections) {
      api<ProviderConnection[]>(`/api/workspaces/${workspaceId}/provider-connections`)
        .then((rows) => {
          setConnections(rows);
          setConnectionId((current) => current || rows[0]?.id || "");
        })
        .catch((reason) => setError(String(reason)));
    }
  }, [initialDatasets, initialMetrics, initialConnections, workspaceId]);

  const dataset = datasets.find((item) => item.id === datasetId);
  const connection = connections.find((item) => item.id === connectionId);
  const isCustom = connection?.connection_type === "openai_compatible";
  const chatModelOptions = modelOptions(connection?.connection_type, customModels);
  const needsEmbedding = selected.some((key) =>
    metrics.find((metric) => metric.key === key)?.resources.includes("embedding"),
  );
  // Embeddings need their own connection, limited to embedding-capable providers.
  const embeddingConnections = connections.filter(
    (item) => item.connection_type === "openai" || item.connection_type === "openai_compatible",
  );
  const embeddingConnection = connections.find((item) => item.id === embeddingConnectionId);
  const embeddingIsCustom = embeddingConnection?.connection_type === "openai_compatible";
  const embeddingModelOptions = modelOptions(
    embeddingConnection?.connection_type,
    embeddingModels,
    true,
  );

  // Load the live model list for a custom connection; reset for native ones.
  useEffect(() => {
    setModel("");
    setModelsError("");
    setCustomModels([]);
    setModelsLoading(false);
    if (!connection || connection.connection_type !== "openai_compatible") return;
    let cancelled = false;
    setModelsLoading(true);
    api<{models: string[]}>(
      `/api/workspaces/${workspaceId}/provider-connections/${connection.id}/models`,
    )
      .then((result) => {
        if (!cancelled) setCustomModels(result.models);
      })
      .catch((reason) => {
        if (!cancelled) setModelsError(reason instanceof Error ? reason.message : "Could not load models");
      })
      .finally(() => {
        if (!cancelled) setModelsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [connection?.id, connection?.connection_type, workspaceId, modelsReload]);

  // Load models for the (separate) embedding connection when it is custom.
  useEffect(() => {
    setEmbeddingModelsError("");
    setEmbeddingModels([]);
    setEmbeddingModelsLoading(false);
    if (!embeddingConnection || embeddingConnection.connection_type !== "openai_compatible") return;
    let cancelled = false;
    setEmbeddingModelsLoading(true);
    api<{models: string[]}>(
      `/api/workspaces/${workspaceId}/provider-connections/${embeddingConnection.id}/models`,
    )
      .then((result) => {
        if (!cancelled) setEmbeddingModels(result.models);
      })
      .catch((reason) => {
        if (!cancelled)
          setEmbeddingModelsError(reason instanceof Error ? reason.message : "Could not load models");
      })
      .finally(() => {
        if (!cancelled) setEmbeddingModelsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [embeddingConnection?.id, embeddingConnection?.connection_type, workspaceId]);

  const endpointResponseMappings = useMemo(
    () => ({
      actual_output: actualOutputJsonpath,
      context: contextJsonpath,
      retrieval_contexts: retrievalContextsJsonpath,
    }),
    [actualOutputJsonpath, contextJsonpath, retrievalContextsJsonpath],
  );
  const activeResponseMappings = mode === "endpoint" ? endpointResponseMappings : {};
  const families = useMemo(
    () =>
      Array.from(
        new Set(
          metrics
            .filter((metric) => metric.category === activeCategory)
            .map((metric) => metric.family),
        ),
      ),
    [activeCategory, metrics],
  );
  const visibleMetrics = useMemo(() => {
    const query = metricSearch.trim().toLowerCase();
    return metrics.filter(
      (metric) =>
        metric.category === activeCategory &&
        (activeFamily === "all" || metric.family === activeFamily) &&
        (!query ||
          metric.display_name.toLowerCase().includes(query) ||
          metric.key.toLowerCase().includes(query) ||
          metric.description.toLowerCase().includes(query)),
    );
  }, [activeCategory, activeFamily, metricSearch, metrics]);
  const familyGroups = useMemo(
    () => Object.groupBy(visibleMetrics, (metric) => metric.family),
    [visibleMetrics],
  );
  const duplicateDisplayNames = useMemo(() => {
    const counts = new Map<string, number>();
    metrics.forEach((metric) =>
      counts.set(metric.display_name, (counts.get(metric.display_name) ?? 0) + 1),
    );
    return new Set(
      Array.from(counts.entries())
        .filter(([, count]) => count > 1)
        .map(([name]) => name),
    );
  }, [metrics]);
  const staticReady = mode === "endpoint" || Boolean(dataset?.schema_map.actual_output);
  const selectedHaveMissingRequirements = selected.some((key) => {
    const metric = metrics.find((item) => item.key === key);
    return !metric || missingRequirements(
      metric,
      dataset,
      activeResponseMappings,
      metricConfigs[key] ?? metric.default_config,
    ).length > 0;
  });
  const selectedConfigInvalid = selected.some((key) => configValidity[key] === false);

  function toggleMetric(metric: Metric, checked: boolean) {
    setSelected((current) =>
      checked ? [...current, metric.key] : current.filter((key) => key !== metric.key),
    );
    if (checked) {
      setMetricConfigs((current) =>
        current[metric.key]
          ? current
          : {...current, [metric.key]: {...metric.default_config}},
      );
      setConfigValidity((current) => ({...current, [metric.key]: true}));
    }
  }

  function presetIsDisabled(preset: MetricPreset) {
    const presetMetrics = preset.metric_keys
      .map((key) => metrics.find((metric) => metric.key === key))
      .filter((metric): metric is Metric => Boolean(metric));
    return (
      presetMetrics.length !== preset.metric_keys.length ||
      presetMetrics.some(
        (metric) =>
          missingRequirements(
            metric,
            dataset,
            activeResponseMappings,
            metric.default_config,
          ).length > 0,
      )
    );
  }

  function applyPreset(preset: MetricPreset) {
    const nextConfigs: Record<string, Record<string, unknown>> = {};
    const nextValidity: Record<string, boolean> = {};
    preset.metric_keys.forEach((key) => {
      const metric = metrics.find((item) => item.key === key);
      if (metric) {
        nextConfigs[key] = {...metric.default_config};
        nextValidity[key] = true;
      }
    });
    setSelected([...preset.metric_keys]);
    setMetricConfigs(nextConfigs);
    setConfigValidity(nextValidity);
  }

  async function launch(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const endpoint_config = mode === "endpoint"
        ? {
            url,
            method,
            headers: JSON.parse(headers),
            body_template: JSON.parse(bodyTemplate),
            response_mappings: Object.fromEntries(
              Object.entries(endpointResponseMappings).filter(([, path]) => path.trim()),
            ),
          }
        : undefined;
      const run = await api<Run>(`/api/workspaces/${workspaceId}/runs`, {
        method: "POST",
        body: JSON.stringify({
          dataset_id: datasetId,
          name,
          mode,
          metrics: selected.map((key) => ({key, config: metricConfigs[key] ?? {}})),
          judge: {
            connection_id: connectionId,
            model,
            embedding_connection_id: needsEmbedding ? embeddingConnectionId : null,
            embedding_model: needsEmbedding ? embeddingModel : null,
          },
          endpoint_config,
        }),
      });
      router.push(`/w/${workspaceId}/runs/${run.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not launch run");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="wizard stack" onSubmit={launch}>
      <section className="panel">
        <p className="step">01 · Dataset</p>
        <label>
          Dataset
          <select value={datasetId} onChange={(event) => setDatasetId(event.target.value)} required>
            {datasets.map((item) => (
              <option value={item.id} key={item.id}>{item.name} · {item.row_count} rows</option>
            ))}
          </select>
        </label>
        {dataset && <p className="muted">Mapped: {Object.keys(dataset.schema_map).join(", ") || "nothing yet"}</p>}
      </section>

      <section className="panel">
        <p className="step">02 · Metrics</p>
        <div className="metric-picker" data-testid="metric-picker">
          <div className="metric-category-tabs" role="tablist" aria-label="Metric capability">
            {(Object.keys(categoryLabels) as Metric["category"][]).map((category) => (
              <button
                key={category}
                type="button"
                aria-pressed={activeCategory === category}
                onClick={() => {
                  setActiveCategory(category);
                  setActiveFamily("all");
                }}
              >
                {categoryLabels[category]}
              </button>
            ))}
          </div>

          {presets.some((preset) => preset.category === activeCategory) && (
            <div className="metric-presets">
              <span>Recommended</span>
              {presets
                .filter((preset) => preset.category === activeCategory)
                .map((preset) => (
                  <button
                    type="button"
                    key={preset.id}
                    title={preset.description}
                    disabled={presetIsDisabled(preset)}
                    onClick={() => applyPreset(preset)}
                  >
                    {preset.display_name}
                  </button>
                ))}
            </div>
          )}

          <div className="metric-picker-controls">
            <label>
              Search metrics
              <input
                type="search"
                value={metricSearch}
                onChange={(event) => setMetricSearch(event.target.value)}
              />
            </label>
            <div className="metric-family-filters" aria-label="Metric families">
              <button
                type="button"
                aria-pressed={activeFamily === "all"}
                onClick={() => setActiveFamily("all")}
              >
                All families
              </button>
              {families.map((family) => (
                <button
                  type="button"
                  key={family}
                  aria-pressed={activeFamily === family}
                  onClick={() => setActiveFamily(family)}
                >
                  {title(family)}
                </button>
              ))}
            </div>
          </div>

          {Object.entries(familyGroups).map(([family, familyMetrics]) => (
            <div className="metric-family" key={family}>
              <h3>{title(family)}</h3>
              {Object.entries(
                Object.groupBy(familyMetrics ?? [], (metric) => metric.framework),
              ).map(([framework, frameworkMetrics]) => (
                <fieldset key={framework}>
                  <legend>{framework}</legend>
                  <div className="metric-grid">
                    {frameworkMetrics?.map((metric) => {
                      const missing = missingRequirements(
                        metric,
                        dataset,
                        activeResponseMappings,
                        metricConfigs[metric.key] ?? metric.default_config,
                      );
                      return (
                        <div
                          className={`metric-card ${missing.length ? "disabled" : ""}`}
                          key={metric.key}
                        >
                          <label className="metric-choice">
                            <input
                              type="checkbox"
                              aria-label={
                                duplicateDisplayNames.has(metric.display_name)
                                  ? metric.key
                                  : metric.display_name
                              }
                              disabled={Boolean(missing.length)}
                              checked={selected.includes(metric.key)}
                              onChange={(event) =>
                                toggleMetric(metric, event.target.checked)
                              }
                            />
                            <span>
                              <strong>{metric.display_name}</strong>
                              <small>{metric.description}</small>
                            </span>
                            {missing.length > 0 && (
                              <em>Needs mapping: {missing.join(", ")}</em>
                            )}
                          </label>
                          <MetricInfoButton metric={metric} onOpen={setActiveMetric} />
                        </div>
                      );
                    })}
                  </div>
                </fieldset>
              ))}
            </div>
          ))}
          {!visibleMetrics.length && (
            <p className="metric-picker-empty">
              {activeCategory === "agentic"
                ? "Agentic metrics arrive in the next phase."
                : "No metrics match these filters."}
            </p>
          )}
        </div>

        {selected.length > 0 && (
          <div className="metric-configurations">
            <h3>Metric configuration</h3>
            {selected.map((key) => {
              const metric = metrics.find((item) => item.key === key);
              if (!metric) return null;
              return (
                <div className="metric-config-card" key={key}>
                  <h4>
                    {metric.display_name} <small>{metric.framework}</small>
                  </h4>
                  <MetricConfigForm
                    metric={metric}
                    value={metricConfigs[key] ?? metric.default_config}
                    onChange={(config) =>
                      setMetricConfigs((current) => ({...current, [key]: config}))
                    }
                    onValidityChange={(valid) =>
                      setConfigValidity((current) =>
                        current[key] === valid ? current : {...current, [key]: valid},
                      )
                    }
                  />
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="panel">
        <p className="step">03 · Answer source</p>
        <div className="segmented">
          <label><input type="radio" checked={mode === "static"} onChange={() => setMode("static")} /> Dataset answers</label>
          <label><input type="radio" checked={mode === "endpoint"} onChange={() => setMode("endpoint")} /> Live endpoint</label>
        </div>
        {mode === "static" && !staticReady && <p className="notice error">Map an actual_output column first.</p>}
        {mode === "endpoint" && (
          <div className="endpoint-grid">
            <label>URL<input type="url" value={url} onChange={(event) => setUrl(event.target.value)} required /></label>
            <label>Method<select value={method} onChange={(event) => setMethod(event.target.value)}><option>POST</option><option>GET</option><option>PUT</option><option>PATCH</option></select></label>
            <label className="wide">Headers (JSON)<textarea value={headers} onChange={(event) => setHeaders(event.target.value)} /></label>
            <label className="wide">Request body (JSON)<textarea value={bodyTemplate} onChange={(event) => setBodyTemplate(event.target.value)} /></label>
            <label>
              Actual output JSONPath
              <input
                value={actualOutputJsonpath}
                onChange={(event) => setActualOutputJsonpath(event.target.value)}
                required
              />
            </label>
            <label>
              Trusted context JSONPath
              <input
                value={contextJsonpath}
                onChange={(event) => setContextJsonpath(event.target.value)}
                placeholder="Optional"
              />
            </label>
            <label className="wide">
              Retrieval contexts JSONPath
              <input
                value={retrievalContextsJsonpath}
                onChange={(event) => setRetrievalContextsJsonpath(event.target.value)}
                placeholder="Optional"
              />
            </label>
          </div>
        )}
      </section>

      <section className="panel">
        <p className="step">04 · Judge and launch</p>
        <div className="form-grid">
          <label>Run name<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
          <label>
            LLM Connection
            <select value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>
              {!connections.length && <option value="">No connections — add one in Settings</option>}
              {connections.map((item) => (
                <option value={item.id} key={item.id}>{item.name}</option>
              ))}
            </select>
          </label>
          <label>
            LLM Model
            {modelsError ? (
              <span className="notice error">
                {modelsError}{" "}
                <button type="button" className="ghost" onClick={() => setModelsReload((n) => n + 1)}>Retry</button>
              </span>
            ) : (
              <SearchableSelect
                options={chatModelOptions}
                value={model}
                onChange={setModel}
                placeholder={modelsLoading ? "Loading models…" : "Select a model"}
                disabled={modelsLoading}
              />
            )}
          </label>
          {needsEmbedding && (
            <>
              <label>
                Embedding Connection
                <select
                  value={embeddingConnectionId}
                  onChange={(event) => {
                    setEmbeddingConnectionId(event.target.value);
                    setEmbeddingModel("");
                  }}
                >
                  <option value="">Select an embedding provider</option>
                  {embeddingConnections.map((item) => (
                    <option value={item.id} key={item.id}>{item.name}</option>
                  ))}
                </select>
              </label>
              <label>
                Embedding Model
                {embeddingModelsError ? (
                  <span className="notice error">{embeddingModelsError}</span>
                ) : (
                  <SearchableSelect
                    options={embeddingModelOptions}
                    value={embeddingModel}
                    onChange={setEmbeddingModel}
                    placeholder={embeddingModelsLoading ? "Loading models…" : "Select a model"}
                    disabled={!embeddingConnectionId || embeddingModelsLoading}
                  />
                )}
              </label>
            </>
          )}
        </div>
        {error && <p className="notice error">{error}</p>}
        <button
          className="primary"
          disabled={
            busy ||
            !datasetId ||
            !selected.length ||
            !staticReady ||
            selectedHaveMissingRequirements ||
            selectedConfigInvalid ||
            !connectionId ||
            !model ||
            (isCustom && Boolean(modelsError)) ||
            (needsEmbedding && (!embeddingConnectionId || !embeddingModel)) ||
            (needsEmbedding && embeddingIsCustom && Boolean(embeddingModelsError))
          }
        >
          {busy ? "Launching…" : "Launch evaluation"}
        </button>
      </section>

      <MetricInfoModal metric={activeMetric} onClose={() => setActiveMetric(null)} />
    </form>
  );
}
