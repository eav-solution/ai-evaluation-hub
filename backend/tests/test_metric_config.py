import pytest
from pydantic import ValidationError


def test_object_schema_builds_nested_pydantic_model():
    from app.evals.json_schema import model_from_object_schema

    model = model_from_object_schema(
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "profile": {
                    "type": "object",
                    "properties": {"active": {"type": "boolean"}},
                    "required": ["active"],
                },
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
            },
            "required": ["name", "profile"],
        }
    )

    value = model.model_validate(
        {"name": "x", "profile": {"active": True}, "items": [1]}
    )
    assert value.name == "x"
    assert value.profile.active is True
    assert value.items == [1]
    with pytest.raises(ValidationError):
        model.model_validate({"profile": {"active": True}, "items": ["bad"]})
    with pytest.raises(ValidationError):
        model.model_validate({"name": 42, "profile": {"active": 1}})
    with pytest.raises(ValidationError):
        model.model_validate({"name": "x", "profile": {"active": True}, "items": ["1"]})
    with pytest.raises(ValidationError):
        model.model_validate(
            {
                "name": "x",
                "profile": {"active": True},
                "items": None,
            }
        )


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        ({"type": "object", "oneOf": []}, "oneOf"),
        (
            {
                "type": "object",
                "properties": {"value": {"type": "string", "$ref": "#/x"}},
            },
            r"properties\.value\.\$ref",
        ),
        (
            {
                "type": "object",
                "properties": {},
                "required": ["missing"],
            },
            "required",
        ),
    ],
)
def test_object_schema_rejects_unsupported_or_invalid_shapes(schema, message):
    from app.evals.json_schema import model_from_object_schema

    with pytest.raises(ValueError, match=message):
        model_from_object_schema(schema)


def test_metric_specific_config_defaults_and_dynamic_requirements():
    from app.evals.base import JsonCorrectnessConfig, PromptAlignmentConfig
    from app.evals.registry import METRICS

    prompt = PromptAlignmentConfig.model_validate({})
    assert prompt.prompt_instructions == ["Follow the instructions in the user input."]
    with pytest.raises(ValidationError):
        PromptAlignmentConfig.model_validate({"prompt_instructions": [" "]})

    json_config = JsonCorrectnessConfig.model_validate({})
    assert json_config.strict_mode is True
    assert json_config.expected_schema == {
        "type": "object",
        "properties": {},
        "required": [],
    }
    with pytest.raises(ValidationError, match="oneOf"):
        JsonCorrectnessConfig.model_validate(
            {"expected_schema": {"type": "object", "oneOf": []}}
        )

    geval = METRICS["deepeval.geval"]
    config = geval.validate_config({"evaluation_fields": ["expected_output"]})
    assert geval.requirements(config) == frozenset({"expected_output"})
