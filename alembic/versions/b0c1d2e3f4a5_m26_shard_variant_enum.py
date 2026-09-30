"""m26 resultvariant enum value 'shard' (fan-out re-probe results)

results.variant is a native Postgres enum (created in m3), so the 'shard'
variant introduced with M25b needs ALTER TYPE ... ADD VALUE, run outside a
transaction. SQLite stores enums as strings and needs nothing.

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
"""

from alembic import op

revision = "b0c1d2e3f4a5"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE resultvariant ADD VALUE IF NOT EXISTS 'shard'")


def downgrade() -> None:
    # Postgres can't drop an enum value; an unused 'shard' label is harmless.
    pass
