"""Load completed NBA games for team-level modeling."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Game


def load_completed_games(session: Session) -> pd.DataFrame:
    stmt = (
        select(
            Game.id,
            Game.season,
            Game.season_type,
            Game.start_time,
            Game.game_date,
            Game.home_team_id,
            Game.away_team_id,
            Game.home_score,
            Game.away_score,
            Game.neutral_site,
            Game.status,
        )
        .where(
            Game.status == "final",
            Game.home_score.is_not(None),
            Game.away_score.is_not(None),
        )
        .order_by(Game.start_time, Game.id)
    )
    frame = pd.DataFrame(session.execute(stmt).mappings().all())
    if frame.empty:
        return frame
    frame["start_time"] = pd.to_datetime(frame["start_time"], utc=True)
    frame["game_date"] = pd.to_datetime(frame["game_date"]).dt.normalize()
    frame["home_win"] = (frame["home_score"] > frame["away_score"]).astype(int)
    # Overtime ties are extremely rare in NBA; treat equal scores as 0.5 for Elo only.
    frame.loc[frame["home_score"] == frame["away_score"], "home_win"] = 0
    return frame


def load_completed_games_before(session: Session, before: datetime) -> pd.DataFrame:
    games = load_completed_games(session)
    if games.empty:
        return games
    cutoff = pd.Timestamp(before)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    return games[games["start_time"] < cutoff].copy()
