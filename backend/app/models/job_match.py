from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.types import JSON

from app.database import Base


class JobMatch(Base):
    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("resume_id", "job_id", name="uq_resume_job_match"),
        Index("idx_resume_score", "resume_id", "match_score"),
    )

    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    match_score = Column(Float, nullable=False)
    matched_skills = Column(JSON)
    missing_skills = Column(JSON)
    calculated_at = Column(DateTime, server_default=func.now())
