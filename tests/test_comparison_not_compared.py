"""Comparison measurements are not compared (ADR-013, "Comparison measurements").

``extract_features`` makes every past-paper vector and computes no comparison
measurement, so a past paper only ever holds the stand-in for them, while
``compute_full_features`` gives the scored paper a real value. Scoring leaves
these codes out by the computing path's own list
(``features.baseline_scope.NOT_COMPUTED_FOR_BASELINES``), never by matching
the stand-in value.
"""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from original.constants import (
    ALL_FEATURE_CODES,
    COMPARISON_CODES,
    FEATURE_DIM,
    MUSICAL_COMPARISON_CODES,
)
from original.features import baseline_scope
from original.features.baseline_scope import (
    NOT_COMPARED_WORDS,
    NOT_COMPUTED_FOR_BASELINES,
    NOT_COMPUTED_FOR_BASELINES_MASK,
)
from original.features.pipeline import extract_features
from original.quantum import scoring as scoring_mod
from original.quantum import state as state_mod
from original.quantum.scoring import score
from original.quantum.state import BaselineSample, StudentState

MASK = NOT_COMPUTED_FOR_BASELINES_MASK
CODES = set(NOT_COMPUTED_FOR_BASELINES)


def _vector(seed: int, comparison: float | None = 0.5) -> np.ndarray:
    v = np.clip(np.random.RandomState(seed).normal(0.5, 0.12, FEATURE_DIM), 0.0, 1.0)
    if comparison is not None:
        v[MASK] = comparison
    return v


def _state(n: int, comparison: float | None = 0.5) -> StudentState:
    return StudentState(
        student_id="s",
        samples=[
            BaselineSample(
                text=f"t{i}",
                vector=_vector(10 + i, comparison),
                provenance="verified",
                auth_weight=1.0,
            )
            for i in range(n)
        ],
    )


def _submission(seed: int, comparison: np.ndarray | float) -> tuple[np.ndarray, dict[str, float]]:
    v = _vector(seed, None)
    v[MASK] = comparison
    return v, {c: float(v[i]) for i, c in enumerate(ALL_FEATURE_CODES)}


def _listed(out) -> set[str]:
    i = out.interference
    codes = {f.code for f in i.constructive_features} | {f.code for f in i.destructive_features}
    for e in i.broken_entanglements:
        codes |= {e.feature_a, e.feature_b}
    return codes


def _without_feature_vector(out) -> str:
    d = dataclasses.asdict(out)
    d.pop("feature_vector")
    return json.dumps(d, sort_keys=True, default=str)


def test_the_list_is_the_computing_paths_own():
    assert set(NOT_COMPUTED_FOR_BASELINES) == set(MUSICAL_COMPARISON_CODES) | set(COMPARISON_CODES)
    assert len(NOT_COMPUTED_FOR_BASELINES) == 7 and MASK.sum() == 7 and MASK.shape == (FEATURE_DIM,)
    assert [c for c, m in zip(ALL_FEATURE_CODES, MASK, strict=True) if m] == [
        c for c in ALL_FEATURE_CODES if c in CODES
    ]
    assert not MASK.flags.writeable
    # extract_features writes the stand-in for exactly these and computes the rest.
    text = "A short paper. It has words, and a comma; then more words follow here.\n" * 20
    feats = extract_features(text)
    assert {c for c in CODES if feats[c] == 0.5} == CODES
    assert baseline_scope.NOT_COMPARED_WORDS == "not compared: past papers have no value for this"


@pytest.mark.parametrize("n", [1, 2, 5])
def test_mask_excludes_them_by_code_whatever_the_stored_values(n):
    # Even synthetic past papers that vary on these codes (real ones never
    # do) do not bring them back: detection is by code, not by value.
    for comparison in (0.5, None):
        active = _state(n, comparison).active_feature_mask
        assert not active[MASK].any()
    if n == 1:
        assert active[~MASK].all()  # cold start: everything else stays active


@pytest.mark.parametrize("n", [1, 3, 6])
@pytest.mark.parametrize("extreme", [0.0, 1.0, 0.955])
def test_never_listed_and_score_ignores_this_papers_comparison_values(n, extreme):
    state = _state(n)
    vec, fd = _submission(99, extreme)
    out = score(state, vec, fd, submission_id="x")
    assert not (_listed(out) & CODES)
    assert out.feature_vector["error_kl_divergence"] == extreme  # still reported as measured
    # The same paper with no comparison values at all: the same score.
    vec0, fd0 = _submission(99, 0.5)
    out0 = score(state, vec0, fd0, submission_id="x")
    assert _without_feature_vector(out) == _without_feature_vector(out0)


def test_score_is_unchanged_when_the_stand_ins_are_all_there_is(monkeypatch):
    # Past papers and this paper all on the stand-in (no comparison computed):
    # with N >= 2 the value-based mask already dropped them, so the fix moves
    # no number; only the reasons lists stop carrying them.
    state = _state(4)
    vec, fd = _submission(7, 0.5)
    after = score(state, vec, fd, submission_id="y")
    off = np.zeros(FEATURE_DIM, dtype=bool)
    monkeypatch.setattr(scoring_mod, "NOT_COMPUTED_FOR_BASELINES_MASK", off)
    monkeypatch.setattr(state_mod, "NOT_COMPUTED_FOR_BASELINES_MASK", off)
    before = score(state, vec, fd, submission_id="y")
    for field in ("deviation_score", "authorship_probability", "quantum_fidelity"):
        assert getattr(after.authorship, field) == getattr(before.authorship, field), field
    assert after.recommendation == before.recommendation
    assert after.catastrophic_drift_rms_z == before.catastrophic_drift_rms_z
    assert after.trajectory == before.trajectory
    assert [f.code for f in after.interference.destructive_features] == [
        f.code for f in before.interference.destructive_features
    ]


def test_deterministic():
    state = _state(3)
    vec, fd = _submission(5, 1.0)
    runs = {
        json.dumps(
            dataclasses.asdict(score(state, vec, fd, submission_id="z")),
            sort_keys=True,
            default=str,
        )
        for _ in range(3)
    }
    assert len(runs) == 1


def test_the_vanished_error_pair_no_longer_uses_a_comparison_code():
    # The vocabulary-spike + error-vanish pair and the ghostwriting override
    # read error_kl_divergence; with it not compared they cannot fire on it.
    state = _state(3)
    vec, fd = _submission(3, 0.5)
    i_ttr = ALL_FEATURE_CODES.index("type_token_ratio")
    vec[i_ttr] = fd["type_token_ratio"] = 1.0
    vec[ALL_FEATURE_CODES.index("error_kl_divergence")] = fd["error_kl_divergence"] = 0.0
    out = score(state, vec, fd, submission_id="g")
    assert not (_listed(out) & CODES)
    assert not any("error-vanish" in e.label for e in out.interference.broken_entanglements)
    assert "vocabulary-spike" not in out.recommendation.rationale


def test_words():
    assert NOT_COMPARED_WORDS.startswith("not compared")
    assert "\u2014" not in NOT_COMPARED_WORDS and "\u2015" not in NOT_COMPARED_WORDS
