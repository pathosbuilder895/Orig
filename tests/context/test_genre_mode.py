"""
tests/context/test_genre_mode.py — GENRE_RESOLVER_V2 parsing and the
abstention label constant.

Task 1 of docs/superpowers/plans/2026-08-08-genre-resolution-v2.md.
"""
from __future__ import annotations

import pytest

from original.context.genre_mode import resolve_mode


class TestGenreMode:
    def test_defaults_to_off_when_unset(self, monkeypatch):
        monkeypatch.delenv("GENRE_RESOLVER_V2", raising=False)
        assert resolve_mode() == "off"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("off", "off"),
            ("shadow", "shadow"),
            ("on", "on"),
            ("1", "on"),
            ("ON", "on"),
            ("  shadow  ", "shadow"),
        ],
    )
    def test_recognised_values(self, monkeypatch, raw, expected):
        monkeypatch.setenv("GENRE_RESOLVER_V2", raw)
        assert resolve_mode() == expected

    @pytest.mark.parametrize("raw", ["", "yes", "true", "2", "garbage", "0"])
    def test_unrecognised_falls_back_to_off(self, monkeypatch, raw):
        """An unparseable value must never silently enable a score-changing
        path — the same rule quantum/scoring.py's _parse_topic_inflation_mode
        enforces for TOPIC_VARIANCE_INFLATION."""
        monkeypatch.setenv("GENRE_RESOLVER_V2", raw)
        assert resolve_mode() == "off"


class TestGenreConstants:
    def test_unknown_is_a_label(self):
        from original.constants import GENRE_LABELS, GENRE_UNKNOWN

        assert GENRE_UNKNOWN == "unknown"
        assert GENRE_UNKNOWN in GENRE_LABELS

    def test_the_original_eight_labels_are_untouched(self):
        """Persisted BaselineSample.genre values and get_genre_stats pooling
        keys depend on these exact strings in this exact order. New labels
        are APPENDED, never substituted or reordered — that is what keeps a
        stored `personal_essay` readable after v2 stopped emitting it, and
        what makes every taxonomy change migration-free.

        The COUNT is deliberately not pinned: additions are expected (this
        has grown twice, for `unknown` and `narrative_prose`). Pinning the
        length would fail on every legitimate addition while catching none
        of the dangerous edits, which are substitution and reordering."""
        from original.constants import GENRE_LABELS

        assert GENRE_LABELS[:8] == [
            "academic_exegesis",
            "scholarly_essay",
            "sermon",
            "personal_essay",
            "creative_fiction",
            "correspondence",
            "blog_post",
            "structured_template",
        ]

    def test_superseded_labels_survive_for_stored_values(self):
        """v2 never emits these, but baselines ingested under v1 carry them
        and must stay poolable and comparable."""
        from original.constants import GENRE_LABELS

        for label in ("creative_fiction", "personal_essay", "correspondence"):
            assert label in GENRE_LABELS

    def test_narrative_prose_is_appended_not_inserted(self):
        from original.constants import GENRE_LABELS, GENRE_NARRATIVE_PROSE

        assert GENRE_NARRATIVE_PROSE in GENRE_LABELS
        assert GENRE_LABELS.index(GENRE_NARRATIVE_PROSE) >= 8

    def test_confidence_floor_is_a_real_probability(self):
        from original.constants import GENRE_CONFIDENCE_MIN

        assert 0.0 < GENRE_CONFIDENCE_MIN < 1.0
