# Changelog

## [0.2.0] — 2026-05-30

### Added
- Anthropic / Claude YouTube channels (`@claude`, `@anthropic-ai`) — handle resolution in `YoutubeIngestor`.
- TechCrunch (full), The Verge (full), Popular Science, Hackaday RSS sources.
- YouTube ingestor now accepts `@handle` URLs and caches the resolved `UCxxxx` id into `config_json.resolved_channel_id`.
- Noise classifier (`CLASSIFY_NOISE_V1`) tightened with a hard topical filter: must be AI / startup-VC / corporate / hard-tech with business angle, else `category=noise`. Now also returns `topic_match` and `comment_worthy` fields.

### Removed
- MIT Technology Review (AI + full) — heavy paywall, RSS bodies are stubs.
- Ars Technica AI — RSS truncates body to one paragraph.

## [0.1.0] — 2026-05-30

Initial MVP.

### Added
- Project architecture document (`ARCHITECTURE.md`).
- PostgreSQL schema with pgvector (Alembic migration `0001_initial`).
- SQLAlchemy 2.x async models for sources, raw content, embeddings, processed content, clusters, cluster items.
- Ingestion layer with `Ingestor` protocol and RSS / HTML / YouTube implementations.
- OpenAI client wrapper with retries, JSON mode, token logging.
- Centralized prompt module (`app/ai/prompts.py`) with versioned constants.
- Services for ingestion, embeddings, dedup+clustering, noise classification, enrichment, LinkedIn angles.
- Daily pipeline orchestrator (`app/pipeline/daily.py`), idempotent, run-id tagged.
- APScheduler async cron-driven daily job.
- FastAPI v1 endpoints: `/news`, `/clusters`, `/trending`, `/linkedin-ideas`, `/sources`, `/reprocess/{id}`, `/stats`, `/admin/run-pipeline`.
- Request-ID middleware + CORS.
- Source seed script (9 RSS + 5 YouTube channels).
- Docker Compose stack (postgres+pgvector + api).
- Test suite for pure logic: hashing, score clamping, prompt formatting, schema round-trip, ingestor dispatch.
- Makefile + `.dockerignore`.
