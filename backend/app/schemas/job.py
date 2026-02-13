from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class SearchFilter(BaseModel):
    job_type: list[str] | None = None
    remote: list[str] | None = None
    work_mode: list[str] | None = None
    salary_min: int | None = None
    experience_level: list[str] | None = None
    date_posted: str | None = None
    location_contains: str | None = None
    match_percentage_min: int | None = Field(default=None, ge=0, le=100)
    match_percentage_max: int | None = Field(default=None, ge=0, le=100)
    relevancy: list[str] | None = None


class JobSearchRequest(BaseModel):
    keywords: str = Field(min_length=1)
    location: str = Field(min_length=1)
    resume_id: int | None = None
    filters: SearchFilter = SearchFilter()
    sources: list[str] = ["indeed", "stepstone", "linkedin", "arbeitnow", "berlinstartupjobs"]


class JobOut(BaseModel):
    id: int
    external_job_id: str
    source: str
    title: str
    company: str | None = None
    location: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    job_type: str | None = None
    remote_type: str | None = None
    experience_level: str | None = None
    description: str | None = None
    requirements: str | None = None
    url: str
    posted_date: date | None = None
    scraped_at: datetime | None = None
    keywords: list[str] | None = None

    class Config:
        from_attributes = True


class JobSearchResponse(BaseModel):
    jobs: list[JobOut]
    match_scores: dict[str, dict] = {}
    search_id: str
    cached: bool


class StoredJobsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    jobs: list[JobOut]
