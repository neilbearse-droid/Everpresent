"""m43 fixes as experiments: interventions gain the recommendation snapshot
and scope, recommendations gain scope, and page_snapshots, page_changes and
fix_outcomes are new

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None

_STR = sqlmodel.sql.sqltypes.AutoString


def _json(name: str, default: str) -> sa.Column:
    return sa.Column(name, sa.JSON(), nullable=False, server_default=sa.text(f"'{default}'"))


def _str(name: str, default: str = "") -> sa.Column:
    return sa.Column(name, _STR(), nullable=False, server_default=default)


def upgrade() -> None:
    with op.batch_alter_table("interventions") as batch:
        batch.add_column(sa.Column("recommendation_id", sa.Integer(), nullable=True))
        batch.add_column(_str("gap_ref"))
        batch.add_column(_str("play"))
        batch.add_column(_str("category"))
        batch.add_column(_str("control"))
        batch.add_column(_str("evidence"))
        batch.add_column(_json("predicted", "{}"))
        batch.add_column(_json("questions", "[]"))
        batch.add_column(_json("families", "[]"))
        batch.add_column(_str("source", "logged"))
        batch.add_column(_str("subject"))
        batch.create_index("ix_interventions_recommendation_id", ["recommendation_id"])
    with op.batch_alter_table("recommendations") as batch:
        batch.add_column(_json("scope", "{}"))

    op.create_table(
        "page_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("url", _STR(), nullable=False),
        _str("owner", "other"),
        _str("owner_name"),
        _str("status", "ok"),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("brand_found", sa.Boolean(), nullable=False, server_default=sa.false()),
        _json("competitors_found", "[]"),
        _json("features", "{}"),
        _str("fingerprint"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_page_snapshots_tenant_id", "page_snapshots", ["tenant_id"])
    op.create_index("ix_page_snapshots_url", "page_snapshots", ["url"])

    op.create_table(
        "page_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("url", _STR(), nullable=False),
        _str("owner", "other"),
        _str("owner_name"),
        _str("kind"),
        _str("summary"),
        _json("detail", "{}"),
        sa.Column("material", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("changed_after", sa.DateTime(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("intervention_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_page_changes_tenant_id", "page_changes", ["tenant_id"])
    op.create_index("ix_page_changes_url", "page_changes", ["url"])
    op.create_index("ix_page_changes_intervention_id", "page_changes", ["intervention_id"])

    op.create_table(
        "fix_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("intervention_id", sa.Integer(), nullable=False),
        _str("status"),
        _str("metric", "mentions"),
        sa.Column("before_rate", sa.Float(), nullable=True),
        sa.Column("after_rate", sa.Float(), nullable=True),
        sa.Column("n_before", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_after", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delta_pts", sa.Float(), nullable=True),
        sa.Column("control_delta_pts", sa.Float(), nullable=True),
        sa.Column("net_pts", sa.Float(), nullable=True),
        _str("verdict"),
        sa.Column("p_value", sa.Float(), nullable=True),
        sa.Column("days_to_effect", sa.Integer(), nullable=True),
        sa.Column("window_days", sa.Integer(), nullable=False, server_default="0"),
        _json("by_engine", "[]"),
        _json("signals", "[]"),
        sa.Column("final", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("measured_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("intervention_id", name="uq_fix_outcome_intervention"),
    )
    op.create_index("ix_fix_outcomes_tenant_id", "fix_outcomes", ["tenant_id"])
    op.create_index("ix_fix_outcomes_intervention_id", "fix_outcomes", ["intervention_id"])


def downgrade() -> None:
    op.drop_table("fix_outcomes")
    op.drop_table("page_changes")
    op.drop_table("page_snapshots")
    with op.batch_alter_table("recommendations") as batch:
        batch.drop_column("scope")
    with op.batch_alter_table("interventions") as batch:
        batch.drop_index("ix_interventions_recommendation_id")
        for name in ("subject", "source", "families", "questions", "predicted", "evidence",
                     "control", "category", "play", "gap_ref", "recommendation_id"):
            batch.drop_column(name)
