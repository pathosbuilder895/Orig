"""
tests/quantum/test_scoring_branches.py — residue branch coverage for
original/quantum/scoring.py (branch-coverage effort, part 8, task 2).

The plan's guessed "12 missing" (docs/superpowers/plans/2026-08-17-branch-
coverage-part8-quantum.md) was stale by the time this task ran — the two
existing files (test_llr_action_modes.py, test_characteristic_weights.py)
already cover the `_recommend`/`LLR_ACTION_MODE` scenarios and the
`_characteristic_weight_factor` off/thin-baseline abstains the plan
described. A fresh `--cov-branch` measurement found a larger, different
residue spread across six functions:

    _length_bucket_for        : loop-continuation + the negative/overflow
                                 fallback (lines 113->112, 115)
    _characteristic_weight_factor : unpack-failure / negative-sigma /
                                 non-positive-median abstains (extended in
                                 test_characteristic_weights.py, not here)
    _amplitude_score           : secret_key truthy branch, conformal_pvalue's
                                 own inner except (lines 831, 841-842)
    _llr_deviation              : zero-active-features guard (line 905)
    score()                     : Bayesian-prior-blend except, amplitude-
                                 scoring except, trajectory "regressive" arm,
                                 theological "critical" balance arm (lines
                                 1075-1076, 1336-1342, 1399-1400, 1458)
    _decompose                  : z_scores=None default (line 1605)
    _recommend                  : severity-ladder boundary rungs, the
                                 conformal nudge-up arm, and its elif's False
                                 arm, the short-submission note (lines
                                 1902->1906, 1907, 1970-1971, 1975->1984, 2041)
    _llr_action_candidates      : blend's own >=1.0 clip (line 2103)

Every scenario below was traced through the actual function (or executed
directly against it) before being written — see the comment above each
assertion for the derivation. `_recommend`'s `1924->1934` branch (the
identity-axis matrix-lookup's `is not None` check) turned out to be
structurally dead code from that call site and is annotated with `# pragma:
no branch` in original/quantum/scoring.py instead of a test — see the
comment there for why.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM
from original.quantum.scoring import (
    _TIER_WEIGHT_VECTOR,
    BaselineConfidence,
    DomainSignal,
    InterferenceDecomposition,
    SHORT_SUBMISSION_TOKENS,
    ScoringConfig,
    _decompose,
    _length_bucket_for,
    _llr_action_candidates,
    _llr_deviation,
    _recommend,
    score,
)
from original.quantum.state import BaselineSample, StudentState

# ── _length_bucket_for ────────────────────────────────────────────────────────
#
# LENGTH_BUCKETS_BY_TOKENS (original/constants.py): short (0,750), medium
# (750,2500), long (2500, 10**9) — a dict iterated in that order, `lo <=
# n_tokens < hi` per entry, `break` on match, "long" as an unconditional
# fallback after the loop if nothing matched.


class TestLengthBucketFor:
    def test_short_range_matches_on_the_first_entry(self):
        assert _length_bucket_for(0) == "short"
        assert _length_bucket_for(749) == "short"

    def test_medium_boundary_requires_the_loop_to_reject_short_first(self):
        # 750 fails short's `0 <= 750 < 750` (750 < 750 is False) -> the
        # loop must continue to the NEXT dict entry (medium) rather than
        # matching immediately -- this is the 113->112 loop-continuation
        # branch. medium's `750 <= 750 < 2500` is True -> "medium".
        assert _length_bucket_for(750) == "medium"

    def test_long_boundary_requires_two_rejections(self):
        # 2500 fails both short and medium (medium's hi=2500 is exclusive
        # too) before long's `2500 <= 2500 < 10**9` matches.
        assert _length_bucket_for(2500) == "long"
        assert _length_bucket_for(999_999) == "long"

    def test_negative_token_count_falls_through_every_bucket_to_the_fallback(self):
        # No bucket's [lo, hi) contains a negative count (short's lo=0
        # excludes it) -> the for-loop exhausts every entry without a
        # match -> line 115's unconditional `return "long"` fires. This is
        # the ONLY way to reach that line: every non-negative int up to
        # 10**9-1 is covered by one of the three ranges.
        assert _length_bucket_for(-1) == "long"


# ── _decompose: z_scores=None default ─────────────────────────────────────────


class TestDecomposeDefaultZScores:
    def test_omitted_z_scores_defaults_to_all_zero_and_every_feature_reads_constructive(self):
        # Direction rule (scoring.py:1616-1621): z < -1 or z > 1 ->
        # destructive; abs(z) < 0.5 -> constructive; else neutral. With
        # z_scores omitted, line 1605 sets z_scores = np.zeros(FEATURE_DIM)
        # -> z=0.0 for every feature -> abs(0.0)=0.0 < 0.5 -> ALL
        # FEATURE_DIM features read "constructive", none destructive or
        # neutral. Verified directly: calling _decompose without the
        # z_scores kwarg produces exactly this split.
        xi = np.full(FEATURE_DIM, 1.0 / math.sqrt(FEATURE_DIM))
        rho_xi = xi.copy()
        feature_dict = {code: 0.5 for code in ALL_FEATURE_CODES}
        baseline_mean = np.full(FEATURE_DIM, 0.5)

        result = _decompose(xi, rho_xi, 1.0, feature_dict, baseline_mean)  # z_scores omitted

        assert result.destructive_features == []
        assert len(result.constructive_features) == 5  # top-5 slice of an all-constructive set


# ── _llr_deviation: zero active features ───────────────────────────────────────


class TestLlrDeviationZeroActive:
    def test_zero_active_features_uses_the_zero_guard_not_a_zero_division(self):
        # `if n_active > 0: rms_z_null = sqrt(sum/n_active) else: rms_z_null
        # = 0.0` (scoring.py:902-905). n_active=0 is the value the real
        # caller computes as `int(active.sum())` when the mask selects
        # nothing, so this reproduces that exact caller shape.
        # Hand check with rms_z_null forced to 0.0: delta = rms_z -
        # rms_z_null = 0.7 - 0.0 = 0.7 -> llr = 0.5 + 0.5*tanh(0.7/1.5).
        # tanh(0.46667): e^0.46667=1.5949, e^-0.46667=0.6270 (by hand) ->
        # (1.5949-0.6270)/(1.5949+0.6270) = 0.9679/2.2219 ~= 0.4356 -> llr
        # ~= 0.5 + 0.2178 = 0.7178. Re-derived programmatically below via
        # the identical closed-form so the assertion is exact, not
        # hand-rounded; the sanity band pins it to that same neighbourhood
        # so a regression to the un-guarded 0/0 (NaN) path fails loudly.
        sub_raw = np.full(FEATURE_DIM, 0.5)
        mu_null = np.full(FEATURE_DIM, 0.5)
        sigma_null = np.full(FEATURE_DIM, 0.1)
        active = np.zeros(FEATURE_DIM, dtype=bool)  # nothing active

        result = _llr_deviation(
            sub_raw, (mu_null, sigma_null), _TIER_WEIGHT_VECTOR, active, n_active=0, rms_z=0.7
        )

        assert not math.isnan(result)
        expected = 0.5 + 0.5 * math.tanh(0.7 / 1.5)
        assert result == pytest.approx(expected, abs=1e-12)
        assert 0.71 < result < 0.72  # matches the by-hand tanh(0.4667)~=0.436 estimate


# ── _recommend: severity-ladder boundaries + conformal nudge arms ─────────────


def _domain(theol=0.5, anomaly=False, balance="balanced") -> DomainSignal:
    return DomainSignal(
        theological_register_score=theol, register_anomaly=anomaly, confessional_balance=balance
    )


def _bc(effective_n=5.0) -> BaselineConfidence:
    return BaselineConfidence(
        purity=1.0,
        sample_count=5,
        authenticated_count=5,
        effective_sample_count=effective_n,
        trajectory_confidence=1.0,
    )


def _empty_interference() -> InterferenceDecomposition:
    return InterferenceDecomposition(
        total_probability=0.9,
        constructive_features=[],
        destructive_features=[],
        broken_entanglements=[],
        tier_breakdown={},
    )


class TestRecommendSeverityLadderBoundaries:
    def test_deviation_exactly_one_hits_the_post_loop_escalate_fallback(self):
        # ACTION_THRESHOLDS["escalate"] = (0.75, 1.00), hi EXCLUSIVE, so the
        # for-loop's `0.75 <= 1.0 < 1.00` is False for every entry -- the
        # loop exhausts without a match (the 1902->1906 branch: fall
        # through the loop to the line after it) and line 1906's `if
        # deviation >= 1.0` fallback is what actually sets "escalate"
        # (line 1907). Verified directly below.
        result = _recommend(0.9, 1.0, _empty_interference(), _domain(), _bc())
        assert result.action == "escalate"

    def test_negative_deviation_also_falls_through_the_loop_but_stays_no_action(self):
        # Symmetric boundary: no bucket's [lo, hi) contains a negative
        # deviation either (no_action's lo=0.0 excludes it) -> loop
        # exhausts (1902->1906 again) -> but `deviation >= 1.0` is False
        # this time, so `action` keeps its pre-loop default of
        # "no_action" rather than being reassigned by 1907.
        result = _recommend(0.9, -0.5, _empty_interference(), _domain(), _bc())
        assert result.action == "no_action"


class TestRecommendConformalNudge:
    def test_confidently_anomalous_conformal_p_raises_a_low_severity_action(self):
        # deviation=0.1 -> no_action (matches (0.00,0.40)) before the
        # conformal block runs. conformal_p=0.001 -> verdict_from_pvalue
        # (alpha_escalate=0.01): 0.001 < 0.01 -> "escalate". severity
        # escalate(3) > no_action(0) AND action != "escalate" -> the `if`
        # at line 1966 is True -> action reassigned to "escalate" (1970)
        # and the nudge-up rationale is appended (1971-1974). Verified
        # directly: this exact call produces action="escalate" with
        # "Conformal calibration" in the rationale.
        result = _recommend(
            0.9, 0.1, _empty_interference(), _domain(), _bc(), conformal_p=0.001
        )
        assert result.action == "escalate"
        assert "Conformal calibration (p=0.001)" in result.rationale
        assert "raised from deviation-score verdict" in result.rationale

    def test_escalate_action_with_a_non_alarming_conformal_p_skips_the_elif_note(self):
        # deviation=0.9 -> action="escalate" directly from the ladder
        # (0.75 <= 0.9 < 1.00). The `if` at 1966 is False purely because
        # `action != "escalate"` is False (short-circuits the whole
        # condition) -> falls to the `elif` at 1975: `conformal_p > 0.20
        # and action == "escalate" and not ghostwriting_confirmed`.
        # conformal_p=0.15 fails `> 0.20` -> elif is ALSO False -> control
        # skips straight to the confidence block (the 1975->1984 branch)
        # without appending either conformal note. Verified directly: no
        # "conformal" substring appears anywhere in the rationale.
        result = _recommend(
            0.9, 0.9, _empty_interference(), _domain(), _bc(), conformal_p=0.15
        )
        assert result.action == "escalate"
        assert "conformal" not in result.rationale.lower()

    def test_escalate_action_with_an_alarming_conformal_p_does_add_the_disagreement_note(self):
        # Companion case proving the elif's TRUE arm still works after the
        # branch above locks down its False arm: conformal_p=0.30 > 0.20,
        # action=="escalate", no ghostwriting -> elif fires, action stays
        # "escalate" (this is a note-only nudge), and the "verify manually"
        # disagreement note is appended.
        result = _recommend(
            0.9, 0.9, _empty_interference(), _domain(), _bc(), conformal_p=0.30
        )
        assert result.action == "escalate"
        assert "verify manually before acting" in result.rationale


class TestRecommendShortSubmissionNote:
    def test_note_appears_below_the_threshold_and_not_at_it(self):
        # SHORT_SUBMISSION_TOKENS = 300; the guard is a strict `<`, so 300
        # itself must NOT add the note (byte-identical to n_tokens=None)
        # while 299 must. Verified directly for both sides of the boundary.
        below = _recommend(
            0.9, 0.1, _empty_interference(), _domain(), _bc(), n_tokens=SHORT_SUBMISSION_TOKENS - 1
        )
        at = _recommend(
            0.9, 0.1, _empty_interference(), _domain(), _bc(), n_tokens=SHORT_SUBMISSION_TOKENS
        )
        assert f"submission is only {SHORT_SUBMISSION_TOKENS - 1} words" in below.rationale
        assert "submission is only" not in at.rationale


# ── _llr_action_candidates: blend's own >=1.0 clip ─────────────────────────────


class TestBlendActionBoundary:
    def test_blend_clips_to_escalate_at_the_top_boundary(self):
        # blended = 0.5*1.0 + 0.5*1.0 = 1.0 -> ACTION_THRESHOLDS["escalate"]
        # is (0.75, 1.00) with hi EXCLUSIVE, so the for-loop's own
        # `0.75 <= 1.0 < 1.00` never matches -- `if blended >= 1.0:
        # blend_action = "escalate"` (line 2103) is what actually sets it.
        # (Also covered from tests/quantum/test_llr_action_modes.py, kept
        # here too since this file groups scoring.py's residue arms.)
        candidates = _llr_action_candidates("no_action", deviation=1.0, llr_deviation_score=1.0)
        assert candidates["blend"] == "escalate"


# ── score(): Bayesian-prior-blend exception ────────────────────────────────────


def _one_sample_state(student_id: str, genre: str | None = None, value: float = 0.5) -> StudentState:
    state = StudentState(student_id=student_id)
    state.add_sample(
        BaselineSample(
            text="baseline 0",
            vector=np.full(FEATURE_DIM, value),
            provenance="proctored",
            auth_weight=1.0,
            assignment="a0",
            genre=genre,
        )
    )
    return state


class TestBayesianPriorBlendException:
    def test_malformed_genre_stats_is_caught_and_falls_back_to_the_unblended_baseline(self, caplog):
        # config.bayesian_prior_enabled=True, state.sample_count=1 (<10),
        # last sample's genre="scholarly_essay" (truthy) -> enters the try
        # block. genre_stats={"std": ...} is missing "mean" ->
        # `_prior["mean"]` raises KeyError while evaluating
        # `mu = _alpha*mu + (1-_alpha)*_prior["mean"]` -- caught by
        # `except Exception as _exc: log.debug(...)` (lines 1075-1076).
        # Because Python evaluates the RHS before assigning, `mu` is never
        # reassigned -- it stays state.baseline_mean (0.5 uniform, since
        # this is the only baseline sample). The submission is also 0.5
        # uniform, so z=(0.5-0.5)/sigma=0 for every feature regardless of
        # sigma -> rms_z=0 -> tanh(0/1.5)=0 -> deviation_score=0.0 exactly.
        # Verified directly: this construction logs "Bayesian prior blend
        # skipped: 'mean'" and produces deviation_score == 0.0.
        state = _one_sample_state("bayes-exc:student", genre="scholarly_essay", value=0.5)
        submission = np.full(FEATURE_DIM, 0.5)
        config = ScoringConfig(
            bayesian_prior_enabled=True,
            genre_stats={"std": np.full(FEATURE_DIM, 0.1)},  # "mean" deliberately absent
        )

        with caplog.at_level(logging.DEBUG, logger="original.quantum.scoring"):
            result = score(
                state=state,
                submission_vector=submission,
                feature_dict={},
                submission_id="s1",
                scoring_config=config,
            )

        assert any(
            "Bayesian prior blend skipped" in r.message and "'mean'" in r.message
            for r in caplog.records
        )
        assert result.authorship.deviation_score == 0.0


# ── score(): amplitude-scoring residue (secret_key, both except blocks) ───────


def _amplitude_state(seed: int = 11, n: int = 3) -> StudentState:
    state = StudentState(student_id="amp:student")
    rng = np.random.default_rng(seed)
    for i in range(n):
        v = np.clip(rng.normal(0.5, 0.05, size=FEATURE_DIM), 0.0, 1.0)
        state.add_sample(
            BaselineSample(
                text=f"baseline {i}",
                vector=v,
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    return state


class TestAmplitudeScoringResidue:
    def test_outer_except_catches_a_failure_anywhere_in_amplitude_score(self, monkeypatch, caplog):
        # score()'s own try/except around the _amplitude_score call (lines
        # 1321-1342) must catch an exception raised ANYWHERE inside that
        # helper -- not just the inner conformal_pvalue try/except a few
        # lines further down. Monkeypatching encode_amplitudes (called
        # unconditionally, well before the conformal block) to raise
        # proves this is the OUTER guard, not the inner one. Verified
        # directly: the call does not raise, fidelity falls back to 0.0/
        # None, and a WARNING is logged.
        import original.quantum.amplitude as amp_mod

        def _boom(*_a, **_k):
            raise RuntimeError("boom")

        monkeypatch.setattr(amp_mod, "encode_amplitudes", _boom)

        state = _amplitude_state()
        submission = np.full(FEATURE_DIM, 0.5)
        config = ScoringConfig(amplitude_scoring_enabled=True)

        with caplog.at_level(logging.WARNING, logger="original.quantum.scoring"):
            result = score(
                state=state,
                submission_vector=submission,
                feature_dict={},
                submission_id="s1",
                scoring_config=config,
            )

        assert result.authorship.quantum_fidelity == 0.0
        assert result.authorship.fidelity_conformal_pvalue is None
        assert any("amplitude scoring failed for s1" in r.message for r in caplog.records)

    def test_secret_key_projection_preserves_fidelity(self):
        # apply_keyed_projection applies a unitary U to both amplitude
        # vectors; quantum_fidelity is |<Ub|Us>|^2 / (||Ub||^2 ||Us||^2),
        # and the module's own docstring states the fidelity is preserved
        # under any unitary. Comparing a plain run (secret_key="", skips
        # line 830's `if secret_key:` guard) against a keyed run (secret_key
        # set, takes it) on the IDENTICAL state/submission is therefore a
        # real correctness check grounded in that invariant, not just "the
        # line executed". Verified directly: the two fidelities agree to
        # float precision (~1e-12 apart from the QR-based unitary's
        # rounding, not conceptually different).
        state = _amplitude_state()
        submission = np.clip(np.random.default_rng(3).normal(0.55, 0.05, size=FEATURE_DIM), 0.0, 1.0)

        plain = score(
            state=state,
            submission_vector=submission,
            feature_dict={},
            submission_id="s1",
            scoring_config=ScoringConfig(amplitude_scoring_enabled=True, secret_key=""),
        )
        keyed = score(
            state=state,
            submission_vector=submission,
            feature_dict={},
            submission_id="s1",
            scoring_config=ScoringConfig(amplitude_scoring_enabled=True, secret_key="shh-a-secret"),
        )
        assert keyed.authorship.quantum_fidelity == pytest.approx(
            plain.authorship.quantum_fidelity, abs=1e-9
        )

    def test_inner_conformal_exception_degrades_only_the_pvalue_not_the_fidelity(self):
        # The `if authentic_fidelities: p_val = conformal_pvalue(...)` call
        # has its OWN try/except (lines 838-842), separate from score()'s
        # outer one exercised above. authentic_fidelities=["not-a-number"]
        # is truthy (non-empty list, passes `if authentic_fidelities:`) but
        # conformal_pvalue's `f <= fidelity` comparison against a float
        # raises TypeError for the string element -- caught by the INNER
        # except, so p_val stays None but F (fidelity) -- already computed
        # above that block -- is unaffected. Verified directly: fidelity is
        # a real positive value while the conformal p-value is None, proving
        # the two exception scopes are independent.
        state = _amplitude_state()
        submission = np.full(FEATURE_DIM, 0.5)
        config = ScoringConfig(
            amplitude_scoring_enabled=True, authentic_fidelities=["not-a-number"]
        )

        result = score(
            state=state,
            submission_vector=submission,
            feature_dict={},
            submission_id="s1",
            scoring_config=config,
        )

        assert result.authorship.fidelity_conformal_pvalue is None
        assert result.authorship.quantum_fidelity > 0.0


# ── score(): trajectory "regressive" direction ─────────────────────────────────


class TestTrajectoryRegressive:
    def test_submission_matching_the_oldest_baseline_reads_as_regressive(self):
        # TRAJECTORY_REGRESSIVE_THRESHOLD = -0.20. Trajectory needs >= 3
        # authenticated samples (TRAJECTORY_MIN_SAMPLES). Two features (i0,
        # i1) swing from (1.0, 0.0) at the oldest sample to (0.0, 1.0) at
        # the newest, with every other feature at 0.0 throughout, so the
        # per-dimension linear-regression slope is EXACTLY zero everywhere
        # except i0 (negative) and i1 (positive) -> traj.vector is the
        # two-hot unit vector (-1/sqrt2, +1/sqrt2, 0, 0, ...). A submission
        # matching the OLDEST sample's pattern (i0=1.0, i1=0.0) is the
        # "moving backward" case: its unit vector's dot with traj.vector is
        # exactly -1/sqrt(2) ~= -0.7071 by construction (only i0, i1 are
        # nonzero on both sides), well past the -0.20 threshold. Verified
        # directly against the real state.trajectory/score() pipeline
        # (not hand-derived in isolation) because the per-sample _unit()
        # normalisation inside _compute_trajectory makes the raw numbers
        # non-obvious -- see the by-hand version in this test's git history
        # for the failed first attempt (uniform-magnitude baseline, which
        # collapses to a zero trajectory vector because _unit() erases
        # magnitude, only direction, and a uniform vector's direction never
        # changes).
        state = StudentState(student_id="traj-regressive:student")
        i0, i1 = 0, 1
        for k, (a, b) in enumerate([(1.0, 0.0), (0.5, 0.5), (0.0, 1.0)]):
            v = np.zeros(FEATURE_DIM)
            v[i0] = a
            v[i1] = b
            state.add_sample(
                BaselineSample(
                    text=f"baseline {k}",
                    vector=v,
                    provenance="proctored",
                    auth_weight=1.0,
                    assignment=f"a{k}",
                )
            )
        submission = np.zeros(FEATURE_DIM)
        submission[i0] = 1.0
        submission[i1] = 0.0

        result = score(
            state=state,
            submission_vector=submission,
            feature_dict={},
            submission_id="s1",
            scoring_config=ScoringConfig(),
        )

        assert result.trajectory.direction == "regressive"
        assert result.trajectory.alignment == pytest.approx(-1.0 / math.sqrt(2.0), abs=1e-9)
        assert result.trajectory.adjustment_factor == 1.15


# ── score(): theological "critical" balance ────────────────────────────────────


class TestTheologicalCriticalBalance:
    def test_low_baseline_theological_register_reads_as_critical(self):
        # domain block (scoring.py:1455-1460): theol_base > 0.5 ->
        # "confessional"; theol_base < 0.25 -> "critical"; else "balanced".
        # theol_base is state.baseline_mean at the
        # theological_register_score index. A single baseline sample with
        # that feature at 0.1 (< 0.25) must read "critical". Verified
        # directly: ALL_FEATURE_CODES.index("theological_register_score")
        # == 33 in the current ordering, and baseline_mean at that index
        # for a single sample equals the sample's own value (0.1).
        idx = ALL_FEATURE_CODES.index("theological_register_score")
        state = StudentState(student_id="theol-critical:student")
        v = np.full(FEATURE_DIM, 0.5)
        v[idx] = 0.1
        state.add_sample(
            BaselineSample(
                text="baseline 0",
                vector=v,
                provenance="proctored",
                auth_weight=1.0,
                assignment="a0",
            )
        )
        submission = np.full(FEATURE_DIM, 0.5)
        submission[idx] = 0.15
        feature_dict = {code: float(x) for code, x in zip(ALL_FEATURE_CODES, submission)}

        result = score(
            state=state,
            submission_vector=submission,
            feature_dict=feature_dict,
            submission_id="s1",
            scoring_config=ScoringConfig(),
        )

        assert state.baseline_mean[idx] == pytest.approx(0.1)
        assert result.domain.confessional_balance == "critical"
        assert result.domain.theological_register_score == pytest.approx(0.15)
