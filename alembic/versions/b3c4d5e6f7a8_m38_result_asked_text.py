"""m38 results.asked_text (the wording a sample actually asked)

Repeated samples rotate through a query's paraphrases, but the wording sent
lived only in the raw envelope (`asked`). Stored on the row so the effect of a
wording can be read without opening object storage. "" for every existing row;
results stay keyed by query_text.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None

_STR = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    with op.batch_alter_table("results") as batch:
        batch.add_column(sa.Column("asked_text", _STR(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("results") as batch:
        batch.drop_column("asked_text")
