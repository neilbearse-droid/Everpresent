"""m10 page presence

Adds the page_presence table: on-page brand/competitor presence + citability
features for the Power Pages the engines cite, refreshed by the crawl job.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_presence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("brand_found", sa.Boolean(), nullable=False),
        sa.Column("competitors_found", sa.JSON(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_page_presence_tenant_id", "page_presence", ["tenant_id"])
    op.create_index("ix_page_presence_url", "page_presence", ["url"])


def downgrade() -> None:
    op.drop_index("ix_page_presence_url", table_name="page_presence")
    op.drop_index("ix_page_presence_tenant_id", table_name="page_presence")
    op.drop_table("page_presence")
