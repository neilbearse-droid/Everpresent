"""m12 scraping v3: locations + blocked status + result location

Adds location-based query support and block-detection signal:
- `locations` table (per-tenant places the corpus is measured from)
- `results.location_label` (which location a cell was measured from)
- `blocked` value on the resultstatus enum (scrape hit an anti-bot wall)

Postgres stores resultstatus as a native ENUM, so the new value is added with
ALTER TYPE ... ADD VALUE (outside a transaction). SQLite stores enums as plain
strings, so that step is a no-op there.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""

import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_locations_tenant_id", "locations", ["tenant_id"])

    op.add_column(
        "results",
        sa.Column("location_label", sa.String(), nullable=False, server_default=""),
    )
    op.create_index("ix_results_location_label", "results", ["location_label"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # ADD VALUE cannot run inside a transaction; commit first.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE resultstatus ADD VALUE IF NOT EXISTS 'blocked'")


def downgrade() -> None:
    op.drop_index("ix_results_location_label", table_name="results")
    op.drop_column("results", "location_label")
    op.drop_index("ix_locations_tenant_id", table_name="locations")
    op.drop_table("locations")
    # Postgres cannot drop an enum value without recreating the type; the unused
    # 'blocked' label is harmless and left in place.
