"""m32 Hash stored log-push tokens; one recommendation per (tenant, gap_ref)

- tenants.agent_log_token now holds a SHA-256 digest; existing plaintext
  tokens are hashed in place, so tokens already handed out keep working.
- recommendations get a unique (tenant_id, gap_ref); duplicates (possible
  only from overlapping regenerations) are removed first, keeping the oldest.

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
"""

import hashlib

import sqlalchemy as sa

from alembic import op

revision = "b6c7d8e9f0a1"
down_revision = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, agent_log_token FROM tenants WHERE agent_log_token IS NOT NULL")
    ).all()
    for tid, token in rows:
        if token.startswith("eplog_"):  # plaintext; digests are 64 hex chars
            digest = hashlib.sha256(token.encode()).hexdigest()
            conn.execute(
                sa.text("UPDATE tenants SET agent_log_token = :d WHERE id = :i"),
                {"d": digest, "i": tid},
            )

    conn.execute(sa.text(
        "DELETE FROM recommendations WHERE id NOT IN ("
        " SELECT keep_id FROM (SELECT MIN(id) AS keep_id FROM recommendations"
        " GROUP BY tenant_id, gap_ref) AS keepers)"
    ))
    with op.batch_alter_table("recommendations") as batch:
        batch.create_unique_constraint("uq_recommendation_gap", ["tenant_id", "gap_ref"])


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch:
        batch.drop_constraint("uq_recommendation_gap", type_="unique")
    # Hashed tokens can't be un-hashed: clear them; admins re-issue.
    op.execute("UPDATE tenants SET agent_log_token = NULL")
