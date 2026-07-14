from typing import Any

from app.evals.registry import METRICS


PRESETS: dict[str, dict[str, Any]] = {
    "rag_live": {
        "id": "rag_live",
        "display_name": "RAG live",
        "description": "Core RAG quality checks that work without references.",
        "category": "rag",
        "mode_hint": "endpoint",
        "metric_keys": [
            "deepeval.answer_relevancy",
            "deepeval.faithfulness",
            "deepeval.contextual_relevancy",
        ],
    },
    "rag_offline_references": {
        "id": "rag_offline_references",
        "display_name": "RAG offline with references",
        "description": "Core RAG checks plus reference-based retrieval coverage.",
        "category": "rag",
        "mode_hint": "static",
        "metric_keys": [
            "deepeval.answer_relevancy",
            "deepeval.faithfulness",
            "deepeval.contextual_relevancy",
            "ragas.context_precision",
            "ragas.context_recall",
        ],
    },
}


_CONCEPTS = {
    "ragas.answer_relevancy": "answer_relevancy",
    "deepeval.answer_relevancy": "answer_relevancy",
    "ragas.faithfulness": "faithfulness",
    "deepeval.faithfulness": "faithfulness",
    "ragas.context_relevance": "context_relevance",
    "deepeval.contextual_relevancy": "context_relevance",
}


def _validate_presets() -> None:
    for preset in PRESETS.values():
        keys = preset["metric_keys"]
        unknown = set(keys) - set(METRICS)
        if unknown:
            raise RuntimeError(f"Preset contains unknown metric: {sorted(unknown)[0]}")
        concepts = [_CONCEPTS.get(key, key) for key in keys]
        if len(concepts) != len(set(concepts)):
            raise RuntimeError(f"Preset contains duplicate concepts: {preset['id']}")


_validate_presets()
