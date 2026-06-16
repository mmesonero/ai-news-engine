# Changelog

## [0.3.0] — 2026-06-16 — Cloud-native, Spanish briefing, Telegram + Web

Major direction change: the project went from a local Docker MVP to a fully
cloud-hosted, autonomous pipeline. It now writes a Spanish briefing and delivers
it to a Telegram channel and a static web page, with no dependency on a PC.

### Added
- **Cloud execution**: GitHub Actions cron (`.github/workflows/daily.yml`) at 04:00 + 15:00 UTC. Neon Postgres + pgvector. All secrets in GitHub Actions only.
- **Telegram delivery** (`app/notify/telegram.py`): one message per story to a private channel (bot admin with post-only rights). Photo when an image exists, no link-preview card. Posts are edited live when more sources cover the story.
- **Static web** (`app/export/static_site.py`): publishes `data.js` (`window.__NEWS`) + per-story `n/<slug>.html` detail pages to `mmesonero.github.io/ai-news`. Ownership split — the engine never overwrites the portfolio's `index.html`. Web card titles and Telegram links share the same detail page.
- **Spanish localization**: `title_es` + Spanish `cleaned_summary` (enrichment rewrites both).
- **Classification fields**: `theme` (8 themes), `importance_tier` (alta/media/baja), `players` list.
- **3-layer dedup**: cosine clustering (0.82) + pairwise LLM same-event judge (cosine band 0.45–0.82 + shared-entity) + holistic LLM grouping (high-confidence). Union-find redirect map; orphan prune/repair.
- **Cross-source boost**: delivered score `+min(20, (sources−1)×8)` + `📡 N fuentes` counter; duplicates rewarded, not discarded.
- **Prompt-injection defense**: `ai/sanitize.py` (neutralize + wrap), `INJECTION_GUARD` preamble, closed-enum output validation.
- **Player tagging** (`ai/players.py`): keyword match over title + key_topics only (never the summary) to avoid false tags.
- **Images** (`ingestion/image_extract.py`): og:image / twitter:image / YouTube thumb for hero + Telegram photo + og:image.
- **OpenAI transcription** (`gpt-4o-transcribe`) for videos without subtitles; local Whisper removed.
- **Retention** (`pipeline/retention.py`): prune raw_content older than `RETENTION_DAYS` (14 in cloud); web bakes 30 days.
- Migrations 0002–0009 (theme, importance_tier, players, title_es, image_url, embedding_pruned, telegram delivery state, representative index).

### Changed
- Scheduler: GitHub Actions cron is now the production scheduler; APScheduler kept for optional local runs only.
- DB connection defaults point at `localhost` (cloud uses Neon secrets).

### Removed
- **Docker**: `Dockerfile`, `docker-compose.yml`, `docker-compose.viewer.yml`, `.dockerignore`, `Makefile`. The project is cloud-native; the Neon database is the backup. Recover from git history if ever needed.
- Local Whisper transcription backend.

### Deprecated
- LinkedIn-angle generation and `linkedin_*` / `novelty_score` / `business_impact_score` / `ai_generated_insights` columns (kept for migration compatibility, unused). `/trending` and `/linkedin-ideas` are legacy.

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
