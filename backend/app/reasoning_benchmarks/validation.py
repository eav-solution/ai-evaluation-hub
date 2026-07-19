"""Cross-reference validation for the reasoning benchmark catalog.

Runs at import time (see catalog.py).  A broken catalog refuses to start the
API and reports every violation at once, naming the offending ids, so editing
mistakes surface immediately instead of rendering wrong.
"""

from app.reasoning_benchmarks.types import ReasoningBenchmarkCatalog


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen and value not in result:
            result.append(value)
        seen.add(value)
    return result


def validate_catalog(catalog: ReasoningBenchmarkCatalog) -> None:
    errors: list[str] = []

    for duplicate in _duplicates([harness.id for harness in catalog.harnesses]):
        errors.append(f"duplicate harness id '{duplicate}'")
    for duplicate in _duplicates([model.id for model in catalog.models]):
        errors.append(f"duplicate model id '{duplicate}'")
    for duplicate in _duplicates([test.id for test in catalog.tests]):
        errors.append(f"duplicate test id '{duplicate}'")

    harness_ids = {harness.id for harness in catalog.harnesses}
    model_ids = {model.id for model in catalog.models}

    for test in catalog.tests:
        prefix = f"test '{test.id}'"

        for duplicate in _duplicates([criterion.id for criterion in test.criteria]):
            errors.append(f"{prefix}: duplicate criterion id '{duplicate}'")

        criteria_by_id = {criterion.id: criterion for criterion in test.criteria}

        for duplicate in _duplicates(
            [f"{entry.model_id}'@'{entry.harness_id}" for entry in test.entries]
        ):
            errors.append(f"{prefix}: duplicate entry '{duplicate}'")

        for entry in test.entries:
            entry_prefix = f"{prefix}, entry '{entry.model_id}'@'{entry.harness_id}'"
            if entry.model_id not in model_ids:
                errors.append(f"{entry_prefix}: unknown model '{entry.model_id}'")
            if entry.harness_id not in harness_ids:
                errors.append(f"{entry_prefix}: unknown harness '{entry.harness_id}'")

            for duplicate in _duplicates([score.criterion_id for score in entry.scores]):
                errors.append(f"{entry_prefix}: duplicate score for criterion '{duplicate}'")

            scored_ids = set()
            for score in entry.scores:
                criterion = criteria_by_id.get(score.criterion_id)
                if criterion is None:
                    errors.append(
                        f"{entry_prefix}: unknown criterion '{score.criterion_id}'"
                    )
                    continue
                scored_ids.add(score.criterion_id)
                if not criterion.minimum <= score.value <= criterion.maximum:
                    errors.append(
                        f"{entry_prefix}: score {score.value} for criterion "
                        f"'{score.criterion_id}' outside "
                        f"[{criterion.minimum}, {criterion.maximum}]"
                    )

            for criterion_id in criteria_by_id:
                if criterion_id not in scored_ids:
                    errors.append(
                        f"{entry_prefix}: missing score for criterion '{criterion_id}'"
                    )

    if errors:
        raise ValueError(
            "Reasoning benchmark catalog is invalid: " + "; ".join(errors)
        )
