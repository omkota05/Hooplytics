"""Load player-game rows from PostgreSQL and validate them before feature engineering."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Game, PlayerGameStat

STAT_COLUMNS = ("minutes", "pts", "reb", "ast", "fg3m", "fga", "fg3a", "fta", "oreb", "tov")
TARGETS = ("pts", "reb", "ast", "fg3m")
COMBINED = {
    "pts_reb": ("pts", "reb"),
    "pts_ast": ("pts", "ast"),
    "reb_ast": ("reb", "ast"),
    "pts_reb_ast": ("pts", "reb", "ast"),
}
ALL_CATEGORIES: dict[str, tuple[str, ...]] = {**{t: (t,) for t in TARGETS}, **COMBINED}


def components(category: str) -> tuple[str, ...]:
    try:
        return ALL_CATEGORIES[category]
    except KeyError as exc:
        raise ValueError(f"Unsupported ML category '{category}'") from exc


def load_raw(session: Session) -> pd.DataFrame:
    """All player-game rows (including DNPs) for games with synced box scores."""
    s = PlayerGameStat
    stmt = (
        select(
            s.player_id,
            s.game_id,
            s.team_id,
            s.opponent_team_id,
            s.season,
            s.season_type,
            s.is_home,
            s.starter,
            s.did_not_play,
            *[getattr(s, c) for c in STAT_COLUMNS],
            Game.start_time,
            Game.game_date,
            Game.status,
        )
        .join(Game, Game.id == s.game_id)
        .where(Game.status == "final")
    )
    frame = pd.DataFrame(session.execute(stmt).mappings().all())
    if frame.empty:
        return frame
    frame["start_time"] = pd.to_datetime(frame["start_time"], utc=True)
    frame["game_date"] = pd.to_datetime(frame["game_date"])
    for c in STAT_COLUMNS:
        frame[c] = pd.to_numeric(frame[c], errors="coerce").astype(float)
    return frame.sort_values(["player_id", "start_time"]).reset_index(drop=True)


def data_snapshot_key(session: Session) -> str:
    """Changes whenever box scores or the schedule change; used to invalidate inference caches."""
    n, max_upd = session.execute(
        select(func.count(), func.max(PlayerGameStat.updated_at)).select_from(PlayerGameStat)
    ).one()
    g_upd = session.scalar(select(func.max(Game.updated_at)))
    return f"pgs{n}|{max_upd.isoformat() if max_upd else 'none'}|g{g_upd.isoformat() if g_upd else 'none'}"


@dataclass
class ValidationReport:
    rows_total: int = 0
    rows_played: int = 0
    rows_dnp: int = 0
    duplicate_player_game: int = 0
    played_missing_minutes: int = 0
    played_zero_minutes: int = 0
    played_missing_targets: int = 0
    negative_values: int = 0
    implausible_values: int = 0
    self_opponent_rows: int = 0
    games_with_one_team_only: int = 0
    player_team_changes: int = 0
    seasons: dict[int, int] = field(default_factory=dict)
    season_types: dict[int, int] = field(default_factory=dict)
    excluded_rows: int = 0

    def as_dict(self) -> dict:
        return {k: (v if not isinstance(v, dict) else {str(a): b for a, b in v.items()}) for k, v in self.__dict__.items()}


def validate_and_clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, ValidationReport]:
    """Return rows usable for modeling plus a report of everything that was checked.

    Rules: DNP rows stay in the frame (they shape rest/availability features) but are never
    targets. Played rows without minutes or with missing target stats are flagged `usable=False`
    rather than imputed to zero.
    """
    rep = ValidationReport()
    if raw.empty:
        return raw, rep
    df = raw.copy()
    rep.rows_total = len(df)
    dup = df.duplicated(["player_id", "game_id"], keep="first")
    rep.duplicate_player_game = int(dup.sum())
    df = df[~dup]

    rep.self_opponent_rows = int((df["team_id"] == df["opponent_team_id"]).sum())
    df = df[df["team_id"] != df["opponent_team_id"]]

    dnp = df["did_not_play"].fillna(False).astype(bool)
    rep.rows_dnp = int(dnp.sum())
    rep.rows_played = int((~dnp).sum())
    played = df[~dnp]
    rep.played_missing_minutes = int(played["minutes"].isna().sum())
    rep.played_zero_minutes = int((played["minutes"] == 0).sum())
    rep.played_missing_targets = int(played[list(TARGETS)].isna().any(axis=1).sum())
    num = df[list(STAT_COLUMNS)]
    rep.negative_values = int((num < 0).any(axis=1).sum())
    implausible = (df["minutes"] > 70) | (df["pts"] > 100) | (df["reb"] > 40) | (df["ast"] > 35) | (df["fg3m"] > 20)
    implausible |= df["fg3m"] > df["fg3a"].fillna(np.inf)
    rep.implausible_values = int(implausible.sum())

    teams_per_game = df.groupby("game_id")["team_id"].nunique()
    rep.games_with_one_team_only = int((teams_per_game < 2).sum())

    ordered = df[~dnp].sort_values(["player_id", "start_time"])
    prev_team = ordered.groupby("player_id")["team_id"].shift(1)
    rep.player_team_changes = int(((prev_team.notna()) & (prev_team != ordered["team_id"])).sum())
    rep.seasons = {int(k): int(v) for k, v in df.groupby("season").size().items()}
    rep.season_types = {int(k): int(v) for k, v in df.groupby("season_type").size().items()}

    bad = (num < 0).any(axis=1) | implausible
    df["did_not_play"] = dnp
    # Played rows with zero/missing minutes are treated as non-appearances for features.
    df["appeared"] = (~dnp) & df["minutes"].fillna(0).gt(0) & ~bad
    df["usable_target"] = df["appeared"] & df[list(TARGETS)].notna().all(axis=1)
    rep.excluded_rows = int(rep.rows_played - df["usable_target"].sum())
    return df.sort_values(["player_id", "start_time"]).reset_index(drop=True), rep
