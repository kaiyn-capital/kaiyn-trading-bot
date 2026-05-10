"""Add pending order mode fields.

Revision ID: 20260510_0002
Revises: 20260509_0001
Create Date: 2026-05-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260510_0002"
down_revision: Union[str, None] = "20260509_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pending_orders",
        sa.Column(
            "order_mode",
            sa.String(),
            nullable=False,
            server_default="market",
        ),
    )
    op.add_column("pending_orders", sa.Column("limit_price", sa.Float(), nullable=True))
    op.add_column("pending_orders", sa.Column("entry_lower", sa.Float(), nullable=True))
    op.add_column("pending_orders", sa.Column("entry_upper", sa.Float(), nullable=True))
    op.alter_column("pending_orders", "order_mode", server_default=None)


def downgrade() -> None:
    op.drop_column("pending_orders", "entry_upper")
    op.drop_column("pending_orders", "entry_lower")
    op.drop_column("pending_orders", "limit_price")
    op.drop_column("pending_orders", "order_mode")
