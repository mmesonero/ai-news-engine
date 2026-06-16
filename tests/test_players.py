"""Player tagging: correctness + the fidelity rule that must not regress."""
from __future__ import annotations

import inspect

from app.ai.players import detect_players, players_for


def test_alias_mapping_to_canonical_player():
    assert detect_players("OpenAI lanza GPT-5.5") == ["OpenAI"]
    assert detect_players("Anthropic releases Claude Fable 5") == ["Anthropic"]
    assert detect_players("Google presenta Gemini 3") == ["Google"]
    assert detect_players("Meta libera Llama 4") == ["Meta"]
    assert detect_players("NVIDIA presenta Nemotron 3") == ["NVIDIA"]


def test_no_match_returns_empty():
    assert detect_players("Una receta de tarta de queso") == []
    assert detect_players(None) == []


def test_players_for_uses_title_and_topics():
    assert players_for("Mistral is raising €3B", ["mistral", "funding"]) == ["Mistral"]
    # company present only in the classifier tags still counts (it's central)
    assert "OpenAI" in players_for("LSEG scaling trusted AI", ["lseg", "openai"])


def test_players_for_ignores_passing_mentions_by_construction():
    # The €3B Mistral story's SUMMARY says "competitors like OpenAI and Anthropic".
    # players_for must NOT see the summary, so OpenAI/Anthropic must not be tagged
    # when they appear only there — only Mistral (title) is tagged.
    title = "Mistral is rumored to be raising €3B at €20B valuation"
    key_topics = ["mistral", "funding", "europe"]  # summary text is intentionally absent
    assert players_for(title, key_topics) == ["Mistral"]


def test_players_for_signature_has_no_summary_param():
    # Structural guard: if someone adds a summary/body param, this fails — forcing
    # them to re-read the fidelity rule before reintroducing the old bug.
    params = set(inspect.signature(players_for).parameters)
    assert params == {"title", "key_topics"}
