"""m15 brand facts + accuracy findings

Adds the per-tenant fact sheet and the accuracy findings it produces
(§AEO-plan M4): flag answers that state something false about the brand.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""

import sqlalchemy as sa
from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brand_facts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("expected", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_facts_tenant_id", "brand_facts", ["tenant_id"])

    op.create_table(
        "accuracy_findings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("result_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("fact_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("expected", sa.String(), nullable=False),
        sa.Column("stated", sa.String(), nullable=False),
        sa.Column("snippet", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=False),
        sa.Column("detector_version", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["result_id"], ["results.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accuracy_findings_result_id", "accuracy_findings", ["result_id"])
    op.create_index("ix_accuracy_findings_tenant_id", "accuracy_findings", ["tenant_id"])
    op.create_index("ix_accuracy_findings_fact_id", "accuracy_findings", ["fact_id"])


def downgrade() -> None:
    op.drop_index("ix_accuracy_findings_fact_id", table_name="accuracy_findings")
    op.drop_index("ix_accuracy_findings_tenant_id", table_name="accuracy_findings")
    op.drop_index("ix_accuracy_findings_result_id", table_name="accuracy_findings")
    op.drop_table("accuracy_findings")
    op.drop_index("ix_brand_facts_tenant_id", table_name="brand_facts")
    op.drop_table("brand_facts")
