"""Cheap keyword-based topic filter applied at ingestion time.

Goal: drop obviously off-topic items BEFORE we waste embeddings + classifier tokens
on them. The noise classifier still runs on what survives — this is a coarse
first-pass for broad sources like Hackaday, PopSci, or generalist tech outlets.

We match against TITLE + first ~500 chars of body, lowercased.
A single hit on any keyword passes the item.
"""
from __future__ import annotations

import re

# AI / ML / agents / labs / models — broad coverage.
_AI_PATTERNS = [
    r"\bai\b", r"\ba\.i\.", r"artificial intelligen", r"machine learn", r"\bml\b",
    r"\bllm[s]?\b", r"large language model", r"foundation model", r"frontier model",
    r"generative", r"genai", r"\bgen ai\b",
    r"neural net", r"deep learn", r"transformer", r"diffusion model",
    r"chat ?gpt", r"\bgpt[- ]?\d", r"claude", r"gemini", r"mistral", r"llama",
    r"openai", r"anthropic", r"deepmind", r"hugging ?face", r"cohere", r"perplexity",
    r"\bagent[s]?\b", r"agentic", r"copilot", r"chatbot",
    r"\brag\b", r"retrieval[- ]augmented",
    r"prompt engineer", r"fine[- ]tun", r"embedding[s]?", r"vector (database|db|search)",
    r"\bnlp\b", r"speech model", r"text[- ]to[- ](image|video|speech)",
    r"\bnvidia\b", r"\btpu[s]?\b", r"\bgpu cluster",
    r"\bsuperintelligen", r"\bagi\b",
]

# Startup / VC / corporate strategy / regulation — business angle.
_BIZ_PATTERNS = [
    r"\bstartup[s]?\b", r"\bunicorn[s]?\b",
    r"series [a-h]\b", r"seed round", r"pre[- ]?seed", r"funding round",
    r"raise[ds]? \$[\d.]+", r"raises \$", r"\bipo\b", r"acqui[- ]?(sition|hire)",
    r"valuation", r"valued at \$", r"down round",
    r"venture capital", r"\bvc\b", r"\bvcs\b", r"\blp[s]?\b",
    r"antitrust", r"regulator", r"\bdoj\b", r"\beu\b act", r"\bsec\b filing",
    r"merger", r"layoff", r"restructur",
    r"chief executive", r"\bceo\b", r"\bcto\b", r"\bcfo\b",
    r"market cap", r"earnings", r"quarterly results", r"\bq[1-4] (results|earnings)",
    r"data center", r"cloud spend", r"compute spend",
    # named big tech (covers corporate moves)
    r"microsoft", r"google", r"alphabet", r"meta\b", r"amazon", r"\baws\b",
    r"\bapple\b", r"tesla", r"\bxai\b", r"\bx\.ai\b", r"\boracle\b",
    r"databricks", r"snowflake", r"salesforce",
]

_COMBINED = re.compile("|".join(_AI_PATTERNS + _BIZ_PATTERNS), re.IGNORECASE)

# Promo / CTA / shorts patterns — content that's marketing, not information.
# Designed for both Spanish and English. Specific enough not to false-positive
# on legitimate articles ("código abierto", "guía de uso" — fine; "te dejo la
# guía fijada en comentarios" — promo).
_PROMO_PATTERNS = [
    # Pointer emojis at the start of titles (very common in promo shorts)
    r"^[\s]*[👉👇👆🔥💥⚡🎁🎉][\s🏻🏼🏽🏾🏿]*",
    # Spanish CTA phrases
    r"te\s+dejo\s+(el|la|los|las)\s+(prompt|gu[íi]a|link|enlace|c[oó]digo|curso|plantilla|tutorial)",
    r"fijad[oa]s?\s+en\s+(los|las)?\s*comentarios",
    r"link\s+en\s+(la\s+)?bio",
    r"enlace\s+en\s+(la\s+)?bio",
    r"link\s+abajo",
    r"descripci[oó]n\s+(del\s+v[ií]deo|tienes|encontrar[aá]s)",
    r"c[oó]digo\s+(promo(cional)?|descuento|exclusivo)",
    r"cup[oó]n",
    r"suscr[íi]bete",
    r"s[íi]gueme|s[íi]guenos",
    r"d[áa]le?\s+(like|me\s+gusta)",
    r"comparte\s+(si|este)",
    r"descarga\s+gratis",
    r"reg[áa]lame?\s+un",
    r"sorteo",
    r"af[íi]liate",
    r"af[íi]liado",
    # English CTA phrases
    r"link\s+in\s+(my\s+)?bio",
    r"link\s+below",
    r"check\s+(the\s+)?(description|link\s+below|pinned\s+comment)",
    r"pinned\s+(comment|in\s+the\s+comments)",
    r"use\s+(my\s+)?(code|coupon|promo)\b",
    r"smash\s+(the\s+)?like",
    r"subscribe\s+to\s+(my|the)",
    r"sponsored\s+by",
    r"\bgiveaway\b",
    r"\baffiliate\b",
    # Generic listicle / clickbait that's almost always promo
    r"top\s+\d+\s+(best|free)\s+ai\s+tools?",
    r"\d+\s+ai\s+tools?\s+you('re|\s+are)\s+not\s+using",
    r"these\s+\d+\s+ai\s+tools?",
    # Free course / day-N / challenge patterns
    r"\bcurso\s+gratis\b", r"\bcurso\s+gratuito\b",
    r"\bd[íi]a\s+\d+(\s|$|\s*[-—|]\s*)",
    r"\breto\s+\d+\s+d[íi]as\b", r"\b\d+[- ]day\s+challenge\b",
    r"\bmasterclass\s+gratis\b",
]
_PROMO_RE = re.compile("|".join(_PROMO_PATTERNS), re.IGNORECASE)

# Robot / fire / lightning emoji-spam ("🤖 X 🤖", "🔥🔥🔥 ..."), or 2+ hashtags.
_EMOJI_HEAVY_RE = re.compile(
    r"(?:[☀-➿✀-➿\U0001F300-\U0001FAFF][\s]*){2,}"
)
_HASHTAG_RE = re.compile(r"(?:#\w+\s*){2,}")

_MAX_BODY_PEEK = 500


def matches_topic(title: str, body: str | None = None) -> bool:
    """Returns True if the item plausibly belongs to AI / startup / corporate / business tech."""
    haystack = (title or "")
    if body:
        haystack += "\n" + body[:_MAX_BODY_PEEK]
    return bool(_COMBINED.search(haystack))


def is_promo(title: str, body: str | None = None) -> bool:
    """Returns True if the item is promotional / CTA spam.

    Catches:
      - Explicit CTA phrases ("te dejo la guía", "link in bio", "use code XYZ")
      - Free course / challenge / day-N patterns
      - Title heavy with emojis (2+ adjacent) — shorts hallmark
      - Title with 2+ hashtags (always promotional)
    """
    haystack = (title or "")
    if body:
        haystack += "\n" + body[:_MAX_BODY_PEEK]
    if _PROMO_RE.search(haystack):
        return True
    # Emoji/hashtag spam checked on title only — body may legitimately contain emoji.
    t = title or ""
    if _EMOJI_HEAVY_RE.search(t) or _HASHTAG_RE.search(t):
        return True
    return False
