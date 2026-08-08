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


class TestMeasuredBaseline:
    def test_v2_abstains_far_more_than_v1_on_the_seminary_corpus(self, mod, paths):
        """The headline finding, pinned so a regression in either resolver
        shows up here: v1 claims a label for everything (86% of it the
        terminal else), v2 claims one only where a rule genuinely fires."""
        from original.constants import GENRE_UNKNOWN

        out = mod.summarise(paths)
        assert GENRE_UNKNOWN not in out["v1_distribution"]
        assert out["abstention_rate"] > 0.5
