from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.evals.samples import SingleTurnSample


EvalRow = SingleTurnSample

MetricCategory = Literal["rag", "agentic", "general"]
SampleKind = Literal["single_turn", "agent_trace", "conversation", "multimodal"]
ResourceRole = Literal["judge", "embedding", "multimodal"]


class MetricConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class DeepEvalMetricConfig(MetricConfig):
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class GEvalConfig(DeepEvalMetricConfig):
    rubric: str = Field(
        default="Evaluate the quality of the response.",
        min_length=1,
        max_length=10_000,
    )


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
    requirement_fn: Callable[[dict[str, Any]], frozenset[str]] | None = None
    resource_fn: Callable[[dict[str, Any]], frozenset[ResourceRole]] | None = None

    def validate_config(self, config: dict | None) -> dict[str, Any]:
        return self.config_model.model_validate(config or {}).model_dump(mode="json")

    def default_config(self) -> dict[str, Any]:
        return self.validate_config({})

    def config_schema(self) -> dict[str, Any]:
        return self.config_model.model_json_schema()

    def requirements(self, config: dict | None = None) -> frozenset[str]:
        validated = self.validate_config(config)
        if self.requirement_fn is not None:
            return self.requirement_fn(validated)
        return self.requires

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
        )
