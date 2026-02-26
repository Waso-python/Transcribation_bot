from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class JobStatusValue(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class SegmentSchema(BaseModel):
    start: float = Field(..., ge=0)
    end: float = Field(..., ge=0)
    text: str


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatusValue
    created_at: datetime
    eta_seconds: int | None = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatusValue
    progress: int = Field(..., ge=0, le=100)
    duration_sec: float | None = None
    error_code: str | None = None
    error_message: str | None = None


class JobResultResponse(BaseModel):
    job_id: str
    language: str
    model: str
    text: str
    segments: list[SegmentSchema]
    audio_duration_sec: float | None = None
    processing_time_sec: float | None = None
