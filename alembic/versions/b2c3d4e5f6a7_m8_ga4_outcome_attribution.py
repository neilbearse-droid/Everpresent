"""m8 ga4 outcome attribution

Adds tenants.ga4_property_id and the ai_referral_daily table (AI-referred
sessions + key events per day and engine, pulled from GA4).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("ga4_property_id", sa.String(), nullable=True))
    op.create_table(
        "ai_referral_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("engine", sa.String(), nullable=False),
        sa.Column("sessions", sa.Integer(), nullable=False),
        sa.Column("conversions", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_referral_daily_tenant_id", "ai_referral_daily", ["tenant_id"])
    op.create_index("ix_ai_referral_daily_date", "ai_referral_daily", ["date"])
    op.create_index("ix_ai_referral_daily_engine", "ai_referral_daily", ["engine"])


def downgrade() -> None:
    op.drop_index("ix_ai_referral_daily_engine", table_name="ai_referral_daily")
    op.drop_index("ix_ai_referral_daily_date", table_name="ai_referral_daily")
    op.drop_index("ix_ai_referral_daily_tenant_id", table_name="ai_referral_daily")
    op.drop_table("ai_referral_daily")
    op.drop_column("tenants", "ga4_property_id")
