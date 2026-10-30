from app.services.prop_hit_cache_service import denormalized_hit_columns


def test_denormalized_hit_columns_pick_side():
    hit = {
        "windows": [
            {
                "window": "L5",
                "games": 5,
                "over_hits": 3,
                "under_hits": 2,
                "over_hit_pct": 60.0,
                "under_hit_pct": 40.0,
                "pushes": 0,
            },
            {
                "window": "L10",
                "games": 10,
                "over_hits": 5,
                "under_hits": 4,
                "over_hit_pct": 55.0,
                "under_hit_pct": 45.0,
                "pushes": 1,
            },
            {
                "window": "L20",
                "games": 20,
                "over_hits": 10,
                "under_hits": 10,
                "over_hit_pct": 50.0,
                "under_hit_pct": 50.0,
                "pushes": 0,
            },
            {
                "window": "H2H_L5",
                "games": 3,
                "over_hits": 1,
                "under_hits": 2,
                "over_hit_pct": 33.3,
                "under_hit_pct": 66.7,
                "pushes": 0,
            },
        ]
    }
    over = denormalized_hit_columns(hit, "over")
    assert over["l5_hit_pct"] == 60.0
    assert over["l10_hit_pct"] == 55.0
    assert over["l10_games"] == 10
    assert over["l10_hits"] == 5
    assert over["l10_attempts"] == 9
    assert over["l10_wilson_lb"] is not None
    assert over["h2h_hit_pct"] == 33.3

    under = denormalized_hit_columns(hit, "under")
    assert under["l10_hit_pct"] == 45.0
    assert under["l10_hits"] == 4
