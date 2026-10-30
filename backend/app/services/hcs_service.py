"""Build HCS bundles from player game logs (cached via prop line hit cache)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.analytics.categories import get_category, stat_value
from app.analytics.historical_consistency import HCSBreakdown, compute_hcs
from app.analytics.hcs_settings import HCS_VERSION
from app.ingestion.providers.base import TRACKED_SEASON_TYPES
from app.repositories import players as players_repo
from app.services.prop_hit_rates import Side

WINDOW_SIZES = {"l5": 5, "l10": 10, "l20": 20, "l30": 30}


def _series_before_start(
    session: Session,
    *,
    player_id: int,
    category_key: str,
    before_start: datetime | None,
) -> tuple[list[float], list[float | None], str | None]:
    category = get_category(category_key)
    logs = players_repo.player_game_logs(session, player_id)
    stats: list[float] = []
    minutes: list[float | None] = []
    last_date: str | None = None
    for row in logs:
        if row.did_not_play:
            continue
        if row.minutes is None or row.minutes <= 0:
            continue
        if row.season_type not in TRACKED_SEASON_TYPES:
            continue
        if before_start is not None and row.game and row.game.start_time and row.game.start_time >= before_start:
            continue
        v = stat_value(row, category)
        if v is None:
            continue
        stats.append(float(v))
        minutes.append(float(row.minutes))
        if last_date is None and row.game_date:
            last_date = row.game_date.isoformat()
    return stats, minutes, last_date


def compute_hcs_bundle_for_line(
    session: Session,
    *,
    player_id: int,
    category_key: str,
    line: float,
    before_start: datetime | None,
) -> dict:
    """Return JSON-serializable hcs_v1 block with over/under per analysis window."""
    stats, minutes, last_date = _series_before_start(
        session,
        player_id=player_id,
        category_key=category_key,
        before_start=before_start,
    )
    out: dict = {"version": HCS_VERSION, "last_game_date": last_date, "windows": {}}
    for key, size in WINDOW_SIZES.items():
        out["windows"][key] = {}
        for side in ("over", "under"):
            bd = compute_hcs(
                stat_values_recent_first=stats,
                minutes_recent_first=minutes,
                line=line,
                pick_side=side,  # type: ignore[arg-type]
                analysis_window=key.upper(),
                window_size=size,
                last_game_date=last_date,
            )
            out["windows"][key][side] = bd.to_dict()
    return out


def breakdown_from_dict(raw: dict) -> HCSBreakdown:
    flags = raw.get("missing_data_flags") or ()
    if isinstance(flags, list):
        flags = tuple(flags)
    fields = {k: raw.get(k) for k in HCSBreakdown.__dataclass_fields__}
    fields["missing_data_flags"] = flags
    return HCSBreakdown(**fields)


def breakdown_from_cache(
    hit_rates: dict | None,
    *,
    pick_side: Side,
    analysis_window: str = "l20",
) -> HCSBreakdown | None:
    if not hit_rates:
        return None
    block = hit_rates.get("hcs_v1") or {}
    win = (block.get("windows") or {}).get(analysis_window) or {}
    raw = win.get(pick_side)
    if not raw:
        return None
    return breakdown_from_dict(raw)


def hcs_score_from_cache(
    hit_rates: dict | None,
    *,
    pick_side: Side,
    analysis_window: str = "l20",
) -> float | None:
    bd = breakdown_from_cache(hit_rates, pick_side=pick_side, analysis_window=analysis_window)
    return bd.hcs if bd else None
