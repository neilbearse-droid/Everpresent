"""m33 Answer shape + first-party data: results.served_model/logged_in,
citations.link_kind, first_party_daily

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "c7d8e9f0a1b2"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None

_STR = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    with op.batch_alter_table("results") as batch:
        batch.add_column(sa.Column("served_model", _STR(), nullable=False, server_default=""))
        batch.add_column(sa.Column("logged_in", sa.Boolean(), nullable=True))
        batch.create_index("ix_results_served_model", ["served_model"])
    with op.batch_alter_table("citations") as batch:
        batch.add_column(sa.Column("link_kind", _STR(), nullable=False, server_default=""))
    op.create_table(
        "first_party_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source", _STR(), nullable=False),
        sa.Column("date", _STR(), nullable=False),
        sa.Column("page", _STR(), nullable=False, server_default=""),
        sa.Column("query", _STR(), nullable=False, server_default=""),
        sa.Column("metric", _STR(), nullable=False, server_default=""),
        sa.Column("value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "source", "date", "page", "query", "metric",
                            name="uq_first_party_cell"),
    )
    op.create_index("ix_first_party_daily_tenant_id", "first_party_daily", ["tenant_id"])
    op.create_index("ix_first_party_daily_source", "first_party_daily", ["source"])
    op.create_index("ix_first_party_daily_date", "first_party_daily", ["date"])


def downgrade() -> None:
    op.drop_index("ix_first_party_daily_date", table_name="first_party_daily")
    op.drop_index("ix_first_party_daily_source", table_name="first_party_daily")
    op.drop_index("ix_first_party_daily_tenant_id", table_name="first_party_daily")
    op.drop_table("first_party_daily")
    with op.batch_alter_table("citations") as batch:
        batch.drop_column("link_kind")
    with op.batch_alter_table("results") as batch:
        batch.drop_index("ix_results_served_model")
        batch.drop_column("logged_in")
        batch.drop_column("served_model")
