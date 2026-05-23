"""Add persistent signal records.

Revision ID: 20260521_0006
Revises: 20260516_0005
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260521_0006"
down_revision: str | None = "20260516_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signal_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("sender_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_username", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("entry_lower", sa.Float(), nullable=False),
        sa.Column("entry_upper", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("take_profit_levels", sa.Text(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("signal_text", sa.Text(), nullable=False),
        sa.Column("granularity", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("chart_status", sa.String(), nullable=True),
        sa.Column("chart_error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(op.f("ix_signal_records_id"), "signal_records", ["id"], unique=False)
    op.create_index(op.f("ix_signal_records_public_id"), "signal_records", ["public_id"], unique=False)
    op.create_index(
        op.f("ix_signal_records_sender_telegram_id"), "signal_records", ["sender_telegram_id"], unique=False
    )
    op.create_index(op.f("ix_signal_records_status"), "signal_records", ["status"], unique=False)
    op.create_index(op.f("ix_signal_records_symbol"), "signal_records", ["symbol"], unique=False)
    op.create_index(op.f("ix_signal_records_user_id"), "signal_records", ["user_id"], unique=False)

    op.create_table(
        "signal_channel_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_record_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("message_thread_id", sa.Integer(), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=False),
        sa.Column("sent_as", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["signal_record_id"], ["signal_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_signal_channel_messages_chat_id"), "signal_channel_messages", ["chat_id"], unique=False)
    op.create_index(op.f("ix_signal_channel_messages_id"), "signal_channel_messages", ["id"], unique=False)
    op.create_index(
        op.f("ix_signal_channel_messages_signal_record_id"),
        "signal_channel_messages",
        ["signal_record_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_signal_channel_messages_signal_record_id"), table_name="signal_channel_messages")
    op.drop_index(op.f("ix_signal_channel_messages_id"), table_name="signal_channel_messages")
    op.drop_index(op.f("ix_signal_channel_messages_chat_id"), table_name="signal_channel_messages")
    op.drop_table("signal_channel_messages")

    op.drop_index(op.f("ix_signal_records_user_id"), table_name="signal_records")
    op.drop_index(op.f("ix_signal_records_symbol"), table_name="signal_records")
    op.drop_index(op.f("ix_signal_records_status"), table_name="signal_records")
    op.drop_index(op.f("ix_signal_records_sender_telegram_id"), table_name="signal_records")
    op.drop_index(op.f("ix_signal_records_public_id"), table_name="signal_records")
    op.drop_index(op.f("ix_signal_records_id"), table_name="signal_records")
    op.drop_table("signal_records")
