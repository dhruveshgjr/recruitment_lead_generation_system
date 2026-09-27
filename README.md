# HiringLeads — production public hiring-signal pipeline

HiringLeads turns public company hiring pages and public ATS APIs into recruiter-facing **company-level hiring signals**.

The system intentionally avoids LinkedIn scraping and personal-contact harvesting. The canonical lead is a company/job signal plus public career/apply/contact URLs.

## What is production-grade here

- Public ATS adapters: Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, JSON-LD, Hacker News hiring.
- Observation-first freshness: `first_seen_at` is when HiringLeads observed the job; provider `posted_at` remains advisory.
- Replayable Postgres model with durable ingestion and delivery runs.
- In-memory bucketed fuzzy dedupe so a large board does not run a database query for every posting.
- Conservative missing-post detection: empty provider responses never mass-close a board.
- Explainable role classification + low-confidence review queue.
- SQL pre-filtering and idempotent delivery watermarking.
- SMTP retries, unsubscribe links, Prometheus metrics, JSON logs.
- Alembic migrations and Docker Compose for API + worker + Postgres.
- Operator CLI for seeding, probing, crawling, ingestion, previewing, sampling and delivery.

## Architecture

Discovery → board registry → public source adapters → normalization → classification → dedupe → Postgres → scoring/matching → CSV/email/API.

## Local development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
export HL_AUTO_CREATE_SCHEMA=true
hl db init
hl seed seeds
hl ingest run
```

For production-like migrations:

```bash
export HL_AUTO_CREATE_SCHEMA=false
hl db upgrade
```

Run tests:

```bash
pytest
ruff check .
```

Run API:

```bash
uvicorn hiringleads.api.main:app --host 0.0.0.0 --port 8000
```

Run worker:

```bash
python -m hiringleads.worker
```

## Docker

```bash
docker compose up --build
```

The compose stack runs Postgres, a one-shot migration container, API, and worker.

## Operator flow

```bash
hl seed probe example.com
hl seed crawl
hl seed boards --provider greenhouse
hl ingest run --concurrency 8
hl ingest board 12
hl leads preview 3 --limit 25 --hours 168 --export ./sample.csv
hl leads sample 3
hl leads deliver --dry-run
hl leads stats
```

## Data contract

`JobPosting.first_seen_at` is an observation timestamp, not a claim that the employer created the job on that date. Bulk board imports are marked with `is_bulk_import` and scored down rather than backdating the observation.

`raw` is sanitized before storage. Obvious applicant/contact/resume/PII fields are removed and payload size is bounded.

## Production checklist

1. Set strong `HL_API_KEY` and `HL_UNSUBSCRIBE_SECRET`.
2. Use `HL_AUTO_CREATE_SCHEMA=false`; apply migrations in deployment.
3. Put the API behind TLS and an application gateway.
4. Configure SMTP, bounce handling and domain authentication separately.
5. Scrape only public endpoints/pages and honor provider terms plus `robots.txt` for generic HTML extraction.
6. Watch `/readyz`, `/metrics`, ingestion run failures and board failure counts.
7. Run exactly one delivery worker per watchlist at a time; advisory locks protect against accidental multi-worker duplication.
8. Tune taxonomy and scoring from recruiter feedback rather than blindly increasing volume.
