"""m14 consulted sources + cited_text

Adds richer retrieval capture (§AEO-plan M6):
- citations.cited_text: the exact snippet an engine quoted (Claude exposes it)
- consulted_sources table: sources an engine read but did NOT cite — kept out
  of the citations table so citation counts stay clean.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
"""

import sqlalchemy as sa
from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "citations",
        sa.Column("cited_text", sa.String(), nullable=False, server_default=""),
    )
    op.create_table(
        "consulted_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("result_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["result_id"], ["results.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_consulted_sources_result_id", "consulted_sources", ["result_id"])
    op.create_index("ix_consulted_sources_tenant_id", "consulted_sources", ["tenant_id"])
    op.create_index("ix_consulted_sources_domain", "consulted_sources", ["domain"])


def downgrade() -> None:
    op.drop_index("ix_consulted_sources_domain", table_name="consulted_sources")
    op.drop_index("ix_consulted_sources_tenant_id", table_name="consulted_sources")
    op.drop_index("ix_consulted_sources_result_id", table_name="consulted_sources")
    op.drop_table("consulted_sources")
    op.drop_column("citations", "cited_text")
