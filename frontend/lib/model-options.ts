import type {ConnectionType} from "@/lib/types";

const OPENAI_CHAT_MODELS = [
  "gpt-5",
  "gpt-5-mini",
  "gpt-5-nano",
  "gpt-4.1",
  "gpt-4.1-mini",
  "gpt-4.1-nano",
  "gpt-4o",
  "gpt-4o-mini",
  "o3",
  "o4-mini",
];

const ANTHROPIC_CHAT_MODELS = [
  "claude-opus-4-1-20250805",
  "claude-opus-4-20250514",
  "claude-sonnet-4-20250514",
  "claude-3-7-sonnet-20250219",
  "claude-3-5-haiku-20241022",
];

const OPENAI_EMBEDDING_MODELS = ["text-embedding-3-large", "text-embedding-3-small"];

export function modelOptions(
  connectionType: ConnectionType | undefined,
  customModels: string[],
  embedding = false,
) {
  if (connectionType === "openai_compatible") return customModels;
  if (embedding) return connectionType === "openai" ? OPENAI_EMBEDDING_MODELS : [];
  if (connectionType === "openai") return OPENAI_CHAT_MODELS;
  return connectionType === "anthropic" ? ANTHROPIC_CHAT_MODELS : [];
}
