"""m9 tenant plan

Adds tenants.plan (pricing tier). Existing tenants default to 'custom'
(uncapped), preserving pre-plan behaviour.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("plan", sa.String(), nullable=False, server_default="custom"),
    )


def downgrade() -> None:
    op.drop_column("tenants", "plan")
