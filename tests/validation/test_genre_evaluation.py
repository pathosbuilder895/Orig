"""
tests/validation/test_genre_evaluation.py — hold-out evaluation and the
author-shuffled control.

Task 12 of docs/superpowers/plans/2026-08-08-genre-resolution-v2.md.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "genre_evaluate", Path("validation/genre_2026-08/evaluate.py")
)


@pytest.fixture(scope="module")
def mod():
    module = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def holdout(mod):
    return mod.evaluate_holdout()


class TestHoldout:
    def test_reports_per_class_precision_and_abstention(self, holdout):
        assert holdout["n_holdout"] > 0
        assert 0.0 <= holdout["abstention_rate"] <= 1.0
        assert holdout["min_precision"] == min(holdout["per_class_precision"].values())

    def test_precision_is_over_claimed_labels_only(self, holdout):
        """Abstentions are not wrong answers. Counting them as errors would
        punish exactly the honesty this design is built on."""
        assert "unknown" not in holdout["per_class_precision"]
        assert holdout["n_claimed"] + holdout["n_abstained"] == holdout["n_holdout"]

    def test_the_holdout_is_author_disjoint_from_derivation(self, mod):
        """The property the whole evaluation rests on."""
        derivation_authors = {e["author"] for e in mod.derive.load_entries("derivation")}
        holdout_authors = {e["author"] for e in mod.derive.load_entries("holdout")}
        assert derivation_authors.isdisjoint(holdout_authors)


class TestShuffledControl:
    def test_permuted_genre_labels_collapse_to_chance(self, mod):
        """The direct test for "this is secretly an author classifier". If
        the model were keying on authorial style it would still predict well
        under permuted labels, because what it learned would not depend on
        the label being genre."""
        out = mod.shuffled_control(seed=1729)
        assert out["accuracy"] <= out["chance"] + 0.10

    def test_the_permutation_actually_moves_labels(self, mod):
        """A permutation that happened to be the identity would make the
        control vacuous — it would 'collapse to chance' only by accident of
        the shuffle, or fail to collapse for the wrong reason."""
        out = mod.shuffled_control(seed=1729)
        entries = mod.derive.load_entries()
        real = {e["author"]: e["label"] for e in entries}
        moved = sum(1 for a, lbl in out["permutation"].items() if real[a] != lbl)
        assert moved >= len(out["permutation"]) * 0.5

    def test_the_control_is_deterministic(self, mod):
        assert (
            mod.shuffled_control(seed=1729)["accuracy"]
            == mod.shuffled_control(seed=1729)["accuracy"]
        )


class TestMeasuredOutcome:
    def test_the_model_does_not_currently_meet_the_precision_floor(self, holdout):
        """Recorded as the measured state, not as an aspiration. The signals
        do not separate personal_essay from scholarly_essay for an unseen
        author, and creative_fiction has only two authors in the entire
        repository. G8 fails on this, which is the gate working."""
        assert holdout["min_precision"] < 0.80

    def test_but_it_is_not_an_author_detector(self, mod):
        """The failure is 'these signals do not separate these genres', not
        'the model learned the wrong thing'. Worth distinguishing: the second
        would invalidate the approach, the first is a corpus limit."""
        out = mod.shuffled_control(seed=1729)
        assert out["accuracy"] <= out["chance"] + 0.10
