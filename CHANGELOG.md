# Changelog

## [0.5.0] — 2026-06-24 — English everywhere, email newsletter, LinkedIn drafts

The project went fully English, gained two new delivery channels (email + LinkedIn drafts), and let the public subscribe from the web.

### Added — email newsletter (`app/notify/email_digest.py`, `weekly_email.yml`)
- **Brevo campaign** transport (preferred): creates + `sendNow`s a campaign to the contact list, with Brevo's compliant 1-click unsubscribe (`{{ unsubscribe }}`). **SMTP fallback** (Gmail/Resend/Brevo SMTP) to a fixed `EMAIL_TO` list when only `EMAIL_*` is set. Fail-loud (red run on send error).
- Magazine-style HTML (gray page + white card, dark wordmark, gold accents, uniform per-story cards, preheader, `List-Unsubscribe`). Read-only — same `_gather()` set as the web (top 10 + extra `high`, cap 15).
- **Web subscribe forms** (portfolio `index.html`): popup + section now POST to Brevo's `sibforms.com/serve` endpoint via a hidden iframe (no reload, no API key exposed); new subscribers land in the list the newsletter sends to.

### Added — LinkedIn drafts (`app/notify/linkedin_draft.py`)
- Copy-paste, **no LinkedIn API**: posts are written and sent to Telegram (`LINKEDIN_DRAFT_CHAT_ID`) as a `<pre>` copy-block + first-comment line for manual approval.
- **weekly** (reuses the email `_gather()`, top 5, headline + paragraph) + **breaking** (every story boosted ≥ `LINKEDIN_MIN_SCORE` 85, once each via `content_clusters.linkedin_drafted_at`; hooked into the daily pipeline).
- **Spanish** drafts: Spanish template + on-the-fly `gpt-4o-mini` translation (falls back to English). Bold titles via Mathematical Sans-Serif Bold (accents dropped, ñ kept). No em/en dashes.

### Changed — English everywhere (migration 0010)
- Content (enrichment now prompts for English), web/Telegram/email chrome, AND internal enums: `theme` keys `models/tools/features/business/cases/insights/tutorials/other` (+ `irrelevant`), `importance_tier` `high/medium/low`. Migration 0010 remapped existing rows in place; `retranslate.yml` re-enriched/re-scored the back catalogue.
- Telegram: English chrome, summaries clipped at a sentence boundary, push gated at boosted ≥ `TELEGRAM_MIN_SCORE` (65). Importance scoring reworked (additive 5-factor, player weight scales with count, anti-rounding).
- Copy: UI label "stories" → "news"; all em/en dashes removed from email + Telegram templates, titles and summaries (hyphens like `GPT-4` kept).
- Morning pipeline window moved 1h earlier (02:47/03:17 UTC).

### Added — robustness
- Migration **0011** (`content_clusters.linkedin_drafted_at`).
- `config.py` `field_validator` coerces blank int secrets (empty GitHub secret → `""`) back to defaults so an unset secret never crashes startup.

### Ops
- Brevo "Authorised IPs → for API keys" disabled so GitHub Actions' dynamic IPs can call the API (security tradeoff accepted; key stays in Secrets).

## [0.4.0] — 2026-06-16 — Web integration, permanent archive, paginated history

The custom portfolio web page now renders real engine data, the detail pages
match its design, and the system became a **permanent, paginated archive**.

### Added — web data integration
- **`data.js`** export (`static_site._emit_data_js`): `window.__NEWS = {now, data:[...]}` in the portfolio `index.html` DATA schema. The index consumes it (falls back to its embedded sample if absent). Theme keys mapped engine→index; each item carries `detail` = `n/<slug>.html`.
- **Click → detail**: index story titles link to the per-story detail page (same target Telegram uses).
- **Player logos**: SpaceX, Tesla, Perplexity, DeepSeek, Cursor added (+ swapped Apple→white, Google→color-G). Players without a logo fall back to a colored dot.

### Added — archive model (Phase 1: permanent storage)
- **Archive-friendly retention** (`retention.py`): past `RETENTION_DAYS` (14) it no longer deletes rows — it drops the embedding + blanks `raw_text` (`embedding_pruned=true`) but KEEPS the `raw_content` row + `processed_content` + cluster **forever**. The site is a permanent archive at ~1KB/story; dedup still has its 14-day window. `RETENTION_DAYS` must stay ≥ `DEDUP_LOOKBACK_DAYS`.

### Added — archive model (Phase 2: paginated history)
- **Split export**: `data.js` = recent `RECENT_DAYS` (90) for a fast default load; **`data-archive.js`** (`window.__NEWS_ARCHIVE`) = everything older, **lazy-loaded** by the index only when the user picks the "All" range (dedup-merged by slug, fetched once). Shared `now` across both files. Detail pages generated for the whole archive. Keeps the page light while making years reachable on demand.
- Index range control: **Month** = real 30 days + new **All** = full archive (triggers the lazy load).

### Changed
- **Detail pages** (`_render_detail`/`_STYLE`/`_nav`) restyled to match the AI News index exactly: `#0D0D0D` plane + warm glows + center vignette, Outfit, gold `#e2ba6b`, nav = "Portfolio · AI News".
- Static-site bake window 30 → 90 days; UI label "stories" → "news".

### Web (portfolio repo, `mmesonero.github.io/ai-news`)
- `index.html` background matched to the main portfolio (`#0D0D0D` + vignette 0.35 + glows + grain).
- Wiring is design-safe: the engine writes only `data.js`, `data-archive.js`, `n/` — never `index.html`.

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
