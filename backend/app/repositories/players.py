from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Player, PlayerGameStat, PlayerTeamSeason
from app.sync.writer import normalize_search_name


def _name_filter(query: str):
    tokens = normalize_search_name(query).split()
    return and_(*(Player.search_name.ilike(f"%{t}%") for t in tokens)), " ".join(tokens)


def search_players(session: Session, query: str, limit: int = 10) -> list[Player]:
    condition, normalized = _name_filter(query)
    if not normalized:
        return []
    stmt = (
        select(Player)
        .where(condition)
        .order_by(
            Player.is_active.desc(),
            case((Player.search_name.startswith(normalized), 0), else_=1),
            case((Player.last_name.ilike(f"{normalized}%"), 0), else_=1),
            func.similarity(Player.search_name, normalized).desc(),
            Player.full_name,
        )
        .limit(limit)
    )
    return list(session.scalars(stmt))


@dataclass
class DirectoryRow:
    player: Player
    games: int
    minutes: float | None
    pts: float | None
    reb: float | None
    ast: float | None


def list_players(
    session: Session,
    *,
    season: int | None,
    query: str | None = None,
    team_id: int | None = None,
    active_only: bool = True,
    sort: str = "pts",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[DirectoryRow], int]:
    played = PlayerGameStat.did_not_play.is_(False)
    averages = (
        select(
            PlayerGameStat.player_id.label("player_id"),
            func.count().label("games"),
            func.avg(PlayerGameStat.minutes).label("minutes"),
            func.avg(PlayerGameStat.pts).label("pts"),
            func.avg(PlayerGameStat.reb).label("reb"),
            func.avg(PlayerGameStat.ast).label("ast"),
        )
        .where(played, PlayerGameStat.season == season)
        .group_by(PlayerGameStat.player_id)
        .subquery()
    )
    stmt: Select = select(Player, averages).outerjoin(averages, averages.c.player_id == Player.id)
    if query:
        condition, _ = _name_filter(query)
        stmt = stmt.where(condition)
    if team_id is not None:
        stmt = stmt.where(Player.current_team_id == team_id)
    if active_only:
        stmt = stmt.where(Player.is_active.is_(True))

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sort_columns = {
        "pts": averages.c.pts,
        "reb": averages.c.reb,
        "ast": averages.c.ast,
        "minutes": averages.c.minutes,
        "games": averages.c.games,
    }
    if sort == "name":
        stmt = stmt.order_by(Player.last_name, Player.full_name)
    else:
        stmt = stmt.order_by(sort_columns.get(sort, averages.c.pts).desc().nulls_last(), Player.full_name)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = [
        DirectoryRow(r.Player, r.games or 0, r.minutes, r.pts, r.reb, r.ast) for r in session.execute(stmt)
    ]
    return rows, total


def get_player(session: Session, player_id: int) -> Player | None:
    return session.get(Player, player_id)


def player_game_logs(
    session: Session,
    player_id: int,
    *,
    opponent_team_id: int | None = None,
    season_types: Sequence[int] | None = None,
    seasons: Sequence[int] | None = None,
    limit: int | None = None,
) -> list[PlayerGameStat]:
    stmt = (
        select(PlayerGameStat)
        .options(joinedload(PlayerGameStat.game), joinedload(PlayerGameStat.opponent))
        .where(PlayerGameStat.player_id == player_id)
        .order_by(PlayerGameStat.game_date.desc())
    )
    if opponent_team_id is not None:
        stmt = stmt.where(PlayerGameStat.opponent_team_id == opponent_team_id)
    if season_types:
        stmt = stmt.where(PlayerGameStat.season_type.in_(season_types))
    if seasons:
        stmt = stmt.where(PlayerGameStat.season.in_(seasons))
    if limit:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).unique())


def available_seasons(session: Session, player_id: int) -> list[int]:
    stmt = (
        select(PlayerGameStat.season)
        .where(PlayerGameStat.player_id == player_id, PlayerGameStat.did_not_play.is_(False))
        .distinct()
        .order_by(PlayerGameStat.season.desc())
    )
    return list(session.scalars(stmt))


def season_aggregates(session: Session, player_id: int, season: int):
    s = PlayerGameStat

    def pct(made, attempted):
        return case((func.sum(attempted) > 0, 100.0 * func.sum(made) / func.sum(attempted)), else_=None)

    stmt = select(
        func.count().label("games"),
        func.count().filter(s.starter.is_(True)).label("starts"),
        func.avg(s.minutes).label("minutes"),
        func.avg(s.pts).label("pts"),
        func.avg(s.reb).label("reb"),
        func.avg(s.ast).label("ast"),
        func.avg(s.stl).label("stl"),
        func.avg(s.blk).label("blk"),
        func.avg(s.tov).label("tov"),
        func.avg(s.fg3m).label("fg3m"),
        pct(s.fgm, s.fga).label("fg_pct"),
        pct(s.fg3m, s.fg3a).label("fg3_pct"),
        pct(s.ftm, s.fta).label("ft_pct"),
    ).where(s.player_id == player_id, s.season == season, s.did_not_play.is_(False))
    return session.execute(stmt).one()


def team_history(session: Session, player_id: int) -> list[PlayerTeamSeason]:
    stmt = (
        select(PlayerTeamSeason)
        .where(PlayerTeamSeason.player_id == player_id)
        .order_by(PlayerTeamSeason.season.desc(), PlayerTeamSeason.last_game_date.desc())
    )
    return list(session.scalars(stmt))


def game_count(session: Session, player_id: int) -> tuple[int, object]:
    stmt = select(func.count(), func.max(PlayerGameStat.game_date)).where(
        PlayerGameStat.player_id == player_id, PlayerGameStat.did_not_play.is_(False)
    )
    count, last = session.execute(stmt).one()
    return count, last


def recent_form(session: Session, player_ids: Sequence[int], last_n: int = 10) -> dict[int, dict]:
    """Averages over each player's last `last_n` played games."""
    if not player_ids:
        return {}
    ranked = (
        select(
            PlayerGameStat.player_id,
            PlayerGameStat.minutes,
            PlayerGameStat.pts,
            PlayerGameStat.reb,
            PlayerGameStat.ast,
            func.row_number()
            .over(partition_by=PlayerGameStat.player_id, order_by=PlayerGameStat.game_date.desc())
            .label("rn"),
        )
        .where(PlayerGameStat.player_id.in_(player_ids), PlayerGameStat.did_not_play.is_(False))
        .subquery()
    )
    stmt = (
        select(
            ranked.c.player_id,
            func.count(),
            func.avg(ranked.c.minutes),
            func.avg(ranked.c.pts),
            func.avg(ranked.c.reb),
            func.avg(ranked.c.ast),
        )
        .where(ranked.c.rn <= last_n)
        .group_by(ranked.c.player_id)
    )
    return {
        pid: {"games": g, "minutes": m, "pts": p, "reb": r, "ast": a}
        for pid, g, m, p, r, a in session.execute(stmt)
    }


def last_n_games_for_players(
    session: Session, player_ids: Sequence[int], last_n: int
) -> dict[int, list[PlayerGameStat]]:
    if not player_ids:
        return {}
    ranked = (
        select(
            PlayerGameStat.id,
            func.row_number()
            .over(partition_by=PlayerGameStat.player_id, order_by=PlayerGameStat.game_date.desc())
            .label("rn"),
        )
        .where(PlayerGameStat.player_id.in_(player_ids), PlayerGameStat.did_not_play.is_(False))
        .subquery()
    )
    stmt = (
        select(PlayerGameStat)
        .join(ranked, ranked.c.id == PlayerGameStat.id)
        .where(ranked.c.rn <= last_n)
        .order_by(PlayerGameStat.player_id, PlayerGameStat.game_date.desc())
    )
    out: dict[int, list[PlayerGameStat]] = {}
    for row in session.scalars(stmt).unique():
        out.setdefault(row.player_id, []).append(row)
    return out


def active_players_on_teams(session: Session, team_ids: Sequence[int]) -> list[Player]:
    stmt = (
        select(Player)
        .where(Player.current_team_id.in_(team_ids), Player.is_active.is_(True))
        .order_by(Player.full_name)
    )
    return list(session.scalars(stmt))


def players_by_ids(session: Session, ids: Sequence[int]) -> dict[int, Player]:
    if not ids:
        return {}
    return {p.id: p for p in session.scalars(select(Player).where(Player.id.in_(ids)))}
