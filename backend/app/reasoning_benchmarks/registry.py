"""Shared registries reused by every reasoning test.

Models and harnesses live here — not inside individual tests — so the same
model keeps one stable id across tests and harness layers, which is what makes
cross-test and cross-harness comparison possible later.
"""

from app.reasoning_benchmarks.types import HarnessRecord, ReasoningModelRecord

HARNESSES: tuple[HarnessRecord, ...] = (
    HarnessRecord(
        id="claude-code",
        display_name="Claude Code",
        description="Anthropic's terminal coding agent with its planning skill stack.",
    ),
    HarnessRecord(
        id="codex-cli",
        display_name="Codex CLI",
        description="OpenAI's terminal coding agent running the same planning task.",
    ),
)

MODELS: tuple[ReasoningModelRecord, ...] = (
    ReasoningModelRecord(
        id="claude-opus-4-8",
        display_name="Claude Opus 4.8",
        developer="Anthropic",
    ),
    ReasoningModelRecord(
        id="claude-fable-5",
        display_name="Claude Fable 5",
        developer="Anthropic",
    ),
    ReasoningModelRecord(
        id="codex-5-6-sol",
        display_name="Codex 5.6 Sol",
        developer="OpenAI",
    ),
    ReasoningModelRecord(
        id="qwen-27b",
        display_name="Qwen 27B",
        developer="Alibaba",
    ),
    ReasoningModelRecord(
        id="qwen-35b-a3b",
        display_name="Qwen 35B-A3B",
        developer="Alibaba",
    ),
)
