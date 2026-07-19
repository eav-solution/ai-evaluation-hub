from datetime import date

import pytest
from pydantic import ValidationError


def test_records_are_frozen_and_reject_unknown_fields():
    from app.reasoning_benchmarks.types import HarnessRecord

    record = HarnessRecord(
        id="claude-code",
        display_name="Claude Code",
        description="Anthropic's CLI coding agent harness.",
    )
    with pytest.raises(ValidationError):
        record.id = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        HarnessRecord(id="x", display_name="X", description="d", extra_field="nope")


def test_registries_expose_seed_harnesses_and_models():
    from app.reasoning_benchmarks.registry import HARNESSES, MODELS

    assert {harness.id for harness in HARNESSES} == {"claude-code", "codex-cli"}
    assert {model.id for model in MODELS} == {
        "claude-opus-4-8",
        "claude-fable-5",
        "qwen-27b",
        "qwen-35b-a3b",
        "codex-5-6-sol",
    }
    assert all(model.display_name for model in MODELS)
    assert all(model.developer for model in MODELS)


def test_criterion_and_score_shapes():
    from app.model_benchmarks.types import ScoreDirection
    from app.reasoning_benchmarks.types import CriterionDefinition, CriterionScore

    criterion = CriterionDefinition(
        id="goal-understanding",
        display_name="Goal understanding",
        description="Did the model infer the intent behind the request?",
        minimum=0,
        maximum=10,
        direction=ScoreDirection.HIGHER_IS_BETTER,
    )
    assert criterion.maximum == 10

    scored = CriterionScore(criterion_id="goal-understanding", value=9.5)
    assert scored.evidence is None


def test_reasoning_test_requires_nonempty_criteria_and_entries():
    from app.model_benchmarks.types import ScoreDirection
    from app.reasoning_benchmarks.types import (
        CriterionDefinition,
        CriterionScore,
        ReasoningTest,
        TestEntry,
    )

    criterion = CriterionDefinition(
        id="c1",
        display_name="C1",
        description="d",
        minimum=0,
        maximum=10,
        direction=ScoreDirection.HIGHER_IS_BETTER,
    )
    entry = TestEntry(
        model_id="claude-opus-4-8",
        harness_id="claude-code",
        summary="s",
        scores=(CriterionScore(criterion_id="c1", value=10),),
    )
    test = ReasoningTest(
        id="t1",
        display_name="T1",
        category="planning",
        series_id=None,
        conducted_at=date(2026, 7, 18),
        task_summary="task",
        methodology="method",
        source_reference="ref",
        criteria=(criterion,),
        entries=(entry,),
        findings=("f",),
        limitations=("l",),
    )
    assert test.entries[0].scores[0].value == 10

    with pytest.raises(ValidationError):
        ReasoningTest(
            id="t2",
            display_name="T2",
            category="planning",
            series_id=None,
            conducted_at=date(2026, 7, 18),
            task_summary="task",
            methodology="method",
            source_reference="ref",
            criteria=(),
            entries=(entry,),
            findings=("f",),
            limitations=("l",),
        )
