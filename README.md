# earnings-lens

**AI-powered earnings call transcript analyzer.** Ingests public earnings call transcripts, extracts structured topics and sentiment via the Claude API, computes quarter-over-quarter drift scores, and surfaces insights through a REST API and a minimal React dashboard.

---

## Features

- **Transcript ingestion** — fetches Motley Fool earnings call pages via httpx + BeautifulSoup
- **Segment parsing** — regex-based boundary detection splits prepared remarks from Q&A
- **Topic extraction** — Claude Haiku extracts 8–12 weighted, sentiment-tagged topics per transcript
- **Drift scoring** — pure-Python algorithm quantifies how much management narrative shifted between quarters
- **Analyst narratives** — Claude Sonnet generates a concise 3-sentence analyst summary per comparison
- **Alerts** — automatic flagging when drift score exceeds thresholds
- **REST API** — FastAPI with interactive Swagger docs at `/docs`
- **Dashboard** — single-file React frontend (no build step, CDN imports)

---

## Architecture

```
earnings-lens/
├── app/
│   ├── main.py           FastAPI app, mounts routers + serves frontend
│   ├── config.py         Pydantic-Settings config from .env
│   ├── database.py       SQLAlchemy engine, session, get_db dependency
│   ├── models.py         ORM models: Company, Transcript, TopicExtraction,
│   │                       QuarterComparison, Alert
│   ├── schemas.py        Pydantic request/response schemas
│   ├── routers/
│   │   ├── companies.py  GET/POST /companies, /{ticker}/transcripts,
│   │   │                   /{ticker}/latest-analysis
│   │   ├── transcripts.py  POST /transcripts  (full ingest pipeline)
│   │   └── analysis.py   GET /alerts
│   └── services/
│       ├── scraper.py    httpx + BeautifulSoup transcript fetcher
│       ├── parser.py     Q&A boundary segmentation
│       ├── analyzer.py   Claude API calls (extract_topics, generate_narrative)
│       └── comparator.py compute_drift_score() helper
├── alembic/              Alembic migrations (initial schema included)
├── frontend/
│   └── index.html        Single-file React dashboard (CDN, no build step)
├── tests/
│   ├── test_parser.py
│   ├── test_comparator.py
│   └── test_analyzer.py
├── .env.example
└── requirements.txt
```

---

## How it works

```
URL  →  scraper  →  parser  →  analyzer (Haiku)  →  comparator  →  analyzer (Sonnet)
                                   ↓                      ↓
                            TopicExtraction         QuarterComparison + Alerts
                                   ↓
                              Postgres (via SQLAlchemy + Alembic)
                                   ↓
                          FastAPI  →  React Dashboard
```

---

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ (local or Docker)
- An [Anthropic API key](https://console.anthropic.com/)

---

## Quick start

### 1. Clone and set up a virtual environment

```bash
git clone https://github.com/YOUR_USERNAME/earnings-lens.git
cd earnings-lens
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://myuser:mypassword@localhost:5432/earnings_lens
SCRAPE_DELAY_SECONDS=2
```

### 3. Create the database

```bash
createdb earnings_lens
# or: psql -c "CREATE DATABASE earnings_lens;" -U postgres
```

### 4. Run database migrations

```bash
PYTHONPATH=. alembic upgrade head
```

### 5. Start the API server

```bash
PYTHONPATH=. uvicorn app.main:app --reload --port 8000
```

- Dashboard: http://localhost:8000
- Interactive API docs: http://localhost:8000/docs

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check — `{"status": "ok"}` |
| `GET`  | `/companies` | List all tracked companies |
| `POST` | `/companies` | Register a company |
| `GET`  | `/companies/{ticker}/transcripts` | List transcripts for a ticker |
| `GET`  | `/companies/{ticker}/latest-analysis` | Most recent `QuarterComparison` |
| `POST` | `/transcripts` | Ingest a transcript (runs full pipeline) |
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

1. Fetch the transcript page (httpx + BeautifulSoup)
2. Segment prepared remarks vs. Q&A via regex boundary detection
3. Call **claude-haiku-4-5** to extract 8–12 weighted, sentiment-tagged topics
4. If a prior transcript exists, run `compare_quarters()` (pure-Python diff)
5. Call **claude-sonnet-4-6** to generate a 3-sentence analyst narrative
6. Persist `Transcript`, `TopicExtraction`, `QuarterComparison`, and any `Alert` rows
7. Return the full `IngestResponse`

---

## Drift score

The drift score quantifies how much the management narrative shifted between two consecutive quarters. It is clamped to `[0.0, 1.0]`.

| Event | Contribution |
|-------|-------------|
| Dropped topic | `weight × 2.0` |
| New topic | `weight × 1.5` |
| Matched topic with `\|Δweight\| > 0.08` | `\|Δweight\| × 1.0` |
| Sentiment degradation (positive→neutral, neutral→negative) | `+0.15` |

**Dashboard color bands:** green `< 0.2` · yellow `0.2–0.4` · red `> 0.4`

---

## Running tests

```bash
PYTHONPATH=. pytest tests/ -v
```

31 tests pass without a live database or real Anthropic API key (the Claude client is mocked in `test_analyzer.py`).

---

## Docker (optional)

Spin up Postgres with Docker Compose:

```yaml
# docker-compose.yml
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

Then set in `.env`:

```env
DATABASE_URL=postgresql://earnings:earnings@localhost:5432/earnings_lens
```

---

## Extending the scraper

`services/scraper.py` exposes a `fetch_by_ticker()` stub. Implement it to automatically resolve transcript URLs from a search index or paid data provider, then pass the resolved URL to `fetch_motley_fool_transcript()` (or a new site-specific parser).

---

## License

MIT
