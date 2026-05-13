"""Initial PostgreSQL schema.

Revision ID: 20260509_0001
Revises:
Create Date: 2026-05-09
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260509_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("first_name", sa.String(), nullable=True),
        sa.Column("last_name", sa.String(), nullable=True),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("encrypted_secret_key", sa.Text(), nullable=True),
        sa.Column("encrypted_passphrase", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("is_api_connected", sa.Boolean(), nullable=True),
        sa.Column("daily_trade_limit", sa.Integer(), nullable=True),
        sa.Column("max_position_size", sa.Float(), nullable=True),
        sa.Column("enable_notifications", sa.Boolean(), nullable=True),
        sa.Column("default_stop_loss_percent", sa.Float(), nullable=True),
        sa.Column("default_trade_amount", sa.Float(), nullable=True),
        sa.Column("auto_stop_loss", sa.Boolean(), nullable=True),
        sa.Column("fixed_risk_amount", sa.Float(), nullable=True),
        sa.Column("is_trader", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=True)

    op.create_table(
        "trading_pairs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("base_currency", sa.String(), nullable=False),
        sa.Column("quote_currency", sa.String(), nullable=False),
        sa.Column("min_order_size", sa.Float(), nullable=False),
        sa.Column("max_order_size", sa.Float(), nullable=False),
        sa.Column("min_price", sa.Float(), nullable=False),
        sa.Column("max_price", sa.Float(), nullable=False),
        sa.Column("price_precision", sa.Integer(), nullable=False),
        sa.Column("quantity_precision", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("is_trading_enabled", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol"),
    )
    op.create_index(op.f("ix_trading_pairs_id"), "trading_pairs", ["id"], unique=False)

    op.create_table(
        "channel_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("chat_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("auto_forward_signals", sa.Boolean(), nullable=True),
        sa.Column("forward_with_buttons", sa.Boolean(), nullable=True),
        sa.Column("added_by_user_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id"),
    )
    op.create_index(op.f("ix_channel_groups_id"), "channel_groups", ["id"], unique=False)

    op.create_table(
        "system_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("module", sa.String(), nullable=False),
        sa.Column("function", sa.String(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("telegram_id", sa.Integer(), nullable=True),
        sa.Column("extra_data", sa.Text(), nullable=True),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_logs_id"), "system_logs", ["id"], unique=False)

    op.create_table(
        "notification_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("message_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_sent", sa.Boolean(), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("extra_data", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notification_logs_id"), "notification_logs", ["id"], unique=False)

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("order_type", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("bitget_order_id", sa.String(), nullable=True),
        sa.Column("client_order_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("filled_quantity", sa.Float(), nullable=True),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("total_amount", sa.Float(), nullable=True),
        sa.Column("fee", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bitget_order_id"),
        sa.UniqueConstraint("client_order_id"),
    )
    op.create_index(op.f("ix_trades_id"), "trades", ["id"], unique=False)

    op.create_table(
        "pending_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("position_value", sa.Float(), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pending_orders_expires_at"), "pending_orders", ["expires_at"], unique=False)
    op.create_index(op.f("ix_pending_orders_id"), "pending_orders", ["id"], unique=False)
    op.create_index(op.f("ix_pending_orders_status"), "pending_orders", ["status"], unique=False)
    op.create_index(op.f("ix_pending_orders_telegram_id"), "pending_orders", ["telegram_id"], unique=False)
    op.create_index(op.f("ix_pending_orders_token"), "pending_orders", ["token"], unique=True)
    op.create_index(op.f("ix_pending_orders_user_id"), "pending_orders", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pending_orders_user_id"), table_name="pending_orders")
    op.drop_index(op.f("ix_pending_orders_token"), table_name="pending_orders")
    op.drop_index(op.f("ix_pending_orders_telegram_id"), table_name="pending_orders")
    op.drop_index(op.f("ix_pending_orders_status"), table_name="pending_orders")
    op.drop_index(op.f("ix_pending_orders_id"), table_name="pending_orders")
    op.drop_index(op.f("ix_pending_orders_expires_at"), table_name="pending_orders")
    op.drop_table("pending_orders")
    op.drop_index(op.f("ix_trades_id"), table_name="trades")
    op.drop_table("trades")
    op.drop_index(op.f("ix_notification_logs_id"), table_name="notification_logs")
    op.drop_table("notification_logs")
    op.drop_index(op.f("ix_system_logs_id"), table_name="system_logs")
    op.drop_table("system_logs")
    op.drop_index(op.f("ix_channel_groups_id"), table_name="channel_groups")
    op.drop_table("channel_groups")
    op.drop_index(op.f("ix_trading_pairs_id"), table_name="trading_pairs")
    op.drop_table("trading_pairs")
    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_table("users")
