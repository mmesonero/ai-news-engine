# AI News Intelligence Engine — Architecture

> An AI-powered intelligence engine that converts fragmented AI/tech news into unique business insights and LinkedIn-ready strategic content.

This document defines the architecture, data model, pipeline, and engineering conventions for the MVP. It is the single source of truth that the implementation follows.

---

## 1. Mission

The engine ingests AI/tech/business news from heterogeneous sources, eliminates noise and duplicates, consolidates overlapping stories into a single canonical insight, and emits LinkedIn-ready content angles. It is explicitly **not** an aggregator: volume is a liability, signal is the product.

Design priorities, in order:

1. **Signal quality** — every stored item must be defensibly worth a human read.
2. **Uniqueness** — one event = one cluster, regardless of how many outlets covered it.
3. **Insight density** — each enriched record carries strategic interpretation, not a headline restatement.
4. **Modularity** — every stage (ingest, embed, dedupe, cluster, classify, enrich) is independently replaceable.
5. **Operability** — fault-tolerant scheduled execution, structured logs, idempotent jobs.

---

## 2. High-Level System View

```
 ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐
 │ Ingestors  │ →  │ Raw Store  │ →  │ Embeddings │ →  │  Dedupe    │
 │ RSS/HTML/  │    │ Postgres   │    │ pgvector   │    │  cosine ≥θ │
 │ YouTube    │    │            │    │            │    │            │
 └────────────┘    └────────────┘    └────────────┘    └─────┬──────┘
                                                             │
                                                             ▼
 ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐
 │ FastAPI    │ ←  │  Enrich    │ ←  │ Classify   │ ←  │ Clustering │
 │ /news      │    │  GPT       │    │ noise vs.  │    │ representative│
 │ /clusters  │    │  insights  │    │  signal    │    │  selection │
 │ /linkedin  │    │            │    │            │    │            │
 └────────────┘    └────────────┘    └────────────┘    └────────────┘
```

The pipeline runs once per day via APScheduler inside the API container (single-process MVP). Each stage reads from and writes to Postgres; no in-memory hand-offs between stages, so any stage can be re-run independently on the records it owns.

---

## 3. Tech Stack

| Concern        | Choice                                           |
| -------------- | ------------------------------------------------ |
| Language       | Python 3.12                                      |
| Web framework  | FastAPI                                          |
| ORM            | SQLAlchemy 2.x (async)                           |
| DB             | PostgreSQL 16 + `pgvector`                       |
| Migrations     | Alembic                                          |
| Embeddings/LLM | OpenAI (`text-embedding-3-small`, `gpt-4o-mini`) |
| Scheduling     | APScheduler (AsyncIOScheduler)                   |
| Scraping       | `feedparser`, `httpx`, `BeautifulSoup`, Playwright (optional, deferred) |
| YouTube        | `youtube-transcript-api`, YouTube Data API v3    |
| Container      | Docker + Docker Compose                          |
| Config         | `pydantic-settings` (`.env` driven)              |
| Logging        | `structlog` JSON, request-id propagation         |

Model choices are centralized in `app/config.py` so an entire model swap is a single env-var change.

---

## 4. Repository Layout

```
ai-news-engine/
├── ARCHITECTURE.md                ← this file
├── README.md                      ← setup, runbook
├── docker-compose.yml             ← postgres + api + worker
├── Dockerfile
├── pyproject.toml
├── .env.example
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py
└── app/
    ├── main.py                    ← FastAPI app factory + lifespan
    ├── config.py                  ← pydantic Settings
    ├── logging_config.py
    ├── database.py                ← async engine, session factory
    ├── models/                    ← SQLAlchemy ORM
    ├── schemas/                   ← pydantic DTOs
    ├── repositories/              ← data access (one repo per aggregate)
    ├── services/                  ← business logic (stateless)
    │   ├── ingestion_service.py
    │   ├── embedding_service.py
    │   ├── deduplication_service.py
    │   ├── clustering_service.py
    │   ├── classification_service.py
    │   ├── enrichment_service.py
    │   └── linkedin_service.py
    ├── ingestion/                 ← source-specific fetchers
    │   ├── base.py                ← Ingestor protocol
    │   ├── rss.py
    │   ├── html.py
    │   └── youtube.py
    ├── ai/
    │   ├── openai_client.py       ← single OpenAI wrapper, retries, cost log
    │   └── prompts.py             ← ALL prompts live here, versioned
    ├── api/
    │   ├── deps.py                ← DB session, auth (future)
    │   └── v1/                    ← versioned routes
    ├── pipeline/
    │   └── daily.py               ← orchestrates the 9-step run
    ├── scheduler/
    │   └── jobs.py                ← APScheduler bootstrap
    └── seeds/
        └── sources.py             ← initial source catalog
```

Layering rule: `api → services → repositories → models`. Services never import from `api`; repositories never import from `services`. Ingestors and AI clients are leaves consumed by services.

---

## 5. Data Model

All tables use `id BIGSERIAL PRIMARY KEY` and `created_at TIMESTAMPTZ DEFAULT now()`. Vector columns require the `pgvector` extension (`CREATE EXTENSION IF NOT EXISTS vector;`).

### 5.1 `sources`

| column      | type         | notes                              |
| ----------- | ------------ | ---------------------------------- |
| id          | bigserial PK |                                    |
| name        | text         | display name                       |
| type        | text         | `rss` \| `html` \| `youtube`       |
| url         | text         | feed URL or channel ID             |
| active      | boolean      | default true                       |
| config_json | jsonb        | per-source overrides (selectors…)  |
| created_at  | timestamptz  |                                    |

Indexes: `(active)`, `(type)`.

### 5.2 `raw_content`

| column        | type         | notes                                  |
| ------------- | ------------ | -------------------------------------- |
| id            | bigserial PK |                                        |
| source_id     | bigint FK    | → sources.id                           |
| external_id   | text         | stable id from the source (e.g. GUID)  |
| title         | text         |                                        |
| url           | text         | unique within source                   |
| author        | text         | nullable                               |
| raw_text      | text         | full body or transcript                |
| published_at  | timestamptz  | nullable, parsed from source           |
| fetched_at    | timestamptz  | when ingestor pulled it                |
| content_hash  | text         | sha256 of normalized text              |
| language      | text         | ISO 639-1                              |
| metadata_json | jsonb        | source-specific extras                 |

Constraints / indexes:
- `UNIQUE (source_id, external_id)`
- `UNIQUE (url)`
- `INDEX (content_hash)`
- `INDEX (published_at DESC)`

### 5.3 `embeddings`

| column          | type           | notes                       |
| --------------- | -------------- | --------------------------- |
| id              | bigserial PK   |                             |
| raw_content_id  | bigint FK UQ   | → raw_content.id, 1:1       |
| embedding       | vector(1536)   | `text-embedding-3-small`    |
| model           | text           | embedding model id          |
| created_at      | timestamptz    |                             |

Index: `ivfflat (embedding vector_cosine_ops) WITH (lists = 100)` — built after a warm-up batch.

### 5.4 `processed_content`

| column                    | type         | notes                                |
| ------------------------- | ------------ | ------------------------------------ |
| id                        | bigserial PK |                                      |
| raw_content_id            | bigint FK UQ | → raw_content.id, 1:1                |
| cleaned_summary           | text         | 3–5 sentence executive summary       |
| key_topics                | text[]       | normalized lowercase tags            |
| novelty_score             | int          | 0–100                                |
| importance_score          | int          | 0–100                                |
| linkedin_potential_score  | int          | 0–100                                |
| business_impact_score     | int          | 0–100                                |
| ai_generated_insights     | jsonb        | structured enrichment object         |
| linkedin_angles           | jsonb        | hooks/angles/debate/implications     |
| rejected_reason           | text         | nullable                             |
| is_noise                  | boolean      | gating flag for downstream consumers |
| created_at                | timestamptz  |                                      |

### 5.5 `content_clusters`

| column                     | type         | notes                                |
| -------------------------- | ------------ | ------------------------------------ |
| id                         | bigserial PK |                                      |
| cluster_topic              | text         | LLM-named theme                      |
| representative_content_id  | bigint FK    | → raw_content.id, "canonical" item   |
| created_at                 | timestamptz  |                                      |

### 5.6 `cluster_items`

| column           | type           | notes                          |
| ---------------- | -------------- | ------------------------------ |
| cluster_id       | bigint FK      | → content_clusters.id          |
| raw_content_id   | bigint FK      | → raw_content.id               |
| similarity_score | double precision | cosine sim to representative |

Primary key: `(cluster_id, raw_content_id)`.

---

## 6. Daily Pipeline

`app/pipeline/daily.py` orchestrates the run. Each step is idempotent and operates on records flagged as "needs stage X" via the presence/absence of dependent rows — no separate status column to keep in sync.

1. **Fetch sources** — load `active=true` rows from `sources`.
2. **Extract content** — dispatch to the right ingestor (RSS / HTML / YouTube) per source. Each ingestor yields `RawContentDraft` records.
3. **Persist raw** — upsert into `raw_content` keyed on `(source_id, external_id)` or `url`. Existing records are skipped, not re-fetched.
4. **Embed new content** — for every `raw_content` row lacking an `embeddings` row, generate one. Batched (100 per request).
5. **Deduplicate** —
   - **Layer 1 (exact):** rejected by the `UNIQUE` constraints at step 3 and by `content_hash` lookup.
   - **Layer 2 (semantic):** for each new embedding, run `<=> (1 - cosine)` against embeddings from the last N days. If `similarity ≥ THRESHOLD` (default `0.90`), attach to the existing cluster of the nearest neighbour instead of creating a new one.
6. **Cluster** — items not attached in step 5 either form a new cluster (with themselves as representative) or join one when their nearest neighbour is itself unattached but within threshold (greedy single-link clustering, recomputed daily on the day's new items only — old clusters are not re-shuffled).
7. **Classify quality** — for every new `raw_content` without a `processed_content` row, call the noise classifier (single LLM call, structured JSON output). Records flagged `is_noise=true` short-circuit: no enrichment, no LinkedIn angles.
8. **Enrich** — non-noise records get the full enrichment pass: summary, scores, insights, LinkedIn angles. Done **once per cluster** (on the representative) — cluster members inherit the cluster's enrichment via the API, not via row duplication.
9. **Persist results** — write `processed_content`. Log per-stage metrics (counts, OpenAI token spend, wall time).

The whole run is wrapped in a single APScheduler job. Failures in one source do not abort the run; each source is a try/except boundary with structured error logging.

---

## 7. Deduplication & Clustering Details

**Two layers, in this order:**

| Layer | Check                            | Action on hit                            |
| ----- | -------------------------------- | ---------------------------------------- |
| 1     | `(source_id, external_id)` match | Skip — already ingested.                 |
| 1     | `url` match                      | Skip.                                    |
| 1     | `content_hash` match             | Skip — exact text duplicate, different URL. |
| 2     | cosine ≥ `DEDUP_THRESHOLD`       | Attach to neighbour's cluster, mark as duplicate of representative. |

Threshold is configurable: `DEDUP_THRESHOLD=0.90` by default. Anything in `[0.82, 0.90)` is treated as *related but distinct* — same cluster, different angle. Below `0.82` is a fresh cluster.

The representative for a cluster is the item with the highest `importance_score` after enrichment; until enrichment runs, it's the earliest `published_at`. Representatives are reselected lazily by the API, not stored as a denormalized field that can rot — the column exists for query speed but is recomputed by the enrichment stage on the day a new member joins.

This intentionally avoids global re-clustering: yesterday's clusters are stable. Only today's new items get clustered, then attached to existing clusters where possible.

---

## 8. AI Layer

All prompts live in `app/ai/prompts.py` as constants. No prompts inline in service code. Each prompt is versioned (`CLASSIFY_NOISE_V1`, `ENRICH_V1`, …) so changes are diff-trackable and an old prompt can be re-run.

The OpenAI client (`app/ai/openai_client.py`) is the only place we touch the SDK. It enforces:

- exponential backoff retry on `RateLimitError` / 5xx
- structured JSON output via response_format
- per-call token logging (input/output) into a `usage_log` table (optional, MVP-friendly)
- a single switchable model id from settings

### 8.1 Noise classifier

Single GPT call. Returns:

```json
{
  "category": "valuable" | "medium" | "noise",
  "reasoning": "...",
  "tags": ["funding", "model-release", ...]
}
```

`category=noise` short-circuits the pipeline. `medium` proceeds to enrichment but is de-prioritized in API ranking.

### 8.2 Enrichment

GPT call per **cluster representative**. Returns:

```json
{
  "cleaned_summary": "...",
  "key_topics": [...],
  "scores": {
    "novelty": 0-100,
    "importance": 0-100,
    "linkedin_potential": 0-100,
    "business_impact": 0-100
  },
  "insights": {
    "executive_summary": "...",
    "business_implications": [...],
    "emerging_trends": [...],
    "controversial_angles": [...],
    "strategic_implications": [...],
    "startup_implications": [...],
    "enterprise_implications": [...]
  }
}
```

### 8.3 LinkedIn angles

Separate call, depends on enrichment output. **Never produces finished posts** — it produces raw material:

```json
{
  "hooks": [...],
  "angles": [...],
  "controversial_points": [...],
  "business_implications": [...],
  "future_predictions": [...]
}
```

Splitting enrichment and LinkedIn into two calls keeps the LinkedIn voice tunable without re-running the analytical pass.

---

## 9. API Surface

All routes mounted under `/api/v1`. Read endpoints by default exclude `is_noise=true` and items inside a cluster that aren't the representative (set `?include_duplicates=true` to override).

| Method | Path                       | Purpose                                     |
| ------ | -------------------------- | ------------------------------------------- |
| GET    | `/news`                    | Paginated news feed (cluster representatives), filterable by `topic`, `min_importance`, `since`. |
| GET    | `/news/{id}`               | Single item with enrichment + LinkedIn payload. |
| GET    | `/clusters`                | Clusters with member counts.                |
| GET    | `/clusters/{id}`           | Cluster with full member list.              |
| GET    | `/trending`                | Top clusters in last 24/72h ranked by member count × importance. |
| GET    | `/linkedin-ideas`          | Just the LinkedIn payloads, sorted by `linkedin_potential_score`. |
| GET    | `/sources`                 | List sources.                               |
| POST   | `/sources`                 | Add a source.                               |
| POST   | `/reprocess/{id}`          | Re-run the enrichment pass on one raw_content (admin / debugging). |

Pagination: cursor-based on `(published_at, id)` to keep responses stable while ingestion runs.

---

## 10. Configuration

`pydantic-settings` reads from environment. `.env.example` ships with every key.

| Key                       | Default                       | Purpose                                  |
| ------------------------- | ----------------------------- | ---------------------------------------- |
| `DATABASE_URL`            | `postgresql+asyncpg://...`    |                                          |
| `OPENAI_API_KEY`          | —                             |                                          |
| `OPENAI_EMBEDDING_MODEL`  | `text-embedding-3-small`      | 1536 dims                                |
| `OPENAI_LLM_MODEL`        | `gpt-4o-mini`                 |                                          |
| `DEDUP_THRESHOLD`         | `0.90`                        | cosine cutoff                            |
| `CLUSTER_THRESHOLD`       | `0.82`                        | same-cluster cutoff                      |
| `DEDUP_LOOKBACK_DAYS`     | `14`                          | how far back semantic dedup looks        |
| `PIPELINE_CRON`           | `0 6 * * *`                   | when daily job runs                      |
| `YOUTUBE_API_KEY`         | —                             | for channel → recent videos              |
| `LOG_LEVEL`               | `INFO`                        |                                          |

---

## 11. Operations

- **Logs**: structlog JSON to stdout. Each pipeline run carries a `run_id` propagated through all stages.
- **Metrics**: per-stage counters logged at run end — items_fetched, items_new, items_noise, clusters_created, openai_tokens_in, openai_tokens_out.
- **Idempotency**: re-running the daily job on the same day is safe; nothing is reprocessed thanks to dependency-row presence checks.
- **Failure model**: per-source try/except in ingestion; per-record try/except in classification and enrichment. One bad article never aborts a run.
- **Migrations**: Alembic. `alembic upgrade head` runs in the container entrypoint.

---

## 12. Out of Scope for MVP (designed for, not built)

- Multi-user auth / RBAC — schema allows a future `users` table; API has a clean place for an auth dependency.
- Newsletter generation — clusters + LinkedIn angles already give a newsletter generator everything it needs; no schema change required.
- Public website — would consume the existing read endpoints.
- Playwright-driven scraping — `ingestion/html.py` is the extension point; not wired up for MVP.
- Re-clustering of historical data — daily clustering is forward-only; a future batch job can revisit history without schema changes.

---

## 13. Engineering Conventions

- Typed everywhere. `mypy --strict` clean.
- Services are stateless; everything that mutates goes through a repository.
- No business logic in routes — routes are thin and call exactly one service method.
- All AI prompts and model ids live in `ai/`. No magic strings sprinkled in services.
- One ingestor per source type, implementing the `Ingestor` protocol.
- Tests (deferred for MVP delivery scope, but folder reserved): unit per service, integration for the pipeline.
