from __future__ import annotations

from datetime import date, datetime, timedelta

from app.api.jobs import _apply_advanced_filters, _passes_date_posted_filter
from app.models.job import Job
from app.schemas.job import SearchFilter

_UNSET = object()


def _job(
    *,
    job_id: int,
    title: str,
    location: str,
    remote_type: str = "onsite",
    experience_level: str = "mid",
    posted_date: date | None = None,
    scraped_at: datetime | None | object = _UNSET,
    match_score: float | None = None,
) -> Job:
    resolved_scraped_at = datetime.utcnow() if scraped_at is _UNSET else scraped_at
    return Job(
        id=job_id,
        external_job_id=f"ext-{job_id}",
        source="linkedin",
        title=title,
        company="Example GmbH",
        location=location,
        description=title,
        requirements=title,
        remote_type=remote_type,
        experience_level=experience_level,
        posted_date=posted_date,
        scraped_at=resolved_scraped_at,
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        keywords=[],
        match_score=match_score,
    )


def test_advanced_filters_location_mode_experience_and_date():
    jobs = [
        _job(
            job_id=1,
            title="Senior Data Engineer",
            location="Berlin, Germany",
            remote_type="remote",
            experience_level="senior",
            posted_date=date.today() - timedelta(days=2),
        ),
        _job(
            job_id=2,
            title="Junior Backend Engineer",
            location="Munich, Germany",
            remote_type="onsite",
            experience_level="junior",
            posted_date=date.today() - timedelta(days=10),
        ),
    ]
    filters = SearchFilter(
        location_contains="berlin",
        remote=["remote"],
        experience_level=["senior"],
        date_posted="last_7_days",
    )
    result = _apply_advanced_filters(jobs, filters, {})
    assert [job.id for job in result] == [1]


def test_advanced_filters_match_percentage_and_relevancy():
    jobs = [
        _job(job_id=1, title="Lead Data Engineer", location="Berlin"),
        _job(job_id=2, title="Backend Engineer", location="Berlin"),
        _job(job_id=3, title="Frontend Engineer", location="Berlin"),
    ]
    scores = {
        "1": {"score": 0.82},
        "2": {"score": 0.57},
        "3": {"score": 0.41},
    }
    filters = SearchFilter(
        match_percentage_min=50,
        match_percentage_max=90,
        relevancy=["strong", "good"],
    )
    result = _apply_advanced_filters(jobs, filters, scores)
    assert [job.id for job in result] == [1, 2]


def test_match_filter_uses_persisted_job_score_when_runtime_score_missing():
    jobs = [
        _job(job_id=1, title="Data Engineer", location="Berlin", match_score=0.76),
        _job(job_id=2, title="Data Analyst", location="Berlin", match_score=None),
    ]
    filters = SearchFilter(match_percentage_min=70)
    result = _apply_advanced_filters(jobs, filters, {})
    assert [job.id for job in result] == [1]


def test_hourly_date_filters_use_scraped_at_time_window():
    now = datetime.utcnow()
    fresh = _job(
        job_id=1,
        title="Data Engineer",
        location="Berlin",
        scraped_at=now - timedelta(minutes=35),
    )
    older = _job(
        job_id=2,
        title="Data Engineer",
        location="Berlin",
        scraped_at=now - timedelta(hours=5),
    )

    assert _passes_date_posted_filter(fresh, "last_1h")
    assert not _passes_date_posted_filter(older, "last_1h")
    assert not _passes_date_posted_filter(older, "last_4h")
    assert _passes_date_posted_filter(older, "last_8h")


def test_hourly_date_filters_fallback_to_today_when_only_posted_date_exists():
    todays_job = _job(
        job_id=1,
        title="Backend Engineer",
        location="Berlin",
        posted_date=date.today(),
        scraped_at=None,
    )
    yesterday_job = _job(
        job_id=2,
        title="Backend Engineer",
        location="Berlin",
        posted_date=date.today() - timedelta(days=1),
        scraped_at=None,
    )

    assert _passes_date_posted_filter(todays_job, "last_1h")
    assert not _passes_date_posted_filter(yesterday_job, "last_8h")
