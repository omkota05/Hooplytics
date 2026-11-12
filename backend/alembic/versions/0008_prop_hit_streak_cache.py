"""prop hit streak cache

Revision ID: 0008_prop_hit_streak_cache
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_prop_hit_streak_cache"
down_revision = "0007_prop_canonical_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prop_hit_streak_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("before_game_id", sa.Integer(), nullable=False),
        sa.Column("category_key", sa.String(length=24), nullable=False),
        sa.Column("line", sa.Float(), nullable=False),
        sa.Column("pick_side", sa.String(length=8), nullable=False),
        sa.Column("current_season_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("streak_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("data_sync_reference", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["before_game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "player_id",
            "before_game_id",
            "category_key",
            "line",
            "pick_side",
            "current_season_only",
            name="uq_prop_hit_streak_cache_key",
        ),
    )
    op.create_index("ix_prop_hit_streak_cache_player", "prop_hit_streak_cache", ["player_id"])
    op.create_index("ix_prop_hit_streak_cache_game", "prop_hit_streak_cache", ["before_game_id"])


def downgrade() -> None:
    op.drop_index("ix_prop_hit_streak_cache_game", table_name="prop_hit_streak_cache")
    op.drop_index("ix_prop_hit_streak_cache_player", table_name="prop_hit_streak_cache")
    op.drop_table("prop_hit_streak_cache")
