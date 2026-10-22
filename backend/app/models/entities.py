from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# IDs are the data provider's stable identifiers (currently ESPN), never names.


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    abbreviation: Mapped[str] = mapped_column(String(8), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    short_name: Mapped[str] = mapped_column(String(40), nullable=False)
    location: Mapped[str] = mapped_column(String(60), nullable=False)
    color: Mapped[str | None] = mapped_column(String(8))
    alternate_color: Mapped[str | None] = mapped_column(String(8))
    logo_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(60))
    last_name: Mapped[str | None] = mapped_column(String(60))
    # Lowercased, accent-stripped name used for search.
    search_name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[str | None] = mapped_column(String(8))
    jersey: Mapped[str | None] = mapped_column(String(4))
    headshot_url: Mapped[str | None] = mapped_column(Text)
    height_in: Mapped[float | None] = mapped_column(Float)
    weight_lb: Mapped[float | None] = mapped_column(Float)
    birth_date: Mapped[date | None] = mapped_column(Date)
    current_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)
    # True when the player appears on a current team roster.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    current_team: Mapped[Team | None] = relationship(lazy="joined")

    __table_args__ = (
        Index(
            "ix_players_search_name_trgm",
            "search_name",
            postgresql_using="gin",
            postgresql_ops={"search_name": "gin_trgm_ops"},
        ),
    )


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    # Season is identified by its ending year: 2027 == the 2026-27 season.
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # 2 = regular season, 3 = playoffs, 5 = play-in.
    season_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Calendar date in US/Eastern, which is how the NBA dates its games.
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    home_score: Mapped[int | None] = mapped_column(SmallInteger)
    away_score: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    status_detail: Mapped[str | None] = mapped_column(String(80))
    venue_name: Mapped[str | None] = mapped_column(String(120))
    venue_city: Mapped[str | None] = mapped_column(String(80))
    venue_state: Mapped[str | None] = mapped_column(String(40))
    neutral_site: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    boxscore_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    boxscore_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    boxscore_error: Mapped[str | None] = mapped_column(Text)
    boxscore_next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id], lazy="joined")
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id], lazy="joined")

    __table_args__ = (
        CheckConstraint("home_team_id <> away_team_id", name="ck_games_distinct_teams"),
        CheckConstraint(
            "status IN ('scheduled','in_progress','final','postponed','canceled','suspended')",
            name="ck_games_status",
        ),
        Index("ix_games_game_date", "game_date"),
        Index("ix_games_season_type", "season", "season_type"),
        Index("ix_games_home_start", "home_team_id", "start_time"),
        Index("ix_games_away_start", "away_team_id", "start_time"),
        Index(
            "ix_games_missing_boxscore",
            "start_time",
            postgresql_where=text("status = 'final' AND boxscore_synced_at IS NULL"),
        ),
    )


class PlayerGameStat(Base):
    """One row per player per game. Unique on (player_id, game_id)."""

    __tablename__ = "player_game_stats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    opponent_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    # Denormalized from games so per-player queries avoid a join.
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    season_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_home: Mapped[bool] = mapped_column(Boolean, nullable=False)
    starter: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    did_not_play: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    dnp_reason: Mapped[str | None] = mapped_column(String(80))
    minutes: Mapped[float | None] = mapped_column(Float)
    pts: Mapped[int | None] = mapped_column(SmallInteger)
    reb: Mapped[int | None] = mapped_column(SmallInteger)
    ast: Mapped[int | None] = mapped_column(SmallInteger)
    stl: Mapped[int | None] = mapped_column(SmallInteger)
    blk: Mapped[int | None] = mapped_column(SmallInteger)
    tov: Mapped[int | None] = mapped_column(SmallInteger)
    fgm: Mapped[int | None] = mapped_column(SmallInteger)
    fga: Mapped[int | None] = mapped_column(SmallInteger)
    fg3m: Mapped[int | None] = mapped_column(SmallInteger)
    fg3a: Mapped[int | None] = mapped_column(SmallInteger)
    ftm: Mapped[int | None] = mapped_column(SmallInteger)
    fta: Mapped[int | None] = mapped_column(SmallInteger)
    oreb: Mapped[int | None] = mapped_column(SmallInteger)
    dreb: Mapped[int | None] = mapped_column(SmallInteger)
    pf: Mapped[int | None] = mapped_column(SmallInteger)
    plus_minus: Mapped[int | None] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    game: Mapped[Game] = relationship(lazy="joined")
    opponent: Mapped[Team] = relationship(foreign_keys=[opponent_team_id], lazy="joined")

    __table_args__ = (
        UniqueConstraint("player_id", "game_id", name="uq_player_game_stats_player_game"),
        Index("ix_pgs_player_date", "player_id", "game_date"),
        Index("ix_pgs_player_opponent_date", "player_id", "opponent_team_id", "game_date"),
        Index("ix_pgs_game", "game_id"),
        Index("ix_pgs_season_date", "season", "game_date"),
    )


class PlayerTeamSeason(Base):
    """Which team(s) a player appeared for in each season, derived from box scores."""

    __tablename__ = "player_team_seasons"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    season: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    games_played: Mapped[int] = mapped_column(Integer, nullable=False)
    first_game_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_game_date: Mapped[date] = mapped_column(Date, nullable=False)

    team: Mapped[Team] = relationship(lazy="joined")


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    games_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    boxscores_synced: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    requests_made: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint("status IN ('running','success','partial','failed')", name="ck_sync_runs_status"),
        Index("ix_sync_runs_kind_started", "kind", "started_at"),
    )


class SyncState(Base):
    """Small key/value store for sync bookkeeping (e.g. last roster refresh)."""

    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
