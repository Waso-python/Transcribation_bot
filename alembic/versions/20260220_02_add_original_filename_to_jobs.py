"""add original_filename to jobs

Revision ID: 20260220_02
Revises: 20260220_01
Create Date: 2026-02-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260220_02"
down_revision: Union[str, None] = "20260220_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("original_filename", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "original_filename")
