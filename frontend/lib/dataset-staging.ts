export type StagedFormat = "csv" | "json" | "jsonl";

export const MAX_ROWS = 5000;

const EXTENSION_FORMATS: Record<string, StagedFormat> = {
  ".csv": "csv",
  ".json": "json",
  ".jsonl": "jsonl",
};

const SCHEMA_FIELDS = [
  "input",
  "actual_output",
  "expected_output",
  "retrieval_contexts",
  "context",
  "agent_trace",
  "tools_called",
  "expected_tools",
  "turns",
  "chatbot_role",
  "conversation_context",
  "mcp_metadata",
  "mcp_events",
] as const;

export function detectFormat(filename: string): StagedFormat | null {
  const match = /\.[^.]+$/.exec(filename.toLowerCase());
  if (!match || match.index === 0) return null;
  return EXTENSION_FORMATS[match[0]] ?? null;
}

export function isSupportedFile(filename: string): boolean {
  return detectFormat(filename) !== null;
}

export function stripExtension(filename: string): string {
  const match = /\.[^.]+$/.exec(filename);
  return match && match.index > 0 ? filename.slice(0, match.index) : filename;
}

function countCsvRows(text: string): number {
  let rows = 0;
  let inQuotes = false;
  let lineStart = 0;
  const flush = (end: number) => {
    if (text.slice(lineStart, end).trim() !== "") rows += 1;
  };
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') inQuotes = !inQuotes;
    else if (char === "\n" && !inQuotes) {
      flush(index);
      lineStart = index + 1;
    }
  }
  flush(text.length);
  return rows;
}

export function countRecords(text: string, format: StagedFormat): number {
  if (format === "json") {
    const parsed: unknown = JSON.parse(text);
    if (!Array.isArray(parsed)) throw new Error("JSON root must be an array");
    return parsed.length;
  }
  if (format === "jsonl") {
    return text.split("\n").filter((line) => line.trim() !== "").length;
  }
  return Math.max(0, countCsvRows(text) - 1);
}

export function autoMapColumns(columns: string[]): Record<string, string> {
  const mapping: Record<string, string> = {};
  for (const column of columns) {
    if ((SCHEMA_FIELDS as readonly string[]).includes(column)) {
      mapping[column] = column;
    }
  }
  if (!mapping.retrieval_contexts && columns.includes("contexts")) {
    mapping.retrieval_contexts = "contexts";
  }
  return mapping;
}
