"""Immutable prospective forecasts recorded before tip-off, settled after the game is final.

Prediction columns are write-once (enforced by a database trigger); only the settlement
columns (`status`, `settled_at`, `actual_*`) change after insert. Rows are never deleted.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MlForecast(Base):
    __tablename__ = "ml_forecasts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False)
    opponent_team_id: Mapped[int] = mapped_column(Integer, nullable=False)
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_tipoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(16), nullable=False)
    data_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    appearances: Mapped[int] = mapped_column(Integer, nullable=False)
    season_appearances: Mapped[int] = mapped_column(Integer, nullable=False)
    projected_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    proj_pts: Mapped[float] = mapped_column(Float, nullable=False)
    proj_reb: Mapped[float] = mapped_column(Float, nullable=False)
    proj_ast: Mapped[float] = mapped_column(Float, nullable=False)
    proj_fg3m: Mapped[float] = mapped_column(Float, nullable=False)
    proj_pts_reb: Mapped[float] = mapped_column(Float, nullable=False)
    proj_pts_ast: Mapped[float] = mapped_column(Float, nullable=False)
    proj_reb_ast: Mapped[float] = mapped_column(Float, nullable=False)
    proj_pts_reb_ast: Mapped[float] = mapped_column(Float, nullable=False)
    quantiles: Mapped[dict] = mapped_column(JSONB, nullable=False)
    baselines: Mapped[dict] = mapped_column(JSONB, nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False)
    probability_status: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # pending | settled | void_dnp | void_game | unresolved
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_minutes: Mapped[float | None] = mapped_column(Float)
    actual_pts: Mapped[float | None] = mapped_column(Float)
    actual_reb: Mapped[float | None] = mapped_column(Float)
    actual_ast: Mapped[float | None] = mapped_column(Float)
    actual_fg3m: Mapped[float | None] = mapped_column(Float)


class MlForecastLine(Base):
    """A sportsbook line that was live (observed pregame) when the forecast run executed."""

    __tablename__ = "ml_forecast_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    forecast_id: Mapped[int] = mapped_column(ForeignKey("ml_forecasts.id"), nullable=False)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("prop_offer_snapshots.id"))
    sportsbook_label: Mapped[str] = mapped_column(String(80), nullable=False)
    category_key: Mapped[str] = mapped_column(String(24), nullable=False)
    line: Mapped[float] = mapped_column(Float, nullable=False)
    pick_side: Mapped[str] = mapped_column(String(8), nullable=False)
    american_odds: Mapped[int | None] = mapped_column(Integer)
    offer_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_tipoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_mean: Mapped[float] = mapped_column(Float, nullable=False)
    model_p_over: Mapped[float | None] = mapped_column(Float)
    model_p_under: Mapped[float | None] = mapped_column(Float)
