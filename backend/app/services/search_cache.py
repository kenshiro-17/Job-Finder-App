from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.search_cache import SearchCache


class SearchCacheService:
    def __init__(self, ttl_minutes: int = 30) -> None:
        self.ttl_minutes = ttl_minutes

    def compute_hash(self, payload: dict[str, Any]) -> str:
        normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()

    def get(self, db: Session, query_hash: str, user_id: int) -> SearchCache | None:
        now = datetime.utcnow()
        return (
            db.query(SearchCache)
            .filter(
                SearchCache.query_hash == query_hash,
                SearchCache.user_id == user_id,
                SearchCache.expires_at > now,
            )
            .first()
        )

    def set(
        self,
        db: Session,
        query_hash: str,
        query_params: dict[str, Any],
        job_ids: list[int],
        user_id: int,
    ) -> SearchCache:
        now = datetime.utcnow()
        expires = now + timedelta(minutes=self.ttl_minutes)

        existing = db.query(SearchCache).filter(SearchCache.query_hash == query_hash, SearchCache.user_id == user_id).first()
        if existing:
            existing.query_params = query_params
            existing.job_ids = job_ids
            existing.expires_at = expires
            db.add(existing)
            db.commit()
            db.refresh(existing)
            return existing

        cache_row = SearchCache(
            user_id=user_id,
            query_hash=query_hash,
            query_params=query_params,
            job_ids=job_ids,
            expires_at=expires,
        )
        db.add(cache_row)
        db.commit()
        db.refresh(cache_row)
        return cache_row
