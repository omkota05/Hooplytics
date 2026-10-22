from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Game, Player, PlayerGameStat, SyncRun
from app.schemas.common import season_label
from app.schemas.sync import SeasonCoverageOut, SyncRunOut, SyncStatusOut
from app.services.seasons import current_season


def get_sync_status(
    session: Session,
    *,
    scheduler_enabled: bool = False,
    next_run_at: datetime | None = None,
) -> SyncStatusOut:
    settings = get_settings()
    last_success = session.scalar(
        select(func.max(SyncRun.finished_at)).where(
            SyncRun.kind == "incremental", SyncRun.status.in_(("success", "partial"))
        )
    )
    last_run = session.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1)).first()
    running = session.scalar(select(func.count()).where(SyncRun.status == "running")) or 0

    coverage_rows = session.execute(
        select(
            Game.season,
            func.count(),
            func.count().filter(Game.status == "final"),
            func.count().filter(Game.boxscore_synced_at.is_not(None)),
            func.sum(
                case((Game.status == "final", 1), else_=0)
                - case((Game.boxscore_synced_at.is_not(None), 1), else_=0)
            ),
        )
        .group_by(Game.season)
        .order_by(Game.season.desc())
    ).all()

    stale_after = timedelta(minutes=settings.sync_stale_minutes)
    return SyncStatusOut(
        provider="ESPN public API (unofficial)",
        current_season=current_season(session),
        last_successful_sync_at=last_success,
        last_run=SyncRunOut.model_validate(last_run, from_attributes=True) if last_run else None,
        is_running=running > 0,
        is_stale=last_success is None or datetime.now(UTC) - last_success > stale_after,
        players=session.scalar(select(func.count()).select_from(Player)) or 0,
        player_game_rows=session.scalar(select(func.count()).select_from(PlayerGameStat)) or 0,
        seasons=[
            SeasonCoverageOut(
                season=s,
                season_label=season_label(s),
                games_scheduled=total,
                games_final=final,
                boxscores_synced=synced,
                boxscores_pending=max(int(pending or 0), 0),
            )
            for s, total, final, synced, pending in coverage_rows
        ],
        scheduler_enabled=scheduler_enabled,
        next_scheduled_sync_at=next_run_at,
    )
