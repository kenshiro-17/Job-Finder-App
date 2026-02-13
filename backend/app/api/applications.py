from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application
from app.models.job import Job
from app.models.resume import Resume
from app.models.user import User
from app.models.user_job import UserJob
from app.schemas.application import (
    ApplicationBulkDeleteRequest,
    ApplicationCreate,
    ApplicationOut,
    ApplicationStatsOut,
    ApplicationStatusUpdate,
)


router = APIRouter()


@router.get("", response_model=list[ApplicationOut])
def list_applications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Application]:
    return (
        db.query(Application)
        .filter(Application.user_id == current_user.id)
        .order_by(Application.updated_at.desc())
        .all()
    )


@router.post("", response_model=ApplicationOut)
def create_application(
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Application:
    resume = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    job = (
        db.query(Job)
        .join(UserJob, UserJob.job_id == Job.id)
        .filter(Job.id == payload.job_id, UserJob.user_id == current_user.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    existing = (
        db.query(Application)
        .filter(
            Application.resume_id == payload.resume_id,
            Application.job_id == payload.job_id,
            Application.user_id == current_user.id,
        )
        .first()
    )
    if existing:
        return existing

    application = Application(
        user_id=current_user.id,
        resume_id=payload.resume_id,
        job_id=payload.job_id,
        status=payload.status,
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


@router.get("/stats", response_model=ApplicationStatsOut)
def application_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplicationStatsOut:
    statuses = [row.status for row in db.query(Application.status).filter(Application.user_id == current_user.id).all()]
    counts = Counter(statuses)
    return ApplicationStatsOut(
        to_apply=counts.get("to_apply", 0),
        applied=counts.get("applied", 0),
        interviewing=counts.get("interviewing", 0),
        rejected=counts.get("rejected", 0),
        accepted=counts.get("accepted", 0),
    )


@router.patch("/{app_id}/status", response_model=ApplicationOut)
def update_application_status(
    app_id: int,
    payload: ApplicationStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Application:
    app = db.query(Application).filter(Application.id == app_id, Application.user_id == current_user.id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    app.status = payload.status
    app.notes = payload.notes
    app.applied_date = payload.applied_date
    db.add(app)
    db.commit()
    db.refresh(app)
    return app


@router.post("/bulk-delete")
def bulk_delete_applications(
    payload: ApplicationBulkDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int | str]:
    unique_ids = sorted(set(payload.application_ids))
    if not unique_ids:
        return {"status": "deleted", "deleted_count": 0}

    deleted_count = (
        db.query(Application)
        .filter(Application.user_id == current_user.id, Application.id.in_(unique_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"status": "deleted", "deleted_count": int(deleted_count)}


@router.delete("/clear")
def clear_applications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int | str]:
    deleted_count = db.query(Application).filter(Application.user_id == current_user.id).delete(synchronize_session=False)
    db.commit()
    return {"status": "cleared", "deleted_count": int(deleted_count)}


@router.delete("/{app_id}")
def delete_application(
    app_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str | int]:
    app = db.query(Application).filter(Application.id == app_id, Application.user_id == current_user.id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    db.delete(app)
    db.commit()
    return {"status": "deleted", "application_id": app_id}
