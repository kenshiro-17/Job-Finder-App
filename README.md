# Job Finder App

Self-hosted job search and application tracking platform focused on the Germany tech market.

Upload your resume, search across multiple job sources, rank jobs by fit, track applications in a Kanban board, and generate tailored cover letters.

## Features

- Resume upload and parsing (`PDF`, `DOCX`)
- Multi-user accounts with data isolation per user
- Job search across:
  - `Indeed`
  - `StepStone`
  - `LinkedIn (guest listings)`
  - `Arbeitnow`
  - `BerlinStartupJobs`
- Match scoring between resume and job content
- Job caching and search history
- Stored jobs page with filtering, pagination, single delete, and clear-all
- Application tracker with lane drag-and-drop, bulk delete, and clear-all
- Cover letter generation and save support
- Recency controls:
  - Jobs older than 21 days are excluded
  - Freshly scraped jobs are prioritized
- Per-user stored jobs cap (minimum 10,000)

## Tech Stack

- Backend: `FastAPI`, `SQLAlchemy`, `SQLite`
- Frontend: `Vanilla JS`, `HTML`, `CSS`, `SortableJS`
- Scraping: `httpx`, `BeautifulSoup`, optional `Playwright`
- NLP/Parsing: `pdfplumber`, `pypdf`, `python-docx`, optional `spaCy`
- Infra: `Docker Compose`, `Nginx`, optional `Redis`

## Project Structure

```text
backend/
  app/
    api/
    models/
    schemas/
    services/
    main.py
frontend/
  index.html
  stored-jobs.html
  login.html
  css/
  js/
docker-compose.yml
nginx.conf
```

## Quick Start (Local)

### 1) Create environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 2) Install optional scraping/NLP extras (recommended)

```bash
pip install 'playwright>=1.41,<2' 'spacy>=3.8,<4' eval_type_backport
python -m playwright install chromium
python -m spacy download de_core_news_sm
```

### 3) Run backend

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open:

- App: `http://127.0.0.1:8000/`
- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

The backend serves the frontend directly (recommended local mode).

## Environment Variables

Copy from `.env.example` and adjust as needed.

Core settings:

- `DATABASE_URL` (default: `sqlite:///./db/jobs.db`)
- `AUTH_SECRET` (set a strong secret in non-dev environments)
- `DEFAULT_OWNER_USERNAME`
- `DEFAULT_OWNER_PASSWORD`
- `UPLOAD_DIR`
- `OUTPUT_DIR`
- `MAX_JOB_AGE_DAYS` (default: `21`)
- `NEWEST_WINDOW_MINUTES` (default: `60`)
- `MAX_STORED_JOBS_PER_USER` (minimum effective value: `10000`)

Scraping tuning:

- `MAX_JOBS_PER_SOURCE`
- `MAX_SCRAPE_PAGES`
- `SCRAPE_DELAY_SECONDS`

## Default Account Behavior

On startup, runtime migrations ensure an owner account exists using:

- `DEFAULT_OWNER_USERNAME`
- `DEFAULT_OWNER_PASSWORD`

You can also create additional users via the UI (`/login.html`).

## API Overview

Auth:

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`

Resumes:

- `POST /api/resumes/upload`
- `GET /api/resumes`
- `GET /api/resumes/{resume_id}`
- `DELETE /api/resumes/{resume_id}`
- `PUT /api/resumes/{resume_id}/set-active`

Jobs:

- `POST /api/jobs/search`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/search-history`
- `DELETE /api/jobs/{job_id}`
- `DELETE /api/jobs/clear`

Applications:

- `GET /api/applications`
- `POST /api/applications`
- `PATCH /api/applications/{app_id}/status`
- `DELETE /api/applications/{app_id}`
- `POST /api/applications/bulk-delete`
- `DELETE /api/applications/clear`
- `GET /api/applications/stats`

Cover letters:

- `POST /api/cover-letters/generate`
- `GET /api/cover-letters/templates`
- `POST /api/cover-letters/save`

## Testing

From repo root:

```bash
source .venv/bin/activate
pytest backend/tests -q
```

## Deployment

### Option A: Docker Compose (single host)

```bash
docker-compose up --build
```

- Frontend + API via Nginx: `http://localhost`
- Backend direct: `http://localhost:8000`

### Option B: Vercel (frontend) + Railway (backend)

Backend (Railway):

1. Deploy `backend/` as a Railway service.
2. Attach persistent volume mounted at `/data`.
3. Set env vars (example):

```bash
DATABASE_URL=sqlite:////data/jobs.db
UPLOAD_DIR=/data/uploads
OUTPUT_DIR=/data/outputs
AUTH_SECRET=replace-with-strong-random-secret
DEFAULT_OWNER_USERNAME=owner
DEFAULT_OWNER_PASSWORD=change-this-password
ENV=production
MAX_JOB_AGE_DAYS=21
NEWEST_WINDOW_MINUTES=60
MAX_STORED_JOBS_PER_USER=10000
```

Frontend (Vercel):

1. Deploy `frontend/`.
2. In `frontend/vercel.json`, point `/api/:path*` rewrite to your Railway backend domain.

## Troubleshooting

- `No jobs from a source`: provider markup may have changed; update selectors in `backend/app/services/job_scraper.py`.
- `Frontend API calls fail when served separately`: frontend uses `/api` base path, so use backend-served frontend or a reverse proxy/rewrite.
- `Port already in use`: run backend on a different port, e.g. `--port 8010`.
- `StepStone/Indeed low yield`: install Playwright + Chromium and increase `MAX_SCRAPE_PAGES`.

## Legal Notice

This project aggregates publicly available job listings. Respect each provider’s terms of service and robots policies in your deployment environment.
