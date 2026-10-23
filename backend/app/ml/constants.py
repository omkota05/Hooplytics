"""ML prediction scope and shared constants."""

from app.analytics.categories import CATEGORIES

# Individual stats with dedicated XGBoost regressors.
COMPONENT_STATS: tuple[str, ...] = ("pts", "reb", "ast", "fg3m")

# Categories exposed by the prediction API (combined stats are sums of components).
PREDICTION_CATEGORIES: tuple[str, ...] = (
    "pts",
    "reb",
    "ast",
    "fg3m",
    "pts_reb",
    "pts_ast",
    "reb_ast",
    "pts_reb_ast",
)

MIN_GAMES_FOR_POINT_PREDICTION = 3
MIN_GAMES_FOR_PROBABILITIES = 8
MIN_GAMES_FOR_FULL_CONFIDENCE = 15

# Chronological split fractions by game date.
TRAIN_FRAC = 0.70
VAL_FRAC = 0.15
TEST_FRAC = 0.15

EWM_SPAN = 10


def components_for_category(category_key: str) -> tuple[str, ...]:
    return CATEGORIES[category_key].components


def is_supported_category(category_key: str) -> bool:
    return category_key in PREDICTION_CATEGORIES
