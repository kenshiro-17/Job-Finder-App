# Match Pilot

Self-hosted job search assistant for Germany-focused sources (Indeed + StepStone + LinkedIn + Arbeitnow + BerlinStartupJobs), powered by resume matching and application tracking.

## Features

- Upload and parse PDF/DOCX resumes
- Account login with per-user data isolation
- Search jobs with source selection and filters
- Rank jobs with match score breakdowns
- Track applications in a Kanban-style board
- Generate cover letters from resume + job context
- Cache search results for 30 minutes
- Browse and clear stored jobs (`/stored-jobs.html`)

## Stack

- Backend: FastAPI, SQLAlchemy, SQLite, Playwright, scikit-learn
- Frontend: Vanilla JS SPA + SortableJS
- Infra: Docker Compose, Nginx, Redis (optional cache layer)

## Local Development (without Docker)

1. Create env and install dependencies:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Optional scraping/NLP extras:

```bash
python -m pip install spacy playwright playwright-stealth fake-useragent
python -m playwright install chromium
python -m spacy download de_core_news_sm
```

2. Run backend:

```bash
uvicorn app.main:app --reload --port 8000
```

3. Serve frontend:

```bash
cd ../frontend
python3 -m http.server 8080
```

4. Open `http://localhost:8080`.

## Docker

```bash
docker-compose up --build
```

- Frontend + API gateway: `http://localhost`
- Backend direct API: `http://localhost:8000`

## Deployment: Railway (Backend) + Vercel (Frontend)

### 1. Deploy backend to Railway

1. Create a new Railway project and add a service from this repo.
2. Set service root directory to `backend` (or deploy `backend` as its own repo).
3. Use Docker deployment (Railway will build `backend/Dockerfile`).
4. Attach a persistent volume and mount it at `/data`.
5. Set these Railway environment variables:

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

6. Generate a public Railway domain for the service.

### 2. Connect frontend on Vercel

1. Create a Vercel project from this same repo.
2. Set root directory to `frontend`.
3. Edit `frontend/vercel.json` and replace:
   - `https://REPLACE_WITH_YOUR_RAILWAY_DOMAIN`
   - with your Railway backend domain, e.g. `https://match-pilot-api.up.railway.app`
4. Deploy on Vercel.

Now all frontend `/api/*` calls are proxied by Vercel to Railway, so no browser CORS setup is required.

## API Overview

- `POST /api/resumes/upload`
- `GET /api/resumes`
- `PUT /api/resumes/{id}/set-active`
- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/jobs/search`
- `GET /api/jobs`
- `DELETE /api/jobs/clear`
- `GET /api/jobs/{id}`
- `GET /api/jobs/search-history`
- `GET /api/applications`
- `POST /api/applications`
- `PATCH /api/applications/{id}/status`
- `GET /api/applications/stats`
- `POST /api/cover-letters/generate`

## Notes

- Scrapers depend on public site markup and may require selector updates when providers change HTML.
- For legal and reliability reasons, keep request rates low and favor caching.
