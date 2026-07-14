from dataclasses import dataclass
from math import isfinite
from typing import Callable, Protocol

from app.evals.samples import SingleTurnSample


EvalRow = SingleTurnSample


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
        value = float(result.score)
        if not isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(
                f"{self.key} must return a finite score in the range 0..1"
            )
        return MetricScore(
            metric=self.key,
            score=value,
            reason=result.reason,
            passed=result.passed,
        )
