"""Chronological Elo ratings (pregame ratings only; updates after final scores)."""

from __future__ import annotations

from collections import defaultdict

DEFAULT_ELO = 1500.0
K_FACTOR = 20.0
HOME_ELO_ADVANTAGE = 100.0  # ~64% for equal teams at home


def expected_home_win_prob(home_elo: float, away_elo: float, home_advantage: float = HOME_ELO_ADVANTAGE) -> float:
    return 1.0 / (1.0 + 10 ** ((away_elo - (home_elo + home_advantage)) / 400.0))


def update_elo(
    home_elo: float,
    away_elo: float,
    home_win: float,
    *,
    home_advantage: float = HOME_ELO_ADVANTAGE,
    k: float = K_FACTOR,
) -> tuple[float, float]:
    """home_win: 1 home won, 0 away won, 0.5 tie."""
    exp_home = expected_home_win_prob(home_elo, away_elo, home_advantage)
    home_new = home_elo + k * (home_win - exp_home)
    away_new = away_elo + k * ((1.0 - home_win) - (1.0 - exp_home))
    return home_new, away_new


class EloTracker:
    def __init__(self) -> None:
        self.ratings: dict[int, float] = defaultdict(lambda: DEFAULT_ELO)

    def pregame(self, home_id: int, away_id: int, *, home_advantage: float) -> tuple[float, float, float]:
        h, a = self.ratings[home_id], self.ratings[away_id]
        return h, a, expected_home_win_prob(h, a, home_advantage)

    def apply_result(self, home_id: int, away_id: int, home_win: float, *, home_advantage: float) -> None:
        h, a = self.ratings[home_id], self.ratings[away_id]
        h2, a2 = update_elo(h, a, home_win, home_advantage=home_advantage, k=K_FACTOR)
        self.ratings[home_id], self.ratings[away_id] = h2, a2

    def season_mean_regression(self, factor: float = 0.25) -> None:
        """Pull ratings toward the league mean between seasons (reduces carryover)."""
        for team_id, rating in list(self.ratings.items()):
            self.ratings[team_id] = rating * (1 - factor) + DEFAULT_ELO * factor
