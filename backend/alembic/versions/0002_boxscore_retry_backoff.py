"""Back off between box score retries

Revision ID: 0002_boxscore_backoff
Revises: 0001_initial
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_boxscore_backoff"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("games", sa.Column("boxscore_next_attempt_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("games", "boxscore_next_attempt_at")
