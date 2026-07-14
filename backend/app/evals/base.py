from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.evals.json_schema import model_from_object_schema

from app.evals.samples import SingleTurnSample


EvalRow = SingleTurnSample

MetricCategory = Literal["rag", "agentic", "general"]
SampleKind = Literal["single_turn", "agent_trace", "conversation", "multimodal"]
ResourceRole = Literal["judge", "embedding", "multimodal"]


class MetricConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional pass threshold from 0 to 1.",
    )


class DeepEvalMetricConfig(MetricConfig):
    threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Pass threshold from 0 to 1.",
    )
    include_reason: bool = Field(
        default=True,
        description="Ask the judge to explain its score.",
    )
    strict_mode: bool = Field(
        default=False,
        description="Require a perfect score to pass.",
    )


class GEvalConfig(MetricConfig):
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    strict_mode: bool = False
    rubric: str = Field(
        default="Evaluate the quality of the response.",
        min_length=1,
        max_length=10_000,
        description="Natural-language evaluation criteria.",
    )
    evaluation_fields: list[
        Literal[
            "input",
            "actual_output",
            "expected_output",
            "context",
            "retrieval_contexts",
        ]
    ] = Field(
        default_factory=lambda: ["input", "actual_output"],
        min_length=1,
        description="Sample fields available to the G-Eval judge.",
    )

    @field_validator("evaluation_fields")
    @classmethod
    def unique_evaluation_fields(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evaluation_fields must not contain duplicates")
        return value


class PromptAlignmentConfig(DeepEvalMetricConfig):
    prompt_instructions: list[str] = Field(
        default_factory=lambda: ["Follow the instructions in the user input."],
        min_length=1,
        description="One prompt constraint per line.",
    )

    @field_validator("prompt_instructions")
    @classmethod
    def non_empty_instructions(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("prompt_instructions must not contain blank values")
        return cleaned


class JsonCorrectnessConfig(DeepEvalMetricConfig):
    strict_mode: bool = True
    expected_schema: dict[str, Any] = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "required": [],
        },
        description="Supported object JSON Schema for the output.",
    )

    @field_validator("expected_schema")
    @classmethod
    def supported_expected_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        model_from_object_schema(value)
        return value


@dataclass(frozen=True)
class JudgeConfig:
    provider: str  # 'openai' | 'anthropic' | 'openai_compatible'
    model: str
    api_key: str | None
    base_url: str | None = None
    # Embedding connection, resolved independently of the judge LLM connection.
    embedding_model: str | None = None
    embedding_provider: str | None = None  # 'openai' | 'openai_compatible'
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None


@dataclass(frozen=True)
class MetricScore:
    metric: str
    score: float
    reason: str | None
    passed: bool | None
    usage: dict[str, int] | None = None
    estimated_cost: float | None = None


class MetricAdapter(Protocol):
    key: str
    revision: str
    framework: str
    category: MetricCategory
    family: str
    display_name: str
    description: str
    sample_kind: SampleKind
    requires: frozenset[str]

    def validate_config(self, config: dict | None) -> dict[str, Any]: ...

    def default_config(self) -> dict[str, Any]: ...

    def config_schema(self) -> dict[str, Any]: ...

    def requirements(self, config: dict | None = None) -> frozenset[str]: ...

    def missing_requirements(
        self, config: dict | None, available_fields: set[str]
    ) -> frozenset[str]: ...

    def resources(self, config: dict | None = None) -> frozenset[ResourceRole]: ...

    def catalog_entry(self) -> dict[str, Any]: ...

    def score(
        self,
        row: EvalRow,
        judge: JudgeConfig,
        config: dict | None = None,
    ) -> MetricScore: ...


@dataclass(frozen=True)
class CallableAdapter:
    key: str
    framework: str
    display_name: str
    description: str
    requires: frozenset[str]
    scorer: Callable[[EvalRow, JudgeConfig, dict | None], MetricScore]
    revision: str = "1"
    category: MetricCategory = "general"
    family: str = "text_safety"
    sample_kind: SampleKind = "single_turn"
    config_model: type[BaseModel] = MetricConfig
    recommended: bool = True
    info: dict[str, Any] = field(default_factory=dict)
    requirement_config_field: str | None = None
    requirement_exclusions: frozenset[str] = frozenset()
    requirement_aliases: dict[str, frozenset[str]] = field(default_factory=dict)
    resource_fn: Callable[[dict[str, Any]], frozenset[ResourceRole]] | None = None

    def validate_config(self, config: dict | None) -> dict[str, Any]:
        return self.config_model.model_validate(config or {}).model_dump(mode="json")

    def default_config(self) -> dict[str, Any]:
        return self.validate_config({})

    def config_schema(self) -> dict[str, Any]:
        return self.config_model.model_json_schema()

    def requirements(self, config: dict | None = None) -> frozenset[str]:
        validated = self.validate_config(config)
        if self.requirement_config_field is not None:
            return (
                frozenset(validated[self.requirement_config_field])
                - self.requirement_exclusions
            )
        return self.requires

    def missing_requirements(
        self, config: dict | None, available_fields: set[str]
    ) -> frozenset[str]:
        return frozenset(
            required
            for required in self.requirements(config)
            if required not in available_fields
            and not (self.requirement_aliases.get(required, frozenset()) & available_fields)
        )

    def resources(self, config: dict | None = None) -> frozenset[ResourceRole]:
        validated = self.validate_config(config)
        if self.resource_fn is not None:
            return self.resource_fn(validated)
        return frozenset({"judge"})

    def catalog_entry(self) -> dict[str, Any]:
        config = self.default_config()
        return {
            "key": self.key,
            "revision": self.revision,
            "framework": self.framework,
            "category": self.category,
            "family": self.family,
            "display_name": self.display_name,
            "description": self.description,
            "sample_kind": self.sample_kind,
            "requires": sorted(self.requirements(config)),
            "requirement_rule": (
                {
                    "config_field": self.requirement_config_field,
                    "exclude": sorted(self.requirement_exclusions),
                }
                if self.requirement_config_field is not None
                else None
            ),
            "requirement_aliases": {
                key: sorted(value) for key, value in self.requirement_aliases.items()
            },
            "resources": sorted(self.resources(config)),
            "config_schema": self.config_schema(),
            "default_config": config,
            "recommended": self.recommended,
            "info": self.info,
        }

    def score(
        self,
        row: EvalRow,
        judge: JudgeConfig,
        config: dict | None = None,
    ) -> MetricScore:
        result = self.scorer(row, judge, config)
        value = float(result.score)
        if not isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{self.key} must return a finite score in the range 0..1")
        return MetricScore(
            metric=self.key,
            score=value,
            reason=result.reason,
            passed=result.passed,
            usage=result.usage,
            estimated_cost=result.estimated_cost,
        )
