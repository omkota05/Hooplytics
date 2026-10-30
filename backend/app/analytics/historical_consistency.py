"""Historical Consistency Score (HCS) v2 — descriptive ranking index, not a win probability."""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Literal

from app.analytics.hcs_settings import DEFAULT_HCS, HCS_VERSION, HCSSettings

Side = Literal["over", "under"]


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _delta(side: Side) -> int:
    return 1 if side == "over" else -1


def outcome_indicator(value: float, line: float, side: Side, *, push_value: float) -> tuple[float, str]:
    if side == "over":
        if value > line:
            return 1.0, "hit"
        if value == line:
            return push_value, "push"
        return 0.0, "miss"
    if value < line:
        return 1.0, "hit"
    if value == line:
        return push_value, "push"
    return 0.0, "miss"


def recency_weights(n: int, *, gamma: float) -> list[float]:
    """w_t = exp(-gamma * (t-1)), t=1 is most recent."""
    return [math.exp(-gamma * t) for t in range(n)]


def kish_effective_sample_size(weights: list[float]) -> float:
    if not weights:
        return 0.0
    s = sum(weights)
    s2 = sum(w * w for w in weights)
    if s2 <= 0:
        return 0.0
    return (s * s) / s2


def recency_wilson_lower_bound(
    p: float,
    n_eff: float,
    *,
    z: float = 1.15,
) -> float:
    """W_rec on 0–100 scale."""
    p = _clip(p, 0.0, 1.0)
    ne = max(n_eff, 1.0)
    z2 = z * z
    radicand = max(0.0, (p * (1.0 - p) / ne) + (z2 / (4.0 * ne * ne)))
    num = p + z2 / (2.0 * ne) - z * math.sqrt(radicand)
    den = 1.0 + z2 / ne
    return 100.0 * _clip(num / den, 0.0, 1.0)


def quantile_triplet(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if len(values) < 4:
        return None, None, None
    qs = statistics.quantiles(values, n=4, method="inclusive")
    return qs[0], qs[1], qs[2]


def cushion_tilt(
    values: list[float],
    line: float,
    side: Side,
    settings: HCSSettings,
) -> tuple[float, float | None, float | None, float, float]:
    """Returns (T_cush, q25, median, iqr, tanh_arg)."""
    if not values:
        return 0.0, None, None, settings.iqr_floor, 0.0
    q25, med, q75 = quantile_triplet(values)
    if med is None:
        med = statistics.median(values)
        spread = max(values) - min(values) if len(values) > 1 else settings.iqr_floor
        iqr = max(spread, settings.iqr_floor)
        q25 = med
        q75 = med
    else:
        iqr = max(q75 - q25, settings.iqr_floor)
    arg = settings.cushion_tanh_scale * _delta(side) * (med - line) / iqr
    t_cush = settings.cushion_tilt_max * math.tanh(arg)
    return t_cush, q25, med, iqr, arg


def minute_tilt(
    minutes_recent_first: list[float],
    side: Side,
    settings: HCSSettings,
) -> tuple[float, float, float, float, float, list[str]]:
    """Returns (T_min, T_trend, P_floor, m5, m20, m15, flags)."""
    flags: list[str] = []
    if len(minutes_recent_first) < 5:
        flags.append("insufficient_minutes_sample")
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, flags

    trail = minutes_recent_first[: settings.minutes_trailing]
    l5 = trail[:5]
    m5 = sum(l5) / len(l5)
    m20 = sum(trail) / len(trail)
    sorted_m = sorted(trail)
    idx = max(0, int(math.floor(0.15 * (len(sorted_m) - 1))))
    m15 = sorted_m[idx]

    m5u = max(m5, 1.0)
    m20u = max(m20, 1.0)
    t_trend = settings.minute_trend_tilt_max * math.tanh(
        settings.minute_trend_tanh_scale * _delta(side) * math.log(m5u / m20u)
    )

    p_floor = 0.0
    if side == "over":
        ratio = m15 / m20u
        if ratio < settings.minute_floor_ratio:
            p_floor = settings.minute_floor_penalty_max * _clip(
                (settings.minute_floor_ratio - ratio) / settings.minute_floor_band,
                0.0,
                1.0,
            )

    t_min = _clip(
        t_trend - p_floor,
        settings.minute_tilt_min,
        settings.minute_tilt_max,
    )
    return t_min, t_trend, p_floor, m5, m20, m15, flags


@dataclass(frozen=True)
class HCSBreakdown:
    version: str
    analysis_window: str
    hcs: float
    h_weighted: float
    h_shrunk: float
    hits: int
    misses: int
    pushes: int
    qualifying_games: int
    effective_sample_size: float
    median: float | None
    iqr: float | None
    c_raw: float | None
    c_cushion: float
    m5_minutes: float | None
    m20_minutes: float | None
    m15_minutes: float | None
    m_modifier: float
    cushion_window: str
    missing_data_flags: tuple[str, ...]
    last_game_date: str | None
    component_historical: float
    component_cushion: float
    component_minutes: float

    def to_dict(self) -> dict:
        return asdict(self)


def compute_hcs(
    *,
    stat_values_recent_first: list[float],
    minutes_recent_first: list[float | None],
    line: float,
    pick_side: Side,
    analysis_window: str,
    window_size: int,
    settings: HCSSettings | None = None,
    last_game_date: str | None = None,
) -> HCSBreakdown:
    """Compute HCS v2 for the last `window_size` qualifying played games (recent-first)."""
    cfg = settings or DEFAULT_HCS
    flags: list[str] = []

    win_stats = stat_values_recent_first[:window_size]
    win_mins_raw = minutes_recent_first[:window_size]
    win_mins = [float(m) for m in win_mins_raw if m is not None and m > 0]
    if len(win_mins) != len(win_stats):
        flags.append("minutes_mismatch_in_window")

    n = len(win_stats)
    if n == 0:
        flags.append("no_qualifying_games")
        w_rec = 50.0
        return HCSBreakdown(
            version=HCS_VERSION,
            analysis_window=analysis_window,
            hcs=50.0,
            h_weighted=0.5,
            h_shrunk=w_rec / 100.0,
            hits=0,
            misses=0,
            pushes=0,
            qualifying_games=0,
            effective_sample_size=0.0,
            median=None,
            iqr=None,
            c_raw=None,
            c_cushion=0.5,
            m5_minutes=None,
            m20_minutes=None,
            m15_minutes=None,
            m_modifier=0.5,
            cushion_window=analysis_window,
            missing_data_flags=tuple(flags),
            last_game_date=last_game_date,
            component_historical=w_rec,
            component_cushion=50.0,
            component_minutes=50.0,
        )

    weights = recency_weights(n, gamma=cfg.gamma)
    hits = misses = pushes = 0
    indicators: list[float] = []
    for v in win_stats:
        ind, label = outcome_indicator(v, line, pick_side, push_value=cfg.push_indicator)
        indicators.append(ind)
        if label == "hit":
            hits += 1
        elif label == "miss":
            misses += 1
        else:
            pushes += 1

    w_sum = sum(weights)
    h_weighted = sum(w * i for w, i in zip(weights, indicators)) / w_sum if w_sum else 0.5
    n_eff = kish_effective_sample_size(weights)
    w_rec = recency_wilson_lower_bound(h_weighted, n_eff, z=cfg.wilson_z)

    t_cush, _q25, med, iqr, tanh_arg = cushion_tilt(win_stats, line, pick_side, cfg)
    c_cushion_norm = 0.5 + 0.5 * math.tanh(tanh_arg)

    mins_for_mod = win_mins if len(win_mins) >= 5 else win_mins
    t_min, _t_trend, p_floor, m5, m20, m15, m_flags = minute_tilt(
        mins_for_mod if len(mins_for_mod) >= 5 else win_mins,
        pick_side,
        cfg,
    )
    flags.extend(m_flags)
    m_modifier_norm = _clip((t_min + 7.0) / 10.0, 0.0, 1.0)

    hcs = _clip(w_rec + t_cush + t_min, 0.0, 100.0)

    return HCSBreakdown(
        version=HCS_VERSION,
        analysis_window=analysis_window,
        hcs=round(hcs, 2),
        h_weighted=round(h_weighted, 4),
        h_shrunk=round(w_rec / 100.0, 4),
        hits=hits,
        misses=misses,
        pushes=pushes,
        qualifying_games=n,
        effective_sample_size=round(n_eff, 3),
        median=round(med, 2) if med is not None else None,
        iqr=round(iqr, 2),
        c_raw=round(tanh_arg, 4),
        c_cushion=round(c_cushion_norm, 4),
        m5_minutes=round(m5, 2) if m5 else None,
        m20_minutes=round(m20, 2) if m20 else None,
        m15_minutes=round(m15, 2) if m15 else None,
        m_modifier=round(m_modifier_norm, 4),
        cushion_window=analysis_window,
        missing_data_flags=tuple(flags),
        last_game_date=last_game_date,
        component_historical=round(w_rec, 2),
        component_cushion=round(c_cushion_norm * 100.0, 2),
        component_minutes=round(m_modifier_norm * 100.0, 2),
    )
