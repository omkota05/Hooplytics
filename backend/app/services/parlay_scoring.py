"""Non-ML Historical Consistency (HCS) and Parlay Consistency (PCS) scoring."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Literal

from app.analytics.hcs_settings import DEFAULT_PCS, PCS_VERSION
from app.analytics.historical_consistency import HCSBreakdown
from app.analytics.wilson import wilson_lower_bound

WindowKey = Literal["l5", "l10", "l20", "l30"]

# Legacy weighted leg score (pre-hcs_v1) — retained for comparison tests only.
LEGACY_DEFAULT_WEIGHTS = {
    "wilson_primary": 0.35,
    "wilson_l20": 0.20,
    "hit_pct_primary": 0.15,
    "margin": 0.15,
    "minutes_stability": 0.10,
    "h2h_wilson": 0.05,
}


@dataclass(frozen=True)
class LegScoreBreakdown:
    """New HCS-based leg breakdown for API responses."""

    hcs: float
    component_historical: float
    component_cushion: float
    component_minutes: float
    h_weighted: float
    h_shrunk: float
    hits: int
    misses: int
    pushes: int
    qualifying_games: int
    effective_sample_size: float
    median: float | None
    iqr: float | None
    c_cushion: float
    m_modifier: float
    m5_minutes: float | None
    m20_minutes: float | None
    analysis_window: str
    missing_data_flags: tuple[str, ...]
    version: str

    @classmethod
    def from_hcs(cls, bd: HCSBreakdown) -> LegScoreBreakdown:
        return cls(
            hcs=bd.hcs,
            component_historical=bd.component_historical,
            component_cushion=bd.component_cushion,
            component_minutes=bd.component_minutes,
            h_weighted=bd.h_weighted,
            h_shrunk=bd.h_shrunk,
            hits=bd.hits,
            misses=bd.misses,
            pushes=bd.pushes,
            qualifying_games=bd.qualifying_games,
            effective_sample_size=bd.effective_sample_size,
            median=bd.median,
            iqr=bd.iqr,
            c_cushion=bd.c_cushion,
            m_modifier=bd.m_modifier,
            m5_minutes=bd.m5_minutes,
            m20_minutes=bd.m20_minutes,
            analysis_window=bd.analysis_window,
            missing_data_flags=bd.missing_data_flags,
            version=bd.version,
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LegacyLegScoreBreakdown:
    wilson_primary: float
    wilson_l20: float
    hit_pct_primary: float
    margin: float
    minutes_stability: float
    h2h_wilson: float
    total: float
    primary_window: str
    primary_hits: int | None
    primary_attempts: int | None
    l20_hits: int | None
    l20_attempts: int | None


@dataclass(frozen=True)
class ParlayScoreBreakdown:
    version: str
    pcs: float
    geometric_mean: float
    min_leg: float
    length_factor: float
    leg_hcs: tuple[float, ...]


def _pct_component(hit_pct: float | None) -> float:
    if hit_pct is None:
        return 0.0
    return max(0.0, min(100.0, float(hit_pct)))


def margin_component(pick_side: str, historical_avg: float | None, line: float) -> float:
    if historical_avg is None:
        return 0.0
    margin = historical_avg - line
    if pick_side == "under":
        margin = -margin
    return max(0.0, min(100.0, 50.0 + margin * 4.0))


def minutes_stability_component(l5_minutes: float | None, l20_minutes: float | None) -> float:
    if l5_minutes is None or l20_minutes is None:
        return 50.0
    diff = abs(l5_minutes - l20_minutes)
    return max(0.0, min(100.0, 100.0 - diff * 2.5))


def legacy_score_leg(
    *,
    pick_side: str,
    line: float,
    historical_avg: float | None,
    primary_window: WindowKey,
    primary_hit_pct: float | None,
    primary_wilson: float | None,
    primary_hits: int | None,
    primary_attempts: int | None,
    l20_hit_pct: float | None,
    l20_wilson: float | None,
    l20_hits: int | None,
    l20_attempts: int | None,
    h2h_wilson: float | None,
    h2h_attempts: int | None,
    l5_minutes: float | None,
    l20_minutes: float | None,
    weights: dict[str, float] | None = None,
) -> LegacyLegScoreBreakdown:
    w = weights or LEGACY_DEFAULT_WEIGHTS
    h2h = h2h_wilson if (h2h_attempts or 0) >= 5 else 0.0
    parts = {
        "wilson_primary": _pct_component(primary_wilson),
        "wilson_l20": _pct_component(l20_wilson),
        "hit_pct_primary": _pct_component(primary_hit_pct),
        "margin": margin_component(pick_side, historical_avg, line),
        "minutes_stability": minutes_stability_component(l5_minutes, l20_minutes),
        "h2h_wilson": _pct_component(h2h if h2h else None),
    }
    total = sum(parts[k] * w[k] for k in parts)
    return LegacyLegScoreBreakdown(
        wilson_primary=parts["wilson_primary"],
        wilson_l20=parts["wilson_l20"],
        hit_pct_primary=parts["hit_pct_primary"],
        margin=parts["margin"],
        minutes_stability=parts["minutes_stability"],
        h2h_wilson=parts["h2h_wilson"],
        total=round(total, 2),
        primary_window=primary_window.upper(),
        primary_hits=primary_hits,
        primary_attempts=primary_attempts,
        l20_hits=l20_hits,
        l20_attempts=l20_attempts,
    )


def score_leg_from_hcs(bd: HCSBreakdown) -> LegScoreBreakdown:
    return LegScoreBreakdown.from_hcs(bd)


def parlay_consistency_score(
    leg_hcs: list[float],
    *,
    length_decay: float | None = None,
    geo_weight: float | None = None,
    min_weight: float | None = None,
) -> ParlayScoreBreakdown:
    """PCS v2 — weakest-link geometric blend on 0–100 HCS scale (not a joint probability)."""
    pcs_cfg = DEFAULT_PCS
    r = length_decay if length_decay is not None else pcs_cfg.length_decay
    gw = geo_weight if geo_weight is not None else pcs_cfg.geo_weight
    mw = min_weight if min_weight is not None else pcs_cfg.min_weight
    if not leg_hcs:
        return ParlayScoreBreakdown(PCS_VERSION, 0.0, 0.0, 0.0, 1.0, tuple())
    h = [max(float(x), 1.0) for x in leg_hcs]
    k = len(h)
    gmean = math.prod(h) ** (1.0 / k)
    mn = min(h)
    pcs_base = gw * gmean + mw * mn
    length_factor = r ** (k - 2) if k >= 2 else 1.0
    pcs = round(max(0.0, min(100.0, pcs_base * length_factor)), 2)
    return ParlayScoreBreakdown(
        version=PCS_VERSION,
        pcs=pcs,
        geometric_mean=round(gmean, 4),
        min_leg=round(mn, 2),
        length_factor=round(length_factor, 4),
        leg_hcs=tuple(round(x, 2) for x in leg_hcs),
    )


def combination_score(leg_totals: list[float]) -> tuple[float, float, float]:
    """Backward-compatible wrapper returning (pcs, min_leg_hcs, geo_mean_pct)."""
    bd = parlay_consistency_score(leg_totals)
    return bd.pcs, bd.min_leg, round(bd.geometric_mean, 2)


def american_to_decimal(american: int) -> float:
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def indicative_parlay_decimal(american_odds: list[int]) -> float | None:
    if not american_odds or any(o == 0 for o in american_odds):
        return None
    total = 1.0
    for o in american_odds:
        total *= american_to_decimal(o)
    return round(total, 3)


def wilson_from_hits(hits: int | None, attempts: int | None) -> float | None:
    if hits is None or attempts is None or attempts <= 0:
        return None
    return wilson_lower_bound(hits, attempts)


# Alias for parlay builder meta
DEFAULT_WEIGHTS = LEGACY_DEFAULT_WEIGHTS


def score_leg(**kwargs) -> LegacyLegScoreBreakdown:
    """Deprecated alias — use legacy_score_leg or score_leg_from_hcs."""
    return legacy_score_leg(**kwargs)
