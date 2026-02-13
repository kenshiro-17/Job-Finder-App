from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class ApplicationCreate(BaseModel):
    resume_id: int
    job_id: int
    status: str = "to_apply"


class ApplicationStatusUpdate(BaseModel):
    status: str = Field(min_length=1)
    notes: str | None = None
    applied_date: date | None = None


class ApplicationOut(BaseModel):
    id: int
    resume_id: int
    job_id: int
    status: str
    applied_date: date | None = None
    notes: str | None = None
    cover_letter_path: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ApplicationStatsOut(BaseModel):
    to_apply: int = 0
    applied: int = 0
    interviewing: int = 0
    rejected: int = 0
    accepted: int = 0


class ApplicationBulkDeleteRequest(BaseModel):
    application_ids: list[int] = Field(default_factory=list)
