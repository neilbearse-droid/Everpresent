"""m42 tenants.audience (d2c = free-tier models, b2b = paid-tier models)

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default so existing rows load "d2c" rather than NULL (the aio_geo
    # lesson: default_factory fires on construction, not on load).
    with op.batch_alter_table("tenants") as batch:
        batch.add_column(sa.Column("audience", sqlmodel.sql.sqltypes.AutoString(),
                                   nullable=False, server_default="d2c"))


def downgrade() -> None:
    with op.batch_alter_table("tenants") as batch:
        batch.drop_column("audience")
