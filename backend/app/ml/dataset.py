"""Leakage-safe training data construction.

Every feature for a player-game row is computed only from games strictly before that
row's game_date (rolling windows are shifted by one game). Targets are that game's
actual stats. This is the foundation a future XGBoost model trains on.
"""

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.categories import BOX_SCORE_FIELDS, CATEGORIES
from app.models import Game, PlayerGameStat

ROLLING_WINDOWS = (5, 10, 20)
FEATURE_STATS = ("minutes", *BOX_SCORE_FIELDS, "fga", "fta")


def load_player_games(session: Session) -> pd.DataFrame:
    s = PlayerGameStat
    stmt = (
        select(
            s.player_id,
            s.game_id,
            s.team_id,
            s.opponent_team_id,
            s.game_date,
            s.season,
            s.season_type,
            s.is_home,
            s.starter,
            s.did_not_play,
            s.minutes,
            *[getattr(s, f) for f in BOX_SCORE_FIELDS],
            s.fga,
            s.fta,
            Game.start_time,
        )
        .join(Game, Game.id == s.game_id)
        .order_by(s.player_id, Game.start_time)
    )
    return pd.DataFrame(session.execute(stmt).mappings().all())


def add_point_in_time_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Rolling per-player features using only prior played games."""
    if frame.empty:
        return frame
    frame = frame.sort_values(["player_id", "start_time"]).reset_index(drop=True)
    frame["game_date"] = pd.to_datetime(frame["game_date"])
    played = frame[~frame["did_not_play"]].copy()
    grouped = played.groupby("player_id", sort=False)

    for stat in FEATURE_STATS:
        prior = grouped[stat].shift(1)
        for window in ROLLING_WINDOWS:
            played[f"{stat}_avg_{window}"] = (
                prior.groupby(played["player_id"])
                .rolling(window, min_periods=1)
                .mean()
                .reset_index(level=0, drop=True)
            )
    played["games_before"] = grouped.cumcount()
    # Days since the player's previous appearance (not the team's previous game).
    played["rest_days"] = grouped["game_date"].diff().dt.days

    for key, category in CATEGORIES.items():
        components = list(category.components)
        played[f"target_{key}"] = played[components].sum(axis=1, min_count=len(components))
    return played


def build_player_game_frame(session: Session) -> pd.DataFrame:
    return add_point_in_time_features(load_player_games(session))
