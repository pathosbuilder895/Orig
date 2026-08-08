"""
tests/context/test_genre_dispatch.py — GENRE_RESOLVER_V2 mode dispatch.

Task 3 of docs/superpowers/plans/2026-08-08-genre-resolution-v2.md.

The byte-identity test below is the property that makes the default safe by
inspection rather than by hope: with the flag off, resolve_genre must return
exactly what it returned before this feature existed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from original.constants import GENRE_UNKNOWN
from original.context.resolvers import _resolve_genre_v1, resolve_genre

_SAMPLES = sorted(Path("validation/corpus").glob("*.txt"))[:30]


@pytest.fixture(autouse=True)
def _clear_mode(monkeypatch):
    monkeypatch.delenv("GENRE_RESOLVER_V2", raising=False)


class TestOffIsByteIdentical:
    def test_off_matches_v1_exactly_on_every_sample(self, monkeypatch):
        monkeypatch.setenv("GENRE_RESOLVER_V2", "off")
        for path in _SAMPLES:
            text = path.read_text(errors="ignore")
            assert resolve_genre(text) == _resolve_genre_v1(text), path.name

    def test_unset_behaves_as_off(self):
        text = _SAMPLES[0].read_text(errors="ignore")
        assert resolve_genre(text) == _resolve_genre_v1(text)

    def test_off_carries_no_shadow_keys(self, monkeypatch):
        monkeypatch.setenv("GENRE_RESOLVER_V2", "off")
        out = resolve_genre("The matter is settled beyond dispute. " * 30)
        assert "shadow_primary" not in out
        assert set(out) == {"primary", "confidence", "secondary"}


class TestShadowIsInert:
    def test_primary_and_confidence_still_come_from_v1(self, monkeypatch):
        monkeypatch.setenv("GENRE_RESOLVER_V2", "shadow")
        for path in _SAMPLES:
            text = path.read_text(errors="ignore")
            v1 = _resolve_genre_v1(text)
            out = resolve_genre(text)
            assert out["primary"] == v1["primary"], path.name
            assert out["confidence"] == v1["confidence"], path.name

    def test_shadow_verdict_rides_along(self, monkeypatch):
        monkeypatch.setenv("GENRE_RESOLVER_V2", "shadow")
        out = resolve_genre("The matter is settled beyond dispute. " * 30)
        assert out["shadow_primary"] == GENRE_UNKNOWN
        assert out["shadow_confidence"] == 0.0

    def test_shadow_emits_one_log_line_per_call(self, monkeypatch, caplog):
        """students_baseline.py persists only `primary`, so the label-shift
        distribution has to be recoverable from production logs."""
        monkeypatch.setenv("GENRE_RESOLVER_V2", "shadow")
        with caplog.at_level("INFO", logger="original.context.resolvers"):
            resolve_genre("The matter is settled beyond dispute. " * 30)
        assert any("genre_shadow" in r.getMessage() for r in caplog.records)


class TestOnUsesV2:
    def test_on_returns_the_v2_verdict(self, monkeypatch):
        monkeypatch.setenv("GENRE_RESOLVER_V2", "on")
        from original.context import genre_v2

        text = "The matter is settled beyond dispute. " * 30
        assert resolve_genre(text) == genre_v2.resolve(text)

    def test_on_abstains_where_v1_claimed_correspondence(self, monkeypatch):
        # Long sentences, no citations: v1 falls through every rule to its
        # terminal else. A SHORT repeated sentence would hit rule 5
        # (blog_post) instead and would not exercise the fallback at all.
        text = (
            "The argument proceeds by considering the nature of the good, and "
            "whether it can be known apart from its particular instances. "
            "Those who deny this must account for the evident agreement of "
            "ordinary language on the matter, which is not easily set aside. "
        ) * 6
        monkeypatch.setenv("GENRE_RESOLVER_V2", "off")
        assert resolve_genre(text)["primary"] == "correspondence"
        monkeypatch.setenv("GENRE_RESOLVER_V2", "on")
        assert resolve_genre(text)["primary"] == GENRE_UNKNOWN

    def test_on_carries_no_shadow_keys(self, monkeypatch):
        monkeypatch.setenv("GENRE_RESOLVER_V2", "on")
        out = resolve_genre("Prose. " * 40)
        assert set(out) == {"primary", "confidence", "secondary"}
