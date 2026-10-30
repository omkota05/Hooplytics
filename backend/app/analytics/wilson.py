"""Wilson score interval for binomial proportions (sample-size-aware ranking)."""

from __future__ import annotations

import math

Z_95 = 1.96


def wilson_lower_bound(hits: int, attempts: int, *, z: float = Z_95) -> float | None:
    """Lower bound of Wilson score interval; attempts exclude pushes (decided games only)."""
    if attempts <= 0 or hits < 0 or hits > attempts:
        return None
    p = hits / attempts
    z2 = z * z
    denom = 1 + z2 / attempts
    center = p + z2 / (2 * attempts)
    radicand = (p * (1 - p) + z2 / (4 * attempts)) / attempts
    if radicand < 0:
        return None
    margin = z * math.sqrt(radicand)
    lb = (center - margin) / denom
    return round(max(0.0, min(1.0, lb)) * 100, 2)
