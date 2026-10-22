from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Player
from app.repositories import games as games_repo
from app.repositories import players as players_repo
from app.schemas.common import GameOut, TeamOut
from app.schemas.games import (
    BoxScoreLineOut,
    GameDetailOut,
    GamePlayerOut,
    RecentFormOut,
    TopPerformerOut,
)
from app.services.errors import NotFoundError
from app.services.serializers import game_out, player_summary, round_or_none, team_out


def upcoming(session: Session, days: int, team_id: int | None = None) -> list[GameOut]:
    now = datetime.now(UTC)
    games = games_repo.upcoming_games(session, now=now, until=now + timedelta(days=days), team_id=team_id)
    return [game_out(g) for g in games]


def recent(session: Session, days: int) -> list[GameOut]:
    latest = games_repo.latest_final_date(session)
    if latest is None:
        return []
    games = games_repo.games_between(session, latest - timedelta(days=days - 1), latest)
    return [game_out(g) for g in reversed(games) if g.status == "final"]


def top_performers(session: Session, limit: int) -> list[TopPerformerOut]:
    latest = games_repo.latest_final_date(session)
    if latest is None:
        return []
    return [
        TopPerformerOut(
            player=player_summary(player),
            game=game_out(stat.game),
            pts=stat.pts or 0,
            reb=stat.reb or 0,
            ast=stat.ast or 0,
        )
        for stat, player in games_repo.top_performers(session, latest, limit)
    ]


def _with_form(session: Session, players: list[Player]) -> list[GamePlayerOut]:
    form = players_repo.recent_form(session, [p.id for p in players])
    out = []
    for p in players:
        f = form.get(p.id)
        out.append(
            GamePlayerOut(
                player=player_summary(p),
                recent=RecentFormOut(
                    games=f["games"],
                    minutes=round_or_none(f["minutes"]),
                    pts=round_or_none(f["pts"]),
                    reb=round_or_none(f["reb"]),
                    ast=round_or_none(f["ast"]),
                )
                if f
                else None,
            )
        )
    # Rotation players first.
    out.sort(key=lambda gp: -(gp.recent.minutes or 0) if gp.recent else 1)
    return out


def detail(session: Session, game_id: int) -> GameDetailOut:
    game = games_repo.get_game(session, game_id)
    if game is None:
        raise NotFoundError(f"Game {game_id} not found")

    lines = games_repo.boxscore_lines(session, game_id)
    home_box: list[BoxScoreLineOut] = []
    away_box: list[BoxScoreLineOut] = []
    for stat, player in lines:
        line = BoxScoreLineOut(
            player=player_summary(player),
            starter=stat.starter,
            did_not_play=stat.did_not_play,
            dnp_reason=stat.dnp_reason,
            minutes=stat.minutes,
            pts=stat.pts,
            reb=stat.reb,
            ast=stat.ast,
            stl=stat.stl,
            blk=stat.blk,
            tov=stat.tov,
            fg3m=stat.fg3m,
            plus_minus=stat.plus_minus,
        )
        (home_box if stat.team_id == game.home_team_id else away_box).append(line)

    if lines:
        source = "boxscore"
        by_team: dict[int, list[Player]] = {game.home_team_id: [], game.away_team_id: []}
        for stat, player in lines:
            if not stat.did_not_play:
                by_team[stat.team_id].append(player)
    else:
        source = "current_roster"
        roster = players_repo.active_players_on_teams(session, [game.home_team_id, game.away_team_id])
        by_team = {
            game.home_team_id: [p for p in roster if p.current_team_id == game.home_team_id],
            game.away_team_id: [p for p in roster if p.current_team_id == game.away_team_id],
        }

    meetings = games_repo.previous_meetings(
        session, game.home_team_id, game.away_team_id, before=game.start_time
    )
    return GameDetailOut(
        game=game_out(game),
        home_players=_with_form(session, by_team[game.home_team_id]),
        away_players=_with_form(session, by_team[game.away_team_id]),
        players_source=source,
        home_boxscore=home_box,
        away_boxscore=away_box,
        previous_meetings=[game_out(g) for g in meetings],
    )


def teams(session: Session) -> list[TeamOut]:
    return [team_out(t) for t in games_repo.list_teams(session)]
