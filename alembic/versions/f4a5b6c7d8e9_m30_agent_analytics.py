"""m30 Agent Analytics: agent_traffic_daily + tenants.agent_log_token

AI bot hits from access logs, aggregated per (day, bot, path, status). Only
AI-bot lines are stored; human traffic never is.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_traffic_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("date", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("bot", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company", sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default=""),
        sa.Column("purpose", sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default=""),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default=""),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("tenant_id", "date", "bot", "path", "status",
                            name="uq_agent_traffic_cell"),
    )
    for col in ("tenant_id", "date", "bot", "purpose"):
        op.create_index(f"ix_agent_traffic_daily_{col}", "agent_traffic_daily", [col])
    op.add_column("tenants", sa.Column("agent_log_token", sqlmodel.sql.sqltypes.AutoString(),
                                       nullable=True))
    op.create_index("ix_tenants_agent_log_token", "tenants", ["agent_log_token"])


def downgrade() -> None:
    op.drop_index("ix_tenants_agent_log_token", "tenants")
    op.drop_column("tenants", "agent_log_token")
    op.drop_table("agent_traffic_daily")
