"""denormalized HCS score column for Prop Finder ranking

Revision ID: 0006_prop_hcs
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_prop_hcs"
down_revision = "0005_prop_hit_ranking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prop_offers", sa.Column("hcs_score", sa.Float(), nullable=True))
    op.create_index(
        "ix_prop_offers_hcs_active_matched",
        "prop_offers",
        ["is_active", "match_status", "hcs_score"],
        postgresql_where=sa.text("is_active = true AND match_status = 'matched'"),
    )


def downgrade() -> None:
    op.drop_index("ix_prop_offers_hcs_active_matched", table_name="prop_offers")
    op.drop_column("prop_offers", "hcs_score")
