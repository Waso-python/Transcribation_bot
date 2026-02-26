"""init jobs and transcripts

Revision ID: 20260220_01
Revises:
Create Date: 2026-02-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260220_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("audio_duration_sec", sa.Float(), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "transcripts",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("segments_json", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("processing_time_sec", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )


def downgrade() -> None:
    op.drop_table("transcripts")
    op.drop_table("jobs")
