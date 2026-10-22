from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


def season_label(season: int) -> str:
    """2027 -> '2026-27'."""
    return f"{season - 1}-{str(season)[-2:]}"


SEASON_TYPE_LABELS = {2: "Regular Season", 3: "Playoffs", 5: "Play-In"}


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TeamOut(ApiModel):
    id: int
    abbreviation: str
    display_name: str
    short_name: str
    location: str
    color: str | None
    alternate_color: str | None
    logo_url: str | None


class PlayerSummaryOut(ApiModel):
    id: int
    full_name: str
    position: str | None
    jersey: str | None
    headshot_url: str | None
    is_active: bool
    team: TeamOut | None


class GameOut(ApiModel):
    id: int
    season: int
    season_label: str
    season_type: int
    season_type_label: str
    start_time: datetime
    game_date: date
    status: str
    status_detail: str | None
    home_team: TeamOut
    away_team: TeamOut
    home_score: int | None
    away_score: int | None
    venue_name: str | None
    venue_city: str | None
    venue_state: str | None
    neutral_site: bool


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
