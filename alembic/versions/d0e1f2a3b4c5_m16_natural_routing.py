"""m16 natural routing probe

Adds routing measurement (§AEO-plan M2):
- resultvariant enum value 'natural' (search offered, not forced)
- results.web_search_calls: how many searches the surface actually ran

Postgres stores resultvariant as a native ENUM, so the new value is added with
ALTER TYPE ... ADD VALUE (outside a transaction). SQLite is a no-op.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""

import sqlalchemy as sa
from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "results",
        sa.Column("web_search_calls", sa.Integer(), nullable=False, server_default="0"),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE resultvariant ADD VALUE IF NOT EXISTS 'natural'")


def downgrade() -> None:
    op.drop_column("results", "web_search_calls")
    # Postgres cannot drop an enum value without recreating the type; the unused
    # 'natural' label is harmless and left in place.
