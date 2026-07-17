"""m11 interventions

Adds the interventions ledger: shipped fixes per gap query, so measurement can
split results into before/after and attribute the lift.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interventions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("query_text", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("shipped_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interventions_tenant_id", "interventions", ["tenant_id"])
    op.create_index("ix_interventions_query_text", "interventions", ["query_text"])


def downgrade() -> None:
    op.drop_index("ix_interventions_query_text", table_name="interventions")
    op.drop_index("ix_interventions_tenant_id", table_name="interventions")
    op.drop_table("interventions")
