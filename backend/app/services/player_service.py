from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Game, PlayerGameStat
from app.repositories import games as games_repo
from app.repositories import players as players_repo
from app.schemas.common import Page, season_label
from app.schemas.players import (
    DirectoryRowOut,
    GameLogEntryOut,
    PlayerProfileOut,
    SeasonAveragesOut,
    TeamSeasonOut,
)
from app.services.errors import NotFoundError
from app.services.seasons import current_season
from app.services.serializers import game_out, player_summary, round_or_none, team_out


def search(session: Session, query: str, limit: int):
    return [player_summary(p) for p in players_repo.search_players(session, query, limit)]


def directory(
    session: Session,
    *,
    query: str | None,
    team_id: int | None,
    active_only: bool,
    sort: str,
    page: int,
    page_size: int,
) -> Page[DirectoryRowOut]:
    season = current_season(session)
    rows, total = players_repo.list_players(
        session,
        season=season,
        query=query,
        team_id=team_id,
        active_only=active_only,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    items = [
        DirectoryRowOut(
            player=player_summary(r.player),
            season=season,
            games=r.games,
            minutes=round_or_none(r.minutes),
            pts=round_or_none(r.pts),
            reb=round_or_none(r.reb),
            ast=round_or_none(r.ast),
        )
        for r in rows
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


def season_averages(session: Session, player_id: int, season: int) -> SeasonAveragesOut | None:
    agg = players_repo.season_aggregates(session, player_id, season)
    if not agg.games:
        return None
    return SeasonAveragesOut(
        season=season,
        season_label=season_label(season),
        games=agg.games,
        starts=agg.starts,
        minutes=round_or_none(agg.minutes),
        pts=round_or_none(agg.pts),
        reb=round_or_none(agg.reb),
        ast=round_or_none(agg.ast),
        stl=round_or_none(agg.stl),
        blk=round_or_none(agg.blk),
        tov=round_or_none(agg.tov),
        fg3m=round_or_none(agg.fg3m),
        fg_pct=round_or_none(agg.fg_pct),
        fg3_pct=round_or_none(agg.fg3_pct),
        ft_pct=round_or_none(agg.ft_pct),
    )


def profile(session: Session, player_id: int, season: int | None = None) -> PlayerProfileOut:
    player = players_repo.get_player(session, player_id)
    if player is None:
        raise NotFoundError(f"Player {player_id} not found")

    seasons = players_repo.available_seasons(session, player_id)
    selected = season or (seasons[0] if seasons else None)
    averages = season_averages(session, player_id, selected) if selected else None

    upcoming = []
    if player.current_team_id and player.is_active:
        now = datetime.now(UTC)
        upcoming = [
            game_out(g)
            for g in games_repo.upcoming_games(
                session,
                now=now,
                until=now + timedelta(days=get_settings().upcoming_days),
                team_id=player.current_team_id,
                limit=5,
            )
        ]

    total, last_date = players_repo.game_count(session, player_id)
    return PlayerProfileOut(
        player=player_summary(player),
        height_in=player.height_in,
        weight_lb=player.weight_lb,
        birth_date=player.birth_date,
        current_season=current_season(session),
        available_seasons=seasons,
        season_averages=averages,
        team_history=[
            TeamSeasonOut(
                season=h.season,
                season_label=season_label(h.season),
                team=team_out(h.team),
                games_played=h.games_played,
            )
            for h in players_repo.team_history(session, player_id)
        ],
        upcoming_games=upcoming,
        last_game_date=last_date,
        total_games_tracked=total,
    )


def game_result(stat: PlayerGameStat, game: Game) -> tuple[int | None, int | None, str | None]:
    team_score = game.home_score if stat.is_home else game.away_score
    opp_score = game.away_score if stat.is_home else game.home_score
    result = None
    if game.status == "final" and team_score is not None and opp_score is not None:
        result = "W" if team_score > opp_score else "L"
    return team_score, opp_score, result


def game_log(session: Session, player_id: int, *, season: int | None, limit: int) -> list[GameLogEntryOut]:
    if players_repo.get_player(session, player_id) is None:
        raise NotFoundError(f"Player {player_id} not found")
    rows = players_repo.player_game_logs(
        session, player_id, seasons=[season] if season else None, limit=limit
    )
    out = []
    for s in rows:
        team_score, opp_score, result = game_result(s, s.game)
        out.append(
            GameLogEntryOut(
                game_id=s.game_id,
                game_date=s.game_date,
                season=s.season,
                season_label=season_label(s.season),
                season_type=s.season_type,
                opponent=team_out(s.opponent),
                is_home=s.is_home,
                team_score=team_score,
                opponent_score=opp_score,
                result=result,
                starter=s.starter,
                did_not_play=s.did_not_play,
                dnp_reason=s.dnp_reason,
                minutes=s.minutes,
                pts=s.pts,
                reb=s.reb,
                ast=s.ast,
                stl=s.stl,
                blk=s.blk,
                tov=s.tov,
                fgm=s.fgm,
                fga=s.fga,
                fg3m=s.fg3m,
                fg3a=s.fg3a,
                ftm=s.ftm,
                fta=s.fta,
                plus_minus=s.plus_minus,
            )
        )
    return out
