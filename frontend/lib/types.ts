export type Dataset = {
  id: string;
  name: string;
  format: string;
  row_count: number;
  storage_path: string;
  schema_map: Record<string, string>;
  preview?: Record<string, unknown>[];
};

export type ConnectionType = "openai" | "anthropic" | "openai_compatible";

export type ProviderConnection = {
  id: string;
  name: string;
  connection_type: ConnectionType;
  base_url: string | null;
  has_key: boolean;
  key_hint: string | null;
};

export type ConnectionSnapshot = {
  connection_id?: string;
  connection_name?: string;
  connection_type?: ConnectionType;
  model: string;
  embedding_connection_id?: string | null;
  embedding_connection_name?: string | null;
  embedding_connection_type?: ConnectionType | null;
  embedding_model?: string | null;
};

export type MetricExample = {
  title: string;
  inputs: {label: string; value: string}[];
  checks: {outcome: "pass" | "fail" | "neutral"; text: string}[];
  result: string;
};

export type MetricInfo = {
  meaning: string;
  score_direction: "higher_is_better" | "lower_is_better";
  calculation_steps: string[];
  formula: string;
  examples: [MetricExample, MetricExample];
  improvement_tips: {area: string; text: string}[];
  required_data: string[];
};

export type Metric = {
  key: string;
  revision: string;
  framework: string;
  category: "rag" | "agentic" | "general";
  family: string;
  display_name: string;
  description: string;
  sample_kind: "single_turn" | "agent_trace" | "conversation" | "multimodal";
  requires: string[];
  requirement_rule?: {config_field: string; exclude: string[]} | null;
  requirement_aliases?: Record<string, string[]>;
  resources: ("judge" | "embedding" | "multimodal")[];
  config_schema: Record<string, unknown>;
  default_config: Record<string, unknown>;
  recommended: boolean;
  info: MetricInfo;
};

export type MetricPreset = {
  id: string;
  display_name: string;
  description: string;
  category: "rag" | "agentic" | "general";
  mode_hint: "static" | "endpoint";
  metric_keys: string[];
};

export type Summary = {
  metric_key: string;
  mean: number;
  min: number;
  max: number;
  p50: number;
  pass_rate: number | null;
  threshold: number | null;
};

export type Run = {
  id: string;
  dataset_id: string;
  name: string;
  mode: "static" | "endpoint";
  metric_config: { metrics: { key: string; threshold?: number; rubric?: string }[] };
  judge_config: ConnectionSnapshot & { provider?: string };
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress_done: number;
  progress_total: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  summaries: Summary[];
};

export type Score = {
  score: number | null;
  reason: string | null;
  passed: boolean | null;
  error: string | null;
};

export type RunResult = {
  id: string;
  row_index: number;
  input: string;
  expected: string | null;
  actual: string | null;
  contexts: string[] | null;
  scores: Record<string, Score>;
  error: string | null;
  latency_ms: number | null;
  details: Record<string, unknown> | null;
  usage: Record<string, unknown> | null;
  estimated_cost: number | null;
};

export type DocumentFile = {
  id: string;
  filename: string;
  format: string;
  size_bytes: number;
  char_count: number;
  chunk_count: number;
  created_at: string;
};

export type GenerationJob = {
  id: string;
  name: string;
  document_ids: string[];
  mode: "chunk" | "document";
  requested_count: number;
  max_count: number;
  generator_config: ConnectionSnapshot & { provider?: string };
  options: { questions_per_chunk: number; language: string | null };
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress_done: number;
  progress_total: number;
  generated_count: number;
  error: string | null;
  unit_errors: { unit: number; error: string }[];
  dataset_id: string | null;
  dataset_created: boolean;
  created_at: string;
  finished_at: string | null;
};

export type GenerationRecord = {
  id: string;
  record_index: number;
  question: string;
  answer: string;
  contexts: string[];
  source: { document_id: string; chunk_index: number | null };
  deleted: boolean;
};

export type GenerationRecordPage = {
  records: GenerationRecord[];
  page: number;
  page_size: number;
  total: number;
};
