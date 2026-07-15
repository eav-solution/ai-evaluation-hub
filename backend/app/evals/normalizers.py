import json
from typing import Any

from app.evals.base import SampleKind
from app.evals.samples import (
    AgentTraceSample,
    EvaluationSample,
    SampleSource,
    SingleTurnSample,
)


_MISSING = object()
_AGENT_STRUCTURED_FIELDS = ("agent_trace", "tools_called", "expected_tools")


def _mapped_value(
    source: dict[str, Any],
    schema_map: dict[str, str],
    field: str,
    overrides: dict[str, Any],
):
    if field in overrides:
        return overrides[field]
    column = schema_map.get(field)
    if column is None:
        return _MISSING
    return source.get(column, _MISSING)


def _structured_value(value: Any, field: str, column: str) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid {field} in column '{column}': expected valid JSON") from exc


def _contexts(value: Any) -> list[str] | None:
    if value is _MISSING or value is None:
        return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        value = parsed
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _sample_source(source_ref: SampleSource | dict[str, Any] | None) -> SampleSource | None:
    if source_ref is None or isinstance(source_ref, SampleSource):
        return source_ref
    return SampleSource.model_validate(source_ref)


def normalize_sample(
    sample_kind: SampleKind,
    source: dict[str, Any],
    schema_map: dict[str, str],
    overrides: dict[str, Any] | None = None,
    source_ref: SampleSource | dict[str, Any] | None = None,
) -> EvaluationSample:
    response_fields = overrides or {}
    input_value = _mapped_value(source, schema_map, "input", response_fields)
    actual_output = _mapped_value(source, schema_map, "actual_output", response_fields)
    if input_value is _MISSING or input_value is None:
        raise ValueError("Mapped input value is missing")
    if actual_output is _MISSING or actual_output is None:
        raise ValueError("Mapped actual_output value is missing")

    common = {
        "input": str(input_value),
        "actual_output": str(actual_output),
        "source": _sample_source(source_ref),
    }
    if sample_kind == "single_turn":
        expected_output = _mapped_value(
            source, schema_map, "expected_output", response_fields
        )
        return SingleTurnSample(
            **common,
            expected_output=(
                None
                if expected_output is _MISSING or expected_output is None
                else str(expected_output)
            ),
            context=_contexts(
                _mapped_value(source, schema_map, "context", response_fields)
            ),
            retrieval_contexts=_contexts(
                _mapped_value(
                    source,
                    schema_map,
                    "retrieval_contexts",
                    response_fields,
                )
            ),
        )

    if sample_kind == "agent_trace":
        structured: dict[str, Any] = {}
        for field in _AGENT_STRUCTURED_FIELDS:
            value = _mapped_value(source, schema_map, field, response_fields)
            if value is _MISSING or value is None:
                if field == "agent_trace":
                    raise ValueError("Mapped agent_trace value is missing")
                structured[field] = []
                continue
            column = schema_map.get(field, field)
            structured[field] = _structured_value(value, field, column)
        metadata = _mapped_value(source, schema_map, "metadata", response_fields)
        tags = _mapped_value(source, schema_map, "tags", response_fields)
        return AgentTraceSample(
            **common,
            **structured,
            metadata={} if metadata is _MISSING or metadata is None else metadata,
            tags=[] if tags is _MISSING or tags is None else tags,
        )

    raise ValueError(f"Sample kind '{sample_kind}' is not supported by this normalizer")
