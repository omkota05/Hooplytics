"""immutable prospective ML forecast archive

Revision ID: 0010_ml_forecasts
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0010_ml_forecasts"
down_revision = "0009_prop_offer_snapshots"
branch_labels = None
depends_on = None

IMMUTABLE_FORECAST_COLUMNS = (
    "player_id", "game_id", "team_id", "opponent_team_id", "predicted_at", "scheduled_tipoff",
    "model_version", "feature_version", "data_snapshot", "appearances", "season_appearances",
    "projected_minutes", "proj_pts", "proj_reb", "proj_ast", "proj_fg3m", "proj_pts_reb",
    "proj_pts_ast", "proj_reb_ast", "proj_pts_reb_ast", "quantiles", "baselines", "context", "warnings",
    "probability_status",
)


def upgrade() -> None:
    op.create_table(
        "ml_forecasts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("game_id", sa.BigInteger(), sa.ForeignKey("games.id"), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("opponent_team_id", sa.Integer(), nullable=False),
        sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_tipoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("feature_version", sa.String(16), nullable=False),
        sa.Column("data_snapshot", sa.String(200), nullable=False),
        sa.Column("appearances", sa.Integer(), nullable=False),
        sa.Column("season_appearances", sa.Integer(), nullable=False),
        sa.Column("projected_minutes", sa.Float(), nullable=False),
        *[sa.Column(f"proj_{c}", sa.Float(), nullable=False) for c in ("pts", "reb", "ast", "fg3m", "pts_reb", "pts_ast", "reb_ast", "pts_reb_ast")],
        sa.Column("quantiles", JSONB(), nullable=False),
        sa.Column("baselines", JSONB(), nullable=False),
        sa.Column("context", JSONB(), nullable=False),
        sa.Column("warnings", JSONB(), nullable=False),
        sa.Column("probability_status", JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("actual_minutes", sa.Float()),
        *[sa.Column(f"actual_{c}", sa.Float()) for c in ("pts", "reb", "ast", "fg3m")],
        sa.UniqueConstraint("player_id", "game_id", "model_version", name="uq_ml_forecast_player_game_model"),
        sa.CheckConstraint("predicted_at < scheduled_tipoff", name="ck_ml_forecast_pregame"),
        sa.CheckConstraint(
            "status IN ('pending','settled','void_dnp','void_game','unresolved')", name="ck_ml_forecast_status"
        ),
    )
    op.create_index("ix_ml_forecast_game", "ml_forecasts", ["game_id"])
    op.create_index("ix_ml_forecast_open", "ml_forecasts", ["game_id"], postgresql_where=sa.text("status IN ('pending','unresolved')"))

    op.create_table(
        "ml_forecast_lines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("forecast_id", sa.BigInteger(), sa.ForeignKey("ml_forecasts.id"), nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), sa.ForeignKey("prop_offer_snapshots.id")),
        sa.Column("sportsbook_label", sa.String(80), nullable=False),
        sa.Column("category_key", sa.String(24), nullable=False),
        sa.Column("line", sa.Float(), nullable=False),
        sa.Column("pick_side", sa.String(8), nullable=False),
        sa.Column("american_odds", sa.Integer()),
        sa.Column("offer_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_tipoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_mean", sa.Float(), nullable=False),
        sa.Column("model_p_over", sa.Float()),
        sa.Column("model_p_under", sa.Float()),
        sa.UniqueConstraint("forecast_id", "sportsbook_label", "category_key", "line", "pick_side", name="uq_ml_forecast_line"),
        sa.CheckConstraint(
            "offer_observed_at < scheduled_tipoff AND recorded_at < scheduled_tipoff", name="ck_ml_forecast_line_pregame"
        ),
    )
    op.create_index("ix_ml_forecast_lines_forecast", "ml_forecast_lines", ["forecast_id"])

    old = ", ".join(f"OLD.{c}" for c in IMMUTABLE_FORECAST_COLUMNS)
    new = ", ".join(f"NEW.{c}" for c in IMMUTABLE_FORECAST_COLUMNS)
    op.execute(
        f"""
        CREATE FUNCTION ml_forecasts_guard() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'ml_forecasts is append-only (delete of id %)', OLD.id;
          END IF;
          IF ROW({old}) IS DISTINCT FROM ROW({new}) THEN
            RAISE EXCEPTION 'ml_forecasts prediction fields are immutable (id %)', OLD.id;
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_ml_forecasts_guard BEFORE UPDATE OR DELETE ON ml_forecasts
          FOR EACH ROW EXECUTE FUNCTION ml_forecasts_guard();

        CREATE FUNCTION ml_forecast_lines_guard() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'ml_forecast_lines is append-only';
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_ml_forecast_lines_guard BEFORE UPDATE OR DELETE ON ml_forecast_lines
          FOR EACH ROW EXECUTE FUNCTION ml_forecast_lines_guard();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_ml_forecast_lines_guard ON ml_forecast_lines")
    op.execute("DROP TRIGGER IF EXISTS trg_ml_forecasts_guard ON ml_forecasts")
    op.drop_table("ml_forecast_lines")
    op.drop_table("ml_forecasts")
    op.execute("DROP FUNCTION IF EXISTS ml_forecast_lines_guard()")
    op.execute("DROP FUNCTION IF EXISTS ml_forecasts_guard()")
