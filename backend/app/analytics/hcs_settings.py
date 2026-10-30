"""Configurable parameters for Historical Consistency Score (HCS) v2."""

from __future__ import annotations

from dataclasses import dataclass

HCS_VERSION = "hcs_v2"
PCS_VERSION = "pcs_v2"


@dataclass(frozen=True)
class HCSSettings:
    gamma: float = 0.045
    wilson_z: float = 1.15
    iqr_floor: float = 1.0
    cushion_tanh_scale: float = 1.5
    cushion_tilt_max: float = 5.0
    minute_trend_tanh_scale: float = 2.5
    minute_trend_tilt_max: float = 3.0
    minute_floor_ratio: float = 0.78
    minute_floor_penalty_max: float = 4.0
    minute_floor_band: float = 0.20
    minute_tilt_min: float = -7.0
    minute_tilt_max: float = 3.0
    push_indicator: float = 0.5
    minutes_trailing: int = 20


@dataclass(frozen=True)
class PCSSettings:
    geo_weight: float = 0.65
    min_weight: float = 0.35
    length_decay: float = 0.97  # 0.97^(K-2)


DEFAULT_HCS = HCSSettings()
DEFAULT_PCS = PCSSettings()
