"""Add channel topic fields.

Revision ID: 20260512_0004
Revises: 20260510_0003
Create Date: 2026-05-12
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260512_0004"
down_revision: Union[str, None] = "20260510_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("channel_groups", sa.Column("message_thread_id", sa.Integer(), nullable=True))
    op.add_column("channel_groups", sa.Column("thread_title", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("channel_groups", "thread_title")
    op.drop_column("channel_groups", "message_thread_id")
