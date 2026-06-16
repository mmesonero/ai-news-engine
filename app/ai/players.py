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
_COMPILED: dict[str, list[re.Pattern]] = {
    player: [re.compile(r"(?<![a-z0-9])" + re.escape(a) + r"", re.IGNORECASE) for a in aliases]
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
