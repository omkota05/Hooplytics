"""Prospective forecast archive: record before tip-off, settle after box scores, summarize.

Recording reuses the engine's cached batch projections (no training, no provider calls) and
the odds already archived by scheduled imports. Inserts use ON CONFLICT DO NOTHING on
(player, game, model version), so the first pregame forecast is kept and never recomputed;
the database trigger rejects any later change to prediction columns.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ml.engine.data import ALL_CATEGORIES, TARGETS, components
from app.ml.engine.evaluation import vectorized_category_probs, vectorized_category_quantiles
from app.ml.engine.features import FEATURE_VERSION
from app.ml.engine.models import BASELINES, baseline_predict
from app.ml.engine.service import MIN_APPEARANCES, EngineService, get_engine_service
from app.models import Game
from app.models.ml_forecast import MlForecast, MlForecastLine

logger = logging.getLogger("hooplytics.ml")

HORIZON_HOURS = 36
QUANTILES = (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)
QUANTILE_KEYS = ("p05", "p10", "p25", "p50", "p75", "p90", "p95")
MIN_SETTLED_FOR_CLAIMS = 1000
MIN_GAMES_FOR_CLAIMS = 50


def record_forecasts(
    session: Session, *, now: datetime | None = None, horizon_hours: int = HORIZON_HOURS, svc: EngineService | None = None
) -> dict:
    """Persist forecasts for games tipping off within the horizon. Idempotent."""
    t0 = time.perf_counter()
    now = now or datetime.now(UTC)
    svc = svc or get_engine_service()
    bundle = svc.bundle()
    batch = svc.batch(session)
    snapshot = svc._state_for(session).snapshot
    projs = [p for p in batch.values() if p.appearances >= MIN_APPEARANCES]
    game_ids = {p.game_id for p in projs}
    games = {
        g.id: g
        for g in session.scalars(select(Game).where(Game.id.in_(game_ids), Game.status == "scheduled")).all()
    } if game_ids else {}
    horizon = now + timedelta(hours=horizon_hours)
    projs = [p for p in projs if p.game_id in games and now < games[p.game_id].start_time <= horizon]
    stats = {"candidates": len(projs), "inserted": 0, "already_recorded": 0, "lines_inserted": 0}
    if projs:
        means = np.array([[p.component_means[s] for s in TARGETS] for p in projs])
        quant = {c: vectorized_category_quantiles(bundle.distribution, means, c, QUANTILES) for c in ALL_CATEGORIES}
        feat = pd.DataFrame([p.features for p in projs]).astype(float)
        base = {k: {s: baseline_predict(feat, s, k) for s in TARGETS} for k in BASELINES}
        rows = []
        for i, p in enumerate(projs):
            cat_means = {c: float(sum(means[i, TARGETS.index(x)] for x in components(c))) for c in ALL_CATEGORIES}
            rows.append(
                {
                    "player_id": p.player_id,
                    "game_id": p.game_id,
                    "team_id": p.team_id,
                    "opponent_team_id": p.opponent_team_id,
                    "predicted_at": now,
                    "scheduled_tipoff": games[p.game_id].start_time,
                    "model_version": bundle.version,
                    "feature_version": FEATURE_VERSION,
                    "data_snapshot": snapshot,
                    "appearances": p.appearances,
                    "season_appearances": p.season_appearances,
                    "projected_minutes": round(p.projected_minutes, 3),
                    **{f"proj_{c}": round(v, 4) for c, v in cat_means.items()},
                    "quantiles": {c: dict(zip(QUANTILE_KEYS, map(float, quant[c][i]), strict=True)) for c in ALL_CATEGORIES},
                    "baselines": {
                        k: {s: (None if np.isnan(v[s][i]) else round(float(v[s][i]), 4)) for s in TARGETS} for k, v in base.items()
                    },
                    "context": {k: v for k, v in p.features.items() if v is not None},
                    "warnings": p.warnings,
                    "probability_status": dict(bundle.probability_status),
                }
            )
        for start in range(0, len(rows), 500):
            chunk = rows[start : start + 500]
            res = session.execute(
                insert(MlForecast)
                .values(chunk)
                .on_conflict_do_nothing(constraint="uq_ml_forecast_player_game_model")
                .returning(MlForecast.id)
            )
            stats["inserted"] += len(res.scalars().all())
        stats["already_recorded"] = len(rows) - stats["inserted"]
        stats["lines_inserted"] = _record_lines(session, bundle, now, [g for g in games if now < games[g].start_time <= horizon])
    session.flush()
    stats["seconds"] = round(time.perf_counter() - t0, 3)
    return stats


def _record_lines(session: Session, bundle, now: datetime, game_ids: list[int]) -> int:
    """Attach the currently live, pregame-observed archived lines to this model's open forecasts."""
    if not game_ids:
        return 0
    cand = pd.DataFrame(
        session.execute(
            text(
                """
                SELECT f.id AS forecast_id, f.scheduled_tipoff, f.proj_pts, f.proj_reb, f.proj_ast, f.proj_fg3m,
                       s.id AS snapshot_id, s.sportsbook_label, s.category_key, s.line, s.pick_side,
                       s.american_odds, s.last_observed_at
                FROM ml_forecasts f
                JOIN prop_offer_snapshots s ON s.player_id = f.player_id AND s.game_id = f.game_id
                JOIN prop_offers o ON o.id = s.offer_id AND o.is_active
                WHERE f.model_version = :v AND f.game_id = ANY(:g) AND f.scheduled_tipoff > :now
                  AND s.is_latest AND NOT s.is_alternate_line AND s.last_observed_at < f.scheduled_tipoff
                  AND s.category_key = ANY(:cats)
                """
            ),
            {"v": bundle.version, "g": list(game_ids), "now": now, "cats": list(ALL_CATEGORIES)},
        ).mappings().all()
    )
    if cand.empty:
        return 0
    means = cand[[f"proj_{s}" for s in TARGETS]].to_numpy(dtype=float)
    p_over = np.full(len(cand), np.nan)
    p_under = np.full(len(cand), np.nan)
    for cat in ALL_CATEGORIES:
        m = (cand["category_key"] == cat).to_numpy()
        if m.any():
            po, pu, _, _, _ = vectorized_category_probs(bundle.distribution, means[m], cat, cand.loc[m, "line"].to_numpy(dtype=float))
            p_over[m], p_under[m] = po, pu
    cat_mean = np.array([sum(means[i, TARGETS.index(c)] for c in components(k)) for i, k in enumerate(cand["category_key"])])
    rows = [
        {
            "forecast_id": int(r.forecast_id),
            "snapshot_id": int(r.snapshot_id),
            "sportsbook_label": r.sportsbook_label,
            "category_key": r.category_key,
            "line": float(r.line),
            "pick_side": r.pick_side,
            "american_odds": None if pd.isna(r.american_odds) else int(r.american_odds),
            "offer_observed_at": r.last_observed_at,
            "recorded_at": now,
            "scheduled_tipoff": r.scheduled_tipoff,
            "model_mean": round(float(cat_mean[i]), 4),
            "model_p_over": round(float(p_over[i]), 5),
            "model_p_under": round(float(p_under[i]), 5),
        }
        for i, r in enumerate(cand.itertuples(index=False))
    ]
    inserted = 0
    for start in range(0, len(rows), 2000):
        res = session.execute(
            insert(MlForecastLine).values(rows[start : start + 2000]).on_conflict_do_nothing(constraint="uq_ml_forecast_line").returning(MlForecastLine.id)
        )
        inserted += len(res.scalars().all())
    return inserted


SETTLE_SQL = text(
    """
    WITH cand AS (
      SELECT f.id,
             CASE
               WHEN g.status IN ('postponed', 'canceled', 'cancelled') THEN 'void_game'
               WHEN p.player_id IS NULL THEN 'unresolved'
               WHEN p.did_not_play OR COALESCE(p.minutes, 0) <= 0 THEN 'void_dnp'
               WHEN p.pts IS NULL OR p.reb IS NULL OR p.ast IS NULL OR p.fg3m IS NULL THEN 'unresolved'
               ELSE 'settled'
             END AS new_status,
             p.minutes, p.pts, p.reb, p.ast, p.fg3m
      FROM ml_forecasts f
      JOIN games g ON g.id = f.game_id
      LEFT JOIN player_game_stats p ON p.game_id = f.game_id AND p.player_id = f.player_id
      WHERE f.status IN ('pending', 'unresolved')
        AND ((g.status = 'final' AND g.boxscore_synced_at IS NOT NULL) OR g.status IN ('postponed', 'canceled', 'cancelled'))
    )
    UPDATE ml_forecasts f
    SET status = c.new_status,
        settled_at = :now,
        actual_minutes = CASE WHEN c.new_status = 'settled' THEN c.minutes END,
        actual_pts = CASE WHEN c.new_status = 'settled' THEN c.pts END,
        actual_reb = CASE WHEN c.new_status = 'settled' THEN c.reb END,
        actual_ast = CASE WHEN c.new_status = 'settled' THEN c.ast END,
        actual_fg3m = CASE WHEN c.new_status = 'settled' THEN c.fg3m END
    FROM cand c
    WHERE f.id = c.id AND f.status IS DISTINCT FROM c.new_status
    RETURNING c.new_status
    """
)


def settle_forecasts(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Grade open forecasts whose games are final. Re-running changes nothing already graded."""
    out: dict[str, int] = {}
    for (status,) in session.execute(SETTLE_SQL, {"now": now or datetime.now(UTC)}).all():
        out[status] = out.get(status, 0) + 1
    return out


def _minutes_tier(m: pd.Series) -> pd.Series:
    return pd.cut(m.fillna(0), [0, 15, 25, 32, 100], labels=["<15", "15-25", "25-32", "32+"], right=False).astype(str)


def _usage_tier(share: pd.Series) -> pd.Series:
    return pd.cut(share, [-1, 0.12, 0.2, 2], labels=["low <12% FGA", "mid 12-20%", "high 20%+"], right=False).astype(str).replace("nan", "unknown")


def forecast_summary(session: Session) -> dict:
    counts = dict(session.execute(text("SELECT status, COUNT(*) FROM ml_forecasts GROUP BY status")).all())
    lines = session.execute(text("SELECT COUNT(*), COUNT(DISTINCT forecast_id) FROM ml_forecast_lines")).one()
    first_last = session.execute(text("SELECT MIN(predicted_at), MAX(predicted_at), COUNT(DISTINCT game_id) FROM ml_forecasts")).one()
    out: dict = {
        "forecasts_recorded": int(sum(counts.values())),
        "by_status": {k: int(v) for k, v in counts.items()},
        "forecasts_settled": int(counts.get("settled", 0)),
        "forecasts_unresolved": int(counts.get("unresolved", 0)),
        "forecasts_pending": int(counts.get("pending", 0)),
        "games_forecast": int(first_last[2] or 0),
        "first_predicted_at": first_last[0],
        "last_predicted_at": first_last[1],
        "lines_recorded": int(lines[0]),
        "forecasts_with_lines": int(lines[1]),
        "warnings": [],
        "categories": {},
        "by_model_version": {},
        "by_minutes_tier": {},
        "by_usage_tier": {},
    }
    df = pd.DataFrame(
        session.execute(
            text(
                """
                SELECT game_id, model_version, scheduled_tipoff, predicted_at, proj_pts, proj_reb, proj_ast, proj_fg3m,
                       quantiles, baselines, context, actual_pts, actual_reb, actual_ast, actual_fg3m
                FROM ml_forecasts WHERE status = 'settled'
                """
            )
        ).mappings().all()
    )
    n_games = int(df["game_id"].nunique()) if len(df) else 0
    out["games_settled"] = n_games
    if len(df) < MIN_SETTLED_FOR_CLAIMS or n_games < MIN_GAMES_FOR_CLAIMS:
        out["warnings"].append(
            f"insufficient_sample: {len(df)} settled forecasts over {n_games} games "
            f"(need >= {MIN_SETTLED_FOR_CLAIMS} and >= {MIN_GAMES_FOR_CLAIMS} games before drawing conclusions)"
        )
    if df.empty:
        return out
    df["minutes_tier"] = _minutes_tier(df["context"].map(lambda c: c.get("minutes_l10")))
    df["usage_tier"] = _usage_tier(df["context"].map(lambda c: c.get("fga_share_l10")).astype(float))

    def metrics(sub: pd.DataFrame, cat: str) -> dict:
        y = sum(sub[f"actual_{c}"].to_numpy(dtype=float) for c in components(cat))
        p = sum(sub[f"proj_{c}"].to_numpy(dtype=float) for c in components(cat))
        e = p - y
        res = {"n": int(len(sub)), "games": int(sub["game_id"].nunique()), "mae": float(np.mean(np.abs(e))),
               "rmse": float(np.sqrt(np.mean(e**2))), "bias": float(np.mean(e)), "baselines": {}}
        for k in ("weighted", "last_10", "season_avg"):
            b = sum(sub["baselines"].map(lambda d, c=c, k=k: d[k][c]).astype(float).to_numpy() for c in components(cat))
            ok = np.isfinite(b)
            if ok.any():
                res["baselines"][k] = {"n": int(ok.sum()), "mae": float(np.mean(np.abs(b[ok] - y[ok]))), "model_mae_same_rows": float(np.mean(np.abs(e[ok])))}
        for name, lo, hi in (("50", "p25", "p75"), ("80", "p10", "p90"), ("90", "p05", "p95")):
            qlo = sub["quantiles"].map(lambda d, lo=lo: d[cat][lo]).to_numpy(dtype=float)
            qhi = sub["quantiles"].map(lambda d, hi=hi: d[cat][hi]).to_numpy(dtype=float)
            res[f"coverage_{name}"] = float(np.mean((y >= qlo) & (y <= qhi)))
            res[f"mean_width_{name}"] = float(np.mean(qhi - qlo))
        return res

    out["categories"] = {cat: metrics(df, cat) for cat in ALL_CATEGORIES}
    for key, target in (("model_version", "by_model_version"), ("minutes_tier", "by_minutes_tier"), ("usage_tier", "by_usage_tier")):
        out[target] = {
            str(k): {cat: {m: v for m, v in metrics(g, cat).items() if m in ("n", "games", "mae", "bias", "coverage_80")} for cat in ("pts", "reb", "ast", "pts_reb_ast")}
            for k, g in df.groupby(key)
        }
    return out


def run_forecast_cycle(*, record: bool = True) -> None:
    """Settle finished forecasts, then record new pregame ones. Background-safe and non-fatal."""
    from app.config import get_settings
    from app.db import session_scope

    if not get_settings().enable_ml_inference:
        return
    try:
        with session_scope() as session:
            settled = settle_forecasts(session)
        if settled:
            logger.info("Settled ML forecasts: %s", settled)
        if record:
            with session_scope() as session:
                stats = record_forecasts(session)
            logger.info("Recorded ML forecasts: %s", stats)
    except Exception:
        logger.exception("ML forecast cycle failed (non-fatal)")
