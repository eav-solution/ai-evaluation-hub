from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    create_model,
)

_COMMON_KEYS = {"type", "title", "description"}
_OBJECT_KEYS = _COMMON_KEYS | {"properties", "required"}
_ARRAY_KEYS = _COMMON_KEYS | {"items"}
_PRIMITIVES: dict[str, type] = {
    "string": StrictStr,
    "integer": StrictInt,
    "number": StrictFloat,
    "boolean": StrictBool,
}
_MAX_DEPTH = 20
_MAX_NODES = 1_000


def _location(path: tuple[str, ...]) -> str:
    return ".".join(path) if path else "schema"


def _check_keys(schema: dict[str, Any], allowed: set[str], path: tuple[str, ...]):
    unknown = sorted(set(schema) - allowed)
    if unknown:
        raise ValueError(
            f"Unsupported JSON Schema keyword: {_location((*path, unknown[0]))}"
        )


def _annotation(
    schema: dict[str, Any],
    *,
    path: tuple[str, ...],
    name: str,
    depth: int,
    nodes: list[int],
):
    if depth > _MAX_DEPTH:
        raise ValueError(f"{_location(path)} exceeds maximum schema depth {_MAX_DEPTH}")
    nodes[0] += 1
    if nodes[0] > _MAX_NODES:
        raise ValueError("schema exceeds maximum size of 1,000 nodes")
    if not isinstance(schema, dict):
        raise ValueError(f"{_location(path)} must be an object")
    schema_type = schema.get("type")
    if schema_type == "object":
        return _object_model(
            schema,
            path=path,
            name=name,
            depth=depth,
            nodes=nodes,
        )
    if schema_type == "array":
        _check_keys(schema, _ARRAY_KEYS, path)
        items = schema.get("items")
        if not isinstance(items, dict):
            raise ValueError(f"{_location((*path, 'items'))} must be an object")
        item_type = _annotation(
            items,
            path=(*path, "items"),
            name=f"{name}Item",
            depth=depth + 1,
            nodes=nodes,
        )
        return list[item_type]
    if schema_type in _PRIMITIVES:
        _check_keys(schema, _COMMON_KEYS, path)
        return _PRIMITIVES[schema_type]
    raise ValueError(
        f"{_location((*path, 'type'))} must be object, array, string, integer, number, or boolean"
    )


def _object_model(
    schema: dict[str, Any],
    *,
    path: tuple[str, ...],
    name: str,
    depth: int,
    nodes: list[int],
) -> type[BaseModel]:
    _check_keys(schema, _OBJECT_KEYS, path)
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict):
        raise ValueError(f"{_location((*path, 'properties'))} must be an object")
    if not isinstance(required, list) or any(
        not isinstance(item, str) for item in required
    ):
        raise ValueError(f"{_location((*path, 'required'))} must be a string array")
    unknown_required = sorted(set(required) - set(properties))
    if unknown_required:
        raise ValueError(
            f"{_location((*path, 'required'))} names unknown property {unknown_required[0]}"
        )

    fields: dict[str, tuple[Any, Any]] = {}
    for property_name, property_schema in properties.items():
        if not isinstance(property_name, str) or not property_name:
            raise ValueError(
                f"{_location((*path, 'properties'))} contains an invalid property name"
            )
        if (
            property_name.startswith("__")
            or property_name.startswith("model_")
            or hasattr(BaseModel, property_name)
        ):
            raise ValueError(
                f"{_location((*path, 'properties', property_name))} is a reserved property name"
            )
        property_path = (*path, "properties", property_name)
        annotation = _annotation(
            property_schema,
            path=property_path,
            name=f"{name}{property_name.title().replace('_', '')}",
            depth=depth + 1,
            nodes=nodes,
        )
        is_required = property_name in required
        default = ... if is_required else None
        fields[property_name] = (
            annotation,
            Field(
                default=default,
                title=property_schema.get("title"),
                description=property_schema.get("description"),
            ),
        )

    return create_model(
        name,
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def model_from_object_schema(
    schema: dict[str, Any],
    name: str = "ExpectedOutput",
) -> type[BaseModel]:
    if not isinstance(schema, dict):
        raise ValueError("schema must be an object")
    if schema.get("type") != "object":
        raise ValueError("schema.type must be object")
    return _annotation(schema, path=(), name=name, depth=0, nodes=[0])
