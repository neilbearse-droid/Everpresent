"""m42 recommendations: category, impact, effort, control, speed, targets

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

_STR = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    with op.batch_alter_table("recommendations") as batch:
        batch.add_column(sa.Column("category", _STR(), nullable=False, server_default=""))
        batch.add_column(sa.Column("impact", sa.JSON(), nullable=False,
                                   server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("effort", _STR(), nullable=False, server_default=""))
        batch.add_column(sa.Column("control", _STR(), nullable=False, server_default=""))
        batch.add_column(sa.Column("speed", _STR(), nullable=False, server_default=""))
        batch.add_column(sa.Column("targets", sa.JSON(), nullable=False,
                                   server_default=sa.text("'[]'")))


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch:
        for name in ("targets", "speed", "control", "effort", "impact", "category"):
            batch.drop_column(name)
