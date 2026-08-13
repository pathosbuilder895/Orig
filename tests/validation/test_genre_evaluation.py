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
    def test_the_model_meets_the_precision_floor(self, holdout):
        """Recorded as the measured state. It took three things to get here,
        and only the third was decisive: eight more authors (the thin classes
        had 2-3, so leave-one-author-out trained on 1-2 and scored 0.000), a
        selector aligned with the conjunction rather than one leg of it, and
        a taxonomy whose class boundaries text can actually carry."""
        assert holdout["min_precision"] >= 0.80

    def test_abstention_stays_under_the_ceiling(self, holdout):
        """Precision bought by abstaining on everything is the degenerate
        win; the ceiling is what makes the precision number mean something."""
        assert holdout["abstention_rate"] <= 0.50

    def test_and_it_is_not_an_author_detector(self, mod):
        """The leg that matters. Precision means nothing if the model reached
        it by recognising writers rather than genres."""
        out = mod.shuffled_control(seed=1729)
        assert out["accuracy"] <= out["chance"] + 0.10


class TestUnclaimedClassesZeroTheMinimum:
    """A class the model never predicts must drag min_precision to zero, the
    same way derive.py's choose_threshold treats it. Otherwise the gate's
    precision leg can be passed by simply never claiming the hard class —
    the degenerate win the abstention ceiling does not cover, because
    abstaining on one CLASS is not the same as abstaining overall."""

    def test_a_class_never_claimed_zeroes_the_minimum(self, mod, monkeypatch):
        from original.context import genre_v2

        # Always claim one class, perfectly confidently. Precision on that
        # class is whatever it is; the other two are never claimed at all.
        monkeypatch.setattr(
            genre_v2,
            "predict",
            lambda text, citation_data=None: {
                "primary": "academic_exegesis",
                "confidence": 0.99,
                "secondary": None,
            },
        )
        out = mod.evaluate_holdout()
        assert out["classes_never_claimed"], "test setup no longer silences a class"
        assert out["min_precision"] == 0.0

    def test_the_reason_is_recorded_not_just_the_zero(self, mod, monkeypatch):
        from original.context import genre_v2

        monkeypatch.setattr(
            genre_v2,
            "predict",
            lambda text, citation_data=None: {
                "primary": "academic_exegesis",
                "confidence": 0.99,
                "secondary": None,
            },
        )
        out = mod.evaluate_holdout()
        assert out["min_precision_zeroed_by_unclaimed"] is True

    def test_a_normal_run_is_unaffected(self, holdout):
        """When every class is claimed the minimum is the ordinary minimum."""
        if holdout["classes_never_claimed"]:
            pytest.skip("a class is genuinely unclaimed on the current model")
        assert holdout["min_precision"] == min(holdout["per_class_precision"].values())
        assert holdout["min_precision_zeroed_by_unclaimed"] is False
