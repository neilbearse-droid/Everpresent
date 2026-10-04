"""m35: sponsored_units (ads kept out of organic visibility)

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "e9f0a1b2c3d4"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None

_STR = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    op.create_table(
        "sponsored_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("result_id", sa.Integer(), sa.ForeignKey("results.id"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("advertiser", _STR(), nullable=False, server_default=""),
        sa.Column("advertiser_type", _STR(), nullable=False, server_default=""),
        sa.Column("domain", _STR(), nullable=False, server_default=""),
        sa.Column("title", _STR(), nullable=False, server_default=""),
        sa.Column("url", _STR(), nullable=False, server_default=""),
        sa.Column("placement", _STR(), nullable=False, server_default=""),
    )
    op.create_index("ix_sponsored_units_result_id", "sponsored_units", ["result_id"])
    op.create_index("ix_sponsored_units_tenant_id", "sponsored_units", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_sponsored_units_tenant_id", table_name="sponsored_units")
    op.drop_index("ix_sponsored_units_result_id", table_name="sponsored_units")
    op.drop_table("sponsored_units")
