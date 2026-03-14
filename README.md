# earnings-lens

A pipeline that ingests public earnings call transcripts, runs multi-dimensional
sentiment and topic analysis via the Anthropic API, stores results in Postgres,
and exposes a REST API + minimal React dashboard.

---

## Architecture

```
earnings-lens/
  app/
    main.py          FastAPI app, mounts router + serves frontend
    config.py        Pydantic-settings from .env
    database.py      SQLAlchemy engine + session + get_db dependency
    models.py        ORM models (Company, Transcript, TopicExtraction,
                       QuarterComparison, Alert)
    schemas.py       Pydantic request/response schemas
    routers/
      companies.py   GET/POST /companies, /{ticker}/transcripts,
                       /{ticker}/latest-analysis
      transcripts.py POST /transcripts  (full ingest pipeline)
      analysis.py    GET /alerts
    services/
      scraper.py     httpx + BeautifulSoup transcript fetcher
      parser.py      Q&A boundary segmentation
      analyzer.py    Claude API calls (extract_topics, compare_quarters,
                       generate_narrative)
      comparator.py  compute_drift_score() helper (also used in tests)
  alembic/           Alembic migrations (initial schema included)
  frontend/
    index.html       Single-file React dashboard (CDN, no build step)
  tests/
    test_parser.py
    test_comparator.py
    test_analyzer.py
  .env.example
  requirements.txt
  README.md
```

---

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ running locally (or via Docker)
- An [Anthropic API key](https://console.anthropic.com/)

---

## Quick start

### 1. Clone and create virtual environment

```bash
git clone <repo-url> earnings-lens
cd earnings-lens
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://myuser:mypassword@localhost:5432/earnings_lens
SCRAPE_DELAY_SECONDS=2
```

### 3. Create the database

```bash
# Using psql:
createdb earnings_lens
# Or with a custom user:
psql -c "CREATE DATABASE earnings_lens;" -U postgres
```

### 4. Run Alembic migrations

```bash
PYTHONPATH=. alembic upgrade head
```

### 5. Start the API server

```bash
PYTHONPATH=. uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000> for the dashboard, or <http://localhost:8000/docs> for the interactive API docs.

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check — `{"status": "ok"}` |
| `GET`  | `/companies` | List all tracked companies |
| `POST` | `/companies` | Add a company `{ticker, name, sector}` |
| `GET`  | `/companies/{ticker}/transcripts` | List transcripts for a ticker |
| `GET`  | `/companies/{ticker}/latest-analysis` | Most recent `QuarterComparison` |
| `POST` | `/transcripts` | Ingest a transcript (full pipeline) |
| `GET`  | `/alerts` | All alerts, newest first |

### POST /companies

```json
{
  "ticker": "AAPL",
  "name": "Apple Inc.",
  "sector": "Technology"
}
```

### POST /transcripts

```json
{
  "ticker": "AAPL",
  "url": "https://www.fool.com/earnings/call-transcripts/...",
  "fiscal_quarter": "Q1",
  "fiscal_year": 2025
}
```

**Pipeline steps:**

1. Fetches the transcript page via httpx (Motley Fool)
2. Segments prepared remarks vs. Q&A with regex boundary detection
3. Calls **claude-haiku-4-5-20251001** to extract 8-12 structured topics
4. If a prior transcript exists, runs `compare_quarters()` (pure Python diff)
5. Calls **claude-sonnet-4-6** to generate a 3-sentence analyst narrative
6. Persists `Transcript`, `TopicExtraction`, `QuarterComparison`, and any `Alert` rows
7. Returns the full `IngestResponse`

---

## Drift score formula

Clamped to `[0.0, 1.0]`:

| Event | Contribution |
|-------|-------------|
| Dropped topic | `weight × 2.0` |
| New topic | `weight × 1.5` |
| Flagged matched topic (`|Δweight| > 0.08`) | `|Δweight| × 1.0` |
| Sentiment degradation (positive→neutral, etc.) | `+0.15` |

Dashboard color bands: green `< 0.2`, yellow `0.2–0.4`, red `> 0.4`.

---

## Running tests

```bash
PYTHONPATH=. pytest tests/ -v
```

All 31 tests pass without a live database or real API key (Anthropic client is mocked in `test_analyzer.py`).

---

## Docker (optional)

A minimal `docker-compose.yml` to spin up Postgres:

```yaml
version: "3.9"
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: earnings
      POSTGRES_PASSWORD: earnings
      POSTGRES_DB: earnings_lens
    ports:
      - "5432:5432"
```

Then set `DATABASE_URL=postgresql://earnings:earnings@localhost:5432/earnings_lens` in `.env`.

---

## Adding more transcript sources

`services/scraper.py` exposes a `fetch_by_ticker()` stub. Implement it to
automatically resolve transcript URLs from a search index or paid data provider,
then call `fetch_motley_fool_transcript()` (or a new site-specific parser) with
the resolved URL.

---

## License

MIT
