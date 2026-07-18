"""m23 content drafts (step 5 — the closed loop)

Adds the content_drafts table: the generated corrective/optimized content that
closes the insight→content loop. Governed utility-LLM output, tied back to the
gap it answers via (source_kind, source_ref).

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
"""

import sqlalchemy as sa
from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_drafts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False, server_default=""),
        sa.Column("body", sa.String(), nullable=False, server_default=""),
        sa.Column("model", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.Enum("draft", "approved", "published", "dismissed", name="contentdraftstatus"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_content_drafts_tenant_id", "content_drafts", ["tenant_id"])
    op.create_index("ix_content_drafts_source_kind", "content_drafts", ["source_kind"])
    op.create_index("ix_content_drafts_source_ref", "content_drafts", ["source_ref"])
    op.create_index("ix_content_drafts_status", "content_drafts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_content_drafts_status", table_name="content_drafts")
    op.drop_index("ix_content_drafts_source_ref", table_name="content_drafts")
    op.drop_index("ix_content_drafts_source_kind", table_name="content_drafts")
    op.drop_index("ix_content_drafts_tenant_id", table_name="content_drafts")
    op.drop_table("content_drafts")
    sa.Enum(name="contentdraftstatus").drop(op.get_bind(), checkfirst=True)
