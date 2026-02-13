from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.resume import Resume
from app.models.user import User
from app.schemas.resume import ResumeOut, ResumeSetActiveRequest
from app.services.resume_parser import ResumeParser


router = APIRouter()
parser = ResumeParser(load_nlp=True)


@router.post("/upload", response_model=ResumeOut)
def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Resume:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are supported")

    raw = file.file.read()
    max_bytes = settings.max_resume_size_mb * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File exceeds {settings.max_resume_size_mb}MB")

    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(file.filename).name)
    safe_name = f"u{current_user.id}_{safe_name}"
    target = Path(settings.upload_dir) / safe_name
    target.write_bytes(raw)

    parsed = parser.parse_file(str(target))

    resume = Resume(
        user_id=current_user.id,
        filename=safe_name,
        file_path=str(target),
        raw_text=parsed.get("raw_text", ""),
        parsed_skills=parsed.get("skills", []),
        parsed_experience=parsed.get("experience", []),
        parsed_education=parsed.get("education", []),
        keywords=parsed.get("keywords", []),
    )

    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


@router.get("", response_model=list[ResumeOut])
def list_resumes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Resume]:
    return db.query(Resume).filter(Resume.user_id == current_user.id).order_by(Resume.upload_date.desc()).all()


@router.get("/{resume_id}", response_model=ResumeOut)
def get_resume(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Resume:
    resume = db.query(Resume).filter(Resume.id == resume_id, Resume.user_id == current_user.id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume


@router.delete("/{resume_id}")
def delete_resume(
    resume_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    resume = db.query(Resume).filter(Resume.id == resume_id, Resume.user_id == current_user.id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    try:
        Path(resume.file_path).unlink(missing_ok=True)
    except Exception:
        pass

    db.delete(resume)
    db.commit()
    return {"status": "deleted"}


@router.put("/{resume_id}/set-active", response_model=ResumeOut)
def set_active_resume(
    resume_id: int,
    payload: ResumeSetActiveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Resume:
    resume = db.query(Resume).filter(Resume.id == resume_id, Resume.user_id == current_user.id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if payload.is_active:
        db.query(Resume).filter(Resume.user_id == current_user.id).update({Resume.is_active: False})

    resume.is_active = payload.is_active
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume
