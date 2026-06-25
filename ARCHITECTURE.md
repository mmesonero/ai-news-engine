# AI News Intelligence Engine — Architecture

> A cloud-hosted, autonomous engine that converts fragmented AI/tech news into a concise, deduplicated **English** briefing, delivered to Telegram, a static web page, a weekly email newsletter (Brevo) and LinkedIn post drafts. Volume is a liability; signal is the product.

This document is the single source of truth for the architecture, data model, pipeline, and conventions.

---

## 1. Mission

Ingest AI/tech/business news from a fixed set of quality sources, eliminate noise and duplicates, consolidate overlapping stories into one canonical insight, write an English summary, and deliver it across four channels. Design priorities, in order:

1. **Signal quality** — every delivered item is defensibly worth a human read.
2. **Uniqueness** — one event = one cluster, no matter how many outlets cover it. Duplicates are *rewarded* (boosted score + source counter), never shown twice.
3. **Autonomy** — runs entirely in the cloud on a schedule. No PC, no server, no Docker.
4. **Modularity** — every stage (ingest, embed, dedup, merge, classify, enrich, deliver) is independently re-runnable.
5. **Safety** — prompt-injection defenses on every LLM call; secrets never leave the CI vault.

---

## 2. High-level system view

```
 GitHub Actions cron (~02:47/03:17 + ~14:37/15:23 UTC)
        │
        ▼
 ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌──────────────┐
 │ Ingest    │ → │ Embed     │ → │ Dedup +   │ → │ LLM merge    │
 │ RSS/HTML/ │   │ pgvector  │   │ cluster   │   │ (pairwise +  │
 │ YouTube   │   │           │   │ cosine    │   │  holistic)   │
 └───────────┘   └───────────┘   └───────────┘   └──────┬───────┘
                                                        │
        ┌───────────────────────────────────────────────┘
        ▼
 ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌──────────────┐
 │ Classify  │ → │ Enrich    │ → │ Players + │ → │ Deliver      │
 │ noise /   │   │ (English  │   │ images    │   │ Telegram +   │
 │ theme /   │   │  summary  │   │           │   │ LinkedIn brk │
 │ tier      │   │  title)   │   │           │   │ + static web │
 └───────────┘   └───────────┘   └───────────┘   └──────────────┘
                                                        │
                                                        ▼
                                                  Retention prune

 weekly_email.yml (Sunday)  →  Brevo email campaign + weekly LinkedIn draft
```

All state lives in Postgres (Neon). No in-memory hand-offs — any stage can be re-run on the records it owns. The scheduler is GitHub Actions cron (UTC, no DST); `app/scheduler/` (APScheduler) exists only for optional local runs.

---

## 3. Tech stack

| Concern | Choice |
| --- | --- |
| Language | Python 3.12 |
| Web framework | FastAPI (local browsing + `/briefing/daily`) |
| ORM | SQLAlchemy 2.x (async) |
| DB | **Neon** PostgreSQL + `pgvector` (cloud); any local Postgres+pgvector for dev |
| Migrations | Alembic |
| Embeddings | OpenAI `text-embedding-3-small` (1536 dims) |
| LLM | OpenAI `gpt-4o-mini` (classify / enrich / dedup judges) |
| Transcription | OpenAI `gpt-4o-transcribe` (videos without subtitles) |
| Scheduler | **GitHub Actions** cron (prod); APScheduler (local only) |
| Scraping | `feedparser`, `httpx`, `BeautifulSoup` |
| Delivery | Telegram Bot API + GitHub Pages static export |
| Config | `pydantic-settings` (`.env` / env-driven) |
| Logging | `structlog` JSON, `run_id` propagation |

Model ids are centralized in `app/config.py` — a model swap is one env-var change.

---

## 4. Repository layout

```
ai-news-engine/
├── ARCHITECTURE.md                 ← this file
├── README.md                       ← setup + runbook
├── SECURITY.md                     ← secret handling
├── CHANGELOG.md
├── pyproject.toml
├── .env.example / .env.cloud.example
├── alembic/versions/               ← 0001 … 0011 (0010 = English enums, 0011 = linkedin_drafted_at)
├── .github/workflows/
│   ├── daily.yml                   ← daily pipeline (cron + Telegram + LinkedIn breaking + publish)
│   ├── weekly_email.yml            ← Sunday: Brevo email newsletter + weekly LinkedIn draft
│   └── retranslate.yml             ← manual re-enrich/re-score (used for the EN migration)
└── app/
    ├── main.py                     ← FastAPI factory + lifespan
    ├── config.py                   ← pydantic Settings
    ├── database.py                 ← async engine + session factory
    ├── links.py                    ← story_slug / detail_path / detail_url
    ├── models/                     ← SQLAlchemy ORM
    ├── repositories/               ← data access (one repo per aggregate)
    ├── services/
    │   ├── ingestion_service.py
    │   ├── embedding_service.py
    │   ├── dedup_clustering_service.py
    │   ├── cluster_merger.py        ← pairwise + holistic LLM merge, prune/repair
    │   ├── classification_service.py
    │   └── enrichment_service.py
    ├── ingestion/                  ← rss / html / youtube + image_extract + transcript_ytdlp
    ├── ai/
    │   ├── openai_client.py        ← single SDK wrapper, retries, cost log
    │   ├── prompts.py              ← ALL prompts, versioned, with INJECTION_GUARD
    │   ├── sanitize.py             ← neutralize + wrap untrusted text
    │   └── players.py              ← player tagging (title + key_topics only)
    ├── export/
    │   └── static_site.py          ← data.js + per-story detail pages
    ├── notify/
    │   ├── telegram.py             ← per-story send + live edit on new sources
    │   ├── email_digest.py         ← weekly newsletter (Brevo campaign / SMTP fallback)
    │   └── linkedin_draft.py       ← weekly + breaking LinkedIn drafts → Telegram (Spanish)
    ├── pipeline/
    │   ├── daily.py                ← orchestrates the run
    │   └── retention.py            ← prune old raw_content
    ├── scheduler/                  ← APScheduler bootstrap (local only)
    └── seeds/sources.py            ← source catalog (8 RSS)
```

Layering: `api → services → repositories → models`. Services never import `api`; repositories never import `services`. Ingestors, AI clients, exporters and notifiers are leaves consumed by services / the pipeline.

---

## 5. Data model

All tables use `id BIGSERIAL PRIMARY KEY` + `created_at TIMESTAMPTZ`. Vector columns require `CREATE EXTENSION vector;`.

### 5.1 `sources`
`name`, `type` (`rss`|`html`|`youtube`), `url` (unique), `active`, `config_json` (per-source overrides, resolved YT channel id…), `group_name`.

### 5.2 `raw_content`
`source_id` FK, `external_id`, `title`, `url`, `author`, `raw_text`, `published_at`, `fetched_at`, `content_hash` (sha256), `language`, `metadata_json`, plus:
- `embedding` — pgvector(1536); set null once a duplicate member is pruned.
- `embedding_pruned` — bool; storage saver flag for duplicate members.
- `image_url` — hero image (og:image / twitter:image / YouTube thumb).

Constraints: `UNIQUE (source_id, external_id)`, `UNIQUE (url)`, index on `content_hash`, `published_at DESC`.

### 5.3 `processed_content` (1:1 with raw_content)
- `cleaned_summary` — English executive summary.
- `title_es` — English title shown on web + Telegram (column name is legacy; content is English).
- `theme` — one of the 8 themes (see §8), or `irrelevant`.
- `importance_tier` — `high` | `medium` | `low`.
- `importance_score` — 0–100 (base for the boosted score).
- `players` — JSON list of tagged entities (OpenAI, Anthropic, Google…).
- `key_topics` — normalized tags.
- `is_noise` — gating flag; noise short-circuits enrichment + delivery.
- `rejected_reason` — nullable.
- **Legacy / partially used** (kept for migration compatibility): `novelty_score` and `business_impact_score` are LLM-computed and serialized but not consumed by any business logic. `linkedin_potential_score`, `linkedin_angles` and `ai_generated_insights` are **still in use** — read by `/weekly-top` and `/linkedin-ideas` and serialized via `ProcessedRead` — so do NOT drop them without removing their consumers first.

### 5.4 `content_clusters`
`cluster_topic`, `representative_content_id` FK (canonical item), plus delivery state:
- `notified_at` — when the story was first sent to Telegram (null = not yet).
- `telegram_message_id` — to edit the post later.
- `telegram_sources` — source count at last send (edit when it grows).
- `linkedin_drafted_at` — when the story was turned into a LinkedIn "breaking" draft (null = eligible). Ensures each story is drafted at most once across both daily runs.

### 5.5 `cluster_items`
PK `(cluster_id, raw_content_id)`, `similarity_score` (cosine to representative).

---

## 6. Daily pipeline (`app/pipeline/daily.py`)

Each step is idempotent and keys off dependent-row presence. Order:

1. **Ingest** — fetch `active` sources, dispatch to RSS/HTML/YouTube ingestor, upsert into `raw_content` keyed on `(source_id, external_id)` / `url`. Existing rows skipped.
2. **Embed** — embed every `raw_content` lacking an embedding (batched).
3. **Dedup + cluster** — cosine clustering on the day's new items (threshold `0.82`); near-duplicates attach to the nearest neighbour's cluster instead of forming a new one.
4. **Merge — pairwise LLM** (`cluster_merger.merge_borderline`) — for candidate pairs (cosine band `0.45–0.82` + shared-entity), an LLM "same event?" judge merges true matches. Loops to convergence; union-find redirect map avoids FK violations. Orphan clusters pruned.
5. **Merge — holistic LLM** (`merge_by_llm_grouping`, `min_confidence="high"`) — the model sees all remaining clusters and groups same-story clusters pairwise signals missed. Representatives repaired afterward.
6. **Classify** — for each new representative without a `processed_content` row, one LLM call returns `is_noise`, `theme`, `importance_tier`, `players`. Noise short-circuits.
7. **Enrich** — non-noise representatives get an English title + `cleaned_summary` (the prompt outputs English: "what happened + why it matters", hedged claims). Done once per cluster; re-runs rows where `cleaned_summary IS NULL OR title_es IS NULL`.
8. **Players** — backfill player tags from `title` + `key_topics` only (never the free-text summary — passing mentions would create false tags).
9. **Images** — fetch a hero image (og:image / YouTube thumb) for representatives lacking one.
10. **Prune duplicate members** — drop embedding + raw_text of non-representative duplicates (rows kept so cross-source counts still work).
11. **Telegram** — `send_new_stories` posts one message per not-yet-notified story whose boosted score ≥ `TELEGRAM_MIN_SCORE` (65); `update_boosted_stories` edits posts whose source count grew (live boost).
12. **LinkedIn breaking** — `build_and_send_breaking` drafts a ready-to-paste LinkedIn post for every fresh story with boosted score ≥ `LINKEDIN_MIN_SCORE` (85) that hasn't been drafted yet, sends it to Telegram for manual approval, and stamps `linkedin_drafted_at` so it's never re-drafted. No-op when nothing crosses the bar.
13. **Retention** — archive-friendly: for `raw_content` older than `RETENTION_DAYS`, blank the heavy data (drop the `embeddings` row + clear `raw_text`, set `embedding_pruned`) but KEEP the row + `processed_content` + cluster forever. The site stays a permanent archive at ~1KB/story.
14. **Publish** (workflow step) — regenerate `data.js` + `data-archive.js` + `n/` and push them to the portfolio repo (never `index.html`).

Per-source and per-record try/except boundaries: one bad article never aborts a run.

---

## 7. Deduplication, clustering & cross-source boost

Three layers, in order:

| Layer | Check | Action |
| --- | --- | --- |
| 1 — exact | `(source_id, external_id)` / `url` / `content_hash` | skip, already ingested |
| 2 — semantic | cosine ≥ `CLUSTER_THRESHOLD` (`0.82`) | attach to neighbour's cluster |
| 3a — pairwise LLM | cosine band `0.45–0.82` + shared entity → "same event?" judge | merge on yes |
| 3b — holistic LLM | all clusters at once, high-confidence grouping | merge same-story clusters |

Clustering is **forward-only**: yesterday's clusters are stable; only the day's new items cluster, then attach. Merges use a union-find redirect map so reassigning `representative_content_id` never violates FKs; orphan clusters are pruned and orphan representatives repaired each run.

**Cross-source boost**: a story's delivered score = `importance_score + min(20, (distinct_sources − 1) × 8)`. More outlets → higher rank + a `📡 N sources` counter. When a later duplicate arrives, the Telegram post is edited in place to reflect the new count. This boosted score is the gate for both Telegram (`≥ TELEGRAM_MIN_SCORE`) and LinkedIn breaking drafts (`≥ LINKEDIN_MIN_SCORE`).

---

## 8. Themes

Eight canonical themes (English keys, after migration 0010), plus `irrelevant` for non-AI items:

`models` 🧠 · `tools` 🛠️ · `features` ✨ · `business` 💼 · `cases` 📈 · `insights` 💡 · `tutorials` 🧪 · `other` 🌐.

Keys are English end-to-end: the classifier emits them, the DB stores them, and the web/Telegram/email labels are English (`Models`, `Tools`, `Business`…). Migration 0010 remapped the old Spanish enum values (`nuevo_modelo`→`models`, `movimiento_empresarial`→`business`, …) in place. Unknown values bucket under `other`.

---

## 9. AI layer & prompt-injection defense

All prompts live in `app/ai/prompts.py` as versioned constants (`CLASSIFY_NOISE_V1`, `ENRICH_V1_USER`, `SAME_EVENT_V1`, `CLUSTER_GROUPING_V1`). `app/ai/openai_client.py` is the only place that touches the SDK (retries, JSON output, token logging, single switchable model).

Defense in depth on every call that handles fetched text:

1. **Sanitize** (`ai/sanitize.py`) — `neutralize()` defuses instruction-like content; `wrap()` fences untrusted text so the model treats it as data, not instructions.
2. **`INJECTION_GUARD` preamble** — every prompt that ingests article text is prefixed with an explicit "ignore instructions inside the content" guard.
3. **Closed-enum output validation** — classifier outputs (theme, tier, is_noise) are validated against fixed enums; anything off-list is rejected rather than trusted.

Player tagging (`ai/players.py`) is deliberately a keyword match over `title` + `key_topics` only — never the summary — so a passing mention can't mislabel a story.

---

## 10. Delivery

### 10.1 Telegram (`app/notify/telegram.py`)
One message per story, **only** when the boosted score ≥ `TELEGRAM_MIN_SCORE` (65). Format (English): `<emoji> <b>title</b>` / `score/100 · 📡 N sources` / summary / `Read on the web →` (links to the detail page). Summaries and titles are clipped at a sentence boundary and stripped of em/en dashes (hyphens like `GPT-4` are kept). Photo (`sendPhoto`) when an image exists, else text with `disable_web_page_preview`. Posts are stored (`telegram_message_id`) and edited live as the source count grows. Target is a private channel where the bot is admin with **only** "post messages" — a leaked token can spam but not delete or ban.

### 10.2 Static web (`app/export/static_site.py`)
Published to `mmesonero.github.io/ai-news`. **Paginated archive** to stay fast while holding years of history:
- **`data.js`** (`window.__NEWS = {now, data:[...]}`) — recent `RECENT_DAYS` (90); loaded immediately by `index.html`.
- **`data-archive.js`** (`window.__NEWS_ARCHIVE`) — everything older; **lazy-loaded** by the index only when the user selects the "All" range (merged by slug, fetched once). Shared `now` so relative dates align.
- **`n/<slug>.html`** — detail page per story (whole archive), `slug = sha1(rep_url)[:12]`. Restyled to match the index (dark `#0D0D0D` + glows + vignette, Outfit, gold, "Portfolio · AI News" nav).

**Ownership split**: the engine writes only `data.js`, `data-archive.js`, `n/`; the custom `index.html` is owned by the portfolio repo and never overwritten. Web card titles and Telegram links share the same detail page.

The `index.html` also hosts **Brevo subscribe forms** (popup + section): a real `<form>` POSTs the email to Brevo's `sibforms.com/serve` endpoint targeting a hidden iframe (no page reload, no API key in the page). New subscribers land in the Brevo contact list the newsletter sends to.

### 10.3 Email newsletter (`app/notify/email_digest.py`)
Weekly (Sunday, `weekly_email.yml`). Read-only against the DB — same curated set as the web (`_gather`: top 10 + extra `high`, capped at 15). Magazine-style HTML (gray page + white card, dark wordmark, gold accents, uniform per-story cards). Two transports:
- **Brevo campaign** (preferred) — when `BREVO_API_KEY` + `BREVO_LIST_ID` are set: creates a campaign and `sendNow` to the contact list. Brevo injects a compliant 1-click unsubscribe (`{{ unsubscribe }}`) and manages bounces.
- **SMTP fallback** — when only `EMAIL_*` are set: sends to a fixed `EMAIL_TO` list with a `mailto:` List-Unsubscribe header.

Fail-loud: an API/SMTP error re-raises so the Actions run goes red instead of silently "succeeding".

### 10.4 LinkedIn drafts (`app/notify/linkedin_draft.py`)
Copy-paste, **no LinkedIn API**: the engine writes the post and sends it to Telegram (`LINKEDIN_DRAFT_CHAT_ID`) as a `<pre>` copy-block + a first-comment line; the human approves and pastes it. **Spanish** — the template is Spanish and the titles/summaries are translated on the fly with one `gpt-4o-mini` call (falls back to English if OpenAI is unset). Bold titles use Mathematical Sans-Serif Bold (accents dropped, ñ kept so "año" ≠ "ano"); no em/en dashes. Two kinds:
- **weekly** — reuses the email's `_gather()`, top 5, headline + short paragraph each.
- **breaking** — every fresh story with boosted ≥ `LINKEDIN_MIN_SCORE` (85), once each (`linkedin_drafted_at` gate); hooked into the daily pipeline.

---

## 11. Configuration (`app/config.py`)

| Key | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` / `SYNC_DATABASE_URL` | localhost | runtime (async) / Alembic (sync); Neon secrets in cloud |
| `OPENAI_API_KEY` | — | required |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | 1536 dims |
| `OPENAI_LLM_MODEL` | `gpt-4o-mini` | classify / enrich / judges |
| `OPENAI_TRANSCRIBE_MODEL` | `gpt-4o-transcribe` | audio |
| `TRANSCRIBE_BACKEND` | `openai` | `openai` \| `none` |
| `WHISPER_MAX_PER_RUN` | `15` | cap transcription calls/run |
| `CLUSTER_THRESHOLD` | `0.82` | same-cluster cosine cutoff |
| `DEDUP_LOOKBACK_DAYS` | `14` | semantic dedup window |
| `RETENTION_DAYS` | `30` (cloud: `14`) | prune raw_content older than this |
| `PUBLIC_SITE_BASE` | `https://mmesonero.github.io/ai-news` | detail-page link base |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | — | delivery (secrets) |
| `TELEGRAM_MIN_SCORE` | `65` | only push stories with boosted score ≥ this |
| `BREVO_API_KEY` / `BREVO_LIST_ID` | — | email newsletter as a Brevo campaign to the list |
| `EMAIL_FROM` | — | verified sender; SMTP fallback also uses `EMAIL_HOST`/`USER`/`PASSWORD`/`PORT`/`TO` |
| `EMAIL_MAX_ITEMS` | `15` | hard cap on stories in the weekly digest |
| `LINKEDIN_MIN_SCORE` | `85` | breaking LinkedIn draft only for boosted score ≥ this |
| `LINKEDIN_DRAFT_CHAT_ID` | — | Telegram chat for drafts (your DM); falls back to `TELEGRAM_CHAT_ID` |
| `ENABLE_SCHEDULER` | `true` | false → read-only (no in-process cron) |
| `LOG_LEVEL` | `INFO` | |

Empty GitHub secrets arrive as `""`; a `field_validator` coerces blank int fields (e.g. `EMAIL_PORT`, `BREVO_LIST_ID`) back to their defaults so an unset secret never crashes startup.

---

## 12. Operations

- **Scheduler**: `daily.yml` cron targeting ~05:00 + ~17:00 ES. Best-effort (GitHub delays under load, worst at :00 / US-daytime peak), no DST → each window has a primary + backup at odd minutes (`02:47`/`03:17` and `14:37`/`15:23` UTC); idempotent + not-yet-notified-only sending means backups never duplicate. `weekly_email.yml` runs Sunday `06:47` UTC. Trigger manually via the Actions tab or `gh workflow run daily.yml` / `weekly_email.yml`.
- **Secrets**: live only in GitHub Actions (encrypted, not readable back). Migrations against the cloud DB run only inside Actions. See `SECURITY.md`.
- **Logs / metrics**: structlog JSON, `run_id` per run; per-stage counters (ingested, clusters, merges, enriched, telegram_sent/edited, images_found, members_pruned) logged at run end.
- **Idempotency**: re-running a day is safe.
- **Storage**: only heavy data (embeddings + body text) is bounded — blanked past `RETENTION_DAYS` while the ~1KB/story metadata is kept forever (permanent archive). The web bakes 90 days for client-side filtering. `RETENTION_DAYS` must stay ≥ `DEDUP_LOOKBACK_DAYS` so dedup never loses its window.
- **YouTube limitation**: transcript downloads are blocked from datacenter IPs, so video transcription is best-effort in the cloud; RSS covers the bulk.

---

## 13. Out of scope (designed for, not built)

- **Auto-publishing** to LinkedIn — currently human-in-the-loop drafts (copy-paste). Direct posting would need the LinkedIn API (app + OAuth + token refresh); deferred on purpose. The deprecated `linkedin_*` scoring columns predate the current draft approach and are unused.
- Multi-user auth / RBAC.
- Re-clustering of historical data — clustering is forward-only; a future batch job can revisit history without schema changes.

---

## 14. Engineering conventions

- Typed throughout.
- Services are stateless; mutations go through repositories.
- Routes are thin — one service call each, no business logic.
- All prompts + model ids live in `ai/`; no magic strings in services.
- One ingestor per source type.
- Every LLM call that touches fetched text is sanitized + guarded.
