"""Interface a future model-backed prediction service will implement.

Nothing here produces predictions yet; the API exposes no prediction endpoints until a
trained, backtested model exists.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class StatProjection:
    player_id: int
    game_id: int
    category: str
    mean: float
    std_dev: float
    model_version: str
    # Latest information the features were allowed to see (must precede tip-off).
    features_as_of: datetime


@dataclass(frozen=True)
class LineProbability:
    projection: StatProjection
    line: float
    p_over: float
    p_under: float
    p_push: float


class StatPredictor(Protocol):
    model_version: str

    def project(self, player_id: int, game_id: int, category: str) -> StatProjection: ...

    def line_probability(
        self, player_id: int, game_id: int, category: str, line: float
    ) -> LineProbability: ...
