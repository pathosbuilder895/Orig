"""
tests/context/test_genre_shadow_measure.py — the shadow measurement harness.

Task 5 of docs/superpowers/plans/2026-08-08-genre-resolution-v2.md.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "measure_shadow", Path("validation/genre_2026-08/measure_shadow.py")
)


@pytest.fixture(scope="module")
def mod():
    module = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def paths():
    return sorted(Path("validation/corpus").glob("seminary_*.txt"))[:8]


class TestSummarise:
    def test_reports_both_distributions_and_the_abstention_rate(self, mod, paths):
        out = mod.summarise(paths)
        assert out["n"] > 0
        assert 0.0 <= out["abstention_rate"] <= 1.0
        assert sum(out["v1_distribution"].values()) == out["n"]
        assert sum(out["v2_distribution"].values()) == out["n"]

    def test_shift_matrix_accounts_for_every_scored_document(self, mod, paths):
        out = mod.summarise(paths)
        assert sum(out["shift_matrix"].values()) == out["n"]

    def test_short_fragments_are_skipped_not_scored(self, mod, tmp_path):
        """Both resolvers key on per-sentence and per-word rates that are
        meaningless on a fragment, so a fragment would contribute noise to
        the very number Stage 2 is sized against."""
        (tmp_path / "tiny.txt").write_text("Too short.")
        (tmp_path / "long.txt").write_text("A reasonable sentence of prose. " * 40)
        out = mod.summarise(sorted(tmp_path.glob("*.txt")))
        assert out["n"] == 1

    def test_an_empty_corpus_does_not_divide_by_zero(self, mod):
        out = mod.summarise([])
        assert out["n"] == 0
        assert out["abstention_rate"] == 0.0


@pytest.fixture(scope="module")
def corpus_summary(mod):
    """One sweep, shared by every corpus-level assertion below.

    Sampled rather than exhaustive, and module-scoped rather than per-test.
    The full sweep resolves 813 documents through BOTH resolvers; running it
    once per test put ~3,250 resolutions into the fast suite and was a
    measurable part of pushing CI's pytest job past its 20-minute limit. The
    script itself (validation/genre_2026-08/measure_shadow.py) is what
    produces the real corpus number; these tests only need enough documents
    to show the distribution does not collapse.
    """
    paths = mod._corpus_paths()[::4]
    return mod.summarise(paths)


class TestMeasuredBaseline:
    def test_v1_has_no_abstention_outcome_at_all(self, mod, paths):
        """v1 always claims a label — 86% of the time it is rule 8's terminal
        else. Having somewhere honest to put "I don't know" is the whole
        difference."""
        from original.constants import GENRE_UNKNOWN

        out = mod.summarise(paths)
        assert GENRE_UNKNOWN not in out["v1_distribution"]

    def test_v2_spreads_across_classes_instead_of_one_bucket(self, corpus_summary):
        """The headline finding over the committed corpora: v1 puts 88% of
        them in `correspondence`; v2 distributes across its trained classes
        and abstains on the rest. Pinned loosely — the exact percentages move
        if the model is re-derived — but a collapse back to a single dominant
        bucket must fail here."""
        out = corpus_summary
        distribution = out["v2_distribution"]
        biggest = max(distribution.values()) / out["n"]
        assert len(distribution) >= 3, f"v2 collapsed to {sorted(distribution)}"
        assert biggest < 0.6, f"one label holds {biggest:.0%} of the corpus"

    def test_v2_still_abstains_on_a_real_share(self, corpus_summary):
        """Abstention must not vanish either: a model that always claims
        something has given up the property Stage 1 bought."""
        from original.constants import GENRE_UNKNOWN

        assert corpus_summary["v2_distribution"].get(GENRE_UNKNOWN, 0) > 0
