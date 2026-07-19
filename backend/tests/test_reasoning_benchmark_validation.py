from datetime import date

import pytest


def _catalog(**overrides):
    from app.model_benchmarks.types import ScoreDirection
    from app.reasoning_benchmarks.types import (
        CriterionDefinition,
        CriterionScore,
        HarnessRecord,
        ReasoningBenchmarkCatalog,
        ReasoningModelRecord,
        ReasoningTest,
        TestEntry,
    )

    criteria = overrides.pop(
        "criteria",
        (
            CriterionDefinition(
                id="c1",
                display_name="C1",
                description="d",
                minimum=0,
                maximum=10,
                direction=ScoreDirection.HIGHER_IS_BETTER,
            ),
        ),
    )
    entries = overrides.pop(
        "entries",
        (
            TestEntry(
                model_id="m1",
                harness_id="h1",
                summary="s",
                scores=(CriterionScore(criterion_id="c1", value=5),),
            ),
        ),
    )
    tests = overrides.pop(
        "tests",
        (
            ReasoningTest(
                id="t1",
                display_name="T1",
                category="planning",
                series_id=None,
                conducted_at=date(2026, 7, 18),
                task_summary="task",
                methodology="method",
                source_reference="ref",
                criteria=criteria,
                entries=entries,
                findings=("f",),
                limitations=("l",),
            ),
        ),
    )
    payload = {
        "catalog_version": "test",
        "last_updated_at": date(2026, 7, 18),
        "harnesses": (
            HarnessRecord(id="h1", display_name="H1", description="d"),
        ),
        "models": (
            ReasoningModelRecord(id="m1", display_name="M1", developer="Dev"),
        ),
        "tests": tests,
    }
    payload.update(overrides)
    return ReasoningBenchmarkCatalog(**payload)


def _score(criterion_id="c1", value=5.0):
    from app.reasoning_benchmarks.types import CriterionScore

    return CriterionScore(criterion_id=criterion_id, value=value)


def _entry(model_id="m1", harness_id="h1", scores=None):
    from app.reasoning_benchmarks.types import TestEntry

    return TestEntry(
        model_id=model_id,
        harness_id=harness_id,
        summary="s",
        scores=scores or (_score(),),
    )


def test_minimal_catalog_passes():
    from app.reasoning_benchmarks.validation import validate_catalog

    validate_catalog(_catalog())


def test_seeded_catalog_passes():
    from app.reasoning_benchmarks.catalog import CATALOG
    from app.reasoning_benchmarks.validation import validate_catalog

    validate_catalog(CATALOG)
    assert len(CATALOG.harnesses) == 2
    assert len(CATALOG.models) == 5
    planning = CATALOG.tests[0]
    assert planning.id == "test-planning-2026-07"
    assert len(planning.criteria) == 11
    assert len(planning.entries) == 5
    assert all(len(entry.scores) == 11 for entry in planning.entries)


def test_duplicate_model_id_is_named():
    from app.reasoning_benchmarks.types import ReasoningModelRecord
    from app.reasoning_benchmarks.validation import validate_catalog

    catalog = _catalog(
        models=(
            ReasoningModelRecord(id="m1", display_name="M1", developer="Dev"),
            ReasoningModelRecord(id="m1", display_name="M1 again", developer="Dev"),
        ),
    )
    with pytest.raises(ValueError, match="duplicate model id 'm1'"):
        validate_catalog(catalog)


def test_entry_with_unknown_model_is_named():
    from app.reasoning_benchmarks.validation import validate_catalog

    catalog = _catalog(entries=(_entry(model_id="ghost"),))
    with pytest.raises(ValueError, match="unknown model 'ghost'"):
        validate_catalog(catalog)


def test_entry_with_unknown_harness_is_named():
    from app.reasoning_benchmarks.validation import validate_catalog

    catalog = _catalog(entries=(_entry(harness_id="ghost"),))
    with pytest.raises(ValueError, match="unknown harness 'ghost'"):
        validate_catalog(catalog)


def test_duplicate_model_harness_entry_is_named():
    from app.reasoning_benchmarks.validation import validate_catalog

    catalog = _catalog(entries=(_entry(), _entry()))
    with pytest.raises(ValueError, match="duplicate entry 'm1'@'h1'"):
        validate_catalog(catalog)


def test_score_for_unknown_criterion_is_named():
    from app.reasoning_benchmarks.validation import validate_catalog

    catalog = _catalog(
        entries=(_entry(scores=(_score(), _score(criterion_id="ghost"))),),
    )
    with pytest.raises(ValueError, match="unknown criterion 'ghost'"):
        validate_catalog(catalog)


def test_missing_score_for_criterion_is_named():
    from app.model_benchmarks.types import ScoreDirection
    from app.reasoning_benchmarks.types import CriterionDefinition
    from app.reasoning_benchmarks.validation import validate_catalog

    catalog = _catalog(
        criteria=(
            CriterionDefinition(
                id="c1",
                display_name="C1",
                description="d",
                minimum=0,
                maximum=10,
                direction=ScoreDirection.HIGHER_IS_BETTER,
            ),
            CriterionDefinition(
                id="c2",
                display_name="C2",
                description="d",
                minimum=0,
                maximum=10,
                direction=ScoreDirection.HIGHER_IS_BETTER,
            ),
        ),
    )
    with pytest.raises(ValueError, match="missing score for criterion 'c2'"):
        validate_catalog(catalog)


def test_duplicate_score_for_criterion_is_named():
    from app.reasoning_benchmarks.validation import validate_catalog

    catalog = _catalog(entries=(_entry(scores=(_score(), _score())),))
    with pytest.raises(ValueError, match="duplicate score for criterion 'c1'"):
        validate_catalog(catalog)


def test_score_outside_bounds_is_named():
    from app.reasoning_benchmarks.validation import validate_catalog

    catalog = _catalog(entries=(_entry(scores=(_score(value=11.0),)),))
    with pytest.raises(ValueError, match="outside \\[0.0, 10.0\\]"):
        validate_catalog(catalog)


def test_all_violations_are_reported_together():
    from app.reasoning_benchmarks.validation import validate_catalog

    catalog = _catalog(
        entries=(
            _entry(model_id="ghost", scores=(_score(value=11.0),)),
        ),
    )
    with pytest.raises(ValueError) as excinfo:
        validate_catalog(catalog)
    message = str(excinfo.value)
    assert "unknown model 'ghost'" in message
    assert "outside [0.0, 10.0]" in message
