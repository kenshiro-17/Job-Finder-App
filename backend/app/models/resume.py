from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.types import JSON

from app.database import Base


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    upload_date = Column(DateTime, server_default=func.now())
    raw_text = Column(Text)
    parsed_skills = Column(JSON)
    parsed_experience = Column(JSON)
    parsed_education = Column(JSON)
    keywords = Column(JSON)
    is_active = Column(Boolean, default=True, nullable=False)
