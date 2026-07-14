from importlib.metadata import version
from typing import Any

from app.endpoints import EndpointConfig
from app.evals.base import MetricAdapter
from app.evals.samples import NORMALIZER_REVISION
from app.models import Dataset, ProviderConnection


def _connection_snapshot(
    connection: ProviderConnection,
    model: str,
) -> dict[str, str]:
    return {
        "connection_id": connection.id,
        "connection_name": connection.name,
        "connection_type": connection.connection_type,
        "model": model,
    }


def build_definition_snapshot(
    *,
    dataset: Dataset,
    selected: list[tuple[MetricAdapter, dict[str, Any]]],
    judge_connection: ProviderConnection,
    judge_model: str,
    embedding_connection: ProviderConnection | None,
    embedding_model: str | None,
    endpoint_config: EndpointConfig | None,
) -> dict[str, Any]:
    resources: dict[str, dict[str, str]] = {
        "judge": _connection_snapshot(judge_connection, judge_model)
    }
    if embedding_connection is not None and embedding_model is not None:
        resources["embedding"] = _connection_snapshot(
            embedding_connection,
            embedding_model,
        )

    return {
        "schema_map": dict(dataset.schema_map),
        "dataset": {
            "storage_path": dataset.storage_path,
            "format": dataset.format,
        },
        "libraries": {
            "ragas": version("ragas"),
            "deepeval": version("deepeval"),
        },
        "sample": {
            "kind": selected[0][0].sample_kind,
            "normalizer_revision": NORMALIZER_REVISION,
        },
        "metrics": [
            {
                "key": adapter.key,
                "revision": adapter.revision,
                "config": config,
            }
            for adapter, config in selected
        ],
        "resources": resources,
        "endpoint": (
            {
                "method": endpoint_config.method,
                "response_jsonpath": endpoint_config.response_jsonpath,
            }
            if endpoint_config is not None
            else None
        ),
    }
