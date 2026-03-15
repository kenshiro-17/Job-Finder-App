# Job Finder App

Self-hosted job search and application tracking platform focused on the Germany tech market.

The app combines resume parsing, multi-source job discovery, relevance scoring, and application tracking in one system so the user can search, shortlist, and manage the pipeline without juggling multiple disconnected tools.

## Key Features

- Resume upload and parsing for `PDF` and `DOCX`
- Multi-user accounts with per-user data isolation
- Job search across multiple sources:
  - `Indeed`
  - `StepStone`
  - `LinkedIn` guest listings
  - `Arbeitnow`
  - `BerlinStartupJobs`
- Match scoring between resume content and job content
- Stored jobs page with pagination, filtering, and cleanup actions
- Kanban-style application tracker with drag-and-drop lane movement
- Tailored cover-letter generation and save support
- Freshness controls for search results
- Large per-user storage limits for collected jobs

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy, Alembic
- **Frontend**: HTML, CSS, vanilla JavaScript, SortableJS
- **Database**: SQLite by default
- **Scraping**: `httpx`, `BeautifulSoup`, optional `Playwright`
- **Parsing**: `pypdf`, `pdfplumber`, `python-docx`
- **Optional NLP**: `spaCy`
- **Infra**: Docker Compose, Nginx, optional Redis

## Repository Structure

```text
backend/
  app/
    api/
    models/
    schemas/
    services/
    main.py
  db/
  tests/
frontend/
  index.html
  stored-jobs.html
  login.html
  css/
  js/
data/
  db/
  uploads/
  outputs/
docker-compose.yml
nginx.conf
```

## Prerequisites

- Python `3.11+`
- `pip`
- Optional but recommended for full scraping support:
  - Playwright Chromium
  - spaCy German model
- Optional: Docker + Docker Compose

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/kenshiro-17/Job-Finder-App.git
cd 'Job Finder App'
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install backend dependencies

```bash
pip install -r backend/requirements.txt
```

### 4. Install optional scraping and NLP extras

```bash
pip install 'playwright>=1.41,<2' 'spacy>=3.8,<4' eval_type_backport
python -m playwright install chromium
python -m spacy download de_core_news_sm
```

### 5. Configure environment variables

```bash
cp .env.example .env
```

Important variables:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Database location |
| `REDIS_URL` | Optional Redis endpoint |
| `DEFAULT_OWNER_USERNAME` | Auto-created owner account |
| `DEFAULT_OWNER_PASSWORD` | Owner password |
| `AUTH_SECRET` | Auth/session secret |
| `MAX_JOB_AGE_DAYS` | Maximum job age retained from scraping |
| `NEWEST_WINDOW_MINUTES` | Window for prioritizing new jobs |
| `MAX_STORED_JOBS_PER_USER` | Upper cap for stored jobs |
| `UPLOAD_DIR` | Resume upload storage |
| `OUTPUT_DIR` | Generated output storage |

### 6. Start the backend

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The backend serves the frontend in the recommended local mode.

Open:

- App: `http://127.0.0.1:8000/`
- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

## Verification

### Run backend tests

```bash
pytest backend/tests -q
```

### Manual QA checklist

- Account creation and login
- Resume upload and parsing
- Search across supported sources
- Job storage and deletion
- Tracker lane drag-and-drop
- Cover letter generation
- No horizontal overflow on smaller screens

## Search and Ranking Model

The project is not just a scraper. It is a workflow app built around three connected steps:

1. parse the candidate profile
2. collect and normalize jobs from several sources
3. rank and track jobs inside one application workflow

Freshness handling is a core part of the logic:

- jobs older than `21` days are excluded by default
- newly scraped jobs are prioritized
- caching reduces unnecessary repeat scraping

## Docker

### Start the stack

```bash
docker compose up --build
```

The compose setup runs:

- backend service
- frontend/static serving path through backend/Nginx pathing
- persistent data directories under `data/`

### Useful commands

```bash
docker compose ps
docker compose logs -f
```

## Deployment Notes

The repo is structured for self-hosted deployment rather than purely static hosting.

Recommended production work before public deployment:

- set a strong `AUTH_SECRET`
- replace default owner credentials
- move SQLite to a managed production database if concurrency grows
- place the app behind HTTPS
- enable Redis-backed caching if scraping volume increases
- review legal/compliance constraints for job-source scraping in your target environment

## Architecture Notes

- Runtime migrations ensure an owner account exists at startup
- The app maintains user-level isolation for stored jobs and tracker data
- Resume parsing and job scraping are decoupled enough to evolve independently
- Optional Playwright support exists for more dynamic job sites

## Troubleshooting

### Playwright issues

If browser-based scraping fails, reinstall Chromium:

```bash
python -m playwright install chromium
```

### spaCy model missing

```bash
python -m spacy download de_core_news_sm
```

### SQLite path issues

Check that `DATABASE_URL`, `UPLOAD_DIR`, and `OUTPUT_DIR` point to writable paths.

## License

Add a license if you intend to distribute the project publicly.
