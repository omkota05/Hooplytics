import time

import pytest

from app.db import session_scope
from app.services.recommendation_service import clear_recommendation_cache, filter_recommendations, generate_recommendations


@pytest.mark.slow
def test_recommendation_generation_under_budget():
    """Uncached 3-day feed should complete in reasonable time after batching."""
    clear_recommendation_cache()
    with session_scope() as s:
        t0 = time.perf_counter()
        bundle = generate_recommendations(s, days=3, expand_player_props=False)
        elapsed = time.perf_counter() - t0
    assert bundle.meta.player_props_generated > 100
    assert elapsed < 120.0, f"generation took {elapsed:.1f}s"
    t1 = time.perf_counter()
    filtered = filter_recommendations(bundle, min_probability=0.55, category="pts")
    assert (time.perf_counter() - t1) < 0.5


def test_cached_response_is_fast():
    clear_recommendation_cache()
    with session_scope() as s:
        generate_recommendations(s, days=3)
        t0 = time.perf_counter()
        generate_recommendations(s, days=3)
        elapsed = time.perf_counter() - t0
    assert elapsed < 2.0
