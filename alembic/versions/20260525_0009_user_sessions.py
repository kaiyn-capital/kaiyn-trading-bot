"""Add persistent user sessions.

Revision ID: 20260525_0009
Revises: 20260523_0008
Create Date: 2026-05-25
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20260525_0009"
down_revision: str | None = "20260523_0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_type", sa.String(length=64), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=True),
        sa.Column("payload_encrypted", sa.Text(), nullable=False),
        sa.Column("payload_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id", name="user_sessions_telegram_id_key"),
    )
    op.create_index(op.f("ix_user_sessions_id"), "user_sessions", ["id"], unique=False)
    op.create_index(op.f("ix_user_sessions_telegram_id"), "user_sessions", ["telegram_id"], unique=False)
    op.create_index(op.f("ix_user_sessions_user_id"), "user_sessions", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_sessions_session_type"), "user_sessions", ["session_type"], unique=False)
    op.create_index(op.f("ix_user_sessions_token"), "user_sessions", ["token"], unique=False)
    op.create_index(op.f("ix_user_sessions_expires_at"), "user_sessions", ["expires_at"], unique=False)
    op.alter_column("user_sessions", "payload_version", server_default=None)
    op.alter_column("user_sessions", "created_at", server_default=None)
    op.alter_column("user_sessions", "updated_at", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_sessions_expires_at"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_token"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_session_type"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_user_id"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_telegram_id"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_id"), table_name="user_sessions")
    op.drop_table("user_sessions")
