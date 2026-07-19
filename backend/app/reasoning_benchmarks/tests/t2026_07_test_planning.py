"""Test 1 — Test-planning reasoning comparison (2026-07-18).

Five agent sessions received the identical prompt: plan full-feature testing
of the AI Evaluation Hub using the 25 oracle sample datasets.  Their planning
artifacts were scored against ground truth extracted from this repository.
Source analysis: DANH-GIA-CHI-TIET-REASONING.md (external report).
"""

from datetime import date

from app.model_benchmarks.types import ScoreDirection
from app.reasoning_benchmarks.types import (
    CriterionDefinition,
    CriterionScore,
    ReasoningTest,
    TestEntry,
)


def _criterion(id_: str, name: str, description: str) -> CriterionDefinition:
    return CriterionDefinition(
        id=id_,
        display_name=name,
        description=description,
        minimum=0,
        maximum=10,
        direction=ScoreDirection.HIGHER_IS_BETTER,
    )


_CRITERIA = (
    _criterion(
        "goal-understanding",
        "Goal understanding",
        "Inferred the intent behind the one-line prompt: the sample datasets are a scoring oracle, so metric correctness is the core mission.",
    ),
    _criterion(
        "active-investigation",
        "Active investigation",
        "Gathered evidence beyond what was handed over: read source and config, probed live services, inspected existing data.",
    ),
    _criterion(
        "factual-accuracy",
        "Factual accuracy",
        "Counts and claims match the application: 25 registered metrics, 25 sample files, exact deterministic score expectations.",
    ),
    _criterion(
        "self-consistency",
        "Self-consistency",
        "No internal contradictions between the strategy document, the execution JSON, and the plan's own numbers.",
    ),
    _criterion(
        "oracle-design",
        "Oracle design",
        "Falsifiable pass/fail rules: exact assertions for deterministic metrics, ordering-only for LLM-judged ones, an inconclusive band against false positives.",
    ),
    _criterion(
        "risk-reasoning",
        "Risk & causal reasoning",
        "Risks tied to concrete failure mechanisms and to the specific cases that would catch them.",
    ),
    _criterion(
        "constraint-planning",
        "Constraint-aware planning",
        "Accounted for real cost and latency of the judge provider: sequencing, concurrency caps, budgets, free-metric shortcuts.",
    ),
    _criterion(
        "safety-reasoning",
        "Safety & side effects",
        "Protected pre-existing data, masked secrets, namespaced artifacts, defined hard stop conditions.",
    ),
    _criterion(
        "orchestration-design",
        "Orchestration design",
        "Executable multi-agent architecture: dependencies, resource locks, isolated worker context, review routing.",
    ),
    _criterion(
        "epistemic-honesty",
        "Epistemic honesty",
        "Separated confirmed facts from inferences and assumptions; named what stayed unknown and how to handle it.",
    ),
    _criterion(
        "instructional-clarity",
        "Instructional clarity",
        "A later executor can follow the plan directly: granular steps, expected results, complete per-case packaging.",
    ),
)

_CRITERION_IDS = tuple(criterion.id for criterion in _CRITERIA)


def _entry(
    model_id: str,
    harness_id: str,
    summary: str,
    values: tuple[float, ...],
    evidence: dict[str, str],
) -> TestEntry:
    return TestEntry(
        model_id=model_id,
        harness_id=harness_id,
        summary=summary,
        scores=tuple(
            CriterionScore(
                criterion_id=criterion_id,
                value=value,
                evidence=evidence.get(criterion_id),
            )
            for criterion_id, value in zip(_CRITERION_IDS, values, strict=True)
        ),
    )


TEST = ReasoningTest(
    id="test-planning-2026-07",
    display_name="Test-planning reasoning comparison",
    category="planning",
    series_id="evalhub-test-planning",
    conducted_at=date(2026, 7, 18),
    task_summary=(
        "Five agent sessions received the identical one-line prompt: plan "
        "full-feature testing of the AI Evaluation Hub web app using the 25 "
        "oracle sample datasets (three engineered records each: all-correct, "
        "all-wrong, half). Deliverables per session: strategy document, "
        "machine-readable execution plan, execution prompt pack."
    ),
    methodology=(
        "Each criterion scored 0-10 from artifact evidence cross-checked "
        "against ground truth extracted from the application source (25-metric "
        "registry, 25 sample files). Counts, lock/dependency coverage, and "
        "sample-file references were extracted by script; prose claims were "
        "verified against the running deployment's repository."
    ),
    source_reference=(
        "/Volumes/LKT-Drive/Data/25.Test_AI-Evalution-Hub/"
        "DANH-GIA-CHI-TIET-REASONING.md"
    ),
    criteria=_CRITERIA,
    entries=(
        _entry(
            "claude-opus-4-8",
            "claude-code",
            "The empiricist - measured the live environment before asserting anything.",
            (10, 10, 10, 10, 10, 10, 10, 9.5, 9.5, 10, 10),
            {
                "active-investigation": (
                    "Probed the judge endpoint before planning: embeddings 501, "
                    "vision confirmed working, ~100 s latency, one 180 s timeout."
                ),
                "constraint-planning": (
                    "Ran the two free deterministic metrics first to validate the "
                    "pipeline before spending a single judge call; serialized all "
                    "judged cases after measuring provider latency."
                ),
                "instructional-clarity": (
                    "71 cases averaging 5.5 steps, each step with its own expected "
                    "result; plan generated by a self-asserting Python script."
                ),
            },
        ),
        _entry(
            "claude-fable-5",
            "claude-code",
            "The gatekeeper - protected pre-existing data and resisted false positives.",
            (10, 9, 8, 9, 10, 9, 8.5, 10, 10, 9.5, 9.5),
            {
                "safety-reasoning": (
                    "Read-only DB inspection found 3 real accounts and 4 workspaces; "
                    "hard rule that every artifact is namespaced and pre-existing "
                    "data is untouchable, with a dedicated global stop condition."
                ),
                "factual-accuracy": (
                    "Prose says 24 metrics while its own breakdown sums to 25; the "
                    "execution plan still covers all 25 sample files."
                ),
                "oracle-design": (
                    "Deterministic exact bands, ordering rules with inverted "
                    "direction warning, and an explicit inconclusive verdict with "
                    "one controlled rerun."
                ),
            },
        ),
        _entry(
            "codex-5-6-sol",
            "codex-cli",
            "The auditor - exact inventories, hidden-API discovery, cost governance.",
            (10, 9, 10, 10, 9, 9.5, 9.5, 9.5, 9, 9.5, 6.5),
            {
                "factual-accuracy": (
                    "Only plan naming both the exact metric count (25) and its "
                    "breakdown (15 single-turn / 3 agent-trace / 5 conversation / "
                    "2 multimodal), matching the registry 100%."
                ),
                "constraint-planning": (
                    "Only plan requiring an approved hard cost cap before any "
                    "judge-dependent execution; sample fixtures checksummed."
                ),
                "instructional-clarity": (
                    "Averages 2.0 macro-steps per case; correct but compressed, "
                    "shifting reasoning load onto the executor."
                ),
            },
        ),
        _entry(
            "qwen-27b",
            "claude-code",
            "Read the frontend source well but missed the point of the oracle datasets.",
            (3, 6.5, 4, 6, 1, 4, 2, 4, 6, 5, 5),
            {
                "oracle-design": (
                    "References 4 of 25 sample files; no expected-score assertions "
                    "anywhere - pass criteria check that UI elements exist."
                ),
                "factual-accuracy": (
                    "Claims 26 metrics (actual: 25); leaked raw tool-call syntax "
                    "into the strategy document."
                ),
                "constraint-planning": (
                    "No judge-provider plan at all: no environment variables, no "
                    "endpoint, no mock - judge-dependent runs cannot start."
                ),
            },
        ),
        _entry(
            "qwen-35b-a3b",
            "claude-code",
            "Surface-level exploration; fabricated workflows where it could not see.",
            (4, 3, 4.5, 3, 1, 5, 2, 5, 5, 6, 5),
            {
                "self-consistency": (
                    "Its JSON invents a wizard flow contradicting its own strategy "
                    "document; promises 9 test categories but delivers cases for "
                    "only 5 - authorization has zero cases."
                ),
                "active-investigation": (
                    "Mostly HTML-level observation; repeatedly notes 'unclear from "
                    "HTML alone' without opening the source that answers it."
                ),
                "oracle-design": (
                    "Uses 7 of 25 sample files; no expected-score verification."
                ),
            },
        ),
    ),
    findings=(
        "The top-3 vs bottom-2 gap is goal inference, not verbosity: three "
        "plans answered 'why do these sample datasets exist?' before writing "
        "cases; both Qwen plans never asked and drifted to UI-only testing.",
        "Active investigation separates the leaders: empirical probing "
        "(Opus), defensive data reconnaissance (Fable), and exact source "
        "inventory (Codex) are three complementary styles at the same level.",
        "Leader errors are presentation slips (a 24-vs-25 prose miscount); "
        "bottom-group errors are cognition failures (fabricated workflows, "
        "phantom UI, missing judge provisioning).",
        "Neither Qwen plan solves where the judge model comes from, so their "
        "evaluation runs cannot actually launch as planned.",
    ),
    limitations=(
        "Single task, single run per model - no repetition to separate skill "
        "from luck.",
        "Sessions may have received different scope-clarification answers "
        "(recorded category selections vary: 6/14/7/9/12).",
        "Scores judge planning artifacts only; the plans were not executed.",
        "Scoring performed by Claude Fable 5, which is also a participant; "
        "all scores are tied to verifiable artifact evidence to mitigate bias.",
    ),
)
