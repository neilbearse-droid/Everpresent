"""m25 fan-out shards + re-probe opt-in (fan-out scorecard, build 2)

Adds the fanout_shards table (per-run fan-out sub-queries with per-shard
presence once re-probed) and tenants.fanout_reprobe_enabled (opt-in to the
bounded re-probe, off by default so existing tenants incur no new spend).
ResultVariant.shard is code-only: results.variant is a plain string column.

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
"""

import sqlalchemy as sa
from alembic import op

revision = "a9b0c1d2e3f4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "fanout_reprobe_enabled", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "fanout_shards",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("parent_query_text", sa.String(), nullable=False),
        sa.Column("shard_text", sa.String(), nullable=False),
        sa.Column("shard_norm", sa.String(), nullable=False),
        sa.Column("issuing_surfaces", sa.JSON(), nullable=True),
        sa.Column("reach", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("brand_present", sa.Boolean(), nullable=True),
        sa.Column("winners", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="unresolved"),
        sa.Column("priority", sa.String(), nullable=False, server_default=""),
        sa.Column("probe_status", sa.String(), nullable=False, server_default=""),
        sa.Column("probe_surface", sa.String(), nullable=False, server_default=""),
        sa.Column("probe_result_id", sa.Integer(), nullable=True),
        sa.Column("probed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "run_id", "parent_query_text", "shard_norm",
            name="uq_fanout_shards_key",
        ),
    )
    op.create_index("ix_fanout_shards_tenant_id", "fanout_shards", ["tenant_id"])
    op.create_index("ix_fanout_shards_run_id", "fanout_shards", ["run_id"])
    op.create_index(
        "ix_fanout_shards_parent_query_text", "fanout_shards", ["parent_query_text"]
    )
    op.create_index("ix_fanout_shards_shard_norm", "fanout_shards", ["shard_norm"])


def downgrade() -> None:
    op.drop_index("ix_fanout_shards_shard_norm", table_name="fanout_shards")
    op.drop_index("ix_fanout_shards_parent_query_text", table_name="fanout_shards")
    op.drop_index("ix_fanout_shards_run_id", table_name="fanout_shards")
    op.drop_index("ix_fanout_shards_tenant_id", table_name="fanout_shards")
    op.drop_table("fanout_shards")
    op.drop_column("tenants", "fanout_reprobe_enabled")
