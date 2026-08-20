"""
tests/test_tier9.py — branch coverage for `original/features/tier9.py`
(Tier 9 — Cognitive Sequencing / Argument Topology).

Covers:
  - `_tag_move`: one direct call per rhetorical move label (Q/K/R/E/C/N),
    extracted per the plan's "singles" guidance — the priority order is
    Q > K > R > E > C > N, so each test text is crafted to trigger exactly
    one cue class.
  - `compute_tier9_comparison`: unit-tested directly with hand-built
    sub/baseline profile dicts. Nothing in the scoped test selection
    reaches this function (it is only wired in via
    `pipeline.compute_full_features`'s baseline-texts branch, which none of
    the directly-imported test modules exercise) — both the short-sequence
    early return (`len(sub_seq) < 2`) and the full Markov-likelihood
    computation are covered.
"""

from __future__ import annotations

from original.features.tier9 import _tag_move, compute_tier9_comparison


def test_tag_move_question_mark_is_q():
    assert _tag_move("Is this argument valid?") == "Q"


def test_tag_move_adversative_marker_is_k():
    assert _tag_move("However, this concern remains valid.") == "K"


def test_tag_move_resolution_cue_is_r():
    assert _tag_move("Therefore, the argument holds firmly.") == "R"


def test_tag_move_evidence_cue_is_e():
    assert _tag_move("According to the text, this is evidence.") == "E"


def test_tag_move_claim_cue_is_c():
    assert _tag_move("I argue that this claim is correct.") == "C"


def test_tag_move_no_cues_is_neutral():
    assert _tag_move("This is a plain background statement.") == "N"


def test_compute_tier9_comparison_short_submission_sequence_is_neutral():
    sub_profile = {"_argument_sequence_profile": ["Q"]}
    baseline_profiles = {"_argument_sequence_profiles": [["Q", "C", "E"]]}
    result = compute_tier9_comparison(sub_profile, baseline_profiles)
    assert result == {"argument_sequence_likelihood": 0.5}


def test_compute_tier9_comparison_full_markov_likelihood():
    sub_profile = {"_argument_sequence_profile": ["Q", "C", "E"]}
    baseline_profiles = {
        "_argument_sequence_profiles": [
            ["Q", "C", "E", "R"],
            ["C", "E", "C", "E"],
        ]
    }
    result = compute_tier9_comparison(sub_profile, baseline_profiles)
    assert "argument_sequence_likelihood" in result
    assert 0.0 <= result["argument_sequence_likelihood"] <= 1.0


def test_compute_tier9_comparison_no_baseline_sequences_uses_uniform_smoothing():
    sub_profile = {"_argument_sequence_profile": ["Q", "N", "N"]}
    baseline_profiles = {}
    result = compute_tier9_comparison(sub_profile, baseline_profiles)
    assert 0.0 <= result["argument_sequence_likelihood"] <= 1.0
