from app.ml.game_winner.elo import EloTracker, expected_home_win_prob, update_elo


def test_elo_home_favorite():
    p = expected_home_win_prob(1600, 1500)
    assert 0.6 < p < 0.8


def test_elo_updates_sum_conservation():
    h, a = update_elo(1500, 1500, 1.0)
    assert abs((h + a) - 3000) < 1e-6


def test_elo_tracker_chronological():
    t = EloTracker()
    h1, a1, p1 = t.pregame(1, 2, home_advantage=100.0)
    assert p1 == expected_home_win_prob(h1, a1, 100.0)
    t.apply_result(1, 2, 1.0, home_advantage=100.0)
    h2, a2, p2 = t.pregame(1, 2, home_advantage=100.0)
    assert h2 > h1
    assert a2 < a1
