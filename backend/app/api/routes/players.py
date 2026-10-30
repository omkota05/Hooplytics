from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.analytics.windows import GameWindow
from app.db import get_db
from app.schemas.analysis import MatchupComparisonOut, StatAnalysisOut
from app.schemas.common import Page, PlayerSummaryOut
from app.schemas.opportunity import PlayerOpportunityOut
from app.schemas.players import (
    DirectoryRowOut,
    GameLogEntryOut,
    PlayerProfileOut,
    SeasonAveragesOut,
)
from app.services.opportunity_service import build_opportunity
from app.services import analysis_service, player_service
from app.services.errors import NotFoundError

router = APIRouter(prefix="/players", tags=["players"])
Db = Annotated[Session, Depends(get_db)]
SeasonScope = Literal["all", "regular", "postseason"]


@router.get("/search", response_model=list[PlayerSummaryOut])
def search_players(
    db: Db,
    q: Annotated[str, Query(min_length=1, max_length=60)],
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
):
    return player_service.search(db, q, limit)


@router.get("", response_model=Page[DirectoryRowOut])
def list_players(
    db: Db,
    q: Annotated[str | None, Query(max_length=60)] = None,
    team_id: int | None = None,
    active_only: bool = True,
    sort: Literal["pts", "reb", "ast", "minutes", "games", "name"] = "pts",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return player_service.directory(
        db,
        query=q,
        team_id=team_id,
        active_only=active_only,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.get("/{player_id}", response_model=PlayerProfileOut)
def get_profile(db: Db, player_id: int, season: int | None = None):
    return player_service.profile(db, player_id, season)


@router.get("/{player_id}/season-averages", response_model=SeasonAveragesOut)
def get_season_averages(db: Db, player_id: int, season: int):
    averages = player_service.season_averages(db, player_id, season)
    if averages is None:
        raise NotFoundError(f"No games for player {player_id} in season {season}")
    return averages


@router.get("/{player_id}/opportunity", response_model=PlayerOpportunityOut)
def get_player_opportunity(
    db: Db,
    player_id: int,
    season: int | None = None,
    before_game_id: int | None = None,
):
    """Minutes / FGA / 3PA trends from synced box scores."""
    before_start = None
    if before_game_id is not None:
        from app.models import Game

        game = db.get(Game, before_game_id)
        if game is None:
            raise NotFoundError(f"Game {before_game_id} not found")
        before_start = game.start_time
        season = season or game.season
    return build_opportunity(db, player_id, before_start=before_start, season=season)


@router.get("/{player_id}/game-logs", response_model=list[GameLogEntryOut])
def get_game_logs(
    db: Db,
    player_id: int,
    season: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
):
    return player_service.game_log(db, player_id, season=season, limit=limit)


@router.get("/{player_id}/stat-analysis", response_model=StatAnalysisOut)
def get_stat_analysis(
    db: Db,
    player_id: int,
    stat: str = "pts",
    line: Annotated[float, Query(ge=0, le=200)] = 0.5,
    window: Literal["last_n", "season", "date_range", "all"] = "last_n",
    n: Annotated[int | None, Query(ge=1, le=500)] = 10,
    season: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    opponent_id: int | None = None,
    season_scope: SeasonScope = "all",
):
    """Historical over/under/push breakdown for one stat category and line.

    With `opponent_id`, only games against that team are considered (head-to-head),
    across every synced season.
    """
    return analysis_service.analyze(
        db,
        player_id=player_id,
        category_key=stat,
        line=line,
        window=GameWindow(
            kind=window,
            n=n if window == "last_n" else None,
            season=season,
            start_date=start_date,
            end_date=end_date,
        ),
        opponent_team_id=opponent_id,
        season_scope=season_scope,
    )


@router.get("/{player_id}/matchup-comparison", response_model=MatchupComparisonOut)
def get_matchup_comparison(
    db: Db,
    player_id: int,
    opponent_id: int,
    stat: str = "pts",
    line: Annotated[float, Query(ge=0, le=200)] = 0.5,
    recent_n: Annotated[int, Query(ge=1, le=100)] = 10,
    h2h_n: Annotated[int | None, Query(ge=1, le=100)] = None,
    season_scope: SeasonScope = "all",
):
    """Recent form against everyone vs. history against one opponent."""
    return analysis_service.compare_with_opponent(
        db,
        player_id=player_id,
        opponent_team_id=opponent_id,
        category_key=stat,
        line=line,
        recent_n=recent_n,
        head_to_head_n=h2h_n,
        season_scope=season_scope,
    )
