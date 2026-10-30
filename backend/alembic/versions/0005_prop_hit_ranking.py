"""denormalized hit counts and wilson lower bounds for prop finder ranking

Revision ID: 0005_prop_hit_ranking
Revises: 0004_prop_hit_cache
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_prop_hit_ranking"
down_revision: str | None = "0004_prop_hit_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("prop_offers", sa.Column("l5_games", sa.SmallInteger(), nullable=True))
    op.add_column("prop_offers", sa.Column("l20_games", sa.SmallInteger(), nullable=True))
    op.add_column("prop_offers", sa.Column("h2h_games", sa.SmallInteger(), nullable=True))
    for prefix in ("l5", "l10", "l20", "h2h"):
        op.add_column("prop_offers", sa.Column(f"{prefix}_hits", sa.SmallInteger(), nullable=True))
        op.add_column("prop_offers", sa.Column(f"{prefix}_attempts", sa.SmallInteger(), nullable=True))
        op.add_column("prop_offers", sa.Column(f"{prefix}_wilson_lb", sa.Float(), nullable=True))
    op.create_index(
        "ix_prop_offers_wilson_l10",
        "prop_offers",
        ["is_active", "match_status", "l10_wilson_lb"],
        postgresql_where=sa.text("is_active = true AND match_status = 'matched'"),
    )


def downgrade() -> None:
    op.drop_index("ix_prop_offers_wilson_l10", table_name="prop_offers")
    for prefix in ("h2h", "l20", "l10", "l5"):
        op.drop_column("prop_offers", f"{prefix}_wilson_lb")
        op.drop_column("prop_offers", f"{prefix}_attempts")
        op.drop_column("prop_offers", f"{prefix}_hits")
    op.drop_column("prop_offers", "h2h_games")
    op.drop_column("prop_offers", "l20_games")
    op.drop_column("prop_offers", "l5_games")
