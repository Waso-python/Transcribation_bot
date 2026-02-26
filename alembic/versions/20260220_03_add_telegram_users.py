"""add telegram users table

Revision ID: 20260220_03
Revises: 20260220_02
Create Date: 2026-02-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260220_03"
down_revision: Union[str, None] = "20260220_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_users",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("is_trusted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("awaiting_auth_answer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_job_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("auth_granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["last_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_telegram_users_is_trusted", "telegram_users", ["is_trusted"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_telegram_users_is_trusted", table_name="telegram_users")
    op.drop_table("telegram_users")

