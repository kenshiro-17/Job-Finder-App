from __future__ import annotations

from sqlalchemy import Column, Date, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.types import JSON

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "external_job_id", name="uq_source_external_job"),
        Index("idx_source_external", "source", "external_job_id"),
        Index("idx_posted_date", "posted_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    external_job_id = Column(String(255), nullable=False)
    source = Column(String(50), nullable=False)
    title = Column(String(500), nullable=False)
    company = Column(String(255))
    location = Column(String(255))
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    job_type = Column(String(50))
    remote_type = Column(String(50))
    experience_level = Column(String(50))
    description = Column(Text)
    requirements = Column(Text)
    url = Column(String(1000), nullable=False)
    posted_date = Column(Date)
    scraped_at = Column(DateTime, server_default=func.now())
    keywords = Column(JSON)
    match_score = Column(Float)
