"""m21 query persona_runs (selective query x persona matrix)

Adds queries.persona_runs (JSON list of {segment, overlay}) so a query can name
which non-baseline personas run against it, with an optional vertical-overlay
clause. Empty for every existing row — tenants without a "generic" baseline
persona keep the full persona × query cross-product, so this is inert until a
tenant opts into selective mode.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
"""

import sqlalchemy as sa
from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "queries",
        sa.Column("persona_runs", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("queries", "persona_runs")
