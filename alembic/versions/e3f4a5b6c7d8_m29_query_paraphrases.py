"""m29 queries.paraphrases (alternate wordings for repeated sampling)

Repeated samples of a query's generic cell rotate through its wordings, so a
mention rate measures the topic, not one exact phrasing.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
"""

import sqlalchemy as sa

from alembic import op

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "queries",
        sa.Column("paraphrases", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("queries", "paraphrases")
