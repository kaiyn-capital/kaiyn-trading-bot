"""Add retention cleanup indexes.

Revision ID: 20260510_0003
Revises: 20260510_0002
Create Date: 2026-05-10
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260510_0003"
down_revision: Union[str, None] = "20260510_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_pending_orders_created_at", "pending_orders", ["created_at"], unique=False
    )
    op.create_index("ix_trades_created_at", "trades", ["created_at"], unique=False)
    op.create_index(
        "ix_notification_logs_created_at",
        "notification_logs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_system_logs_created_at", "system_logs", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_system_logs_created_at", table_name="system_logs")
    op.drop_index("ix_notification_logs_created_at", table_name="notification_logs")
    op.drop_index("ix_trades_created_at", table_name="trades")
    op.drop_index("ix_pending_orders_created_at", table_name="pending_orders")
