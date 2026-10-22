"""Over/under/push evaluation against a custom line, plus distribution summaries."""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Outcome = Literal["over", "under", "push"]

SMALL_SAMPLE_THRESHOLD = 5


class InvalidLineError(ValueError):
    pass


def validate_line(line: float) -> float:
    if not math.isfinite(line) or line < 0 or line > 200:
        raise InvalidLineError("Line must be a number between 0 and 200")
    return line


def classify(value: float, line: float) -> Outcome:
    if value > line:
        return "over"
    if value < line:
        return "under"
    return "push"


@dataclass(frozen=True)
class LineResult:
    line: float
    total: int
    over: int
    under: int
    push: int

    def _pct(self, count: int, denominator: int) -> float | None:
        return round(100 * count / denominator, 1) if denominator else None

    @property
    def over_pct(self) -> float | None:
        """Share of all analyzed games (pushes included in the denominator)."""
        return self._pct(self.over, self.total)

    @property
    def under_pct(self) -> float | None:
        return self._pct(self.under, self.total)

    @property
    def push_pct(self) -> float | None:
        return self._pct(self.push, self.total)

    @property
    def over_pct_excluding_pushes(self) -> float | None:
        """Over rate among decided games only (over + under)."""
        return self._pct(self.over, self.over + self.under)


def evaluate_line(values: Sequence[float], line: float) -> LineResult:
    validate_line(line)
    outcomes = [classify(v, line) for v in values]
    return LineResult(
        line=line,
        total=len(outcomes),
        over=outcomes.count("over"),
        under=outcomes.count("under"),
        push=outcomes.count("push"),
    )


@dataclass(frozen=True)
class Distribution:
    count: int
    mean: float | None
    median: float | None
    std_dev: float | None
    minimum: float | None
    maximum: float | None


def summarize(values: Sequence[float]) -> Distribution:
    """Sample standard deviation (n-1); undefined for fewer than two games."""
    if not values:
        return Distribution(0, None, None, None, None, None)
    return Distribution(
        count=len(values),
        mean=round(statistics.fmean(values), 2),
        median=round(statistics.median(values), 2),
        std_dev=round(statistics.stdev(values), 2) if len(values) > 1 else None,
        minimum=min(values),
        maximum=max(values),
    )


def is_small_sample(count: int) -> bool:
    return count < SMALL_SAMPLE_THRESHOLD
