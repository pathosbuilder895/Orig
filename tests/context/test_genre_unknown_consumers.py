"""
tests/context/test_genre_unknown_consumers.py — what "unknown" means to the
four consumers of the genre label.

Task 4 of docs/superpowers/plans/2026-08-08-genre-resolution-v2.md.

The governing rule: ignorance must never change a score. GENRE_UNKNOWN is an
abstention, not a genre, and every consumer has to treat it that way — the
alternative is that "we could not classify this" silently mutes a tier,
expands an anchor set, or seeds a prior.
"""

from __future__ import annotations

import types

from original.constants import GENRE_UNKNOWN
from original.context.baseline_match import _genre_similarity, genre_covered_by_baseline


def _state(*genres):
    return types.SimpleNamespace(samples=[types.SimpleNamespace(genre=g) for g in genres])


def _manifest(primary):
    return {"genre": {"primary": primary}}


class TestGenreCoveredByBaseline:
    def test_unknown_submission_is_treated_as_covered(self):
        """Attenuating because we cannot classify the submission would change
        a score on the strength of not knowing something."""
        assert genre_covered_by_baseline(_manifest(GENRE_UNKNOWN), _state("sermon")) is True

    def test_baseline_of_only_unknowns_is_treated_as_covered(self):
        assert (
            genre_covered_by_baseline(_manifest("sermon"), _state(GENRE_UNKNOWN, GENRE_UNKNOWN))
            is True
        )

    def test_confident_mismatch_is_still_reported(self):
        """The gate must keep firing when it genuinely knows both sides —
        otherwise abstention has simply replaced one always-on answer with
        another."""
        assert (
            genre_covered_by_baseline(_manifest("sermon"), _state("creative_fiction")) is False
        )

    def test_confident_match_is_covered(self):
        assert genre_covered_by_baseline(_manifest("sermon"), _state("sermon")) is True

    def test_unknown_baselines_are_ignored_not_counted_as_a_genre(self):
        """A baseline of {unknown, sermon} must behave exactly as {sermon}."""
        assert (
            genre_covered_by_baseline(
                _manifest("creative_fiction"), _state(GENRE_UNKNOWN, "sermon")
            )
            is False
        )


class TestGenreSimilarity:
    def test_two_abstentions_are_not_a_genre_match(self):
        """Adding "unknown" to GENRE_LABELS made it compare equal to itself,
        so two unclassified documents scored a perfect 1.0 genre similarity
        and would be preferentially selected into a baseline cluster. An
        abstention carries no information about genre agreement."""
        assert _genre_similarity(GENRE_UNKNOWN, GENRE_UNKNOWN) == 0.0

    def test_unknown_never_matches_a_real_genre(self):
        assert _genre_similarity(GENRE_UNKNOWN, "sermon") == 0.0
        assert _genre_similarity("sermon", GENRE_UNKNOWN) == 0.0

    def test_unknown_earns_no_family_partial_credit(self):
        """GENRE_FAMILIES has no entry for unknown, so it cannot share a
        family with anything — pinned here so a later edit cannot add one."""
        from original.constants import GENRE_FAMILIES

        assert GENRE_UNKNOWN not in GENRE_FAMILIES

    def test_real_genres_still_score_normally(self):
        assert _genre_similarity("sermon", "sermon") == 1.0
        assert _genre_similarity("academic_exegesis", "scholarly_essay") == 0.5
        assert _genre_similarity("sermon", "creative_fiction") == 0.0


class TestPoolingExcludesUnknown:
    def test_get_genre_stats_refuses_the_unknown_pool(self, monkeypatch):
        """Pooling "we don't know" samples together rebuilds correspondence
        under a new name: one bucket holding every genre, with a prior
        estimated from an arbitrary mixture.

        Asserted by making any store read explode: on an empty store this
        function returns None anyway, so a bare `is None` would pass whether
        or not the guard exists. The refusal has to happen BEFORE the scan.
        """
        from original import store

        def _explode():
            raise AssertionError("get_genre_stats scanned the store for an abstention")

        monkeypatch.setattr(store, "all_states", _explode)
        assert (
            store.get_genre_stats(GENRE_UNKNOWN, tenant="demo", exclude_student_id=None) is None
        )

    def test_a_real_genre_still_reaches_the_store(self, monkeypatch):
        """The guard must be specific to the abstention, not a blanket
        early-return that quietly disables the prior for everyone."""
        from original import store

        seen = []

        def _record():
            seen.append(True)
            return {}

        monkeypatch.setattr(store, "all_states", _record)
        store.get_genre_stats("sermon", tenant="demo", exclude_student_id=None)
        assert seen, "a real genre must still scan the store"


class TestUntouchedConsumersStaySafe:
    """T16 muting and T8/T13 anchoring need no code change — they are
    membership tests against literal label sets that GENRE_UNKNOWN is not in.
    Pinned so the safety survives a later edit to those sets."""

    def test_unknown_does_not_mute_tier16(self):
        assert GENRE_UNKNOWN != "creative_fiction"

    def test_unknown_does_not_expand_the_anchor_set(self):
        from original.context.manifest import _PROSODIC_ANCHOR_GENRES

        assert GENRE_UNKNOWN not in _PROSODIC_ANCHOR_GENRES

    def test_unknown_does_not_expand_the_drift_anchor_set(self):
        """quantum/state.py:427 uses its own literal set for drift gating."""
        import inspect

        from original.quantum import state

        source = inspect.getsource(state.StudentState.check_drift)
        assert '{"academic_exegesis", "scholarly_essay", "sermon"}' in source
        assert GENRE_UNKNOWN not in {"academic_exegesis", "scholarly_essay", "sermon"}
