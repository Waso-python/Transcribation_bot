from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    file_path: Mapped[str] = mapped_column(Text)
    normalized_path: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_name: Mapped[str] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(10), default="ru")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    transcript: Mapped["Transcript | None"] = relationship(
        "Transcript",
        uselist=False,
        back_populates="job",
        cascade="all, delete-orphan",
    )
    telegram_users: Mapped[list["TelegramUser"]] = relationship("TelegramUser", back_populates="last_job")


class Transcript(Base):
    __tablename__ = "transcripts"

    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    text: Mapped[str] = mapped_column(Text)
    segments_json: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="ru")
    processing_time_sec: Mapped[float | None] = mapped_column(Float, nullable=True)

    job: Mapped[Job] = relationship("Job", back_populates="transcript")


class TelegramUser(Base):
    __tablename__ = "telegram_users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_trusted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    awaiting_auth_answer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    auth_granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_job: Mapped["Job | None"] = relationship("Job", back_populates="telegram_users")
