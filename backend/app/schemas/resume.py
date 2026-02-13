from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ResumeOut(BaseModel):
    id: int
    filename: str
    file_path: str
    upload_date: datetime | None = None
    parsed_skills: list[str] | None = None
    parsed_experience: list[dict] | None = None
    parsed_education: list[dict] | None = None
    keywords: list[str] | None = None
    is_active: bool

    class Config:
        from_attributes = True


class ResumeSetActiveRequest(BaseModel):
    is_active: bool
