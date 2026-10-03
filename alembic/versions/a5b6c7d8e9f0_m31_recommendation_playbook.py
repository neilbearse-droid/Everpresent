"""m31 Recommendations playbook: title, priority, evidence, why, steps,
query_text, link on recommendations

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "a5b6c7d8e9f0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None

_STR = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    with op.batch_alter_table("recommendations") as batch:
        batch.add_column(sa.Column("title", _STR(), nullable=False, server_default=""))
        batch.add_column(sa.Column("priority", sa.Integer(), nullable=False,
                                   server_default="50"))
        batch.add_column(sa.Column("evidence", _STR(), nullable=False, server_default=""))
        batch.add_column(sa.Column("why", _STR(), nullable=False, server_default=""))
        batch.add_column(sa.Column("steps", sa.JSON(), nullable=False,
                                   server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("query_text", _STR(), nullable=False, server_default=""))
        batch.add_column(sa.Column("link", _STR(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch:
        for name in ("link", "query_text", "steps", "why", "evidence", "priority", "title"):
            batch.drop_column(name)
