"""m22 untracked mentions + entity-extraction opt-in (step 4)

Adds the untracked_mentions table (products/companies an answer named that
aren't the tracked brand or a tracked competitor — the whitespace slide) and
tenants.entity_extraction_enabled (opt-in to the governed extraction LLM pass,
off by default so existing tenants incur no LLM cost).

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
"""

import sqlalchemy as sa
from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "entity_extraction_enabled", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "untracked_mentions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("result_id", sa.Integer(), sa.ForeignKey("results.id"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("entity_name", sa.String(), nullable=False),
        sa.Column("detector_version", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_untracked_mentions_result_id", "untracked_mentions", ["result_id"])
    op.create_index("ix_untracked_mentions_tenant_id", "untracked_mentions", ["tenant_id"])
    op.create_index("ix_untracked_mentions_entity_name", "untracked_mentions", ["entity_name"])


def downgrade() -> None:
    op.drop_index("ix_untracked_mentions_entity_name", table_name="untracked_mentions")
    op.drop_index("ix_untracked_mentions_tenant_id", table_name="untracked_mentions")
    op.drop_index("ix_untracked_mentions_result_id", table_name="untracked_mentions")
    op.drop_table("untracked_mentions")
    op.drop_column("tenants", "entity_extraction_enabled")
