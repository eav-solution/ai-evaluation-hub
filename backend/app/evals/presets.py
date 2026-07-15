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
    "agentic": {
        "id": "agentic",
        "display_name": "Agentic essentials",
        "description": "Core task completion and loop checks for agent traces.",
        "category": "agentic",
        "mode_hint": "static",
        "metric_keys": [
            "deepeval.task_completion",
            "deepeval.agent_loop_detection",
        ],
    },
    "conversational": {
        "id": "conversational",
        "display_name": "Conversational quality",
        "description": "Completeness, relevancy, and role checks for conversations.",
        "category": "general",
        "mode_hint": "static",
        "metric_keys": [
            "deepeval.conversation_completeness",
            "deepeval.turn_relevancy",
            "deepeval.role_adherence",
        ],
    },
    "mcp": {
        "id": "mcp",
        "display_name": "MCP quality",
        "description": "Task completion and correct MCP use for conversations.",
        "category": "agentic",
        "mode_hint": "static",
        "metric_keys": [
            "deepeval.mcp_task_completion",
            "deepeval.mcp_use",
        ],
    },
    "multimodal": {
        "id": "multimodal",
        "display_name": "Multimodal quality",
        "description": "Coherence and helpfulness checks for generated images.",
        "category": "general",
        "mode_hint": "static",
        "metric_keys": [
            "deepeval.image_coherence",
            "deepeval.image_helpfulness",
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
