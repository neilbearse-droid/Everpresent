"""m27 spend_entries ledger (paid calls outside runs count toward the cap)

Content drafting is a paid LLM call that isn't part of a Run, so it was
invisible to the monthly spend cap. Each such call now books a row here and
month_spend_usd sums runs + entries.

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spend_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_spend_entries_tenant_id", "spend_entries", ["tenant_id"])
    op.create_index("ix_spend_entries_kind", "spend_entries", ["kind"])
    op.create_index("ix_spend_entries_created_at", "spend_entries", ["created_at"])


def downgrade() -> None:
    op.drop_table("spend_entries")
