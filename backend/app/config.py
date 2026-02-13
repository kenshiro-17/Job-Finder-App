from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote


@dataclass
class Settings:
    app_name: str = "Match Pilot"
    environment: str = os.getenv("ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./db/jobs.db")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    scrape_delay_seconds: float = float(os.getenv("SCRAPE_DELAY_SECONDS", "1.2"))
    max_jobs_per_source: int = int(os.getenv("MAX_JOBS_PER_SOURCE", "120"))
    max_scrape_pages: int = int(os.getenv("MAX_SCRAPE_PAGES", "10"))
    max_job_age_days: int = int(os.getenv("MAX_JOB_AGE_DAYS", "21"))
    newest_window_minutes: int = int(os.getenv("NEWEST_WINDOW_MINUTES", "60"))
    max_stored_jobs_per_user: int = max(10000, int(os.getenv("MAX_STORED_JOBS_PER_USER", "10000")))
    max_resume_size_mb: int = int(os.getenv("MAX_RESUME_SIZE_MB", "5"))
    upload_dir: str = os.getenv("UPLOAD_DIR", "./uploads")
    output_dir: str = os.getenv("OUTPUT_DIR", "./outputs")
    enable_redis_cache: bool = os.getenv("ENABLE_REDIS_CACHE", "false").lower() == "true"
    default_owner_username: str = os.getenv("DEFAULT_OWNER_USERNAME", "owner")
    default_owner_password: str = os.getenv("DEFAULT_OWNER_PASSWORD", "owner1234")

    def ensure_directories(self) -> None:
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        self._ensure_sqlite_directory()

    def _ensure_sqlite_directory(self) -> None:
        if not self.database_url.startswith("sqlite:///"):
            return
        raw_path = self.database_url.replace("sqlite:///", "", 1)
        if not raw_path or raw_path == ":memory:":
            return
        db_path = Path(unquote(raw_path))
        if not db_path.is_absolute():
            db_path = Path(".") / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
