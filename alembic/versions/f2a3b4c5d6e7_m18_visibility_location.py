"""m18 visibility_daily location dimension (audit worker-8)

The visibility_daily rollup grouped by (surface, persona_segment) only, so a
multi-location tenant's per-location scores were blended into a single row and
the location dimension was lost. This adds visibility_daily.location_label (""
= the tenant's single default location, and every Mode A result) so the rollup
can emit one row per location.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""

import sqlalchemy as sa
from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "visibility_daily",
        sa.Column("location_label", sa.String(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_visibility_daily_location_label", "visibility_daily", ["location_label"]
    )


def downgrade() -> None:
    op.drop_index("ix_visibility_daily_location_label", table_name="visibility_daily")
    op.drop_column("visibility_daily", "location_label")
