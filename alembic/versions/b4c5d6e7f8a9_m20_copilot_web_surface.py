"""m20 copilot_web surface

Adds the Microsoft Copilot consumer-web measured surface (copilot_web) to the
surfacecode enum. Postgres stores surfacecode as a native ENUM, so the new
value is added with ALTER TYPE ... ADD VALUE (outside a transaction). SQLite has
no native enum (values are plain strings), so this is a no-op there.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""

from alembic import op

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # ADD VALUE cannot run inside a transaction block; commit the surrounding
    # migration transaction first. IF NOT EXISTS keeps re-runs idempotent.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE surfacecode ADD VALUE IF NOT EXISTS 'copilot_web'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum without recreating the type;
    # leaving the unused label in place is harmless and the safe choice.
    pass
