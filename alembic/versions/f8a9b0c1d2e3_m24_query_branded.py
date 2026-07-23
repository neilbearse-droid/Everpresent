"""m24 query.branded (branded vs competitive query split)

Adds queries.branded. A branded query names the brand and probes what the model
says about it; these form the brand-knowledge layer and are excluded from the
competitive-visibility metrics so they don't inflate them. False for every
existing row, so the split is inert until queries are flagged.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
"""

import sqlalchemy as sa
from alembic import op

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "queries",
        sa.Column("branded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_queries_branded", "queries", ["branded"])


def downgrade() -> None:
    op.drop_index("ix_queries_branded", table_name="queries")
    op.drop_column("queries", "branded")
