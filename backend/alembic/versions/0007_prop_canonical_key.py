"""Canonical prop offer unique key (dedupe market_line_id variants)

Revision ID: 0007_prop_canonical_key
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_prop_canonical_key"
down_revision = "0006_prop_hcs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY source_kind, sportsbook_label, unabated_event_id,
                                    unabated_person_id, unabated_bet_type_id, line, pick_side
                       ORDER BY is_active DESC, updated_at DESC NULLS LAST, id DESC
                   ) AS rn
            FROM prop_offers
            WHERE source_kind = 'unabated'
              AND unabated_event_id IS NOT NULL
        )
        DELETE FROM prop_offers
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )
    op.drop_constraint("uq_prop_offer_natural_key", "prop_offers", type_="unique")
    op.create_unique_constraint(
        "uq_prop_offer_canonical_key",
        "prop_offers",
        [
            "source_kind",
            "sportsbook_label",
            "unabated_event_id",
            "unabated_person_id",
            "unabated_bet_type_id",
            "line",
            "pick_side",
        ],
    )
    op.create_index(
        "ix_prop_offers_eligible_list",
        "prop_offers",
        ["is_active", "match_status", "is_alternate_line", "game_start_time", "hcs_score"],
        postgresql_where=sa.text(
            "is_active = true AND match_status = 'matched' AND is_alternate_line = false"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_prop_offers_eligible_list", table_name="prop_offers")
    op.drop_constraint("uq_prop_offer_canonical_key", "prop_offers", type_="unique")
    op.create_unique_constraint(
        "uq_prop_offer_natural_key",
        "prop_offers",
        [
            "source_kind",
            "sportsbook_label",
            "unabated_event_id",
            "unabated_person_id",
            "unabated_bet_type_id",
            "unabated_side_index",
            "unabated_market_line_id",
            "line",
            "pick_side",
            "alternate_key",
        ],
    )
