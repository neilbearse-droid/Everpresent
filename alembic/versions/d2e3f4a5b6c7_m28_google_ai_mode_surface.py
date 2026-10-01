"""m28 surfacecode enum value 'google_ai_mode' (Google AI Mode via SerpApi)

surface columns (results, tenant_surfaces, classifications, visibility_daily,
...) share the native Postgres enum `surfacecode`, so the new surface needs
ALTER TYPE ... ADD VALUE, run outside a transaction. SQLite stores enums as
strings and needs nothing.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""

from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE surfacecode ADD VALUE IF NOT EXISTS 'google_ai_mode'")


def downgrade() -> None:
    # Postgres can't drop an enum value; leaving it is harmless.
    pass
