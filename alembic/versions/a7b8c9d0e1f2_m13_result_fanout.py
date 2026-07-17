"""m13 result fanout queries

Adds results.fanout_queries (JSON): the sub-queries an engine fanned out into
on the way to an answer (§AEO-plan M1). Exposed by Gemini (webSearchQueries)
and, where present, OpenAI web_search_call actions.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "results",
        sa.Column("fanout_queries", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("results", "fanout_queries")
