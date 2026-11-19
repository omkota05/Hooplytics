"""Inference for upcoming games using saved v2 artifacts.

The model is loaded lazily on first ML request (never at startup) and never retrained here.
Pregame features for every player's next scheduled game are computed in one batch per data
snapshot and cached; a request for any other game builds a single extra row. Caches are keyed
by model version + data snapshot, so new box scores or schedule changes invalidate them.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ml.engine import artifacts as art
from app.ml.engine.data import (
    ALL_CATEGORIES,
    TARGETS,
    components,
    data_snapshot_key,
    load_raw,
    validate_and_clean,
)
from app.ml.engine.distribution import JointResidualDistribution
from app.ml.engine.features import FEATURE_SETS, build_features
from app.models import Game, Player, SyncRun

logger = logging.getLogger("hooplytics.ml")

MIN_APPEARANCES = 3
LIMITED_HISTORY = 10
BATCH_DAYS = 7
STALE_MODEL_DAYS = 45


class EngineUnavailableError(RuntimeError):
    pass


class InsufficientHistoryError(ValueError):
    pass


@dataclass
class Projection:
    player_id: int
    game_id: int
    team_id: int
    opponent_team_id: int
    is_home: bool
    start_time: datetime
    appearances: int
    season_appearances: int
    component_means: dict[str, float]
    projected_minutes: float
    features: dict[str, float | None]
    warnings: list[str] = field(default_factory=list)


@dataclass
class _State:
    snapshot: str
    hist: pd.DataFrame
    built_at: float
    batch: dict[tuple[int, int], Projection] = field(default_factory=dict)
    single: dict[tuple[int, int], Projection] = field(default_factory=dict)


_CONTEXT_FEATURES = (
    "pts_l10", "reb_l10", "ast_l10", "fg3m_l10", "minutes_l10", "minutes_l20", "pts_season", "reb_season",
    "ast_season", "fg3m_season", "fga_l10", "fg3a_l10", "fga_share_l10", "start_rate_l10", "days_since_last_app",
    "team_rest_days", "b2b", "opp_allowed_pts_l10", "opp_allowed_reb_l10", "opp_allowed_ast_l10",
    "opp_allowed_fg3m_l10", "opp_team_pace_l10", "h2h_n", "h2h_delta_pts", "team_changed", "minutes_trend",
    "pts_l5", "reb_l5", "ast_l5", "fg3m_l5", "pts_l20", "reb_l20", "ast_l20", "fg3m_l20",
    "pts_ewm", "reb_ewm", "ast_ewm", "fg3m_ewm", "minutes_std10",
)


class EngineService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._bundle: art.EngineBundle | None = None
        self._load_error: str | None = None
        self._state: _State | None = None
        self.last_load_seconds: float | None = None
        self.last_batch_seconds: float | None = None

    # ---- model -------------------------------------------------------------------------
    def bundle(self) -> art.EngineBundle:
        if not get_settings().enable_ml_inference:
            raise EngineUnavailableError("ML inference disabled (ENABLE_ML_INFERENCE=false)")
        with self._lock:
            active = art.active_version()
            if self._bundle is None or self._bundle.version != active:
                t0 = time.perf_counter()
                try:
                    self._bundle = art.load_bundle(active)
                    self._load_error = None
                except (art.EngineArtifactsMissingError, art.EngineArtifactsIncompatibleError) as exc:
                    self._bundle = None
                    self._load_error = str(exc)
                    raise EngineUnavailableError(str(exc)) from exc
                self.last_load_seconds = round(time.perf_counter() - t0, 3)
                self._state = None
            return self._bundle

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def reset(self) -> None:
        with self._lock:
            self._bundle = None
            self._state = None

    # ---- data --------------------------------------------------------------------------
    def _state_for(self, session: Session) -> _State:
        snap = data_snapshot_key(session)
        with self._lock:
            if self._state is None or self._state.snapshot != snap:
                hist, _ = validate_and_clean(load_raw(session))
                self._state = _State(snapshot=snap, hist=hist, built_at=time.time())
            return self._state

    def _upcoming_rows(self, session: Session, *, days: int, game_id: int | None = None, player_id: int | None = None) -> pd.DataFrame:
        now = datetime.now(UTC)
        q = select(Game).where(Game.status.in_(("scheduled",)), Game.start_time > now)
        if game_id is not None:
            q = select(Game).where(Game.id == game_id)
        else:
            q = q.where(Game.start_time <= now + timedelta(days=days))
        games = session.scalars(q.order_by(Game.start_time)).all()
        if not games:
            return pd.DataFrame()
        team_ids = {g.home_team_id for g in games} | {g.away_team_id for g in games}
        pq = select(Player.id, Player.current_team_id).where(Player.is_active.is_(True), Player.current_team_id.in_(team_ids))
        if player_id is not None:
            pq = pq.where(Player.id == player_id)
        roster: dict[int, list[int]] = {}
        for pid, tid in session.execute(pq).all():
            roster.setdefault(tid, []).append(pid)
        rows = []
        seen: set[int] = set()
        for g in games:  # chronological: first match is each player's next game
            for tid, oid, home in ((g.home_team_id, g.away_team_id, True), (g.away_team_id, g.home_team_id, False)):
                for pid in roster.get(tid, []):
                    if pid in seen:
                        continue
                    seen.add(pid)
                    rows.append(
                        {
                            "player_id": pid, "game_id": g.id, "team_id": tid, "opponent_team_id": oid,
                            "season": g.season, "season_type": g.season_type, "is_home": home,
                            "start_time": g.start_time, "game_date": g.game_date,
                        }
                    )
        return pd.DataFrame(rows)

    def _project_frame(self, bundle: art.EngineBundle, feats: pd.DataFrame) -> list[Projection]:
        rows = feats[feats["is_upcoming"]]
        if rows.empty:
            return []
        preds = {s: bundle.models[s].predict(rows) for s in TARGETS}
        mins = bundle.minutes_model.predict(rows)
        ranges = bundle.manifest.get("feature_ranges", {})
        out: list[Projection] = []
        for i, (_, r) in enumerate(rows.iterrows()):
            warnings: list[str] = []
            apps = int(r["appearances"])
            if apps < LIMITED_HISTORY:
                warnings.append(f"limited_history: {apps} prior appearances in synced data")
            if r.get("team_changed", 0) == 1:
                warnings.append("team_change: first game(s) with a new team; history is from the previous role")
            if (r.get("days_since_last_app") or 0) >= 10:
                warnings.append("long_layoff: 10+ days since last appearance (possible injury return; minutes uncertain)")
            missing = [c for c in FEATURE_SETS["core"] if pd.isna(r.get(c))]
            if missing:
                warnings.append(f"missing_features: {', '.join(missing[:6])}{'…' if len(missing) > 6 else ''}")
            ood = [c for c, (lo, hi) in ranges.items() if pd.notna(r.get(c)) and not (lo <= float(r[c]) <= hi)]
            if ood:
                warnings.append(f"out_of_distribution: {', '.join(ood[:5])}")
            out.append(
                Projection(
                    player_id=int(r["player_id"]), game_id=int(r["game_id"]), team_id=int(r["team_id"]),
                    opponent_team_id=int(r["opponent_team_id"]), is_home=bool(r["is_home"]),
                    start_time=pd.Timestamp(r["start_time"]).to_pydatetime(), appearances=apps,
                    season_appearances=int(r["season_appearances"]),
                    component_means={s: float(preds[s][i]) for s in TARGETS},
                    projected_minutes=float(mins[i]),
                    features={c: (None if pd.isna(r.get(c)) else float(r[c])) for c in _CONTEXT_FEATURES},
                    warnings=warnings,
                )
            )
        return out

    def batch(self, session: Session, *, days: int = BATCH_DAYS) -> dict[tuple[int, int], Projection]:
        bundle = self.bundle()
        state = self._state_for(session)
        with self._lock:
            if state.batch:
                return state.batch
            t0 = time.perf_counter()
            up = self._upcoming_rows(session, days=days)
            if not up.empty:
                up = up[~up["player_id"].isin(set(up["player_id"]) - set(state.hist["player_id"]))]
            feats = build_features(state.hist, up if not up.empty else None)
            state.batch = {(p.player_id, p.game_id): p for p in self._project_frame(bundle, feats)}
            self.last_batch_seconds = round(time.perf_counter() - t0, 3)
            logger.info("ML batch projections: %d player-games in %.2fs", len(state.batch), self.last_batch_seconds)
            return state.batch

    def project(self, session: Session, player_id: int, game_id: int | None = None) -> Projection:
        batch = self.batch(session)
        if game_id is None:
            hits = [p for (pid, _), p in batch.items() if pid == player_id]
            if not hits:
                raise InsufficientHistoryError("No upcoming scheduled game with synced history for this player")
            proj = hits[0]
        elif (player_id, game_id) in batch:
            proj = batch[(player_id, game_id)]
        else:
            state = self._state_for(session)
            key = (player_id, game_id)
            with self._lock:
                if key not in state.single:
                    up = self._upcoming_rows(session, days=0, game_id=game_id, player_id=player_id)
                    if up.empty:
                        raise InsufficientHistoryError("Player is not on an active roster for either team in this game")
                    game = session.get(Game, game_id)
                    if game is None or game.status == "final":
                        raise InsufficientHistoryError("Projections are only for games that have not finished")
                    feats = build_features(state.hist, up)
                    projs = self._project_frame(self.bundle(), feats)
                    if not projs:
                        raise InsufficientHistoryError("No features for this player-game")
                    state.single[key] = projs[0]
                proj = state.single[key]
        if proj.appearances < MIN_APPEARANCES:
            raise InsufficientHistoryError(f"Need at least {MIN_APPEARANCES} prior appearances; player has {proj.appearances}")
        return proj

    # ---- distributions -----------------------------------------------------------------
    def category_samples(self, proj: Projection, category: str) -> np.ndarray:
        dist: JointResidualDistribution = self.bundle().distribution
        means = np.array([proj.component_means[s] for s in TARGETS])
        return dist.category_samples(means, category)

    def probability_state(self, category: str, *, for_lab: bool = False) -> tuple[bool, str]:
        """(allowed, status). Probabilities need a passing gate and the matching feature flag."""
        settings = get_settings()
        status = self.bundle().probability_status.get(category, "unavailable")
        if status == "unavailable":
            return False, status
        if settings.enable_ml_probabilities or (for_lab and settings.enable_ml_experimental_ui):
            return True, status
        return False, "disabled_by_flag"


def last_sync_at(session: Session) -> datetime | None:
    return session.scalar(
        select(func.max(SyncRun.finished_at)).where(SyncRun.kind == "incremental", SyncRun.status.in_(("success", "partial")))
    )


def model_health(session: Session, service: EngineService) -> dict:
    warnings: list[str] = []
    info: dict = {"active_version": art.active_version(), "previous_version": art.previous_version(), "versions": art.list_versions()}
    try:
        b = service.bundle()
        trained = datetime.fromisoformat(b.manifest["trained_at"])
        info["loaded"] = True
        age = (datetime.now(UTC) - trained).days
        if age > STALE_MODEL_DAYS:
            warnings.append(f"old_model: trained {age} days ago; consider `make ml-train`")
        cutoff = pd.Timestamp(b.manifest["dataset_cutoff"])
        latest = session.scalar(select(func.max(Game.start_time)).where(Game.status == "final"))
        if latest is not None:
            new_games = session.scalar(
                select(func.count()).select_from(Game).where(Game.status == "final", Game.start_time > cutoff.to_pydatetime())
            )
            info["final_games_since_training_cutoff"] = int(new_games or 0)
        if all(v != "validated_real_lines" for v in b.probability_status.values()):
            warnings.append("calibration_not_validated: no category passes the archived real-line gate; probabilities are experimental")
        failing = [k for k, v in b.probability_status.items() if v == "unavailable"]
        if failing:
            warnings.append(f"calibration_failure: probabilities withheld for {', '.join(failing)}")
    except EngineUnavailableError as exc:
        info["loaded"] = False
        warnings.append(f"artifact_load_failed: {exc}")
    sync = last_sync_at(session)
    if sync is None or datetime.now(UTC) - sync > timedelta(hours=24):
        warnings.append("stale_nba_data: last successful sync is older than 24h")
    upcoming = session.scalar(select(func.count()).select_from(Game).where(Game.status == "scheduled", Game.start_time > datetime.now(UTC)))
    if not upcoming:
        warnings.append("missing_upcoming_games: no scheduled games found")
    info["last_sync_at"] = sync
    info["warnings"] = warnings
    return info


_service = EngineService()


def get_engine_service() -> EngineService:
    return _service


def category_list() -> list[str]:
    return list(ALL_CATEGORIES)


def components_of(category: str) -> tuple[str, ...]:
    return components(category)
