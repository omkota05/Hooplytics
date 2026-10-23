from datetime import date

from app.analytics.categories import get_category
from app.services.recommendation_lines import synthetic_line_from_recent_mean


class _FakeLog:
    def __init__(self, pts: float, *, game_date: date | None = None) -> None:
        self.pts = pts
        self.reb = 0
        self.ast = 0
        self.fg3m = 0
        self.did_not_play = False
        self.season_type = 2
        self.season = 2027
        self.game_date = game_date or date(2026, 10, 1)
        self.opponent_team_id = 1


def test_synthetic_line_from_recent_mean_uses_select_games_api():
    logs = [_FakeLog(20.0 + i * 0.1) for i in range(10)]
    line = synthetic_line_from_recent_mean(logs, get_category("pts"))
    assert line == 20.5
