from __future__ import annotations

from pydantic import BaseModel


class CoverLetterGenerateRequest(BaseModel):
    resume_id: int
    job_id: int
    tone: str = "professional"
    custom_intro: str = ""


class CoverLetterResponse(BaseModel):
    cover_letter: str
    file_path: str
