"""m19 notify_emails NULL backfill + results composite index (audit low)

Two low-severity audit fixups:

1. M5 added tenants.notify_emails as a nullable JSON column with no
   server_default and no backfill (the M17 backfill covered only aio_geo and
   google_aio_signals). The model types it as a non-optional list[str], so a
   pre-M5 row loads None and `len(tenant.notify_emails)` raises TypeError while
   finalizing a run. Backfill NULL -> [] and pin a Postgres server_default,
   mirroring M17.

2. Add a (tenant_id, variant, status) composite index on results — the exact
   predicate six dashboard endpoints filter on — so they don't scan the
   tenant's whole result history per request.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
"""

import sqlalchemy as sa
from alembic import op

revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE tenants SET notify_emails = '[]' WHERE notify_emails IS NULL")
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("tenants", "notify_emails", server_default=sa.text("'[]'"))
    op.create_index(
        "ix_results_tenant_variant_status", "results", ["tenant_id", "variant", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_results_tenant_variant_status", table_name="results")
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("tenants", "notify_emails", server_default=None)
