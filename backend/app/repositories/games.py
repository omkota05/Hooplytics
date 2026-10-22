from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Game, Player, PlayerGameStat, Team

# Keep games visible as "upcoming" for a while after tip-off in case status lags.
_LIVE_GRACE = timedelta(hours=4)


def get_game(session: Session, game_id: int) -> Game | None:
    return session.get(Game, game_id)


def upcoming_games(
    session: Session, *, now: datetime, until: datetime, team_id: int | None = None, limit: int = 200
) -> list[Game]:
    """Games not yet completed, starting from slightly before now (to include live games)."""
    stmt = (
        select(Game)
        .where(
            Game.start_time <= until,
            or_(
                and_(Game.status == "scheduled", Game.start_time >= now - _LIVE_GRACE),
                Game.status == "in_progress",
                and_(Game.status.in_(("postponed", "suspended")), Game.start_time >= now - _LIVE_GRACE),
            ),
        )
        .order_by(Game.start_time, Game.id)
        .limit(limit)
    )
    if team_id is not None:
        stmt = stmt.where(or_(Game.home_team_id == team_id, Game.away_team_id == team_id))
    return list(session.scalars(stmt))


def games_between(session: Session, start: date, end: date) -> list[Game]:
    stmt = (
        select(Game).where(Game.game_date >= start, Game.game_date <= end).order_by(Game.start_time, Game.id)
    )
    return list(session.scalars(stmt))


def latest_final_date(session: Session) -> date | None:
    return session.scalar(
        select(func.max(Game.game_date)).where(Game.status == "final", Game.boxscore_synced_at.is_not(None))
    )


def previous_meetings(
    session: Session, team_a: int, team_b: int, before: datetime, limit: int = 10
) -> list[Game]:
    stmt = (
        select(Game)
        .where(
            Game.status == "final",
            Game.start_time < before,
            or_(
                and_(Game.home_team_id == team_a, Game.away_team_id == team_b),
                and_(Game.home_team_id == team_b, Game.away_team_id == team_a),
            ),
        )
        .order_by(Game.start_time.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def boxscore_lines(session: Session, game_id: int) -> list[tuple[PlayerGameStat, Player]]:
    stmt = (
        select(PlayerGameStat, Player)
        .join(Player, Player.id == PlayerGameStat.player_id)
        .where(PlayerGameStat.game_id == game_id)
        .order_by(
            PlayerGameStat.did_not_play,
            PlayerGameStat.starter.desc(),
            PlayerGameStat.minutes.desc().nulls_last(),
        )
    )
    return list(session.execute(stmt).tuples())


def top_performers(session: Session, game_date: date, limit: int = 8):
    stmt = (
        select(PlayerGameStat, Player)
        .options(joinedload(PlayerGameStat.game))
        .join(Player, Player.id == PlayerGameStat.player_id)
        .where(PlayerGameStat.game_date == game_date, PlayerGameStat.did_not_play.is_(False))
        .order_by(PlayerGameStat.pts.desc().nulls_last(), PlayerGameStat.reb.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).tuples())


def list_teams(session: Session) -> list[Team]:
    return list(session.scalars(select(Team).where(Team.is_active.is_(True)).order_by(Team.display_name)))


def get_team(session: Session, team_id: int) -> Team | None:
    return session.get(Team, team_id)
