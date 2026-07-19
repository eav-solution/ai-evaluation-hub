"""Curated reasoning benchmark catalog.

Like the model benchmark catalog, this is an audited static record, not a
runtime scraper.  Tests are hand-scored comparisons of model reasoning across
harness layers, updated by editing files in this package.

Adding a new test takes three steps:

1. Copy the newest module in ``tests/`` (e.g. ``t2026_07_test_planning.py``)
   to a new file, keep the ``TEST`` export, and edit its content.  Reuse model
   and harness ids from ``registry.py``; add new ones there first if needed.
   Re-running the same protocol later?  Give the new test the same
   ``series_id`` and a fresh ``id``/``conducted_at``.
2. Import the module below and append its ``TEST`` to ``tests=(...)``.
3. Reload the page.  ``validate_catalog`` runs at import and rejects broken
   edits (unknown ids, missing or out-of-range scores) with messages naming
   the exact offender; the API will not start on an invalid catalog.
"""

from datetime import date

from app.reasoning_benchmarks.registry import HARNESSES, MODELS
from app.reasoning_benchmarks.tests.t2026_07_test_planning import TEST as TEST_PLANNING_2026_07
from app.reasoning_benchmarks.types import ReasoningBenchmarkCatalog
from app.reasoning_benchmarks.validation import validate_catalog

CATALOG = ReasoningBenchmarkCatalog(
    catalog_version="2026.07.18",
    last_updated_at=date(2026, 7, 18),
    harnesses=HARNESSES,
    models=MODELS,
    tests=(TEST_PLANNING_2026_07,),
)

validate_catalog(CATALOG)
