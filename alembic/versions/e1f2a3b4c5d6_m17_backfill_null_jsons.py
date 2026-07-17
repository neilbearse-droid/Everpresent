"""m17 backfill NULL json defaults (audit C1/M2)

M6 added tenants.aio_geo and classifications.google_aio_signals as nullable
columns with NO server_default, so rows that predate M6 were backfilled NULL.
The models type these as non-optional dicts (default_factory fires only on
ORM construction, never on load), so a migrated production row loads None and
crashes `dict(tenant.aio_geo)` in the Mode B worker. This backfills the NULLs
and sets a server_default so future inserts can't reintroduce them.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE tenants SET aio_geo = '{\"gl\": \"ca\", \"hl\": \"en\"}' "
        "WHERE aio_geo IS NULL"
    )
    op.execute(
        "UPDATE classifications SET google_aio_signals = '{}' "
        "WHERE google_aio_signals IS NULL"
    )
    # Postgres: pin a server_default so future inserts never store NULL again.
    # SQLite can't ALTER a column default; the backfill above plus the model
    # default_factory covers it there.
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("tenants", "aio_geo",
                        server_default=sa.text("'{\"gl\": \"ca\", \"hl\": \"en\"}'"))
        op.alter_column("classifications", "google_aio_signals",
                        server_default=sa.text("'{}'"))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("tenants", "aio_geo", server_default=None)
        op.alter_column("classifications", "google_aio_signals", server_default=None)
