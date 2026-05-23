"""Convert order sizing fields to numeric.

Revision ID: 20260522_0007
Revises: 20260521_0006
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260522_0007"
down_revision: str | None = "20260521_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NUMERIC = sa.Numeric(38, 18, asdecimal=True)
FLOAT = sa.Float()


def _alter_columns(table_name: str, columns: list[str], target_type, existing_type, using_type: str) -> None:
    for column in columns:
        op.alter_column(
            table_name,
            column,
            existing_type=existing_type,
            type_=target_type,
            postgresql_using=f"{column}::{using_type}",
        )


def upgrade() -> None:
    _alter_columns("users", ["max_position_size", "fixed_risk_amount"], NUMERIC, FLOAT, "numeric(38,18)")
    _alter_columns(
        "pending_orders",
        [
            "limit_price",
            "entry_lower",
            "entry_upper",
            "quantity",
            "stop_loss",
            "position_value",
            "current_price",
        ],
        NUMERIC,
        FLOAT,
        "numeric(38,18)",
    )
    _alter_columns(
        "trades",
        ["quantity", "price", "filled_quantity", "avg_price", "total_amount", "fee"],
        NUMERIC,
        FLOAT,
        "numeric(38,18)",
    )


def downgrade() -> None:
    _alter_columns(
        "trades",
        ["quantity", "price", "filled_quantity", "avg_price", "total_amount", "fee"],
        FLOAT,
        NUMERIC,
        "double precision",
    )
    _alter_columns(
        "pending_orders",
        [
            "limit_price",
            "entry_lower",
            "entry_upper",
            "quantity",
            "stop_loss",
            "position_value",
            "current_price",
        ],
        FLOAT,
        NUMERIC,
        "double precision",
    )
    _alter_columns("users", ["max_position_size", "fixed_risk_amount"], FLOAT, NUMERIC, "double precision")
