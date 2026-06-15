# AI News Intelligence Engine

Production-grade MVP that ingests AI/tech news, removes noise, semantically deduplicates and clusters overlapping stories, and emits LinkedIn-ready content angles.

**See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full design.**

---

## Quick Start

### 1. Prerequisites

- Docker + Docker Compose
- An OpenAI API key
- (Optional) YouTube Data API v3 key — only required if you enable YouTube sources

### 2. Configure

```bash
cp .env.example .env
# edit .env and set OPENAI_API_KEY (and YOUTUBE_API_KEY if using YT sources)
```

### 3. Run

```bash
docker compose up --build
```

This brings up:

- `db` — PostgreSQL 16 with `pgvector`
- `api` — FastAPI on `http://localhost:8000` (also runs the APScheduler daily job)

Migrations run automatically on container start. Initial sources are seeded on first boot.

### 4. Trigger the pipeline manually

The daily job runs via cron, but you can force a run for testing:

```bash
docker compose exec api python -m app.pipeline.daily
```

### 5. Hit the API

- Interactive docs: `http://localhost:8000/docs`
- Trending: `http://localhost:8000/api/v1/trending`
- LinkedIn ideas: `http://localhost:8000/api/v1/linkedin-ideas`

---

## Local development (without Docker)

```bash
# Postgres with pgvector must be available — easiest is to keep docker-compose's db up:
docker compose up -d db

# Python deps
pip install -e .

# Migrations
alembic upgrade head

# Seed sources
python -m app.seeds.sources

# Run API
uvicorn app.main:app --reload

# Run pipeline manually
python -m app.pipeline.daily
```

---

## Adding a new source

```bash
curl -X POST http://localhost:8000/api/v1/sources \
  -H 'Content-Type: application/json' \
  -d '{
        "name": "Example AI Blog",
        "type": "rss",
        "url": "https://example.com/rss"
      }'
```

Supported `type` values: `rss`, `html`, `youtube`.

---

## Project layout

```
app/
  api/          FastAPI routes (versioned under /api/v1)
  ai/           OpenAI client + centralized prompts
  ingestion/    Source-specific fetchers (RSS, HTML, YouTube)
  models/       SQLAlchemy ORM models
  pipeline/     Daily orchestration
  repositories/ Data access layer
  schemas/      Pydantic DTOs
  scheduler/    APScheduler bootstrap
  seeds/        Initial source catalog
  services/     Business logic (stateless)
```

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the why behind each layer.

---

## Operational notes

- All structured logs are JSON on stdout; pipe to your log aggregator of choice.
- Token usage is logged per OpenAI call.
- The pipeline is idempotent — re-running on the same day is a no-op.
- Per-source failures do not abort the daily run.

---

## License

Internal / private. Adjust as needed.
