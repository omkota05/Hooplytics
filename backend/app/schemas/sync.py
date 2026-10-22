from datetime import datetime

from pydantic import BaseModel


class SyncRunOut(BaseModel):
    id: int
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    games_updated: int
    boxscores_synced: int
    requests_made: int
    error: str | None


class SeasonCoverageOut(BaseModel):
    season: int
    season_label: str
    games_scheduled: int
    games_final: int
    boxscores_synced: int
    boxscores_pending: int


class SyncStatusOut(BaseModel):
    provider: str
    current_season: int | None
    last_successful_sync_at: datetime | None
    last_run: SyncRunOut | None
    is_running: bool
    is_stale: bool
    players: int
    player_game_rows: int
    seasons: list[SeasonCoverageOut]
    scheduler_enabled: bool
    next_scheduled_sync_at: datetime | None
