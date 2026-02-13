from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.application import Application
from app.models.job import Job
from app.models.job_match import JobMatch
from app.models.resume import Resume
from app.models.user import User
from app.models.user_job import UserJob
from app.schemas.cover_letter import CoverLetterGenerateRequest, CoverLetterResponse
from app.services.cover_letter_generator import CoverLetterGenerator


router = APIRouter()
generator = CoverLetterGenerator()


@router.post("/generate", response_model=CoverLetterResponse)
def generate_cover_letter(
    payload: CoverLetterGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CoverLetterResponse:
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

    match = (
        db.query(JobMatch)
        .filter(JobMatch.resume_id == resume.id, JobMatch.job_id == job.id)
        .first()
    )

    resume_data = {
        "raw_text": resume.raw_text or "",
        "skills": resume.parsed_skills or [],
        "experience": resume.parsed_experience or [],
        "matched_skills": (match.matched_skills if match else []),
        "missing_skills": (match.missing_skills if match else []),
    }
    job_data = {
        "title": job.title,
        "company": job.company,
        "description": job.description,
        "requirements": job.requirements,
    }

    letter = generator.generate(
        resume_data=resume_data,
        job_data=job_data,
        tone=payload.tone,
        custom_intro=payload.custom_intro,
    )

    filename = f"cover_letter_{payload.job_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.md"
    path = Path(settings.output_dir) / filename
    path.write_text(letter, encoding="utf-8")

    app_row = (
        db.query(Application)
        .filter(Application.resume_id == resume.id, Application.job_id == job.id, Application.user_id == current_user.id)
        .first()
    )
    if app_row:
        app_row.cover_letter_path = str(path)
        db.add(app_row)
        db.commit()

    return CoverLetterResponse(cover_letter=letter, file_path=str(path))


@router.get("/templates")
def list_templates(current_user: User = Depends(get_current_user)) -> list[str]:
    return ["professional", "enthusiastic", "concise"]


@router.post("/save")
def save_cover_letter(payload: dict, current_user: User = Depends(get_current_user)) -> dict[str, str]:
    content = payload.get("content", "")
    filename = payload.get("filename", f"cover_letter_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.md")

    safe = "".join(c for c in filename if c.isalnum() or c in {"_", "-", "."})
    path = Path(settings.output_dir) / safe
    path.write_text(content, encoding="utf-8")
    return {"file_path": str(path)}
