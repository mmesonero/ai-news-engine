from __future__ import annotations

from app.services.ingestion_service import _hash, _normalize_for_hash


def test_normalize_collapses_whitespace_and_lowercases() -> None:
    assert _normalize_for_hash("  Hello   WORLD\n\nfoo  ") == "hello world foo"


def test_hash_is_stable_for_equivalent_inputs() -> None:
    a = _hash("Title", "Body  with   spacing")
    b = _hash("title", "body with spacing")
    assert a == b


def test_hash_differs_when_body_differs() -> None:
    a = _hash("Title", "Body one")
    b = _hash("Title", "Body two")
    assert a != b


def test_hash_differs_when_title_differs() -> None:
    a = _hash("Title A", "Same body")
    b = _hash("Title B", "Same body")
    assert a != b
