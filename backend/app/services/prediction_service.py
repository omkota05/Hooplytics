"""Player stat predictions for upcoming or scheduled games."""

import math
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.analytics.categories import UnknownCategoryError, get_category
from app.analytics.lines import InvalidLineError, validate_line
from app.analytics.windows import GameWindow
from app.ml.artifacts import ModelArtifactsMissingError
from app.ml.constants import (
    MIN_GAMES_FOR_POINT_PREDICTION,
    MIN_GAMES_FOR_PROBABILITIES,
    is_supported_category,
)
from app.ml.dataset import load_player_games
from app.ml.features import build_inference_row
from app.ml.game_winner.artifacts import GameWinnerArtifactsMissingError
from app.ml.game_winner.dataset import load_completed_games_before
from app.ml.game_winner.features import add_derived_columns, build_pregame_features
from app.ml.game_winner.inference import GameWinnerEngine, get_game_winner_engine, reset_game_winner_engine
from app.ml.inference import PredictionEngine, get_prediction_engine, reset_prediction_engine
from app.models import Player, Team
from app.repositories import games as games_repo
from app.repositories import players as players_repo
from app.schemas.prediction import (
    GameOutcomeFactorsOut,
    GameOutcomePredictionOut,
    HistoricalHitRateOut,
    PlayerStatPredictionOut,
)
from app.services.analysis_service import build_analysis
from app.services.errors import BadRequestError, NotFoundError


class ModelNotReadyError(Exception):
    pass


_PREPARED_LINE_CACHE: dict[tuple[int, int, str], object] = {}
_PREPARED_LINE_CACHE_MAX = 400


def _prepared_for_line(engine, row, *, player_id: int, game_id: int):
    from app.ml.inference import PreparedPlayerGame

    key = (player_id, game_id, engine.model_version)
    hit = _PREPARED_LINE_CACHE.get(key)
    if isinstance(hit, PreparedPlayerGame):
        return hit
    if len(_PREPARED_LINE_CACHE) >= _PREPARED_LINE_CACHE_MAX:
        _PREPARED_LINE_CACHE.clear()
    prepared = engine.prepare_player_game(row, player_id=player_id, game_id=game_id)
    _PREPARED_LINE_CACHE[key] = prepared
    return prepared


def _historical_context(
    session: Session,
    *,
    player_id: int,
    category_key: str,
    line: float,
    opponent_team_id: int,
) -> HistoricalHitRateOut | None:
    logs = players_repo.player_game_logs(session, player_id)
    if not logs:
        return None
    opp = session.get(Team, opponent_team_id)
    analysis = build_analysis(
        player_id=player_id,
        logs=logs,
        category=get_category(category_key),
        line=line,
        window=GameWindow(kind="last_n", n=10),
        opponent=opp,
    )
    h2h = build_analysis(
        player_id=player_id,
        logs=logs,
        category=get_category(category_key),
        line=line,
        window=GameWindow(kind="all"),
        opponent=opp,
    )
    # Prefer head-to-head when enough games, else recent window.
    use = h2h if h2h.distribution.count >= 3 else analysis
    label = f"vs {opp.abbreviation}" if use is h2h and opp else "Last 10 games"
    return HistoricalHitRateOut(
        window_label=label,
        games=use.distribution.count,
        line_result=use.line_result,
        distribution=use.distribution,
        small_sample=use.small_sample,
        note=use.note,
    )


def predict_player_stat(
    session: Session,
    *,
    player_id: int,
    game_id: int,
    category_key: str,
    line: float,
    engine: PredictionEngine | None = None,
) -> PlayerStatPredictionOut:
    if not is_supported_category(category_key):
        raise BadRequestError(f"Category '{category_key}' is not supported for ML predictions")
    try:
        validate_line(line)
        get_category(category_key)
    except (InvalidLineError, UnknownCategoryError) as exc:
        raise BadRequestError(str(exc)) from exc

    player = session.get(Player, player_id)
    if player is None:
        raise NotFoundError(f"Player {player_id} not found")
    game = games_repo.get_game(session, game_id)
    if game is None:
        raise NotFoundError(f"Game {game_id} not found")
    if game.status == "final":
        raise BadRequestError("Predictions are for upcoming games, not completed ones")

    if player.current_team_id not in (game.home_team_id, game.away_team_id):
        raise BadRequestError("Player is not on either team in this game")

    is_home = player.current_team_id == game.home_team_id
    opponent_team_id = game.away_team_id if is_home else game.home_team_id

    raw = load_player_games(session)
    history = raw[(raw["player_id"] == player_id) & (~raw["did_not_play"])].copy()
    if history.empty:
        raise BadRequestError("No synced game history for this player")

    row = build_inference_row(
        history,
        player_id=player_id,
        game_id=game_id,
        team_id=player.current_team_id,
        opponent_team_id=opponent_team_id,
        game_date=game.game_date,
        start_time=game.start_time,
        season=game.season,
        season_type=game.season_type,
        is_home=is_home,
        starter=True,
    )
    games_before = int(row["games_before"].iloc[0])
    if games_before < MIN_GAMES_FOR_POINT_PREDICTION:
        raise BadRequestError(
            f"Need at least {MIN_GAMES_FOR_POINT_PREDICTION} prior games; player has {games_before}"
        )

    try:
        engine = engine or get_prediction_engine()
    except ModelArtifactsMissingError as exc:
        raise ModelNotReadyError(str(exc)) from exc

    prepared = _prepared_for_line(engine, row, player_id=player_id, game_id=game_id)
    lp = engine.line_probability_prepared(prepared, category_key, line)
    proj = lp.projection
    if games_before < MIN_GAMES_FOR_PROBABILITIES or lp.p_over is None:
        prob_status = "experimental" if games_before >= MIN_GAMES_FOR_POINT_PREDICTION else "unavailable"
    else:
        prob_status = "available"

    bundle = engine.bundle
    selected_summary = ", ".join(
        f"{s}:{bundle.component_selected_model[s]}" for s in bundle.component_selected_model
    )

    hist = _historical_context(
        session,
        player_id=player_id,
        category_key=category_key,
        line=line,
        opponent_team_id=opponent_team_id,
    )

    category = get_category(category_key)
    return PlayerStatPredictionOut(
        player_id=player_id,
        player_name=player.full_name,
        game_id=game_id,
        opponent_team_id=opponent_team_id,
        category=category_key,
        category_label=category.label,
        line=line,
        predicted_mean=round(proj.mean, 2),
        predicted_std_dev=round(proj.std_dev, 2),
        p_over=lp.p_over,
        p_under=lp.p_under,
        p_push=lp.p_push,
        probability_status=prob_status,
        historical_hit_rate=hist,
        model_version=proj.model_version,
        selected_model_summary=selected_summary,
        predicted_at=datetime.now(UTC),
    )


def predict_game_outcome(
    session: Session,
    *,
    game_id: int,
    engine: GameWinnerEngine | None = None,
) -> GameOutcomePredictionOut:
    game = games_repo.get_game(session, game_id)
    if game is None:
        raise NotFoundError(f"Game {game_id} not found")
    if game.status == "final":
        raise BadRequestError("Game outcome predictions are only for upcoming or in-progress games")

    home = session.get(Team, game.home_team_id)
    away = session.get(Team, game.away_team_id)
    if home is None or away is None:
        raise NotFoundError("Home or away team not found")

    completed = load_completed_games_before(session, game.start_time)
    row = add_derived_columns(
        build_pregame_features(
            completed,
            home_team_id=game.home_team_id,
            away_team_id=game.away_team_id,
            season=game.season,
            season_type=game.season_type,
            game_date=game.game_date,
            start_time=game.start_time,
            neutral_site=bool(game.neutral_site),
            game_id=game.id,
        )
    )

    try:
        engine = engine or get_game_winner_engine()
    except GameWinnerArtifactsMissingError as exc:
        raise ModelNotReadyError(str(exc)) from exc

    p_home, p_raw, cal_applied, prob_status = engine.predict_home_win_prob(row)
    p_away = 1.0 - p_home
    if not math.isfinite(p_home) or not math.isfinite(p_away):
        raise ModelNotReadyError("Invalid model probability")
    r = row.iloc[0]
    factors = GameOutcomeFactorsOut(
        home_elo=round(float(r["home_elo"]), 1),
        away_elo=round(float(r["away_elo"]), 1),
        elo_home_win_prob=round(float(r["elo_home_win_prob"]), 4),
        home_win_pct_season=round(float(r["home_win_pct_season"]), 4),
        away_win_pct_season=round(float(r["away_win_pct_season"]), 4),
        home_rest_days=round(float(r["home_rest_days"]), 1),
        away_rest_days=round(float(r["away_rest_days"]), 1),
        home_b2b=bool(r["home_b2b"]),
        away_b2b=bool(r["away_b2b"]),
        h2h_home_win_pct=round(float(r["h2h_home_win_pct"]), 4),
        neutral_site=bool(r["neutral_site"]),
        games_before_home=int(r.get("games_before_home", 0)),
        games_before_away=int(r.get("games_before_away", 0)),
    )
    return GameOutcomePredictionOut(
        game_id=game.id,
        home_team_id=game.home_team_id,
        away_team_id=game.away_team_id,
        home_team_name=home.display_name,
        away_team_name=away.display_name,
        start_time=game.start_time,
        home_win_probability=round(p_home, 4),
        away_win_probability=round(p_away, 4),
        model_home_win_probability_raw=round(p_raw, 4),
        calibration_applied=cal_applied,
        selected_model=engine.bundle.selected_model,
        model_version=engine.bundle.version,
        probability_status=prob_status,
        predicted_at=datetime.now(UTC),
        factors=factors,
    )


def reload_all_prediction_models() -> None:
    _PREPARED_LINE_CACHE.clear()
    reset_prediction_engine()
    reset_game_winner_engine()
