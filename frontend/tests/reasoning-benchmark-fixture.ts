import type {ReasoningBenchmarkCatalogPayload} from "@/lib/reasoning-benchmarks";

export const catalog: ReasoningBenchmarkCatalogPayload = {
  catalog_version: "2026.07.18-test",
  last_updated_at: "2026-07-18",
  harnesses: [
    {id: "claude-code", display_name: "Claude Code", description: "Terminal agent."},
    {id: "codex-cli", display_name: "Codex CLI", description: "Terminal agent."},
  ],
  models: [
    {id: "claude-opus-4-8", display_name: "Claude Opus 4.8", developer: "Anthropic"},
    {id: "claude-fable-5", display_name: "Claude Fable 5", developer: "Anthropic"},
    {id: "codex-5-6-sol", display_name: "Codex 5.6 Sol", developer: "OpenAI"},
    {id: "qwen-27b", display_name: "Qwen 27B", developer: "Alibaba"},
  ],
  tests: [
    {
      id: "test-planning-2026-07",
      display_name: "Test-planning reasoning comparison",
      category: "planning",
      series_id: "evalhub-test-planning",
      conducted_at: "2026-07-18",
      task_summary: "Five sessions planned full-feature testing from one prompt.",
      methodology: "Scored 0-10 from artifact evidence against source ground truth.",
      source_reference: "/reports/planning.md",
      criteria: [
        {
          id: "goal-understanding",
          display_name: "Goal understanding",
          description: "Inferred oracle intent.",
          minimum: 0,
          maximum: 10,
          direction: "higher_is_better",
        },
        {
          id: "oracle-design",
          display_name: "Oracle design",
          description: "Falsifiable pass/fail rules.",
          minimum: 0,
          maximum: 10,
          direction: "higher_is_better",
        },
        {
          id: "instructional-clarity",
          display_name: "Instructional clarity",
          description: "Executor can follow directly.",
          minimum: 0,
          maximum: 10,
          direction: "higher_is_better",
        },
      ],
      entries: [
        {
          model_id: "claude-opus-4-8",
          harness_id: "claude-code",
          summary: "The empiricist.",
          scores: [
            {criterion_id: "goal-understanding", value: 10, evidence: null},
            {criterion_id: "oracle-design", value: 10, evidence: "Ordering-only assertions."},
            {criterion_id: "instructional-clarity", value: 10, evidence: null},
          ],
        },
        {
          model_id: "claude-fable-5",
          harness_id: "claude-code",
          summary: "The gatekeeper.",
          scores: [
            {criterion_id: "goal-understanding", value: 10, evidence: null},
            {criterion_id: "oracle-design", value: 10, evidence: null},
            {criterion_id: "instructional-clarity", value: 9.5, evidence: null},
          ],
        },
        {
          model_id: "qwen-27b",
          harness_id: "claude-code",
          summary: "Missed the oracle.",
          scores: [
            {criterion_id: "goal-understanding", value: 3, evidence: null},
            {criterion_id: "oracle-design", value: 1, evidence: "4 of 25 sample files."},
            {criterion_id: "instructional-clarity", value: 5, evidence: null},
          ],
        },
      ],
      findings: ["Goal inference separated the groups."],
      limitations: ["Single run per model."],
    },
    {
      id: "debugging-2026-08",
      display_name: "Debugging comparison",
      category: "debugging",
      series_id: null,
      conducted_at: "2026-08-01",
      task_summary: "Two sessions debugged an injected fault.",
      methodology: "Scored 0-10 from transcripts.",
      source_reference: "/reports/debugging.md",
      criteria: [
        {
          id: "root-cause-accuracy",
          display_name: "Root-cause accuracy",
          description: "Found the injected fault.",
          minimum: 0,
          maximum: 10,
          direction: "higher_is_better",
        },
      ],
      entries: [
        {
          model_id: "claude-opus-4-8",
          harness_id: "claude-code",
          summary: "Systematic.",
          scores: [{criterion_id: "root-cause-accuracy", value: 9, evidence: null}],
        },
        {
          model_id: "codex-5-6-sol",
          harness_id: "codex-cli",
          summary: "Fast.",
          scores: [{criterion_id: "root-cause-accuracy", value: 8, evidence: null}],
        },
      ],
      findings: [],
      limitations: [],
    },
  ],
};
