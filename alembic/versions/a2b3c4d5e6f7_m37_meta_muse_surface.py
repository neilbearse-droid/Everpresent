"""m37 surfacecode enum value 'meta_muse' (Muse, imported captures only)

Same pattern as m36: the native Postgres enum `surfacecode` needs ALTER TYPE
... ADD VALUE outside a transaction. SQLite stores enums as strings.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""

from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE surfacecode ADD VALUE IF NOT EXISTS 'meta_muse'")


def downgrade() -> None:
    # Postgres can't drop an enum value; leaving it is harmless.
    pass
