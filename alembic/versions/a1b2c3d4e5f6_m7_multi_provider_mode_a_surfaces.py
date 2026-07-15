"""m7 multi-provider mode a surfaces

Adds the API-mode measured surfaces perplexity_api, claude_api, gemini_api to
the surfacecode enum. Postgres stores surfacecode as a native ENUM, so new
values must be added with ALTER TYPE ... ADD VALUE (outside a transaction).
SQLite has no native enum (values are plain strings), so this is a no-op there.

Revision ID: a1b2c3d4e5f6
Revises: 730dbcb527fe
"""

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "730dbcb527fe"
branch_labels = None
depends_on = None

NEW_VALUES = ("perplexity_api", "claude_api", "gemini_api")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # ADD VALUE cannot run inside a transaction block; commit the surrounding
    # migration transaction first. IF NOT EXISTS keeps re-runs idempotent.
    with op.get_context().autocommit_block():
        for value in NEW_VALUES:
            op.execute(f"ALTER TYPE surfacecode ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum without recreating the type;
    # leaving the unused labels in place is harmless and the safe choice.
    pass
