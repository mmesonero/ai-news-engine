from __future__ import annotations

from app.services.enrichment_service import _safe_int


def test_safe_int_clamps_to_0_100() -> None:
    assert _safe_int(150) == 100
    assert _safe_int(-3) == 0
    assert _safe_int(42) == 42


def test_safe_int_handles_none_and_garbage() -> None:
    assert _safe_int(None) is None
    assert _safe_int("not-a-number") is None
    assert _safe_int({"x": 1}) is None


def test_safe_int_accepts_numeric_strings() -> None:
    assert _safe_int("75") == 75
