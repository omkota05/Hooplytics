from app.services.parlay_scoring import combination_score
from app.services.prop_finder_service import DEFAULT_PAGE_SIZE, RANKED_RESULTS_CAP


def test_ranked_cap_constants():
    assert RANKED_RESULTS_CAP == 100
    assert DEFAULT_PAGE_SIZE == 10


def test_combination_score_min_leg_drag():
    high, _, _ = combination_score([90.0, 88.0, 85.0])
    dragged, _, _ = combination_score([90.0, 88.0, 30.0])
    assert high > dragged
