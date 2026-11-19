"""prop offer snapshots (historical odds archive + settlement)

Revision ID: 0009_prop_offer_snapshots
"""

import sqlalchemy as sa

from alembic import op

revision = "0009_prop_offer_snapshots"
down_revision = "0008_prop_hit_streak_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prop_offer_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("prop_offers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("import_run_id", sa.Integer(), sa.ForeignKey("prop_import_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("sportsbook_label", sa.String(80), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=True),
        sa.Column("game_id", sa.BigInteger(), sa.ForeignKey("games.id"), nullable=True),
        sa.Column("category_key", sa.String(24), nullable=False),
        sa.Column("line", sa.Float(), nullable=False),
        sa.Column("pick_side", sa.String(8), nullable=False),
        sa.Column("american_odds", sa.Integer(), nullable=True),
        sa.Column("is_alternate_line", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("unabated_event_id", sa.BigInteger(), nullable=True),
        sa.Column("unabated_person_id", sa.BigInteger(), nullable=True),
        sa.Column("unabated_bet_type_id", sa.Integer(), nullable=True),
        sa.Column("unabated_market_line_id", sa.BigInteger(), nullable=True),
        sa.Column("game_start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("line_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("market_status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("result", sa.String(16), nullable=True),
        sa.Column("actual_value", sa.Float(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pos_game", "prop_offer_snapshots", ["game_id"])
    op.create_index("ix_pos_player_game_cat", "prop_offer_snapshots", ["player_id", "game_id", "category_key"])
    op.create_index(
        "ix_pos_unsettled", "prop_offer_snapshots", ["game_id"], postgresql_where=sa.text("result IS NULL")
    )
    op.create_index(
        "uq_pos_offer_latest",
        "prop_offer_snapshots",
        ["offer_id"],
        unique=True,
        postgresql_where=sa.text("is_latest AND offer_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_pos_offer_latest", table_name="prop_offer_snapshots")
    op.drop_index("ix_pos_unsettled", table_name="prop_offer_snapshots")
    op.drop_index("ix_pos_player_game_cat", table_name="prop_offer_snapshots")
    op.drop_index("ix_pos_game", table_name="prop_offer_snapshots")
    op.drop_table("prop_offer_snapshots")
