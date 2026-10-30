"""m36 surfacecode enum value 'meta_api' (Meta AI via the Meta Model API)

Same pattern as m28: the native Postgres enum `surfacecode` needs ALTER TYPE
... ADD VALUE outside a transaction. SQLite stores enums as strings.

Revision ID: f1a2b3c4d5e6
Revises: e9f0a1b2c3d4
"""

from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE surfacecode ADD VALUE IF NOT EXISTS 'meta_api'")


def downgrade() -> None:
    # Postgres can't drop an enum value; leaving it is harmless.
    pass
