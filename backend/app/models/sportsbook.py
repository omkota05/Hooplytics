"""Sportsbook prop offers and cross-provider identity mappings."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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


class SportsbookSource(Base):
    __tablename__ = "sportsbook_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unabated_market_source_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UnabatedIdentityMapping(Base):
    __tablename__ = "unabated_identity_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)  # player | event
    unabated_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hooplytics_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    match_method: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")
    meta: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("entity_type", "unabated_id", name="uq_unabated_entity"),
        Index("ix_unabated_mapping_hoop", "entity_type", "hooplytics_id"),
    )


class PropHitStreakCache(Base):
    __tablename__ = "prop_hit_streak_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    before_game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    category_key: Mapped[str] = mapped_column(String(24), nullable=False)
    line: Mapped[float] = mapped_column(Float, nullable=False)
    pick_side: Mapped[str] = mapped_column(String(8), nullable=False)
    current_season_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    streak_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    data_sync_reference: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "before_game_id",
            "category_key",
            "line",
            "pick_side",
            "current_season_only",
            name="uq_prop_hit_streak_cache_key",
        ),
        Index("ix_prop_hit_streak_cache_player", "player_id"),
        Index("ix_prop_hit_streak_cache_game", "before_game_id"),
    )


class PropLineHitCache(Base):
    __tablename__ = "prop_line_hit_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    opponent_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    category_key: Mapped[str] = mapped_column(String(24), nullable=False)
    line: Mapped[float] = mapped_column(Float, nullable=False)
    hit_rates: Mapped[dict] = mapped_column(JSONB, nullable=False)
    historical_avg: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    data_sync_reference: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint("player_id", "game_id", "category_key", "line", name="uq_prop_line_hit_cache_key"),
        Index("ix_prop_line_hit_cache_player", "player_id"),
        Index("ix_prop_line_hit_cache_game", "game_id"),
    )


class PropOffer(Base):
    __tablename__ = "prop_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)  # unabated | manual | csv
    sportsbook_source_id: Mapped[int | None] = mapped_column(ForeignKey("sportsbook_sources.id"))
    sportsbook_label: Mapped[str] = mapped_column(String(80), nullable=False)

    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id"), index=True)
    opponent_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))

    unabated_event_id: Mapped[int | None] = mapped_column(BigInteger)
    unabated_person_id: Mapped[int | None] = mapped_column(BigInteger)
    unabated_bet_type_id: Mapped[int | None] = mapped_column(Integer)
    unabated_market_line_id: Mapped[int | None] = mapped_column(BigInteger)
    unabated_side_index: Mapped[int | None] = mapped_column(SmallInteger)
    period_type_id: Mapped[int | None] = mapped_column(SmallInteger)

    category_key: Mapped[str] = mapped_column(String(24), nullable=False)
    line: Mapped[float] = mapped_column(Float, nullable=False)
    pick_side: Mapped[str] = mapped_column(String(8), nullable=False)  # over | under
    american_odds: Mapped[int | None] = mapped_column(Integer)
    is_alternate_line: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    alternate_key: Mapped[str | None] = mapped_column(String(64))

    deep_link_raw: Mapped[str | None] = mapped_column(Text)
    deep_link_published: Mapped[str | None] = mapped_column(Text)

    event_name: Mapped[str | None] = mapped_column(String(120))
    player_name_raw: Mapped[str | None] = mapped_column(String(120))
    game_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    game_date: Mapped[date | None] = mapped_column(Date)

    line_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    match_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="matched")
    match_note: Mapped[str | None] = mapped_column(Text)

    hit_rates: Mapped[dict | None] = mapped_column(JSONB)
    historical_avg: Mapped[float | None] = mapped_column(Float)
    hit_cache_id: Mapped[int | None] = mapped_column(ForeignKey("prop_line_hit_cache.id"))
    l5_hit_pct: Mapped[float | None] = mapped_column(Float)
    l10_hit_pct: Mapped[float | None] = mapped_column(Float)
    l15_hit_pct: Mapped[float | None] = mapped_column(Float)
    l20_hit_pct: Mapped[float | None] = mapped_column(Float)
    l30_hit_pct: Mapped[float | None] = mapped_column(Float)
    h2h_hit_pct: Mapped[float | None] = mapped_column(Float)
    l5_games: Mapped[int | None] = mapped_column(SmallInteger)
    l10_games: Mapped[int | None] = mapped_column(SmallInteger)
    l20_games: Mapped[int | None] = mapped_column(SmallInteger)
    h2h_games: Mapped[int | None] = mapped_column(SmallInteger)
    l5_hits: Mapped[int | None] = mapped_column(SmallInteger)
    l10_hits: Mapped[int | None] = mapped_column(SmallInteger)
    l20_hits: Mapped[int | None] = mapped_column(SmallInteger)
    h2h_hits: Mapped[int | None] = mapped_column(SmallInteger)
    l5_attempts: Mapped[int | None] = mapped_column(SmallInteger)
    l10_attempts: Mapped[int | None] = mapped_column(SmallInteger)
    l20_attempts: Mapped[int | None] = mapped_column(SmallInteger)
    h2h_attempts: Mapped[int | None] = mapped_column(SmallInteger)
    l5_wilson_lb: Mapped[float | None] = mapped_column(Float)
    l10_wilson_lb: Mapped[float | None] = mapped_column(Float)
    l20_wilson_lb: Mapped[float | None] = mapped_column(Float)
    h2h_wilson_lb: Mapped[float | None] = mapped_column(Float)
    hit_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hcs_score: Mapped[float | None] = mapped_column(Float)

    player: Mapped["Player | None"] = relationship("Player", lazy="joined")
    game: Mapped["Game | None"] = relationship("Game", lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "source_kind",
            "sportsbook_label",
            "unabated_event_id",
            "unabated_person_id",
            "unabated_bet_type_id",
            "line",
            "pick_side",
            name="uq_prop_offer_canonical_key",
        ),
        Index("ix_prop_offers_game_start", "game_start_time"),
        Index("ix_prop_offers_category", "category_key"),
    )


class PropImportRun(Base):
    __tablename__ = "prop_import_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offers_seen: Mapped[int] = mapped_column(Integer, server_default="0")
    offers_upserted: Mapped[int] = mapped_column(Integer, server_default="0")
    offers_matched: Mapped[int] = mapped_column(Integer, server_default="0")
    offers_unmatched: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSONB)
