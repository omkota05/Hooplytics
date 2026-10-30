from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.analysis import StatCategoryOut
from app.schemas.hcs import HCSBreakdownOut


class PropRefreshProgressOut(BaseModel):
    phase: str | None = None
    processed: int | None = None
    parsed_total: int | None = None
    upserted: int | None = None


class PropImportStatusOut(BaseModel):
    configured: bool
    last_run_status: str | None = None
    last_run_finished_at: datetime | None = None
    last_run_error: str | None = None
    offers_active: int = 0
    offers_matched: int = 0
    offers_eligible_upcoming: int = 0
    diagnostics: dict | None = None
    last_import_details: dict | None = None
    refresh_in_progress: bool = False
    refresh_started_at: datetime | None = None
    unique_line_caches: int = 0
    last_hit_computed_at: datetime | None = None
    refresh_progress: PropRefreshProgressOut | None = None


class PropHitWindowOut(BaseModel):
    window: str
    games: int
    over_hits: int = 0
    under_hits: int = 0
    over_hit_pct: float | None
    under_hit_pct: float | None
    pushes: int
    side_hits: int | None = None
    side_attempts: int | None = None


class PropFinderRowOut(BaseModel):
    id: int
    source_kind: Literal["unabated", "manual", "csv"]
    player_id: int | None
    player_name: str | None
    game_id: int | None
    matchup_label: str | None
    opponent_abbreviation: str | None
    opponent_team_id: int | None = None
    sportsbook: str
    category: StatCategoryOut
    line: float
    pick_side: Literal["over", "under"]
    american_odds: int | None
    l5_hit_pct: float | None
    l10_hit_pct: float | None
    l20_hit_pct: float | None
    h2h_hit_pct: float | None
    l5_hits: int | None = None
    l5_attempts: int | None = None
    l5_games: int | None = None
    l10_hits: int | None = None
    l10_attempts: int | None = None
    l10_games: int | None = None
    l20_hits: int | None = None
    l20_attempts: int | None = None
    l20_games: int | None = None
    h2h_hits: int | None = None
    h2h_attempts: int | None = None
    h2h_games: int | None = None
    historical_avg: float | None
    game_start_time: datetime | None
    deep_link_published: str | None
    is_alternate_line: bool
    match_status: str
    line_modified_at: datetime | None
    updated_at: datetime
    hit_computed_at: datetime | None = None
    hcs_score: float | None = None


class PropFinderListOut(BaseModel):
    rows: list[PropFinderRowOut]
    total: int
    total_available: int | None = None
    limit: int = 10
    offset: int = 0
    last_import_finished_at: datetime | None
    last_hit_computed_at: datetime | None = None
    refresh_in_progress: bool = False
    disclaimer: str = (
        "Historical hit rates count past game results against this sportsbook line. "
        "They are not predictions of the upcoming game."
    )


class PropFinderDetailOut(PropFinderRowOut):
    hit_windows: list[PropHitWindowOut]
    player_analysis_href: str | None = None
    hcs_breakdown: HCSBreakdownOut | None = None


class ManualPropIn(BaseModel):
    player_id: int
    game_id: int
    category_key: str
    line: float = Field(ge=0, le=200)
    pick_side: Literal["over", "under"]
    american_odds: int | None = None
    sportsbook_label: str = "Manual entry"
