"""m34 Engine smoke test results: engine_checks

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "d8e9f0a1b2c3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None

_STR = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    op.create_table(
        "engine_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("surface", _STR(), nullable=False),
        sa.Column("status", _STR(), nullable=False, server_default=""),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("served_model", _STR(), nullable=False, server_default=""),
        sa.Column("text_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("citations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("searches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("detail", _STR(), nullable=False, server_default=""),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_engine_checks_tenant_id", "engine_checks", ["tenant_id"])
    op.create_index("ix_engine_checks_surface", "engine_checks", ["surface"])
    op.create_index("ix_engine_checks_checked_at", "engine_checks", ["checked_at"])


def downgrade() -> None:
    op.drop_index("ix_engine_checks_checked_at", table_name="engine_checks")
    op.drop_index("ix_engine_checks_surface", table_name="engine_checks")
    op.drop_index("ix_engine_checks_tenant_id", table_name="engine_checks")
    op.drop_table("engine_checks")
