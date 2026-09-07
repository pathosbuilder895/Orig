"""
tests/test_tier4.py — degenerate-input branch coverage for
`original/features/tier4.py` (Tier 4 — Character & Punctuation Fingerprint).

Covers `_shannon_entropy`'s zero-total arm (unit-tested directly — every
public caller already guards against an empty Counter before calling it,
so the arm is otherwise unreachable through the extractors).
"""

from __future__ import annotations

from collections import Counter

from original.features import tier4


def test_shannon_entropy_empty_counter_returns_zero():
    assert tier4._shannon_entropy(Counter()) == 0.0


def test_shannon_entropy_nonzero_counter_returns_positive_entropy():
    result = tier4._shannon_entropy(Counter({"a": 3, "b": 1}))
    assert result > 0.0
