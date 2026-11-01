"""m40 waitlist_signups (landing-page waitlist)

Revision ID: d7e8f9a0b1c2
Revises: c4d5e6f7a8b9
"""

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision = "d7e8f9a0b1c2"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "waitlist_signups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("industry", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "new",
                "contacted",
                "invited",
                "activated",
                "declined",
                name="waitliststatus",
            ),
            nullable=False,
        ),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("utm", sa.JSON(), nullable=True),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("submissions", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_waitlist_signups_email", "waitlist_signups", ["email"], unique=True)
    op.create_index("ix_waitlist_signups_status", "waitlist_signups", ["status"], unique=False)
    op.create_index(
        "ix_waitlist_signups_created_at", "waitlist_signups", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_waitlist_signups_created_at", table_name="waitlist_signups")
    op.drop_index("ix_waitlist_signups_status", table_name="waitlist_signups")
    op.drop_index("ix_waitlist_signups_email", table_name="waitlist_signups")
    op.drop_table("waitlist_signups")
    sa.Enum(name="waitliststatus").drop(op.get_bind(), checkfirst=True)
