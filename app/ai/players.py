"""Detect the top AI 'players' (companies) a news item is about.

Keyword/alias matching over a curated vocabulary — deterministic and free
(no LLM). Maps each company's products/people to the company, e.g. GPT -> OpenAI,
Claude/Fable/Mythos -> Anthropic, Gemini/DeepMind -> Google, Llama -> Meta.

Used to tag current + future items (run in the pipeline backfill).
"""
from __future__ import annotations

import re

# Canonical player -> list of alias terms (lowercase, word-boundary matched).
PLAYER_ALIASES: dict[str, list[str]] = {
    "OpenAI": ["openai", "chatgpt", "gpt-", "gpt ", "gpt5", "gpt4", "sora", "dall-e", "dall·e", "sam altman", "codex"],
    "Anthropic": ["anthropic", "claude", "opus", "sonnet", "haiku", "fable", "mythos", "dario amodei"],
    "Google": ["google", "deepmind", "gemini", "alphabet", "demis hassabis", "gemma", "waymo", "google i/o"],
    "Meta": ["meta ", "meta.", "meta,", "llama", "zuckerberg", " fair ", "facebook", "instagram"],
    "NVIDIA": ["nvidia", "jensen huang", "blackwell", "nemotron", "cuda"],
    "Microsoft": ["microsoft", "copilot", "azure", "satya nadella", "suleyman"],
    "Amazon": ["amazon", "aws", "bedrock", "andy jassy", "trainium", "anthropic-aws"],
    "Apple": ["apple", "siri", "apple intelligence", "tim cook"],
    "xAI": ["xai", "grok"],
    "Mistral": ["mistral", "le chat"],
    "Cohere": ["cohere"],
    "Perplexity": ["perplexity"],
    "Hugging Face": ["hugging face", "huggingface"],
    "DeepSeek": ["deepseek"],
    "SpaceX": ["spacex"],
    "Tesla": ["tesla"],
}

# Pre-compile word-boundary patterns per alias (alias may contain spaces/hyphens).
# Leading boundary always; trailing boundary ONLY when the alias ends in an
# alphanumeric char. Aliases that already encode their right edge with a trailing
# space/hyphen/punct ("gpt-", "gpt ", "meta ", " fair ") must keep matching the
# following token (e.g. "gpt-" → "gpt-4"), so they get no extra trailing boundary.
# Without the trailing boundary, prefix collisions produced false tags
# ("coherent"→Cohere, "applesauce"→Apple, "grokking"→xAI, "codexample"→OpenAI).
def _compile_alias(alias: str) -> re.Pattern:
    trailing = r"(?![a-z0-9])" if alias[-1:].isalnum() else r""
    return re.compile(r"(?<![a-z0-9])" + re.escape(alias) + trailing, re.IGNORECASE)


_COMPILED: dict[str, list[re.Pattern]] = {
    player: [_compile_alias(a) for a in aliases]
    for player, aliases in PLAYER_ALIASES.items()
}


def detect_players(text: str | None) -> list[str]:
    """Return the canonical players mentioned in `text`, in PLAYER_ALIASES order."""
    if not text:
        return []
    low = " " + text.lower() + " "
    found: list[str] = []
    for player, patterns in _COMPILED.items():
        if any(p.search(low) for p in patterns):
            found.append(player)
    return found


def players_for(title: str | None, key_topics: list[str] | None) -> list[str]:
    """Canonical way to tag a news item with its players.

    IMPORTANT — fidelity rule (do not regress): tag ONLY from the title and the
    classifier's key_topics (the entities the story is actually ABOUT). NEVER feed
    the free-text summary here: summaries carry passing mentions like
    "competitors such as OpenAI and Anthropic", which produced false player tags.
    This function deliberately takes no summary parameter so that can't happen again.
    """
    parts = [title or ""]
    parts.extend(key_topics or [])
    return detect_players(" \n ".join(parts))
