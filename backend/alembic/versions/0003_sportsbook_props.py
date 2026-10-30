"""sportsbook prop offers and unabated mappings

Revision ID: 0003_sportsbook_props
Revises: 0002_boxscore_retry_backoff
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_sportsbook_props"
down_revision: str | None = "0002_boxscore_backoff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sportsbook_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("unabated_market_source_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("unabated_market_source_id"),
    )
    op.create_table(
        "unabated_identity_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("unabated_id", sa.BigInteger(), nullable=False),
        sa.Column("hooplytics_id", sa.BigInteger(), nullable=False),
        sa.Column("match_method", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "unabated_id", name="uq_unabated_entity"),
    )
    op.create_index("ix_unabated_mapping_hoop", "unabated_identity_mappings", ["entity_type", "hooplytics_id"])

    op.create_table(
        "prop_offers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("sportsbook_source_id", sa.Integer(), nullable=True),
        sa.Column("sportsbook_label", sa.String(length=80), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=True),
        sa.Column("game_id", sa.BigInteger(), nullable=True),
        sa.Column("opponent_team_id", sa.Integer(), nullable=True),
        sa.Column("unabated_event_id", sa.BigInteger(), nullable=True),
        sa.Column("unabated_person_id", sa.BigInteger(), nullable=True),
        sa.Column("unabated_bet_type_id", sa.Integer(), nullable=True),
        sa.Column("unabated_market_line_id", sa.BigInteger(), nullable=True),
        sa.Column("unabated_side_index", sa.SmallInteger(), nullable=True),
        sa.Column("period_type_id", sa.SmallInteger(), nullable=True),
        sa.Column("category_key", sa.String(length=24), nullable=False),
        sa.Column("line", sa.Float(), nullable=False),
        sa.Column("pick_side", sa.String(length=8), nullable=False),
        sa.Column("american_odds", sa.Integer(), nullable=True),
        sa.Column("is_alternate_line", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("alternate_key", sa.String(length=64), nullable=True),
        sa.Column("deep_link_raw", sa.Text(), nullable=True),
        sa.Column("deep_link_published", sa.Text(), nullable=True),
        sa.Column("event_name", sa.String(length=120), nullable=True),
        sa.Column("player_name_raw", sa.String(length=120), nullable=True),
        sa.Column("game_start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("game_date", sa.Date(), nullable=True),
        sa.Column("line_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("match_status", sa.String(length=16), server_default="matched", nullable=False),
        sa.Column("match_note", sa.Text(), nullable=True),
        sa.Column("hit_rates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("historical_avg", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["opponent_team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["sportsbook_source_id"], ["sportsbook_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
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
            name="uq_prop_offer_natural_key",
        ),
    )
    op.create_index("ix_prop_offers_game_start", "prop_offers", ["game_start_time"])
    op.create_index("ix_prop_offers_category", "prop_offers", ["category_key"])
    op.create_index("ix_prop_offers_player_id", "prop_offers", ["player_id"])
    op.create_index("ix_prop_offers_game_id", "prop_offers", ["game_id"])

    op.create_table(
        "prop_import_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offers_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("offers_upserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("offers_matched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("offers_unmatched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("prop_import_runs")
    op.drop_table("prop_offers")
    op.drop_table("unabated_identity_mappings")
    op.drop_table("sportsbook_sources")
