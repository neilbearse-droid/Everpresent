"""m39 tenants.engine_weights (audience weights for the pooled headline)

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenants") as batch:
        batch.add_column(sa.Column("engine_weights", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("engine_weights_changed_on",
                                   sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tenants") as batch:
        batch.drop_column("engine_weights_changed_on")
        batch.drop_column("engine_weights")
