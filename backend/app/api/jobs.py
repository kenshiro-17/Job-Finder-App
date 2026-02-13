from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs, quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.job import Job
from app.models.job_match import JobMatch
from app.models.application import Application
from app.models.resume import Resume
from app.models.search_cache import SearchCache
from app.models.user import User
from app.models.user_job import UserJob
from app.schemas.job import JobOut, JobSearchRequest, JobSearchResponse, StoredJobsResponse
from app.services.job_scraper import JobScraper
from app.services.matcher import JobMatcher
from app.services.search_cache import SearchCacheService


router = APIRouter()
scraper = JobScraper()
matcher = JobMatcher()
cache_service = SearchCacheService(ttl_minutes=30)


def _canonical_job_url(
    source: str,
    url: str | None,
    external_job_id: str | None,
    title: str | None,
    location: str | None,
) -> str:
    raw_url = (url or "").strip()
    external = (external_job_id or "").strip()

    if source == "indeed":
        parsed = urlparse(raw_url) if raw_url else None
        host = (parsed.netloc or "").lower() if parsed else ""
        path = (parsed.path or "").lower() if parsed else ""
        query = parse_qs(parsed.query) if parsed else {}
        if "indeed." in host and (
            "/viewjob" in path
            or "/rc/clk" in path
            or "/pagead/clk" in path
            or "/company/" in path
            or bool(query.get("jk"))
            or bool(query.get("vjk"))
        ):
            return raw_url
        if external and re.fullmatch(r"[A-Za-z0-9_-]{8,}", external):
            return f"https://de.indeed.com/viewjob?jk={quote(external, safe='')}"
        return raw_url

    if source == "stepstone":
        parsed = urlparse(raw_url) if raw_url else None
        host = (parsed.netloc or "").lower() if parsed else ""
        path = (parsed.path or "").lower() if parsed else ""
        if "stepstone.de" in host and ("/job/" in path or "/stellenangebote" in path):
            return raw_url
        if external.isdigit():
            return f"https://www.stepstone.de/job/{external}"
        if external.startswith("stellenangebote"):
            return f"https://www.stepstone.de/{external}"
        return raw_url

    if source == "linkedin":
        if raw_url:
            linked_id = _extract_linkedin_job_id(raw_url)
            if linked_id:
                return f"https://www.linkedin.com/jobs/view/{linked_id}/"
            if "linkedin.com/jobs/view/" in raw_url:
                return raw_url
        if external.isdigit():
            return f"https://www.linkedin.com/jobs/view/{external}/"
        return raw_url

    if source == "berlinstartupjobs":
        if raw_url.startswith("http://") or raw_url.startswith("https://"):
            return raw_url
        if external:
            return f"https://berlinstartupjobs.com/jobs/{quote(external, safe='')}/"
        return raw_url

    if source == "arbeitnow":
        return raw_url

    return raw_url


def _has_valid_posting_url(job: Job) -> bool:
    url = (job.url or "").strip().lower()
    if not url.startswith("http://") and not url.startswith("https://"):
        return False
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    query = parse_qs(parsed.query)
    if job.source == "stepstone":
        return "stepstone.de" in host and ("/job/" in path or "/stellenangebote" in path)
    if job.source == "indeed":
        return "indeed." in host and (
            "/viewjob" in path
            or "/rc/clk" in path
            or "/pagead/clk" in path
            or "/company/" in path
            or bool(query.get("jk"))
            or bool(query.get("vjk"))
        )
    if job.source == "linkedin":
        return "linkedin.com" in host and "/jobs/view/" in path
    if job.source == "berlinstartupjobs":
        return "berlinstartupjobs.com" in host and path not in ("", "/")
    if job.source == "arbeitnow":
        return True
    return True


def _extract_linkedin_job_id(value: str) -> str:
    if not value:
        return ""
    direct = re.search(r"/jobs/view/(\d+)", value)
    if direct:
        return direct.group(1)
    slug = re.search(r"/jobs/view/[^/?#]*-(\d+)", value)
    if slug:
        return slug.group(1)
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    for key in ("currentJobId", "jobId", "trkJobId"):
        vals = query.get(key)
        if vals and vals[0].isdigit():
            return vals[0]
    return ""


def _upsert_job(db: Session, payload: dict) -> Job:
    payload["url"] = _canonical_job_url(
        source=payload.get("source", ""),
        url=payload.get("url"),
        external_job_id=payload.get("external_job_id"),
        title=payload.get("title"),
        location=payload.get("location"),
    )

    existing = (
        db.query(Job)
        .filter(Job.source == payload["source"], Job.external_job_id == payload["external_job_id"])
        .first()
    )
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.scraped_at = datetime.utcnow()
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    new_job = Job(**payload)
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return new_job


def _link_jobs_to_user(db: Session, user_id: int, job_ids: list[int]) -> None:
    unique = _unique_ids(job_ids)
    if not unique:
        return
    now = datetime.utcnow()
    existing_rows = db.query(UserJob).filter(UserJob.user_id == user_id, UserJob.job_id.in_(unique)).all()
    existing_by_job = {row.job_id: row for row in existing_rows}
    for rank, job_id in enumerate(unique):
        row = existing_by_job.get(job_id)
        if row:
            row.sort_rank = rank
            row.last_seen_at = now
            db.add(row)
        else:
            db.add(UserJob(user_id=user_id, job_id=job_id, sort_rank=rank, last_seen_at=now))
    db.commit()
    _prune_user_jobs_limit(db, user_id)


def _unique_ids(values: list[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _user_scoped_job_query(db: Session, user_id: int):
    return db.query(Job).join(UserJob, UserJob.job_id == Job.id).filter(UserJob.user_id == user_id)


def _cutoff_date():
    return (datetime.utcnow() - timedelta(days=settings.max_job_age_days)).date()


def _cutoff_datetime():
    return datetime.utcnow() - timedelta(days=settings.max_job_age_days)


def _newest_window_datetime():
    return datetime.utcnow() - timedelta(minutes=settings.newest_window_minutes)


def _is_recent_job(job: Job) -> bool:
    cutoff_day = _cutoff_date()
    cutoff_dt = _cutoff_datetime()
    if job.posted_date:
        return job.posted_date >= cutoff_day
    if job.scraped_at:
        return job.scraped_at >= cutoff_dt
    return True


def _recent_jobs_filter_expression():
    cutoff_day = _cutoff_date()
    cutoff_dt = _cutoff_datetime()
    return or_(
        Job.posted_date >= cutoff_day,
        and_(Job.posted_date.is_(None), Job.scraped_at >= cutoff_dt),
    )


def _is_newest_window(job: Job) -> bool:
    if not job.scraped_at:
        return False
    return job.scraped_at >= _newest_window_datetime()


def _recent_sort_key(job: Job) -> tuple:
    posted_rank = job.posted_date.toordinal() if job.posted_date else 0
    scraped_rank = job.scraped_at.timestamp() if job.scraped_at else 0.0
    return (1 if _is_newest_window(job) else 0, posted_rank, scraped_rank, job.id or 0)


def _cleanup_orphan_jobs(db: Session, candidate_job_ids: list[int] | None = None) -> int:
    query = db.query(Job.id).filter(~exists().where(UserJob.job_id == Job.id)).filter(~exists().where(Application.job_id == Job.id))
    if candidate_job_ids:
        query = query.filter(Job.id.in_(candidate_job_ids))
    orphan_ids = [job_id for (job_id,) in query.all()]
    if orphan_ids:
        db.query(Job).filter(Job.id.in_(orphan_ids)).delete(synchronize_session=False)
        db.commit()
    return len(orphan_ids)


def _prune_user_jobs_limit(db: Session, user_id: int) -> None:
    limit = max(10000, settings.max_stored_jobs_per_user)
    over_limit_ids = [
        row_id
        for (row_id,) in (
            db.query(UserJob.id)
            .filter(UserJob.user_id == user_id)
            .order_by(UserJob.last_seen_at.desc(), UserJob.sort_rank.asc(), UserJob.id.desc())
            .offset(limit)
            .all()
        )
    ]
    if not over_limit_ids:
        return
    dropped_job_ids = [
        job_id
        for (job_id,) in db.query(UserJob.job_id).filter(UserJob.id.in_(over_limit_ids)).all()
    ]
    db.query(UserJob).filter(UserJob.id.in_(over_limit_ids)).delete(synchronize_session=False)
    db.commit()
    if dropped_job_ids:
        _cleanup_orphan_jobs(db, dropped_job_ids)


def _recent_fallback_jobs(
    db: Session,
    user_id: int,
    keywords: str,
    location: str,
    sources: list[str] | None = None,
    limit: int = 20,
) -> list[Job]:
    tokens = [token.strip().lower() for token in keywords.split() if token.strip()]
    city = location.split(",")[0].strip()

    query = _user_scoped_job_query(db, user_id).filter(_recent_jobs_filter_expression())
    if sources:
        normalized_sources = [source.strip().lower() for source in sources if source and source.strip()]
        if normalized_sources:
            query = query.filter(Job.source.in_(normalized_sources))
    if city:
        query = query.filter(Job.location.ilike(f"%{city}%"))
    candidates = [
        job
        for job in query.order_by(UserJob.last_seen_at.desc(), UserJob.sort_rank.asc(), Job.id.desc()).limit(400).all()
        if _has_valid_posting_url(job) and _is_recent_job(job)
    ]

    if not tokens:
        return candidates[:limit]

    scored: list[tuple[int, Job]] = []
    for job in candidates:
        haystack = f"{job.title or ''} {job.description or ''} {job.requirements or ''}".lower()
        score = sum(1 for token in tokens if token in haystack)
        if score > 0:
            scored.append((score, job))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [job for _, job in scored[:limit]]


def _resume_to_dict(resume: Resume) -> dict:
    return {
        "raw_text": resume.raw_text or "",
        "skills": resume.parsed_skills or [],
        "experience": resume.parsed_experience or [],
        "keywords": resume.keywords or [],
    }


@router.post("/search", response_model=JobSearchResponse)
async def search_jobs(
    payload: JobSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobSearchResponse:
    requested_sources = {source.strip().lower() for source in payload.sources if source and source.strip()}
    search_payload = {
        "keywords": payload.keywords,
        "location": payload.location,
        "filters": payload.filters.model_dump(),
        "sources": sorted(requested_sources),
        "user_id": current_user.id,
    }
    query_hash = cache_service.compute_hash(search_payload)

    cached_row = cache_service.get(db, query_hash, current_user.id)
    jobs: list[Job] = []
    cached = False

    if cached_row and cached_row.job_ids:
        ordered_ids = _unique_ids(cached_row.job_ids)
        job_map = {job.id: job for job in _user_scoped_job_query(db, current_user.id).filter(Job.id.in_(ordered_ids)).all()}
        jobs = [
            job_map[job_id]
            for job_id in ordered_ids
            if job_id in job_map
            and _has_valid_posting_url(job_map[job_id])
            and _is_recent_job(job_map[job_id])
            and (not requested_sources or job_map[job_id].source in requested_sources)
        ]
        cached = True

    if not jobs:
        scraped = await scraper.search(payload.keywords, payload.location, payload.filters.model_dump(), sorted(requested_sources))
        for item in scraped:
            jobs.append(_upsert_job(db, item))
        jobs = [job for job in jobs if _has_valid_posting_url(job) and _is_recent_job(job)]
        if requested_sources:
            jobs = [job for job in jobs if job.source in requested_sources]
        if not jobs:
            jobs = _recent_fallback_jobs(
                db,
                user_id=current_user.id,
                keywords=payload.keywords,
                location=payload.location,
                sources=list(requested_sources),
                limit=50,
            )
        cached = False

    match_scores: dict[str, dict] = {}
    if payload.resume_id:
        resume = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
        if not resume:
            raise HTTPException(status_code=404, detail="Resume not found")

        resume_dict = _resume_to_dict(resume)
        for job in jobs:
            score = matcher.calculate_match_score(
                resume_dict,
                {
                    "title": job.title,
                    "description": job.description or "",
                    "requirements": job.requirements or "",
                    "keywords": job.keywords or [],
                    "location": job.location or "",
                },
            )
            match_scores[str(job.id)] = score
            match_row = (
                db.query(JobMatch)
                .filter(JobMatch.resume_id == resume.id, JobMatch.job_id == job.id)
                .first()
            )
            if match_row:
                match_row.match_score = score["score"]
                match_row.matched_skills = score["matched_skills"]
                match_row.missing_skills = score["missing_skills"]
                db.add(match_row)
            else:
                db.add(
                    JobMatch(
                        resume_id=resume.id,
                        job_id=job.id,
                        match_score=score["score"],
                        matched_skills=score["matched_skills"],
                        missing_skills=score["missing_skills"],
                    )
                )

            job.match_score = score["score"]
            db.add(job)

        db.commit()

    sorted_jobs = sorted(jobs, key=_recent_sort_key, reverse=True)
    changed = False
    for job in sorted_jobs:
        canonical = _canonical_job_url(
            source=job.source,
            url=job.url,
            external_job_id=job.external_job_id,
            title=job.title,
            location=job.location,
        )
        if canonical and canonical != job.url:
            job.url = canonical
            db.add(job)
            changed = True
    if changed:
        db.commit()

    _link_jobs_to_user(db, current_user.id, [job.id for job in sorted_jobs])
    cache_service.set(db, query_hash, search_payload, _unique_ids([job.id for job in sorted_jobs]), current_user.id)

    return JobSearchResponse(
        jobs=[JobOut.model_validate(j) for j in sorted_jobs],
        match_scores=match_scores,
        search_id=query_hash,
        cached=cached,
    )


@router.get("", response_model=StoredJobsResponse)
def list_jobs(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(default=None),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StoredJobsResponse:
    query = _user_scoped_job_query(db, current_user.id).filter(_recent_jobs_filter_expression())
    if source:
        query = query.filter(Job.source == source.strip().lower())
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Job.title.ilike(term),
                Job.company.ilike(term),
                Job.location.ilike(term),
                Job.description.ilike(term),
                Job.requirements.ilike(term),
            )
        )

    total = query.count()
    jobs = (
        query.order_by(UserJob.last_seen_at.desc(), UserJob.sort_rank.asc(), Job.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    changed = False
    for job in jobs:
        canonical = _canonical_job_url(
            source=job.source,
            url=job.url,
            external_job_id=job.external_job_id,
            title=job.title,
            location=job.location,
        )
        if canonical and canonical != job.url:
            job.url = canonical
            db.add(job)
            changed = True
    if changed:
        db.commit()

    return StoredJobsResponse(total=total, limit=limit, offset=offset, jobs=[JobOut.model_validate(j) for j in jobs])


@router.delete("/clear")
def clear_stored_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int | str]:
    job_ids = [job_id for (job_id,) in db.query(UserJob.job_id).filter(UserJob.user_id == current_user.id).all()]

    deleted_links = db.query(UserJob).filter(UserJob.user_id == current_user.id).delete(synchronize_session=False)
    db.query(SearchCache).filter(SearchCache.user_id == current_user.id).delete(synchronize_session=False)
    if job_ids:
        resume_ids = [rid for (rid,) in db.query(Resume.id).filter(Resume.user_id == current_user.id).all()]
        if resume_ids:
            db.query(JobMatch).filter(
                JobMatch.job_id.in_(job_ids),
                JobMatch.resume_id.in_(resume_ids),
            ).delete(synchronize_session=False)
    db.commit()

    orphan_count = _cleanup_orphan_jobs(db, job_ids)

    return {"status": "cleared", "removed_user_job_links": int(deleted_links), "removed_orphan_jobs": orphan_count}


@router.get("/search-history")
def search_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    rows = (
        db.query(SearchCache)
        .filter(SearchCache.user_id == current_user.id)
        .order_by(SearchCache.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "query_hash": row.query_hash,
            "query_params": row.query_params,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
        }
        for row in rows
    ]


@router.delete("/{job_id}")
def delete_stored_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int | str]:
    link = db.query(UserJob).filter(UserJob.user_id == current_user.id, UserJob.job_id == job_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Job not found")

    db.delete(link)
    resume_ids = [rid for (rid,) in db.query(Resume.id).filter(Resume.user_id == current_user.id).all()]
    if resume_ids:
        db.query(JobMatch).filter(
            JobMatch.job_id == job_id,
            JobMatch.resume_id.in_(resume_ids),
        ).delete(synchronize_session=False)
    db.commit()

    orphan_count = _cleanup_orphan_jobs(db, [job_id])
    _prune_user_jobs_limit(db, current_user.id)
    return {"status": "deleted", "job_id": job_id, "removed_orphan_jobs": orphan_count}


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobOut:
    job = (
        _user_scoped_job_query(db, current_user.id)
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not _is_recent_job(job):
        raise HTTPException(status_code=404, detail="Job not found")
    canonical = _canonical_job_url(
        source=job.source,
        url=job.url,
        external_job_id=job.external_job_id,
        title=job.title,
        location=job.location,
    )
    if canonical and canonical != job.url:
        job.url = canonical
        db.add(job)
        db.commit()
        db.refresh(job)
    return JobOut.model_validate(job)
