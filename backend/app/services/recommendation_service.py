"""Aggregate ML player props and game-winner picks for upcoming games."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.categories import get_category
from app.analytics.windows import GameWindow
from app.ml.artifacts import ModelArtifactsMissingError, active_version as player_model_version
from app.models import Game, Player, SyncRun, Team
from app.ml.constants import MIN_GAMES_FOR_POINT_PREDICTION, PREDICTION_CATEGORIES
from app.ml.dataset import load_player_games
from app.ml.features import build_inference_row
from app.ml.game_winner.artifacts import active_version as gw_model_version
from app.ml.inference import PreparedPlayerGame, PredictionEngine, get_prediction_engine
from app.repositories import games as games_repo
from app.repositories import players as players_repo
from app.schemas.common import GameOut
from app.schemas.recommendations import (
    GameWinnerRecommendationOut,
    GameWinnerWarningOut,
    HistoricalWindowHitOut,
    PlayerPropRecommendationOut,
    RecommendationsMetaOut,
    RecommendationsOut,
    RecommendationsPipelineOut,
)
from app.services.analysis_service import build_analysis
from app.services.prediction_service import ModelNotReadyError, predict_game_outcome
from app.services.recommendation_lines import synthetic_line_from_recent_mean
from app.services.serializers import game_out, player_summary, team_out

logger = logging.getLogger("hooplytics")

CACHE_TTL_SECONDS = 3600
MIN_ROTATION_MINUTES = 8.0
MAX_PLAYERS_PER_TEAM = 12
ELO_DISAGREE_THRESHOLD = 0.15
EARLY_SEASON_GAMES_THRESHOLD = 5

_cache: dict[str, tuple[float, RecommendationsOut]] = {}


@dataclass
class _PropCandidate:
    rec: PlayerPropRecommendationOut
    sort_prob: float


def _last_sync_at(session: Session) -> datetime | None:
    return session.scalar(
        select(func.max(SyncRun.finished_at)).where(
            SyncRun.kind == "incremental", SyncRun.status.in_(("success", "partial"))
        )
    )


def _cache_key(session: Session, days: int, expand: bool) -> str:
    pv = player_model_version() or "none"
    gv = gw_model_version() or "none"
    sync_at = _last_sync_at(session)
    sync_tag = sync_at.isoformat() if sync_at else "never"
    return f"d{days}|e{int(expand)}|p{pv}|g{gv}|s{sync_tag}"


def _invalidate_stale() -> None:
    now = time.time()
    for key, (exp, _) in list(_cache.items()):
        if exp < now:
            del _cache[key]


def _historical_windows(
    session: Session,
    *,
    player_id: int,
    category_key: str,
    line: float,
    opponent: Team | None,
) -> list[HistoricalWindowHitOut]:
    logs = players_repo.player_game_logs(session, player_id)
    category = get_category(category_key)
    out: list[HistoricalWindowHitOut] = []
    for n, label in ((5, "L5"), (10, "L10"), (20, "L20")):
        analysis = build_analysis(
            player_id=player_id,
            logs=logs,
            category=category,
            line=line,
            window=GameWindow(kind="last_n", n=n),
            opponent=opponent,
        )
        lr = analysis.line_result
        out.append(
            HistoricalWindowHitOut(
                window=label,
                games=analysis.distribution.count,
                over_pct=lr.over_pct,
                under_pct=lr.under_pct,
                small_sample=analysis.small_sample,
            )
        )
    return out


def _rotation_players(session: Session, game: Game) -> list[tuple[Player, Team]]:
    """Pregame rotation estimate: recent minutes or current roster."""
    lines = games_repo.boxscore_lines(session, game.id)
    players: list[Player] = []
    if lines:
        seen: set[int] = set()
        for stat, player in lines:
            if stat.did_not_play or player.id in seen:
                continue
            seen.add(player.id)
            players.append(player)
    else:
        roster = players_repo.active_players_on_teams(session, [game.home_team_id, game.away_team_id])
        players = roster

    form = players_repo.recent_form(session, [p.id for p in players])
    scored: list[tuple[float, Player]] = []
    for p in players:
        minutes = (form.get(p.id) or {}).get("minutes") or 0.0
        if minutes >= MIN_ROTATION_MINUTES:
            scored.append((minutes, p))
    scored.sort(key=lambda x: -x[0])
    home_cap = away_cap = MAX_PLAYERS_PER_TEAM
    result: list[tuple[Player, Team]] = []
    home = session.get(Team, game.home_team_id)
    away = session.get(Team, game.away_team_id)
    for _m, p in scored:
        if p.current_team_id == game.home_team_id and home_cap > 0:
            result.append((p, away))
            home_cap -= 1
        elif p.current_team_id == game.away_team_id and away_cap > 0:
            result.append((p, home))
            away_cap -= 1
    return result


def _game_winner_warnings(
    outcome,
    *,
    home_games_before: int,
    away_games_before: int,
) -> list[GameWinnerWarningOut]:
    warnings: list[GameWinnerWarningOut] = []
    if outcome.probability_status != "available":
        warnings.append(
            GameWinnerWarningOut(
                code="experimental_model",
                message="Game-winner probability is experimental or limited; interpret with caution.",
            )
        )
    if home_games_before < EARLY_SEASON_GAMES_THRESHOLD or away_games_before < EARLY_SEASON_GAMES_THRESHOLD:
        warnings.append(
            GameWinnerWarningOut(
                code="early_season",
                message="Early-season sample: team form features may be noisy.",
            )
        )
    f = outcome.factors
    if f.home_win_pct_season in (0.0, 1.0) or f.away_win_pct_season in (0.0, 1.0):
        warnings.append(
            GameWinnerWarningOut(
                code="small_season_sample",
                message="A team has very few games in the current season window.",
            )
        )
    if abs(outcome.home_win_probability - f.elo_home_win_prob) >= ELO_DISAGREE_THRESHOLD:
        warnings.append(
            GameWinnerWarningOut(
                code="elo_model_gap",
                message="Production model and Elo disagree meaningfully; compare both estimates.",
            )
        )
    if outcome.calibration_applied and abs(outcome.model_home_win_probability_raw - outcome.home_win_probability) >= 0.08:
        warnings.append(
            GameWinnerWarningOut(
                code="calibration_shift",
                message="Isotonic calibration shifted the raw model probability.",
            )
        )
    return warnings


def _prepare_player_game(
    engine: PredictionEngine,
    player_histories: dict[int, __import__("pandas").DataFrame],
    *,
    player: Player,
    opponent: Team,
    game: Game,
) -> PreparedPlayerGame | None:
    history = player_histories.get(player.id)
    if history is None or history.empty:
        return None
    is_home = player.current_team_id == game.home_team_id
    try:
        row = build_inference_row(
            history,
            player_id=player.id,
            game_id=game.id,
            team_id=player.current_team_id,
            opponent_team_id=opponent.id,
            game_date=game.game_date,
            start_time=game.start_time,
            season=game.season,
            season_type=game.season_type,
            is_home=is_home,
            starter=True,
        )
        prepared = engine.prepare_player_game(row, player_id=player.id, game_id=game.id)
    except Exception:
        return None
    if prepared.games_before < MIN_GAMES_FOR_POINT_PREDICTION:
        return None
    return prepared


def _build_player_prop(
    session: Session,
    engine: PredictionEngine,
    *,
    player: Player,
    opponent: Team,
    game: Game,
    game_out_obj: GameOut,
    category_key: str,
    prepared: PreparedPlayerGame,
    logs: list,
    line: float | None = None,
    include_history: bool = True,
) -> _PropCandidate | None:
    category = get_category(category_key)
    if line is None:
        line = synthetic_line_from_recent_mean(logs, category)
        if line is None:
            return None

    games_before = prepared.games_before

    lp = engine.line_probability_prepared(prepared, category_key, line)
    if lp.p_over is None or lp.p_under is None:
        return None

    p_over, p_under = lp.p_over, lp.p_under
    if p_over >= p_under:
        pick, sort_prob = "over", p_over
    else:
        pick, sort_prob = "under", p_under

    from app.ml.constants import MIN_GAMES_FOR_PROBABILITIES

    if games_before < MIN_GAMES_FOR_PROBABILITIES:
        prob_status = "experimental"
    else:
        prob_status = "available"

    hit = (
        _historical_windows(session, player_id=player.id, category_key=category_key, line=line, opponent=opponent)
        if include_history
        else []
    )
    proj = lp.projection
    href = f"/players/{player.id}?stat={category_key}&opponent={opponent.id}&game={game.id}&line={line}"

    rec = PlayerPropRecommendationOut(
        player=player_summary(player),
        opponent=team_out(opponent),
        game=game_out_obj,
        category=category_key,
        category_label=category.label,
        line=line,
        line_source="synthetic_l10_half",
        predicted_mean=round(proj.mean, 2),
        predicted_std_dev=round(proj.std_dev, 2),
        pick_side=pick,
        model_probability=round(sort_prob, 4),
        p_over=round(p_over, 4),
        p_under=round(p_under, 4),
        probability_status=prob_status,
        games_used=games_before,
        historical_hit_rates=hit,
        model_version=proj.model_version,
        player_analysis_href=href,
    )
    return _PropCandidate(rec=rec, sort_prob=sort_prob)


def generate_recommendations(
    session: Session,
    *,
    days: int = 7,
    expand_player_props: bool = False,
) -> RecommendationsOut:
    _invalidate_stale()
    key = _cache_key(session, days, expand_player_props)
    now = time.time()
    if key in _cache and _cache[key][0] > now:
        return _cache[key][1]

    t0 = time.perf_counter()
    errors: list[str] = []
    player_ver: str | None = None
    gw_ver: str | None = None
    props: list[_PropCandidate] = []
    winners: list[GameWinnerRecommendationOut] = []
    pipeline = RecommendationsPipelineOut(upcoming_games=0)

    try:
        engine = get_prediction_engine()
        player_ver = engine.bundle.version
    except ModelArtifactsMissingError as exc:
        errors.append(f"Player ML unavailable: {exc}")

    games = games_repo.upcoming_games(
        session,
        now=datetime.now(UTC),
        until=datetime.now(UTC) + timedelta(days=days),
    )
    pipeline.upcoming_games = len(games)
    game_outs = {g.id: game_out(g) for g in games}

    raw_games = load_player_games(session) if player_ver else None
    player_histories: dict[int, __import__("pandas").DataFrame] = {}
    if raw_games is not None and not raw_games.empty:
        played = raw_games[~raw_games["did_not_play"]]
        for pid, grp in played.groupby("player_id"):
            player_histories[int(pid)] = grp.copy()

    logs_cache: dict[int, list] = {}
    prep_cache: dict[tuple[int, int], PreparedPlayerGame] = {}

    def _player_logs(player_id: int) -> list:
        if player_id not in logs_cache:
            logs_cache[player_id] = players_repo.player_game_logs(session, player_id)
        return logs_cache[player_id]

    if player_ver and engine and raw_games is not None:
        for game in games:
            gout = game_outs[game.id]
            rotation = _rotation_players(session, game)
            pipeline.rotation_player_slots += len(rotation)
            for player, opponent in rotation:
                if opponent is None:
                    continue
                pg_key = (player.id, game.id)
                prepared = prep_cache.get(pg_key)
                if prepared is None:
                    prepared = _prepare_player_game(
                        engine, player_histories, player=player, opponent=opponent, game=game
                    )
                    if prepared is None:
                        pipeline.props_skipped_ml += len(PREDICTION_CATEGORIES)
                        pipeline.ml_prop_attempts += len(PREDICTION_CATEGORIES)
                        continue
                    prep_cache[pg_key] = prepared
                plogs = _player_logs(player.id)
                for cat in PREDICTION_CATEGORIES:
                    pipeline.ml_prop_attempts += 1
                    category = get_category(cat)
                    line = synthetic_line_from_recent_mean(plogs, category)
                    if line is None:
                        pipeline.props_skipped_no_line += 1
                        continue
                    try:
                        cand = _build_player_prop(
                            session,
                            engine,
                            player=player,
                            opponent=opponent,
                            game=game,
                            game_out_obj=gout,
                            category_key=cat,
                            prepared=prepared,
                            logs=plogs,
                            line=line,
                            include_history=False,
                        )
                        if cand:
                            props.append(cand)
                        else:
                            pipeline.props_skipped_ml += 1
                    except Exception as exc:
                        pipeline.props_skipped_ml += 1
                        logger.warning("prop skip player=%s cat=%s: %s", player.id, cat, exc)
    elif not player_ver:
        errors.append("Player prop recommendations require trained player-stat models (make ml-train).")

    pipeline.props_candidates_before_dedupe = len(props)

    # Deduplicate: best pick per player per game (or per category if expanded).
    best: dict[tuple, _PropCandidate] = {}
    for cand in props:
        key_p = (
            cand.rec.player.id,
            cand.rec.game.id,
            cand.rec.category if expand_player_props else None,
        )
        prev = best.get(key_p)
        if prev is None or cand.sort_prob > prev.sort_prob:
            best[key_p] = cand
    player_props = sorted([v.rec for v in best.values()], key=lambda r: -r.model_probability)
    for rec in player_props:
        if not rec.historical_hit_rates:
            opp = session.get(Team, rec.opponent.id)
            rec.historical_hit_rates = _historical_windows(
                session,
                player_id=rec.player.id,
                category_key=rec.category,
                line=rec.line,
                opponent=opp,
            )
    pipeline.props_after_dedupe = len(player_props)
    pipeline.player_game_prepares = len(prep_cache) if player_ver else 0

    for game in games:
        try:
            outcome = predict_game_outcome(session, game_id=game.id)
            gw_ver = outcome.model_version
            gout = game_outs[game.id]
            warnings = _game_winner_warnings(
                outcome,
                home_games_before=outcome.factors.games_before_home,
                away_games_before=outcome.factors.games_before_away,
            )
            pred_id = (
                gout.home_team.id
                if outcome.home_win_probability >= outcome.away_win_probability
                else gout.away_team.id
            )
            winners.append(
                GameWinnerRecommendationOut(
                    game=gout,
                    home_win_probability=outcome.home_win_probability,
                    away_win_probability=outcome.away_win_probability,
                    model_home_win_probability_raw=outcome.model_home_win_probability_raw,
                    calibration_applied=outcome.calibration_applied,
                    elo_home_win_probability=outcome.factors.elo_home_win_prob,
                    predicted_winner_team_id=pred_id,
                    selected_model=outcome.selected_model,
                    model_version=outcome.model_version,
                    probability_status=outcome.probability_status,
                    factors=outcome.factors,
                    warnings=warnings,
                    matchup_href=f"/matchups/{game.id}",
                )
            )
        except ModelNotReadyError as exc:
            errors.append(f"Game winner ML unavailable for game {game.id}: {exc}")
        except Exception as exc:
            errors.append(f"Game {game.id}: {exc}")

    sync_at = _last_sync_at(session)
    meta = RecommendationsMetaOut(
        generated_at=datetime.now(UTC),
        player_model_version=player_ver,
        game_winner_model_version=gw_ver,
        upcoming_games_scanned=len(games),
        player_props_generated=len(player_props),
        game_winners_generated=len(winners),
        data_sync_reference=sync_at.isoformat() if sync_at else None,
        disclaimer=(
            "Synthetic lines and ML probabilities are experimental analytics, not sportsbook odds "
            "or betting advice."
        ),
        pipeline=pipeline,
        generation_ms=round((time.perf_counter() - t0) * 1000, 1),
    )
    out = RecommendationsOut(
        meta=meta,
        player_props=player_props,
        game_winners=winners,
        categories=list(PREDICTION_CATEGORIES),
        errors=errors,
    )
    _cache[key] = (now + CACHE_TTL_SECONDS, out)
    return out


def filter_recommendations(
    bundle: RecommendationsOut,
    *,
    game_id: int | None = None,
    team_id: int | None = None,
    category: str | None = None,
    side: str | None = None,
    min_probability: float | None = None,
    player_query: str | None = None,
    game_date: date | None = None,
    sort: str = "probability",
) -> RecommendationsOut:
    props = list(bundle.player_props)
    before_filter = len(props)
    if game_id is not None:
        props = [p for p in props if p.game.id == game_id]
    if team_id is not None:
        props = [
            p
            for p in props
            if p.player.team and p.player.team.id == team_id
            or p.opponent.id == team_id
        ]
    if category:
        props = [p for p in props if p.category == category]
    if side in ("over", "under"):
        props = [p for p in props if p.pick_side == side]
    if min_probability is not None:
        props = [p for p in props if p.model_probability >= min_probability]
    if player_query:
        q = player_query.lower()
        props = [p for p in props if q in p.player.full_name.lower()]
    if game_date is not None:
        props = [p for p in props if p.game.game_date == game_date]

    winners = bundle.game_winners
    if game_id is not None:
        winners = [w for w in winners if w.game.id == game_id]
    if team_id is not None:
        winners = [
            w
            for w in winners
            if w.game.home_team.id == team_id or w.game.away_team.id == team_id
        ]
    if game_date is not None:
        winners = [w for w in winners if w.game.game_date == game_date]

    if sort == "probability":
        props = sorted(props, key=lambda p: -p.model_probability)
    elif sort == "time":
        props = sorted(props, key=lambda p: p.game.start_time)
    elif sort == "player":
        props = sorted(props, key=lambda p: p.player.full_name)

    winners = sorted(winners, key=lambda w: -max(w.home_win_probability, w.away_win_probability))

    meta = bundle.meta.model_copy(deep=True)
    meta.pipeline = meta.pipeline.model_copy(deep=True)
    meta.pipeline.props_filtered_by_query = max(0, before_filter - len(props))

    return RecommendationsOut(
        meta=meta,
        player_props=props,
        game_winners=winners,
        categories=bundle.categories,
        errors=bundle.errors,
    )


def clear_recommendation_cache() -> None:
    _cache.clear()
