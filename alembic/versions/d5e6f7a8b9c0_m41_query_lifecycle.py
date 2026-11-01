"""m41 queries.created_at / paused_at / paused_by (question lifecycle)

Revision ID: d5e6f7a8b9c0
Revises: d7e8f9a0b1c2
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("queries") as batch:
        batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("paused_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("paused_by", sqlmodel.sql.sqltypes.AutoString(),
                                   nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("queries") as batch:
        batch.drop_column("paused_by")
        batch.drop_column("paused_at")
        batch.drop_column("created_at")
