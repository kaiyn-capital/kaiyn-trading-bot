"""Use global position cap by default for all users.

Revision ID: 20260523_0008
Revises: 20260522_0007
Create Date: 2026-05-23
"""

from alembic import op

revision: str = "20260523_0008"
down_revision: str | None = "20260522_0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("UPDATE users SET max_position_size = NULL")


def downgrade() -> None:
    # Best-effort semantic downgrade: previous per-user values are intentionally not recoverable.
    op.execute("UPDATE users SET max_position_size = 1000 WHERE max_position_size IS NULL")
