"""prop line hit cache and denormalized list columns

Revision ID: 0004_prop_hit_cache
Revises: 0003_sportsbook_props
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_prop_hit_cache"
down_revision: str | None = "0003_sportsbook_props"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prop_line_hit_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("opponent_team_id", sa.Integer(), nullable=True),
        sa.Column("category_key", sa.String(length=24), nullable=False),
        sa.Column("line", sa.Float(), nullable=False),
        sa.Column("hit_rates", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("historical_avg", sa.Float(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("data_sync_reference", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["opponent_team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "player_id", "game_id", "category_key", "line", name="uq_prop_line_hit_cache_key"
        ),
    )
    op.create_index("ix_prop_line_hit_cache_player", "prop_line_hit_cache", ["player_id"])
    op.create_index("ix_prop_line_hit_cache_game", "prop_line_hit_cache", ["game_id"])

    op.add_column("prop_offers", sa.Column("hit_cache_id", sa.Integer(), nullable=True))
    op.add_column("prop_offers", sa.Column("l5_hit_pct", sa.Float(), nullable=True))
    op.add_column("prop_offers", sa.Column("l10_hit_pct", sa.Float(), nullable=True))
    op.add_column("prop_offers", sa.Column("l15_hit_pct", sa.Float(), nullable=True))
    op.add_column("prop_offers", sa.Column("l20_hit_pct", sa.Float(), nullable=True))
    op.add_column("prop_offers", sa.Column("l30_hit_pct", sa.Float(), nullable=True))
    op.add_column("prop_offers", sa.Column("h2h_hit_pct", sa.Float(), nullable=True))
    op.add_column("prop_offers", sa.Column("l10_games", sa.SmallInteger(), nullable=True))
    op.add_column("prop_offers", sa.Column("hit_computed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_prop_offers_hit_cache_id",
        "prop_offers",
        "prop_line_hit_cache",
        ["hit_cache_id"],
        ["id"],
    )
    op.create_index(
        "ix_prop_offers_active_matched_l10",
        "prop_offers",
        ["is_active", "match_status", "l10_hit_pct"],
        postgresql_where=sa.text("is_active = true AND match_status = 'matched'"),
    )
    op.create_index("ix_prop_offers_game_start_active", "prop_offers", ["game_start_time", "is_active"])
    op.create_index("ix_prop_offers_category_line", "prop_offers", ["category_key", "line"])


def downgrade() -> None:
    op.drop_index("ix_prop_offers_category_line", table_name="prop_offers")
    op.drop_index("ix_prop_offers_game_start_active", table_name="prop_offers")
    op.drop_index("ix_prop_offers_active_matched_l10", table_name="prop_offers")
    op.drop_constraint("fk_prop_offers_hit_cache_id", "prop_offers", type_="foreignkey")
    op.drop_column("prop_offers", "hit_computed_at")
    op.drop_column("prop_offers", "l10_games")
    op.drop_column("prop_offers", "h2h_hit_pct")
    op.drop_column("prop_offers", "l30_hit_pct")
    op.drop_column("prop_offers", "l20_hit_pct")
    op.drop_column("prop_offers", "l15_hit_pct")
    op.drop_column("prop_offers", "l10_hit_pct")
    op.drop_column("prop_offers", "l5_hit_pct")
    op.drop_column("prop_offers", "hit_cache_id")
    op.drop_table("prop_line_hit_cache")
