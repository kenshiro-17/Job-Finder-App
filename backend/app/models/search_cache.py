from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.types import JSON

from app.database import Base


class SearchCache(Base):
    __tablename__ = "search_cache"
    __table_args__ = (
        Index("idx_expires", "expires_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query_hash = Column(String(64), unique=True, nullable=False)
    query_params = Column(JSON)
    job_ids = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)
