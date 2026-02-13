from __future__ import annotations

import re
from datetime import date, datetime, timedelta
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
from app.schemas.job import JobOut, JobSearchRequest, JobSearchResponse, SearchFilter, StoredJobsResponse
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


def _normalize_experience_level(value: str) -> str:
    token = value.lower().strip()
    if any(part in token for part in ("intern", "internship", "praktikum", "graduate", "entry level", "entry-level", "trainee")):
        return "entry"
    if any(part in token for part in ("junior", " jr", "jr ")):
        return "junior"
    if any(part in token for part in ("lead", "principal", "head of", "staff")):
        return "lead"
    if "senior" in token or " sr" in token or "sr " in token:
        return "senior"
    if any(part in token for part in ("mid", "intermediate", "experienced", "professional")):
        return "mid"
    return ""


def _infer_experience_level(job: Job) -> str:
    existing = _normalize_experience_level(str(getattr(job, "experience_level", "") or ""))
    if existing:
        return existing
    haystack = " ".join(
        str(value or "")
        for value in (job.title, job.description, job.requirements)
    )
    inferred = _normalize_experience_level(haystack)
    return inferred or "mid"


def _normalize_work_mode(value: str) -> str:
    token = value.lower().replace("_", " ").replace("-", " ").strip()
    if "hybrid" in token:
        return "hybrid"
    if any(part in token for part in ("remote", "home office", "work from home", "wfh", "distributed")):
        return "remote"
    if any(part in token for part in ("on site", "onsite", "office", "vor ort")):
        return "onsite"
    return ""


def _infer_work_mode(job: Job) -> str:
    existing = _normalize_work_mode(str(job.remote_type or ""))
    if existing:
        return existing
    haystack = " ".join(
        str(value or "")
        for value in (job.title, job.location, job.description, job.requirements)
    )
    inferred = _normalize_work_mode(haystack)
    return inferred or "onsite"


def _job_reference_date(job: Job) -> date | None:
    if job.posted_date:
        return job.posted_date
    if job.scraped_at:
        return job.scraped_at.date()
    return None


def _passes_date_posted_filter(job: Job, date_posted_filter: str | None) -> bool:
    value = (date_posted_filter or "").strip().lower()
    if not value:
        return True
    now = datetime.utcnow()
    hour_windows = {
        "last_1h": 1,
        "last_4h": 4,
        "last_8h": 8,
    }
    hours = hour_windows.get(value)
    if hours is not None:
        if job.scraped_at:
            return job.scraped_at >= (now - timedelta(hours=hours))
        if job.posted_date:
            return job.posted_date >= now.date()
        return True
    windows = {
        "last_24h": 1,
        "last_3_days": 3,
        "last_7_days": 7,
        "last_14_days": 14,
        "last_21_days": 21,
        "last_30_days": 30,
    }
    days = windows.get(value)
    if not days:
        return True
    ref_date = _job_reference_date(job)
    if not ref_date:
        return True
    return ref_date >= (now.date() - timedelta(days=days))


def _extract_score(job: Job, match_scores: dict[str, dict]) -> float | None:
    row = match_scores.get(str(job.id))
    if row and isinstance(row.get("score"), (int, float)):
        return float(row["score"])
    if isinstance(job.match_score, (int, float)):
        return float(job.match_score)
    return None


def _relevancy_bucket(score: float) -> str:
    if score >= 0.7:
        return "strong"
    if score >= 0.5:
        return "good"
    return "possible"


def _apply_advanced_filters(
    jobs: list[Job],
    filters: SearchFilter,
    match_scores: dict[str, dict],
) -> list[Job]:
    if not jobs:
        return []

    work_modes = {
        _normalize_work_mode(str(mode))
        for mode in ((filters.remote or []) + (getattr(filters, "work_mode", None) or []))
    }
    work_modes = {mode for mode in work_modes if mode}
    experience_levels = {_normalize_experience_level(str(level)) for level in (filters.experience_level or [])}
    experience_levels = {level for level in experience_levels if level}
    relevancy_levels = {str(level).strip().lower() for level in (filters.relevancy or []) if str(level).strip()}

    min_pct = filters.match_percentage_min
    max_pct = filters.match_percentage_max
    if min_pct is not None and max_pct is not None and min_pct > max_pct:
        min_pct, max_pct = max_pct, min_pct

    location_contains = (filters.location_contains or "").strip().lower()
    salary_min = filters.salary_min

    filtered: list[Job] = []
    for job in jobs:
        if salary_min and job.salary_min and job.salary_min < salary_min:
            continue
        if location_contains and location_contains not in str(job.location or "").lower():
            continue
        if work_modes and _infer_work_mode(job) not in work_modes:
            continue
        if experience_levels and _infer_experience_level(job) not in experience_levels:
            continue
        if not _passes_date_posted_filter(job, filters.date_posted):
            continue

        score = _extract_score(job, match_scores)
        if min_pct is not None or max_pct is not None or relevancy_levels:
            if score is None:
                continue
            pct = score * 100
            if min_pct is not None and pct < min_pct:
                continue
            if max_pct is not None and pct > max_pct:
                continue
            if relevancy_levels and _relevancy_bucket(score) not in relevancy_levels:
                continue
        filtered.append(job)

    return filtered


def _csv_values(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


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

    jobs = _apply_advanced_filters(jobs, payload.filters, match_scores)
    if match_scores:
        allowed_ids = {str(job.id) for job in jobs}
        match_scores = {job_id: details for job_id, details in match_scores.items() if job_id in allowed_ids}

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
    location_contains: str | None = Query(default=None),
    date_posted: str | None = Query(default=None),
    experience_level: str | None = Query(default=None),
    work_mode: str | None = Query(default=None),
    match_percentage_min: int | None = Query(default=None, ge=0, le=100),
    match_percentage_max: int | None = Query(default=None, ge=0, le=100),
    relevancy: str | None = Query(default=None),
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
    if location_contains:
        query = query.filter(Job.location.ilike(f"%{location_contains.strip()}%"))

    ordered_jobs = (
        query.order_by(UserJob.last_seen_at.desc(), UserJob.sort_rank.asc(), Job.id.desc())
        .all()
    )
    work_modes = {_normalize_work_mode(part) for part in _csv_values(work_mode)}
    work_modes = {mode for mode in work_modes if mode}
    experience_levels = {_normalize_experience_level(part) for part in _csv_values(experience_level)}
    experience_levels = {level for level in experience_levels if level}
    relevancy_levels = {part.lower() for part in _csv_values(relevancy)}

    min_pct = match_percentage_min
    max_pct = match_percentage_max
    if min_pct is not None and max_pct is not None and min_pct > max_pct:
        min_pct, max_pct = max_pct, min_pct

    filtered_jobs: list[Job] = []
    for job in ordered_jobs:
        if work_modes and _infer_work_mode(job) not in work_modes:
            continue
        if experience_levels and _infer_experience_level(job) not in experience_levels:
            continue
        if not _passes_date_posted_filter(job, date_posted):
            continue
        score = job.match_score if isinstance(job.match_score, (int, float)) else None
        if min_pct is not None or max_pct is not None or relevancy_levels:
            if score is None:
                continue
            pct = float(score) * 100
            if min_pct is not None and pct < min_pct:
                continue
            if max_pct is not None and pct > max_pct:
                continue
            if relevancy_levels and _relevancy_bucket(float(score)) not in relevancy_levels:
                continue
        filtered_jobs.append(job)

    total = len(filtered_jobs)
    jobs = filtered_jobs[offset: offset + limit]
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
