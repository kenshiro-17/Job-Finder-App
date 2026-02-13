from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.auth import hash_password
from app.config import settings


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info('{table_name}')")).fetchall()
    return any(row[1] == column_name for row in rows)


def _add_column_if_missing(conn, table_name: str, column_name: str, column_sql: str) -> None:
    if _column_exists(conn, table_name, column_name):
        return
    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))


def run_runtime_migrations(engine: Engine) -> None:
    with engine.begin() as conn:
        _add_column_if_missing(conn, "resumes", "user_id", "user_id INTEGER")
        _add_column_if_missing(conn, "applications", "user_id", "user_id INTEGER")
        _add_column_if_missing(conn, "search_cache", "user_id", "user_id INTEGER")
        _add_column_if_missing(conn, "user_jobs", "sort_rank", "sort_rank INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "user_jobs", "last_seen_at", "last_seen_at DATETIME")
        _add_column_if_missing(conn, "jobs", "experience_level", "experience_level VARCHAR(50)")

        owner_username = settings.default_owner_username.strip().lower()
        owner_password = settings.default_owner_password

        owner_row = conn.execute(
            text("SELECT id FROM users WHERE username = :username"),
            {"username": owner_username},
        ).fetchone()
        if owner_row:
            owner_id = int(owner_row[0])
        else:
            conn.execute(
                text(
                    "INSERT INTO users (username, password_hash, is_active) VALUES (:username, :password_hash, 1)"
                ),
                {"username": owner_username, "password_hash": hash_password(owner_password)},
            )
            owner_id = int(
                conn.execute(
                    text("SELECT id FROM users WHERE username = :username"),
                    {"username": owner_username},
                ).scalar_one()
            )

        conn.execute(
            text("UPDATE resumes SET user_id = :owner_id WHERE user_id IS NULL"),
            {"owner_id": owner_id},
        )
        conn.execute(
            text(
                """
                UPDATE applications
                SET user_id = (
                    SELECT resumes.user_id FROM resumes WHERE resumes.id = applications.resume_id
                )
                WHERE user_id IS NULL
                """
            ),
        )
        conn.execute(
            text("UPDATE applications SET user_id = :owner_id WHERE user_id IS NULL"),
            {"owner_id": owner_id},
        )
        conn.execute(
            text("UPDATE search_cache SET user_id = :owner_id WHERE user_id IS NULL"),
            {"owner_id": owner_id},
        )

        conn.execute(
            text(
                """
                INSERT OR IGNORE INTO user_jobs (user_id, job_id)
                SELECT :owner_id, jobs.id FROM jobs
                """
            ),
            {"owner_id": owner_id},
        )
        conn.execute(
            text("UPDATE user_jobs SET sort_rank = 0 WHERE sort_rank IS NULL"),
        )
        conn.execute(
            text("UPDATE user_jobs SET last_seen_at = COALESCE(last_seen_at, created_at, CURRENT_TIMESTAMP)"),
        )
