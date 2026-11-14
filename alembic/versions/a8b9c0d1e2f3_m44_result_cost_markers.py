"""m44 results gain requested_model and entities_version, so paid work
(the diagnosis twin, entity extraction) is recognised as done without
re-reading raw envelopes or paying for it twice

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None

_STR = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    with op.batch_alter_table("results") as batch:
        batch.add_column(sa.Column("requested_model", _STR(), nullable=False, server_default=""))
        batch.add_column(sa.Column("entities_version", _STR(), nullable=False, server_default=""))
    # Answers that already have extracted names were read by the current
    # extractor: mark them, so the next reprocess doesn't buy them again.
    op.execute(
        "UPDATE results SET entities_version = 'entities-v1' WHERE id IN "
        "(SELECT DISTINCT result_id FROM untracked_mentions "
        "WHERE detector_version = 'entities-v1')"
    )


def downgrade() -> None:
    with op.batch_alter_table("results") as batch:
        batch.drop_column("entities_version")
        batch.drop_column("requested_model")
