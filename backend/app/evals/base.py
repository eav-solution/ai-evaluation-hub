from dataclasses import dataclass
from math import isfinite
from typing import Callable, Protocol


@dataclass(frozen=True)
class EvalRow:
    input: str
    actual_output: str
    expected_output: str | None
    contexts: list[str] | None


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
    framework: str
    display_name: str
    description: str
    requires: frozenset[str]

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

    def score(
        self,
        row: EvalRow,
        judge: JudgeConfig,
        config: dict | None = None,
    ) -> MetricScore:
        result = self.scorer(row, judge, config)
        if not isfinite(result.score):
            raise ValueError(f"{self.key} returned a non-finite score")
        return MetricScore(
            metric=self.key,
            score=max(0.0, min(1.0, float(result.score))),
            reason=result.reason,
            passed=result.passed,
        )
