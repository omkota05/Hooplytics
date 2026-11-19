"""API-facing helpers around the v2 engine: projections, prop estimates, and line comparison."""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.categories import CATEGORIES
from app.config import get_settings
from app.ml.engine import artifacts as art
from app.ml.engine.data import ALL_CATEGORIES
from app.ml.engine.distribution import JointResidualDistribution
from app.ml.engine.service import (
    EngineService,
    InsufficientHistoryError,
    Projection,
    get_engine_service,
    last_sync_at,
    model_health,
)
from app.models import Game, Player, Team
from app.models.sportsbook import PropImportRun, PropOffer
from app.schemas.ml import (
    CategoryProjectionOut,
    ComparisonOut,
    ComparisonRowOut,
    FlagsOut,
    ModelStatusOut,
    PlayerProjectionOut,
    PropEstimateOut,
    UpcomingProjectionRowOut,
    UpcomingProjectionsOut,
)
from app.services.errors import BadRequestError, NotFoundError
from app.services.odds_archive_service import archive_status

MIN_ELIGIBLE_APPEARANCES = 10


def _flags() -> FlagsOut:
    s = get_settings()
    return FlagsOut(
        enable_ml_inference=s.enable_ml_inference,
        enable_ml_experimental_ui=s.enable_ml_experimental_ui,
        enable_ml_recommendations=s.enable_ml_recommendations,
        enable_ml_probabilities=s.enable_ml_probabilities,
    )


def status(session: Session, svc: EngineService | None = None) -> ModelStatusOut:
    svc = svc or get_engine_service()
    health = model_health(session, svc)
    out = ModelStatusOut(
        loaded=health.get("loaded", False),
        active_version=health["active_version"],
        previous_version=health["previous_version"],
        versions=health["versions"],
        final_games_since_training_cutoff=health.get("final_games_since_training_cutoff"),
        last_sync_at=health["last_sync_at"],
        flags=_flags(),
        warnings=health["warnings"],
        model_load_seconds=svc.last_load_seconds,
        last_batch_seconds=svc.last_batch_seconds,
        odds_archive=archive_status(session),
    )
    if out.loaded:
        m = svc.bundle().manifest
        out.trained_at = m.get("trained_at")
        out.dataset_cutoff = m.get("dataset_cutoff")
        out.feature_version = m.get("feature_version")
        out.split = m.get("split")
        out.selected_models = m.get("selected_models")
        out.probability_status = m.get("probability_status")
        out.probability_gates = m.get("probability_gates")
        out.acceptance_checks = m.get("acceptance_checks")
        out.timings_seconds = m.get("timings_seconds")
        out.data_validation = m.get("data_validation")
    return out


def metrics_summary(svc: EngineService | None = None) -> dict:
    """Evaluation artifacts trimmed for the dashboard (no per-opponent dumps by default)."""
    svc = svc or get_engine_service()
    b = svc.bundle()
    m = b.metrics
    test = {}
    for cat, d in m.get("test", {}).items():
        slices = {k: v for k, v in d.get("slices", {}).items() if k != "opponent"}
        test[cat] = {**{k: v for k, v in d.items() if k != "slices"}, "slices": slices}
    synth = {}
    for cat, d in m.get("synthetic_thresholds", {}).items():
        synth[cat] = d
    return {
        "version": b.version,
        "selection": m.get("selection"),
        "test": test,
        "minutes_model_test": m.get("minutes_model_test"),
        "synthetic_thresholds": synth,
        "real_lines": m.get("real_lines"),
        "feature_importance_validation": m.get("feature_importance_validation"),
        "split": b.manifest.get("split"),
    }


def _teams(session: Session, ids: set[int]) -> dict[int, Team]:
    return {t.id: t for t in session.scalars(select(Team).where(Team.id.in_(ids)))} if ids else {}


def _category_rows(svc: EngineService, proj: Projection, *, for_lab: bool) -> list[CategoryProjectionOut]:
    out = []
    for cat in ALL_CATEGORIES:
        samples = svc.category_samples(proj, cat)
        summ = JointResidualDistribution.summary(samples)
        allowed, st = svc.probability_state(cat, for_lab=for_lab)
        out.append(
            CategoryProjectionOut(
                category=cat,
                label=CATEGORIES[cat].label,
                mean=round(sum(proj.component_means[c] for c in CATEGORIES[cat].components), 2),
                median=summ["median"],
                p10=summ["p10"],
                p90=summ["p90"],
                sd=round(summ["sd"], 2),
                probability_status=st,
            )
        )
    return out


def player_projection(session: Session, player_id: int, game_id: int | None = None) -> PlayerProjectionOut:
    svc = get_engine_service()
    player = session.get(Player, player_id)
    if player is None:
        raise NotFoundError(f"Player {player_id} not found")
    try:
        proj = svc.project(session, player_id, game_id)
    except InsufficientHistoryError as exc:
        raise BadRequestError(str(exc)) from exc
    teams = _teams(session, {proj.team_id, proj.opponent_team_id})
    b = svc.bundle()
    return PlayerProjectionOut(
        player_id=player_id,
        player_name=player.full_name,
        team_id=proj.team_id,
        team_abbreviation=getattr(teams.get(proj.team_id), "abbreviation", None),
        opponent_team_id=proj.opponent_team_id,
        opponent_abbreviation=getattr(teams.get(proj.opponent_team_id), "abbreviation", None),
        game_id=proj.game_id,
        start_time=proj.start_time,
        is_home=proj.is_home,
        appearances=proj.appearances,
        season_appearances=proj.season_appearances,
        projected_minutes=round(proj.projected_minutes, 1),
        categories=_category_rows(svc, proj, for_lab=True),
        context=proj.features,
        warnings=proj.warnings,
        model_version=b.version,
        data_last_sync_at=last_sync_at(session),
        dataset_cutoff=b.manifest["dataset_cutoff"],
    )


def prop_estimate(session: Session, *, player_id: int, game_id: int, category: str, line: float, for_lab: bool = True) -> PropEstimateOut:
    if category not in ALL_CATEGORIES:
        raise BadRequestError(f"Category '{category}' is not modeled. Supported: {', '.join(ALL_CATEGORIES)}")
    if not (0 <= line <= 200):
        raise BadRequestError("line must be between 0 and 200")
    svc = get_engine_service()
    try:
        proj = svc.project(session, player_id, game_id)
    except InsufficientHistoryError as exc:
        raise BadRequestError(str(exc)) from exc
    samples = svc.category_samples(proj, category)
    summ = JointResidualDistribution.summary(samples)
    allowed, st = svc.probability_state(category, for_lab=for_lab)
    lp = JointResidualDistribution.line_probabilities(samples, line)
    if allowed:
        note = (
            "Validated on archived pregame sportsbook lines."
            if st == "validated_real_lines"
            else "Experimental: calibrated on synthetic pregame thresholds only, not validated on real sportsbook lines."
        )
    elif st == "disabled_by_flag":
        note = "Probabilities are disabled (ENABLE_ML_PROBABILITIES=false)."
    else:
        note = "Withheld: this category failed its calibration gate on held-out data."
    return PropEstimateOut(
        player_id=player_id,
        game_id=proj.game_id,
        category=category,
        line=line,
        mean=round(sum(proj.component_means[c] for c in CATEGORIES[category].components), 2),
        median=summ["median"],
        p10=summ["p10"],
        p90=summ["p90"],
        p_over=round(lp.p_over, 4) if allowed else None,
        p_under=round(lp.p_under, 4) if allowed else None,
        p_push=round(lp.p_push, 4) if allowed else None,
        probability_status=st,
        probability_note=note,
        n_samples=lp.n_samples,
        warnings=proj.warnings,
        model_version=svc.bundle().version,
    )


def upcoming(session: Session, *, team_id: int | None, limit: int, q: str | None) -> UpcomingProjectionsOut:
    svc = get_engine_service()
    batch = svc.batch(session)
    projs = [p for p in batch.values() if p.appearances >= 3 and (team_id is None or p.team_id == team_id)]
    players = {p.id: p for p in session.scalars(select(Player).where(Player.id.in_({p.player_id for p in projs})))} if projs else {}
    if q:
        needle = q.lower()
        projs = [p for p in projs if needle in players[p.player_id].full_name.lower()]
    projs.sort(key=lambda p: -(p.component_means["pts"] + p.component_means["reb"] + p.component_means["ast"]))
    teams = _teams(session, {p.team_id for p in projs} | {p.opponent_team_id for p in projs})
    rows = [
        UpcomingProjectionRowOut(
            player_id=p.player_id,
            player_name=players[p.player_id].full_name,
            team_abbreviation=getattr(teams.get(p.team_id), "abbreviation", None),
            opponent_abbreviation=getattr(teams.get(p.opponent_team_id), "abbreviation", None),
            game_id=p.game_id,
            start_time=p.start_time,
            projected_minutes=round(p.projected_minutes, 1),
            **{s: round(p.component_means[s], 2) for s in ("pts", "reb", "ast", "fg3m")},
            pra=round(p.component_means["pts"] + p.component_means["reb"] + p.component_means["ast"], 2),
            appearances=p.appearances,
            warnings=p.warnings,
        )
        for p in projs[:limit]
    ]
    return UpcomingProjectionsOut(rows=rows, total=len(projs), model_version=svc.bundle().version, batch_seconds=svc.last_batch_seconds)


def _gap_lean(mean: float, median: float, sd: float, line: float) -> tuple[float, str]:
    gap = (mean - line) / sd if sd > 0 else 0.0
    if median > line and mean > line:
        return gap, "over"
    if median < line and mean < line:
        return gap, "under"
    return gap, "neutral"


def comparison(
    session: Session,
    *,
    sportsbook: str | None = None,
    prizepicks_only: bool = False,
    category: str | None = None,
    game_date: date | None = None,
    player_query: str | None = None,
    side: str | None = None,
    min_sample: int = 0,
    eligible_only: bool = False,
    limit: int = 100,
) -> ComparisonOut:
    settings = get_settings()
    svc = get_engine_service()
    last_import = session.scalar(select(PropImportRun.finished_at).where(PropImportRun.status == "success").order_by(PropImportRun.id.desc()).limit(1))
    if not settings.enable_ml_inference or not settings.enable_ml_experimental_ui and not settings.enable_ml_recommendations:
        return ComparisonOut(mode="disabled", mode_explanation="ML inference or the experimental UI is disabled by configuration.", rows=[], total=0, total_offers_considered=0, model_version=None, last_import_finished_at=last_import, sportsbooks=[], gating={})
    b = svc.bundle()
    statuses = b.probability_status
    validated = {c for c, s in statuses.items() if s == "validated_real_lines"}
    mode = "validated" if settings.enable_ml_recommendations and validated else "experimental_comparison"
    explanation = (
        f"Ranking by model probability for categories validated on archived pregame lines: {', '.join(sorted(validated))}."
        if mode == "validated"
        else "Experimental projection comparison. No category has passed validation against archived pregame "
        "sportsbook lines (or ENABLE_ML_RECOMMENDATIONS is off), so rows are ordered by the descriptive projection "
        "gap, not by a probability of winning."
    )

    now = datetime.now(UTC)
    q = (
        select(PropOffer)
        .join(Game, Game.id == PropOffer.game_id)
        .where(
            PropOffer.is_active.is_(True),
            PropOffer.match_status == "matched",
            PropOffer.is_alternate_line.is_(False),
            PropOffer.player_id.is_not(None),
            Game.status == "scheduled",
            Game.start_time > now,
            PropOffer.category_key.in_(list(ALL_CATEGORIES)),
        )
    )
    if prizepicks_only:
        q = q.where(PropOffer.sportsbook_label == "PrizePicks")
    elif sportsbook:
        q = q.where(PropOffer.sportsbook_label == sportsbook)
    if category:
        q = q.where(PropOffer.category_key == category)
    if side in ("over", "under"):
        q = q.where(PropOffer.pick_side == side)
    if game_date:
        q = q.where(Game.game_date == game_date)
    offers = list(session.scalars(q).unique())
    books = sorted({o.sportsbook_label for o in offers})
    if player_query:
        needle = player_query.lower()
        offers = [o for o in offers if o.player and needle in o.player.full_name.lower()]

    batch = svc.batch(session) if offers else {}
    teams = _teams(session, {o.game.home_team_id for o in offers if o.game} | {o.game.away_team_id for o in offers if o.game})
    rows: list[ComparisonRowOut] = []
    sample_cache: dict[tuple[int, int, str], np.ndarray] = {}
    for o in offers:
        proj = batch.get((o.player_id, o.game_id))
        if proj is None:
            try:
                proj = svc.project(session, o.player_id, o.game_id)
            except InsufficientHistoryError:
                continue
        if proj.appearances < max(min_sample, 3):
            continue
        key = (o.player_id, o.game_id, o.category_key)
        if key not in sample_cache:
            sample_cache[key] = svc.category_samples(proj, o.category_key)
        samples = sample_cache[key]
        summ = JointResidualDistribution.summary(samples)
        mean = sum(proj.component_means[c] for c in CATEGORIES[o.category_key].components)
        gap, lean = _gap_lean(mean, summ["median"], summ["sd"], o.line)
        allowed, st = svc.probability_state(o.category_key, for_lab=False)
        p_side = None
        if allowed:
            lp = JointResidualDistribution.line_probabilities(samples, o.line)
            p_side = round(lp.p_over if o.pick_side == "over" else lp.p_under, 4)
        reasons = []
        if proj.appearances < MIN_ELIGIBLE_APPEARANCES:
            reasons.append(f"fewer than {MIN_ELIGIBLE_APPEARANCES} prior appearances")
        if statuses.get(o.category_key) == "unavailable":
            reasons.append("category failed calibration gate")
        if any(w.startswith(("team_change", "long_layoff")) for w in proj.warnings):
            reasons.append("projection warning")
        if mode == "validated" and o.category_key not in validated:
            reasons.append("category not validated on real lines")
        if eligible_only and reasons:
            continue
        rows.append(
            ComparisonRowOut(
                offer_id=o.id,
                player_id=o.player_id,
                player_name=o.player.full_name if o.player else (o.player_name_raw or "?"),
                team_abbreviation=getattr(teams.get(proj.team_id), "abbreviation", None),
                opponent_abbreviation=getattr(teams.get(proj.opponent_team_id), "abbreviation", None),
                game_id=o.game_id,
                start_time=o.game.start_time if o.game else proj.start_time,
                sportsbook=o.sportsbook_label,
                category=o.category_key,
                category_label=CATEGORIES[o.category_key].label,
                line=o.line,
                side=o.pick_side,
                american_odds=o.american_odds,
                projected_mean=round(mean, 2),
                projected_median=summ["median"],
                p10=summ["p10"],
                p90=summ["p90"],
                projection_gap=round(gap, 3),
                model_leans=lean,
                agrees_with_side=lean == o.pick_side,
                p_side=p_side,
                probability_status=st,
                l10_hit_pct=o.l10_hit_pct,
                l20_hit_pct=o.l20_hit_pct,
                l10_games=o.l10_games,
                l20_games=o.l20_games,
                hcs_score=o.hcs_score,
                appearances=proj.appearances,
                eligible=not reasons,
                ineligible_reasons=reasons,
                warnings=proj.warnings,
            )
        )
    if mode == "validated":
        rows.sort(key=lambda r: (not r.eligible, -(r.p_side or 0)))
    else:
        rows.sort(key=lambda r: (not r.eligible, not r.agrees_with_side, -abs(r.projection_gap)))
    return ComparisonOut(
        mode=mode,
        mode_explanation=explanation,
        rows=rows[:limit],
        total=len(rows),
        total_offers_considered=len(offers),
        model_version=b.version,
        last_import_finished_at=last_import,
        sportsbooks=books,
        gating={"probability_status": statuses, "rules": b.manifest.get("probability_gates", {}).get("rules"), "flags": _flags().model_dump()},
    )


def active_version_or_none() -> str | None:
    return art.active_version()
