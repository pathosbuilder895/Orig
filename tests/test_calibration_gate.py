"""
tests/test_calibration_gate.py — pure-math unit tests for the calibration
gate criteria. The full corpus-driven run (validation/calibration_gate.py
executed as a script against seminary+public_authors+Plato) is slow and
belongs in CI's validation job, not the fast unit-test suite — this file
only tests the gate LOGIC on small synthetic inputs.
"""

from __future__ import annotations

import json

import pytest

from validation import calibration_gate
from validation.calibration_gate import (
    GateResult,
    _compute_g2_q_values,
    _compute_g4_group_means,
    _compute_g6_fairness_data,
    _conformal_p_floor,
    _g1_entity_baseline_counts,
    _g3_inputs_from_pa_report,
    _g5_machinery_error_result,
    _g6_insufficient_data_result,
    _g6_short_group_message,
    _g6_unreachable_threshold_result,
    _machinery_error_result,
    _min_n_for_threshold,
    _paraphrase_proxy,
    _reachability_block,
    _require_healthy_leg,
    _score_corpus_for_g1,
    _threshold_reachable,
    _uniformity_features_enabled,
    _uniformity_slice_summary,
    evaluate_g1_fpr,
    evaluate_g2_bland_impostor,
    evaluate_g2b_paraphrase_resistant,
    evaluate_g3_attribution,
    evaluate_g4_career_drift_monotone,
    evaluate_g5_permutation_null,
    evaluate_g6_fairness,
    evaluate_g7_cross_topic_fpr,
    render,
    run_g5,
)
from validation.power import conformal_p_floor


class TestG1Fpr:
    def test_passes_when_flagged_rate_at_or_below_five_percent(self):
        actions = ["no_action"] * 95 + ["monitor"] * 5
        result = evaluate_g1_fpr(actions, per_corpus={"synthetic": actions})
        assert result.passed is True

    def test_fails_when_flagged_rate_above_five_percent(self):
        actions = ["no_action"] * 85 + ["monitor"] * 15
        result = evaluate_g1_fpr(actions, per_corpus={"synthetic": actions})
        assert result.passed is False

    def test_reports_per_corpus_breakdown_not_just_pooled(self):
        per_corpus = {
            "good_corpus": ["no_action"] * 100,
            "bad_corpus": ["escalate"] * 20 + ["no_action"] * 80,
        }
        pooled = per_corpus["good_corpus"] + per_corpus["bad_corpus"]
        result = evaluate_g1_fpr(pooled, per_corpus=per_corpus)
        assert "bad_corpus" in result.detail["per_corpus_flagged_rate"]
        assert result.detail["per_corpus_flagged_rate"]["bad_corpus"] > 0.05


class TestConformalReachability:
    """The shared reachability guard. A conformal p-value cannot fall below
    1/(n+1), so a gate thresholding p at 0.02 with n=4 is testing something
    structurally impossible — its 'zero flags' result is vacuous, not fair."""

    def test_p_floor_is_one_over_n_plus_one(self):
        assert _conformal_p_floor(4) == pytest.approx(0.2)
        assert _conformal_p_floor(49) == pytest.approx(0.02)

    def test_p_floor_rejects_non_positive_n(self):
        """FIX 3(a): _conformal_p_floor now delegates to
        validation.power.conformal_p_floor instead of re-implementing the
        same arithmetic. This REPLACES the old assertion that
        `_conformal_p_floor(0) == 1.0` — that degenerate return value was
        exactly the drift between the two copies the review flagged
        (power.conformal_p_floor(0) has always raised ValueError). No
        caller in this module relied on the old degenerate value (checked:
        _reachability_block only ever calls this with n>=1), so the
        wrapper now lets power's ValueError surface instead of preserving a
        second, disagreeing definition of "degenerate"."""
        with pytest.raises(ValueError):
            _conformal_p_floor(0)

    def test_threshold_unreachable_below_required_n(self):
        assert _threshold_reachable(4, 0.02) is False
        assert _threshold_reachable(48, 0.02) is False

    def test_threshold_reachable_at_exactly_required_n(self):
        """Spec §5's reachability table: the .02 central boundary needs N>=49."""
        assert _threshold_reachable(49, 0.02) is True

    def test_min_n_matches_the_specs_reachability_table(self):
        assert _min_n_for_threshold(0.02) == 49
        assert _min_n_for_threshold(0.03) == 33
        # Self-consistency at every boundary: n-1 unreachable, n reachable.
        for threshold in (0.005, 0.015, 0.02, 0.03, 0.05, 0.1):
            n = _min_n_for_threshold(threshold)
            assert _threshold_reachable(n, threshold) is True
            assert _threshold_reachable(n - 1, threshold) is False

    def test_block_reports_the_binding_minimum_n(self):
        block = _reachability_block([60, 4, 12], 0.02)
        assert block["observed"] is True
        assert block["min_typicality_n"] == 4
        assert block["p_floor"] == pytest.approx(0.2)
        assert block["required_n"] == 49
        assert block["reachable"] is False

    def test_block_records_when_no_typicality_n_was_observed(self):
        """No typicality_n on any fold means the actions came from the
        deviation path, not the conformal band — the floor does not apply
        and the block must say so rather than inventing a verdict."""
        block = _reachability_block([], 0.02)
        assert block["observed"] is False
        assert block["reachable"] is None


class TestG1ReachabilityAnnotation:
    """G1's flagged rate is genuinely defined, so a real flagged rate is
    never suppressed — but a 0.0% rate produced at an N where no flag is
    structurally possible must never read as demonstrated discrimination."""

    def test_unreachable_threshold_downgrades_a_would_be_pass_to_uninformative(self):
        """UPDATED for FIX 3(b): this test used to assert `result.passed is
        True` here — i.e. an unreachable typicality_ns annotated
        current_value with "UNINFORMATIVE" while the verdict stayed "pass".
        That is precisely the self-contradictory `G1 [PASS] ... current:
        0.0% (UNINFORMATIVE: ...)` render the review flagged: two
        mechanisms estimating the same reachability question must not be
        allowed to disagree in the rendered verdict. typicality_ns is the
        MORE accurate signal (observed per-fold N), so a would-be pass with
        flagged == 0 that it finds unreachable is now downgraded exactly
        like the entity_baseline_counts mechanism downgrades one."""
        actions = ["no_action"] * 100
        result = evaluate_g1_fpr(
            actions, per_corpus={"synthetic": actions}, typicality_ns=[12] * 100
        )
        assert result.verdict == "uninformative"
        assert result.passed is False
        assert "UNINFORMATIVE" in result.current_value
        assert "n<=12" in result.current_value
        assert result.detail["reachability"]["min_typicality_n"] == 12
        assert result.detail["reachability"]["reachable"] is False

    def test_reachable_threshold_leaves_current_value_clean(self):
        actions = ["no_action"] * 100
        result = evaluate_g1_fpr(
            actions, per_corpus={"synthetic": actions}, typicality_ns=[60] * 100
        )
        assert "UNINFORMATIVE" not in result.current_value
        assert result.detail["reachability"]["reachable"] is True

    def test_annotation_is_absent_when_no_typicality_ns_are_supplied(self):
        actions = ["no_action"] * 100
        result = evaluate_g1_fpr(actions, per_corpus={"synthetic": actions})
        assert result.current_value == "0.0%"
        assert result.detail["reachability"]["observed"] is False


class TestG2BlandImpostor:
    def test_passes_when_impostor_q_is_lower_than_holdout_q(self):
        """q = min(p_far, p_central). Impostor should score LOWER (more
        anomalous) than genuine holdouts."""
        holdout_q = [0.5, 0.45, 0.5, 0.48]
        impostor_q = [0.05, 0.03, 0.02]
        result = evaluate_g2_bland_impostor(holdout_q, impostor_q)
        assert result.passed is True

    def test_fails_when_impostor_q_exceeds_holdout_q(self):
        """Reproduces the CURRENT defect: Eryxias-like impostor looks MORE
        typical than genuine holdouts."""
        holdout_q = [0.5, 0.45, 0.5, 0.48]
        impostor_q = [0.9, 0.85, 0.88]
        result = evaluate_g2_bland_impostor(holdout_q, impostor_q)
        assert result.passed is False


class TestG5PermutationNull:
    def test_passes_when_shuffled_labels_collapse_to_chance(self):
        result = evaluate_g5_permutation_null(
            real_g1_mean_deviation=0.42,      # same-author LOO deviations
            shuffled_g1_mean_deviation=0.71,  # cross-author blends look MORE deviant -> good
            shuffled_g3_accuracy=0.12,        # near 1/n_authors, not 0.7+ -> good
            g4_nonmonotone_draws=3,           # no draw retains chronological signal -> good
            g4_total_draws=3,
        )
        assert result.passed is True

    def test_fails_when_shuffled_labels_still_pass_the_real_gates(self):
        """If G1/G3/G4 still look good on shuffled labels, the pipeline is
        measuring the selection procedure, not authorship signal."""
        result = evaluate_g5_permutation_null(
            real_g1_mean_deviation=0.42,
            shuffled_g1_mean_deviation=0.40,  # blending baselines changed nothing -> suspicious
            shuffled_g3_accuracy=0.75,        # suspiciously still high on noise
            g4_nonmonotone_draws=0,           # every draw still "monotone" on blends
            g4_total_draws=3,
        )
        assert result.passed is False

    def test_single_suspicious_leg_fails_the_gate(self):
        """ANY leg that still looks like real signal fails G5. Here only the
        G1 leg is suspicious: shuffled mean == real mean, i.e. the measurement
        is insensitive to cross-author baseline blending."""
        result = evaluate_g5_permutation_null(
            real_g1_mean_deviation=0.42,
            shuffled_g1_mean_deviation=0.42,  # <= real -> suspicious
            shuffled_g3_accuracy=0.12,
            g4_nonmonotone_draws=3,
            g4_total_draws=3,
        )
        assert result.passed is False

    def test_two_of_three_nonmonotone_draws_counts_as_collapsed(self):
        """Majority boundary: 2 of 3 non-monotone draws IS a majority — the
        G4 leg reads as collapsed and (with the other legs collapsed) the
        gate passes."""
        result = evaluate_g5_permutation_null(
            real_g1_mean_deviation=0.42,
            shuffled_g1_mean_deviation=0.71,
            shuffled_g3_accuracy=0.12,
            g4_nonmonotone_draws=2,
            g4_total_draws=3,
        )
        assert result.passed is True

    def test_one_of_three_nonmonotone_draws_is_still_suspicious(self):
        """Majority boundary: only 1 of 3 draws non-monotone means shuffled
        labels still produce 'chronological' orderings most of the time —
        suspicious, gate fails."""
        result = evaluate_g5_permutation_null(
            real_g1_mean_deviation=0.42,
            shuffled_g1_mean_deviation=0.71,
            shuffled_g3_accuracy=0.12,
            g4_nonmonotone_draws=1,
            g4_total_draws=3,
        )
        assert result.passed is False


class TestRequireHealthyLeg:
    def test_exactly_ten_percent_errors_is_tolerated(self):
        """10/100 == 0.10 is NOT > 0.10 — the guard is strictly greater-than."""
        _require_healthy_leg("leg", n_success=90, n_errors=10)  # must not raise

    def test_above_ten_percent_errors_raises(self):
        with pytest.raises(RuntimeError, match="11/100"):
            _require_healthy_leg("leg", n_success=89, n_errors=11)

    def test_zero_successful_folds_raises(self):
        with pytest.raises(RuntimeError, match="zero successful"):
            _require_healthy_leg("leg", n_success=0, n_errors=0)


class _FakeStatusResponse:
    """Minimal stand-in for the scoring client's response object, scoped to
    what _compute_g2_q_values / _compute_g4_group_means read: .status_code
    and .json()."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeG2Client:
    """Fake client for _compute_g2_q_values: every /baseline POST returns
    `baseline_status_code` (controllable per test, to simulate a dropped
    upload) UNLESS its "text" is listed in `fail_baseline_texts`, in which
    case that specific upload fails regardless of `baseline_status_code` —
    used to isolate a failure to one leg's baseline pool without touching
    the other's. Every /score POST succeeds with a canned typicality
    payload."""

    def __init__(self, baseline_status_code=200, fail_baseline_texts=frozenset()):
        self.baseline_status_code = baseline_status_code
        self.fail_baseline_texts = frozenset(fail_baseline_texts)

    def post(self, url, json=None):
        if url.endswith("/baseline"):
            if json is not None and json.get("text") in self.fail_baseline_texts:
                return _FakeStatusResponse(500)
            return _FakeStatusResponse(self.baseline_status_code)
        if url.endswith("/score"):
            return _FakeStatusResponse(
                200, {"typicality_p_far": 0.5, "typicality_p_central": 0.5}
            )
        return _FakeStatusResponse(200, {})


class TestComputeG2QValuesBaselineHealthCheck:
    """Regression test for the reproducibility bug diagnosed in the Task 3
    report: _compute_g2_q_values used to POST each holdout baseline chunk
    without checking the response status, so a dropped upload silently
    shrank that dialogue's LOO sample count (and hence its q-value
    denominator) without raising anything — producing a different,
    non-comparable result on a later run even with byte-identical corpus
    input. The fix reuses _require_healthy_leg (same convention as every
    other scoring leg in this file) to fail loudly instead."""

    def _one_dialogue(self, n_chunks=6):
        return {"plato_testdialogue": [f"chunk{i}" for i in range(n_chunks)]}

    def test_raises_when_holdout_baseline_uploads_mostly_fail(self, monkeypatch):
        import validation.calibration_gate as cg

        monkeypatch.setattr(cg, "_load_plato_texts_by_dialogue", self._one_dialogue)
        client = _FakeG2Client(baseline_status_code=500)

        with pytest.raises(RuntimeError):
            cg._compute_g2_q_values(client)

    def test_healthy_baseline_uploads_still_produce_holdout_q(self, monkeypatch):
        import validation.calibration_gate as cg

        monkeypatch.setattr(cg, "_load_plato_texts_by_dialogue", self._one_dialogue)
        client = _FakeG2Client(baseline_status_code=200)

        holdout_q, _impostor_q, _n_holdout_errors = cg._compute_g2_q_values(client)

        assert holdout_q == [0.5]


class TestComputeG2QValuesImpostorSharedPoolRaise:
    """Site #3, the most severe of the seven unchecked-baseline-POST call
    sites: the impostor leg builds ONE shared reference pool
    (`reference_dialogues`) reused to score every impostor text (Eryxias
    chunks + ai_*.txt). A single failed baseline upload into that shared
    pool silently degrades EVERY subsequent impostor score, not just one
    fold — the per-fold "skip and count" convention used elsewhere in this
    file (see TestComputeG2QValuesBaselineHealthCheck) would routinely stay
    under _require_healthy_leg's 10% pooled-error threshold while still
    poisoning 100% of the impostor q-values, so this leg must raise
    immediately on any reference-pool baseline failure instead."""

    def _dialogues(self):
        return {
            "plato_apology": [f"chunk{i}" for i in range(6)],
            # Below the >= 5 LOO minimum -- excluded from the holdout loop
            # entirely (see the "len(chunks) < 5" skip), but its chunks
            # still feed the impostor leg's shared reference pool (which has
            # no length filter). This isolates a reference-pool-only
            # baseline failure from the holdout leg, so a failure here can
            # only be explained by the impostor leg's guard.
            "plato_short": ["short_0", "short_1"],
            "plato_eryxias": ["ery_0", "ery_1"],
        }

    def test_raises_immediately_when_any_reference_pool_upload_fails(self, monkeypatch):
        import validation.calibration_gate as cg

        monkeypatch.setattr(cg, "_load_plato_texts_by_dialogue", self._dialogues)
        client = _FakeG2Client(fail_baseline_texts={"short_0"})

        with pytest.raises(RuntimeError, match="impostor leg"):
            cg._compute_g2_q_values(client)

    def test_healthy_reference_pool_does_not_raise(self, monkeypatch):
        import validation.calibration_gate as cg

        monkeypatch.setattr(cg, "_load_plato_texts_by_dialogue", self._dialogues)
        client = _FakeG2Client()

        # Must not raise -- a healthy shared pool is the normal case.
        _holdout_q, impostor_q, _n_holdout_errors = cg._compute_g2_q_values(client)
        # eryxias chunks (2) score against the healthy shared pool.
        assert len(impostor_q) >= 2


class _FakeG2bClient:
    """Fake client for _compute_g2b_paraphrase_data — same shape as
    _FakeG2Client (the two functions share the same baseline/score call
    pattern; G2b additionally wraps them in _uniformity_features_enabled,
    which this fake doesn't need to know about)."""

    def __init__(self, fail_baseline_texts=frozenset()):
        self.fail_baseline_texts = frozenset(fail_baseline_texts)

    def post(self, url, json=None):
        if url.endswith("/baseline"):
            if json is not None and json.get("text") in self.fail_baseline_texts:
                return _FakeStatusResponse(500)
            return _FakeStatusResponse(200)
        if url.endswith("/score"):
            return _FakeStatusResponse(
                200, {"typicality_p_far": 0.5, "typicality_p_central": 0.5}
            )
        return _FakeStatusResponse(200, {})


class TestComputeG2bParaphraseDataBaselineFailures:
    """Sites #4 and #5 of the RP-3c audit: _compute_g2b_paraphrase_data
    repeats _compute_g2_q_values's machinery (same two shapes: per-fold
    holdout leg, shared-pool impostor leg — see
    TestComputeG2QValuesBaselineHealthCheck /
    TestComputeG2QValuesImpostorSharedPoolRaise for the fully-worked-out
    versions of these two tests). Lighter treatment here since the
    underlying logic being exercised is identical to G2's."""

    def _dialogues(self):
        return {
            "plato_apology": [f"chunk{i}" for i in range(6)],
            # Below the >= 5 LOO minimum -- feeds only the shared reference
            # pool, isolating a pool-only failure from the holdout leg.
            "plato_short": ["short_0", "short_1"],
            "plato_eryxias": ["ery_0", "ery_1"],
        }

    def _patch(self, monkeypatch, tmp_path):
        import validation.calibration_gate as cg

        monkeypatch.setattr(cg, "_load_plato_texts_by_dialogue", self._dialogues)
        monkeypatch.setattr(cg, "_ROOT", tmp_path)
        (tmp_path / "validation" / "corpus").mkdir(parents=True)
        return cg

    def test_holdout_fold_skipped_and_counted_on_baseline_failure(self, monkeypatch, tmp_path):
        cg = self._patch(monkeypatch, tmp_path)
        # "plato_apology" is the only dialogue eligible for the holdout
        # loop; failing one of its baseline chunks must skip its ONLY fold
        # instead of scoring against an undersized baseline. NOTE: this
        # function's reference pool for the impostor leg (below) also draws
        # from apology's full chunk list (not just chunks[:-1]), and both
        # legs' _require_healthy_leg checks are deferred to AFTER both legs
        # run — so with only one non-eryxias dialogue in this fixture, a
        # failed apology chunk trips the impostor leg's stricter
        # shared-pool guard (raises immediately, mid-leg) before the
        # holdout leg's deferred check is ever reached. Either raise
        # correctly proves the fix: before it, this fixture's baseline
        # failure was silently ignored and every leg "succeeded" anyway.
        client = _FakeG2bClient(fail_baseline_texts={"chunk0"})

        with pytest.raises(RuntimeError):
            cg._compute_g2b_paraphrase_data(client)

    def test_impostor_shared_pool_raises_immediately_on_baseline_failure(
        self, monkeypatch, tmp_path
    ):
        cg = self._patch(monkeypatch, tmp_path)
        # "short_0" feeds only the shared reference pool (see _dialogues),
        # so the holdout leg is unaffected -- a failure here can only be
        # explained by the impostor leg's own guard.
        client = _FakeG2bClient(fail_baseline_texts={"short_0"})

        with pytest.raises(RuntimeError, match="impostor leg"):
            cg._compute_g2b_paraphrase_data(client)


class _FakeG4Client:
    """Fake client for _compute_g4_group_means: every /baseline POST returns
    `baseline_status_code` (controllable per test) UNLESS its exact URL is
    listed in `fail_baseline_urls`, which fails regardless -- used to fail
    one cross-fit half's baseline pool without touching the main
    early-group baseline loop's uploads (same chunk text can appear in
    both, so a text-based matcher can't isolate them; the URL differs:
    "{sid}/baseline" for the main loop vs. "{sid}_loo_{tag}/baseline" for
    each cross-fit half). Every /score POST succeeds with a canned
    deviation_score payload."""

    def __init__(self, baseline_status_code=200, fail_baseline_urls=frozenset()):
        self.baseline_status_code = baseline_status_code
        self.fail_baseline_urls = frozenset(fail_baseline_urls)

    def post(self, url, json=None):
        if url.endswith("/baseline"):
            if url in self.fail_baseline_urls:
                return _FakeStatusResponse(500)
            return _FakeStatusResponse(self.baseline_status_code)
        if url.endswith("/score"):
            return _FakeStatusResponse(200, {"authorship": {"deviation_score": 0.3}})
        return _FakeStatusResponse(200, {})


class TestComputeG4GroupMeansBaselineHealthCheck:
    """Same reproducibility gap as G2 (see
    TestComputeG2QValuesBaselineHealthCheck), for G4's early-group baseline
    upload loop — a dropped upload there silently shrinks the early-group
    baseline that middle/late are scored against, without changing the
    on-disk corpus. "apology" is a real early-group dialogue slug (see
    validation/plato/chronology.ranked()), so plato_texts only needs one
    entry to populate groups["early"]."""

    def _early_only(self, n_chunks=6):
        return {"plato_apology": [f"chunk{i}" for i in range(n_chunks)]}

    def test_raises_when_early_baseline_uploads_mostly_fail(self):
        client = _FakeG4Client(baseline_status_code=500)

        with pytest.raises(RuntimeError):
            _compute_g4_group_means(plato_texts=self._early_only(), client=client)

    def test_healthy_early_baseline_uploads_still_compute_group_means(self):
        client = _FakeG4Client(baseline_status_code=200)

        group_means, _stats = _compute_g4_group_means(
            plato_texts=self._early_only(), client=client
        )

        assert group_means["early"] == pytest.approx(0.3)


class TestComputeG4GroupMeansCrossFitBaselineFailure:
    """Site #7's second half: the cross-fit LOO branch (score_early_loo=True,
    used by G5's shuffled G4 draws — see _compute_g4_group_means's
    docstring) uploads each half of the early group as a SHARED baseline
    pool used to score every held-out chunk in the OTHER half — the same
    shared-sub-pool shape as the main early-group loop above, at half
    scale. A dropped upload into one half's pool must not be silently
    absorbed; it must raise, same as the main loop's health check."""

    def test_raises_when_one_halfs_baseline_uploads_fail(self):
        sid = "demo:gate_g4_crossfit_test"
        plato_texts = {"plato_apology": ["e0", "e1"]}
        # half_a = [e0] (stride-2 index 0), half_b = [e1] (index 1). Tag "a"
        # uploads half_b (e1) as loo_sid_a's baseline pool -- fail THAT
        # upload only; the main early-group loop uploads e0 and e1 to
        # `sid` (not loo_sid_a), so it is unaffected and passes its own
        # health check first.
        loo_sid_a = f"{sid}_loo_a"
        client = _FakeG4Client(fail_baseline_urls={f"/students/{loo_sid_a}/baseline"})

        with pytest.raises(RuntimeError, match="cross-fit"):
            _compute_g4_group_means(
                plato_texts=plato_texts, sid=sid, score_early_loo=True, client=client
            )


class TestG6Fairness:
    """All four zero/non-zero rate cases are pinned. The inherited
    'handles zero native fpr without division error' test (whose only
    assertion was isinstance(passed, bool)) was REMOVED: it blessed the
    defect below — an infinite disparity silently returning ratio 1.0."""

    def test_passes_when_both_rates_nonzero_and_ratio_at_most_two(self):
        result = evaluate_g6_fairness(
            native_fpr=0.04,
            non_native_fpr=0.06,
        )
        assert result.passed is True
        assert result.detail["ratio"] == pytest.approx(1.5)

    def test_fails_when_both_rates_nonzero_and_ratio_exceeds_two(self):
        result = evaluate_g6_fairness(
            native_fpr=0.02,
            non_native_fpr=0.10,  # 5x — matches the documented NNE risk direction
        )
        assert result.passed is False

    def test_exactly_one_zero_rate_is_an_infinite_disparity_not_a_pass(self):
        """One group never flagged and the other flagged 5% of the time is
        the most fairness-relevant small-sample case there is. It must fail,
        never collapse to ratio 1.0. This IS real signal (Task 6): verdict
        stays "fail", not "uninformative" — unlike the both-zero case, this
        is genuine evidence of disparity, not an absence of evidence."""
        result = evaluate_g6_fairness(native_fpr=0.0, non_native_fpr=0.05)
        assert result.passed is False
        assert result.verdict == "fail"
        assert result.detail["ratio_status"] == "one_group_zero"
        assert result.detail["ratio"] == float("inf")
        assert "infinite" in result.current_value.lower()
        # Direction-symmetric.
        mirrored = evaluate_g6_fairness(native_fpr=0.05, non_native_fpr=0.0)
        assert mirrored.passed is False
        assert mirrored.verdict == "fail"

    def test_both_rates_zero_is_undefined_not_a_pass(self):
        """Zero flags in both groups demonstrates no fairness — it is an
        absence of evidence, and must not render as a green gate. This is a
        genuinely can't-know outcome (Task 6): verdict is "uninformative",
        not "fail" — a "fail" would claim disparity evidence that isn't
        there."""
        result = evaluate_g6_fairness(native_fpr=0.0, non_native_fpr=0.0)
        assert result.passed is False
        assert result.verdict == "uninformative"
        assert result.detail["ratio_status"] == "undefined_both_zero"
        assert result.detail["ratio"] is None
        assert result.current_value.startswith("UNDEFINED")

    def test_medium_effect_size_is_surfaced_in_current_value(self):
        """The Welch bridge is contradicting evidence — _analyze_dimension
        would read a medium effect as NOT FAIR. The ratio stays the verdict
        (per spec), but the disagreement cannot hide in attach-only detail."""
        result = evaluate_g6_fairness(
            native_fpr=0.04,
            non_native_fpr=0.06,
            welch_effect_magnitude="medium",
            welch_cohens_d=0.504,
        )
        assert result.passed is True
        assert "medium" in result.current_value
        assert "0.504" in result.current_value

    def test_negligible_effect_size_adds_no_caveat(self):
        result = evaluate_g6_fairness(
            native_fpr=0.04,
            non_native_fpr=0.06,
            welch_effect_magnitude="negligible",
            welch_cohens_d=0.03,
        )
        assert "CAVEAT" not in result.current_value

    def test_informational_cannot_overwrite_verdict_bearing_detail(self):
        result = evaluate_g6_fairness(
            native_fpr=0.04,
            non_native_fpr=0.06,
            informational={"ratio": 999.0, "native_fpr": 999.0},
        )
        assert result.detail["ratio"] == pytest.approx(1.5)
        assert result.detail["native_fpr"] == pytest.approx(0.04)

    def test_unreachable_threshold_records_loud_skip_not_a_pass(self):
        """CRITICAL: 5 essays/author scored LOO gives typicality_n=4, whose
        p_central support is {0.2 … 1.0} — the 0.02 flag threshold cannot be
        crossed by construction, so 'zero flags in both groups' is vacuous."""
        result = _g6_unreachable_threshold_result(
            observed_n=4,
            threshold=0.02,
            n_native_scored=15,
            n_non_native_scored=10,
        )
        assert result.passed is False
        assert result.verdict == "uninformative"
        assert result.current_value == (
            "SKIPPED (threshold unreachable): p_central floor 1/(n+1)=0.200 at "
            "n=4, flag threshold 0.02 needs n>=49"
        )
        assert result.detail["min_typicality_n"] == 4
        assert result.detail["p_floor"] == pytest.approx(0.2)
        assert result.detail["threshold"] == 0.02
        assert result.detail["required_n"] == 49
        assert result.detail["n_native_scored"] == 15
        assert result.detail["n_non_native_scored"] == 10

    def test_zero_observed_n_does_not_crash(self):
        """FIX E: _g6_unreachable_threshold_result calls _conformal_p_floor,
        which now delegates to validation.power.conformal_p_floor (FIX 3(a))
        and raises ValueError at n<=0 — the pre-delegation copy instead
        returned 1.0, so this caller was never re-audited when the helpers
        were delegated and would crash at observed_n=0. There is no
        production call site for observed_n<=0 today (only this test
        exercises the helper at all), so this closes a latent crash, not an
        observed failure."""
        result = _g6_unreachable_threshold_result(
            observed_n=0,
            threshold=0.02,
            n_native_scored=0,
            n_non_native_scored=0,
        )
        assert result.passed is False
        assert result.verdict == "uninformative"
        assert result.detail["p_floor"] is None
        assert result.detail["min_typicality_n"] == 0
        assert "n=0" in result.current_value
        assert "undefined" in result.current_value

    def test_short_group_message_names_both_groups_when_both_are_short(self):
        both = _g6_short_group_message(2, 1, 5)
        assert "native_english=true" in both and "native_english=false" in both
        only_non_native = _g6_short_group_message(15, 1, 5)
        assert "native_english=false" in only_non_native
        assert "native_english=true" not in only_non_native

    def test_insufficient_data_records_loud_skip_not_a_pass(self):
        """Honest-instrument convention: a corpus without enough
        native_english-annotated authentic entries must surface as a loud
        SKIPPED result — passed must NOT be silently true."""
        result = _g6_insufficient_data_result(
            "native_english=false group has 0 scored authentic entries (need >= 5)",
            n_native_scored=15,
            n_non_native_scored=0,
        )
        assert result.name == "G6"
        assert result.passed is False
        assert result.verdict == "uninformative"
        assert result.current_value.startswith("SKIPPED (insufficient data):")
        assert result.detail["n_non_native_scored"] == 0
        assert "0 scored authentic entries" in result.detail["missing"]

    def test_criterion_scopes_the_verdict_to_the_p_central_action(self):
        """Spec's G6 row also names the Phase-4 uniformity features. Those
        are recorded as measurement, not gated — the criterion string must
        say so plainly rather than implying full coverage."""
        criterion = evaluate_g6_fairness(0.04, 0.06).criterion
        assert "p_central action ONLY" in criterion
        assert "not gated" in criterion


class TestUniformitySliceSummary:
    def test_reports_per_group_means_and_flags_constant_features(self):
        summary = _uniformity_slice_summary(
            {
                True: [{"a": 0.5, "b": 0.1}, {"a": 0.5, "b": 0.3}],
                False: [{"a": 0.5, "b": 0.9}],
            }
        )
        assert summary["native_english_true_means"]["b"] == pytest.approx(0.2)
        assert summary["native_english_false_means"]["b"] == pytest.approx(0.9)
        # "a" never varies anywhere in the slice — a constant feature cannot
        # carry a fairness signal, and the Tier-18 bounds miscalibration makes
        # that a real possibility, so it is called out by name.
        assert summary["constant_across_slice"] == ["a"]
        assert summary["gated"] is False

    def test_empty_groups_do_not_raise(self):
        summary = _uniformity_slice_summary({True: [], False: []})
        assert summary["native_english_true_means"] == {}
        assert summary["constant_across_slice"] == []


class TestG2bParaphraseResistance:
    def test_passes_when_paraphrased_impostor_q_still_lower_than_holdout(self):
        result = evaluate_g2b_paraphrase_resistant(
            holdout_q=[0.5, 0.48, 0.5],
            paraphrased_impostor_q=[0.15, 0.1],
        )
        assert result.passed is True

    def test_fails_when_paraphrase_defeats_the_signal(self):
        """Documents the expected real-world outcome per the design spec's
        research review — this SHOULD fail with a naive implementation,
        which is itself the finding G2b exists to surface."""
        result = evaluate_g2b_paraphrase_resistant(
            holdout_q=[0.5, 0.48, 0.5],
            paraphrased_impostor_q=[0.6, 0.55],  # paraphrase raised q above holdout
        )
        assert result.passed is False

    def test_criterion_and_detail_label_the_mechanical_proxy(self):
        """Standing decision: G2b must never be presentable as an
        LLM-paraphrase robustness claim. Both the criterion string and the
        detail must carry the proxy label."""
        result = evaluate_g2b_paraphrase_resistant(
            holdout_q=[0.5], paraphrased_impostor_q=[0.1]
        )
        proxy_label = "paraphrase proxy (mechanical transformation, not LLM paraphrase)"
        assert proxy_label in result.criterion
        assert proxy_label in result.detail["proxy_note"]

    def test_proxy_note_states_the_measured_limits_of_the_transform(self):
        """The reviewer measured them: ~1% of tokens substituted, and three
        of the six Tier-18 features invariant by construction. Those numbers
        belong in the gate's own report, not in a review thread."""
        note = evaluate_g2b_paraphrase_resistant([0.5], [0.1]).detail["proxy_note"]
        assert "~1% of tokens" in note
        assert "sentence_length_dispersion_ratio" in note
        assert "punctuation_dispersion_ratio" in note
        assert "clause_depth_variance_ratio" in note
        assert "invariant" in note

    def test_informational_cannot_overwrite_the_proxy_note(self):
        result = evaluate_g2b_paraphrase_resistant(
            [0.5], [0.1], informational={"proxy_note": "validated against real attacks"}
        )
        assert "not LLM paraphrase" in result.detail["proxy_note"]

    def test_paraphrase_proxy_is_deterministic_and_rewrites_the_text(self):
        text = (
            "This point is important. However, the essay shows that we use "
            "many words. Therefore we think the argument is very good."
        )
        out1 = _paraphrase_proxy(text)
        out2 = _paraphrase_proxy(text)
        assert out1 == out2  # deterministic — no hidden randomness
        assert out1 != text  # actually transforms the input

    def test_paraphrase_proxy_preserves_paragraph_structure(self):
        """The first cut split on sentences and rejoined with single spaces,
        collapsing every 6-paragraph essay to 1 — which moved
        avg_paragraph_length by 0.77 normalized and pushed two features to
        their 'cannot compute' placeholder, swamping the <=0.036 movement in
        the Tier-18 features the gate actually exists to stress."""
        text = (
            "Alpha one. Beta two.\n\n"
            "Gamma three. Delta four.\n\n"
            "Epsilon five. Zeta six."
        )
        out = _paraphrase_proxy(text)
        assert out.count("\n\n") == text.count("\n\n") == 2
        paragraphs = out.split("\n\n")
        assert len(paragraphs) == 3
        # Sentences swap WITHIN a paragraph, never across the boundary.
        assert paragraphs[0].startswith("Beta two.")
        assert paragraphs[1].startswith("Delta four.")
        assert "Gamma" not in paragraphs[0]

    def test_paraphrase_proxy_preserves_the_exact_original_separators(self):
        text = "One. Two.\n\n\nThree. Four.\n\nFive. Six."
        out = _paraphrase_proxy(text)
        assert "\n\n\n" in out
        assert out.count("\n") == text.count("\n")


class TestUniformityEnablementGuard:
    def test_restores_exact_prior_state_even_on_exception(self):
        """DISABLED_FEATURE_GROUPS is a process-global module-level set read
        at feature-extraction call time — a leaked discard('uniformity')
        would silently change every later leg's feature vectors. The guard
        must restore the exact prior state on both the clean and the
        exception path."""
        from original.constants import DISABLED_FEATURE_GROUPS

        before = set(DISABLED_FEATURE_GROUPS)
        try:
            # Clean path.
            with _uniformity_features_enabled():
                assert "uniformity" not in DISABLED_FEATURE_GROUPS
            assert DISABLED_FEATURE_GROUPS == before
            # Exception path.
            with pytest.raises(RuntimeError, match="boom"):
                with _uniformity_features_enabled():
                    assert "uniformity" not in DISABLED_FEATURE_GROUPS
                    raise RuntimeError("boom")
            assert DISABLED_FEATURE_GROUPS == before
        finally:
            # Belt-and-braces: never let THIS test leak state either.
            DISABLED_FEATURE_GROUPS.clear()
            DISABLED_FEATURE_GROUPS.update(before)


class TestG5MachineryErrors:
    def test_machinery_error_result_fails_without_masquerading_as_a_verdict(self):
        """run_all()'s G5 wrapper: a crash in the shuffled legs must render as
        a FAILED gate clearly labeled as a machinery error, so it can neither
        discard the four completed real gates nor read as a genuine null
        verdict."""
        result = _g5_machinery_error_result(
            RuntimeError("G5 shuffled G3 leg: zero successful scoring folds")
        )
        assert result.name == "G5"
        assert result.passed is False
        assert result.current_value.startswith("ERROR (machinery):")
        assert "zero successful scoring folds" in result.detail["machinery_error"]

    def test_run_g5_refuses_an_empty_real_deviation_sample(self):
        """The deviation-shift criterion needs the real leg's sample; an empty
        one is a machinery failure, not a comparison point."""
        with pytest.raises(RuntimeError):
            run_g5(real_g1_deviations=[])

    def test_run_g5_health_checks_the_real_anchor_leg(self):
        """A 4xx-riddled real G1 anchor (>10% scoring errors) must become a
        machinery error, not a silently weakened comparison baseline."""
        with pytest.raises(RuntimeError):
            run_g5(real_g1_deviations=[0.4] * 89, real_g1_n_errors=11)


class TestGateVerdicts:
    def test_verdict_defaults_from_passed(self):
        r = GateResult(name="X", passed=True, criterion="c", current_value="v")
        assert r.verdict == "pass"
        r = GateResult(name="X", passed=False, criterion="c", current_value="v")
        assert r.verdict == "fail"

    def test_explicit_uninformative_verdict_sticks(self):
        r = GateResult(
            name="X", passed=False, criterion="c", current_value="v",
            verdict="uninformative",
        )
        assert r.verdict == "uninformative"
        assert r.passed is False


class TestG1Informativeness:
    def test_unreachable_band_turns_clean_pass_into_uninformative(self):
        actions = ["no_action"] * 216
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 12, "s2": 8},
            band_threshold=0.03,
        )
        assert result.verdict == "uninformative"
        assert result.passed is False
        power = result.detail["power"]
        assert power["min_conformal_p_at_max_n"] == conformal_p_floor(12)
        assert power["entities_reachable"] == 0
        assert power["rule_of_three_fpr_upper"] == 3 / 216

    def test_reachable_entities_keep_a_clean_pass_informative(self):
        actions = ["no_action"] * 216
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 40},
            band_threshold=0.03,
        )
        assert result.verdict == "pass"

    def test_a_real_failure_is_never_downgraded_to_uninformative(self):
        actions = ["monitor"] * 30 + ["no_action"] * 70
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 12},
        )
        assert result.verdict == "fail"

    def test_omitting_counts_preserves_legacy_behavior(self):
        actions = ["no_action"] * 95 + ["monitor"] * 5
        result = evaluate_g1_fpr(actions, per_corpus={"synthetic": actions})
        assert result.verdict == "pass"
        assert result.passed is True


class TestG3Informativeness:
    """
    G1's arithmetic floor has a sampling-uncertainty twin. At n=22 held-out
    essays a G3 FAIL is real (CI upper 0.653 < 0.7) but a G3 PASS is not
    evidence (0.818 → CI [0.615, 0.927], straddling the bar).
    """

    def test_measured_failure_stays_a_real_failure(self):
        result = evaluate_g3_attribution(0.455, n_essays=22)
        assert result.verdict == "fail"
        assert result.detail["power"]["bar_decidable"] == "below"

    def test_pass_above_the_bar_is_uninformative_at_n22(self):
        result = evaluate_g3_attribution(18 / 22, n_essays=22)
        assert result.verdict == "uninformative"
        assert result.passed is False
        ci = result.detail["power"]["wilson_ci"]
        assert ci[0] < 0.7 < ci[1]

    def test_pass_is_informative_when_n_supports_it(self):
        result = evaluate_g3_attribution(230 / 306, n_essays=306)
        assert result.verdict == "pass"

    def test_omitting_n_preserves_legacy_behavior(self):
        assert evaluate_g3_attribution(0.9).verdict == "pass"
        assert evaluate_g3_attribution(0.455).verdict == "fail"

    def test_the_real_measured_number_is_uninformative_but_n_essays_none_would_pass(self):
        """FIX 1's exact motivating scenario, pinned on the real measured
        number: 0.7273 (validation/benchmarks/2026-07-31/public_authors/
        report.json, n=22) is UNINFORMATIVE with the real n_essays wired
        through, but would silently report a bare "pass" if n_essays were
        None — precisely what happens if run_all() ever fed None through
        (see TestG3InputsFromPaReport below for the producer/consumer
        contract that stops that from happening silently)."""
        with_n = evaluate_g3_attribution(0.7273, n_essays=22)
        without_n = evaluate_g3_attribution(0.7273, n_essays=None)
        assert with_n.verdict == "uninformative"
        assert without_n.verdict == "pass"
        assert without_n.passed is True


class TestG3InputsFromPaReport:
    """
    FIX 1: run_all() used to read `pa_summary.get("n_scored_essays")`
    inline — a bare `.get()` with a `None` default that can't tell "the
    corpus legitimately produced no summary" (run()'s documented < 2
    -eligible-authors error path) apart from "the summary exists but this
    one key is missing" (a machinery bug: run.py's producer contract
    broke). Both used to silently feed n_essays=None into
    evaluate_g3_attribution, reverting G3 to legacy two-valued pass/fail —
    see test_the_real_measured_number_is_uninformative_but_n_essays_none_
    would_pass above for why that's dangerous on the real number.

    _g3_inputs_from_pa_report() is the extracted, unit-testable version of
    that branch (same convention as _g1_entity_baseline_counts): these
    tests exercise it directly against synthetic pa_report dicts, without
    running validation.public_authors.run.run()'s live-TestClient scoring.
    grep -rn n_scored_essays tests/ returned zero hits before this file —
    this is the first coverage of that key anywhere in the suite.
    """

    def test_normal_summary_extracts_all_three_fields_silently(self, capsys):
        pa_report = {
            "summary": {
                "top1_accuracy": 0.7273,
                "top1_accuracy_raw_argmin": 0.6818,
                "n_scored_essays": 22,
            }
        }
        top1, top1_raw, n_essays = _g3_inputs_from_pa_report(pa_report)
        assert (top1, top1_raw, n_essays) == (0.7273, 0.6818, 22)
        assert capsys.readouterr().err == ""

    def test_no_summary_at_all_is_the_silent_legitimate_error_path(self, capsys):
        """run() returns {"error": ..., "skipped_authors": [...]} with no
        "summary" key when fewer than 2 authors are eligible — nothing is
        broken here, so no warning should print."""
        pa_report = {"error": "Need at least 2 eligible authors", "skipped_authors": []}
        top1, top1_raw, n_essays = _g3_inputs_from_pa_report(pa_report)
        assert (top1, top1_raw, n_essays) == (0.0, None, None)
        assert capsys.readouterr().err == ""

    def test_summary_present_but_missing_the_key_warns_loudly(self, capsys):
        """The machinery-bug case FIX 1 exists to catch: a renamed or
        dropped "n_scored_essays" key in run.py's summary. Must warn on
        stderr, name the missing key, and NOT crash."""
        pa_report = {"summary": {"top1_accuracy": 0.7273}}
        top1, top1_raw, n_essays = _g3_inputs_from_pa_report(pa_report)
        assert (top1, top1_raw, n_essays) == (0.7273, None, None)
        err = capsys.readouterr().err
        assert "n_scored_essays" in err
        assert "public_authors summary" in err


class TestG1LooOffByOne:
    """FIX 1: the conformal N for a G1 fold is len(texts) - 1 (the per-fold
    LOO baseline size), NOT len(texts) — _score_corpus_for_g1 posts every
    text EXCEPT the held-out one. A 33-document entity's folds therefore see
    n=32, one short of what the default 0.03 band needs (n>=33)."""

    def test_33_documents_loo_n_32_is_not_reachable_at_the_003_band(self):
        actions = ["no_action"] * 216
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 32},  # 33 docs - 1
            band_threshold=0.03,
        )
        assert result.verdict == "uninformative"
        assert result.detail["power"]["entities_reachable"] == 0

    def test_34_documents_loo_n_33_is_reachable_at_the_003_band(self):
        actions = ["no_action"] * 216
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 33},  # 34 docs - 1
            band_threshold=0.03,
        )
        assert result.verdict == "pass"
        assert result.detail["power"]["entities_reachable"] == 1


class TestG1EntityBaselineCounts:
    """FIX C: the previous round's run_all() change to
    `entity_baseline_counts = len(texts) - 1` (FIX 1) was never actually
    exercised by a test — TestG1LooOffByOne above passes already-decremented
    literals (`{"s1": 32}` / `{"s1": 33}`) straight into evaluate_g1_fpr, so
    both of those tests pass identically against a buggy `len(texts)`
    (no `- 1`) version too. This targets the extracted
    `_g1_entity_baseline_counts` helper itself, which performs the `- 1`
    conversion run_all() now delegates to."""

    def test_subtracts_one_from_each_entitys_document_count(self):
        texts_by_id = {"s1": ["doc"] * 33, "s2": ["doc"] * 12}
        per_corpus_actions = {"s1": ["no_action"] * 33, "s2": ["no_action"] * 12}
        counts = _g1_entity_baseline_counts(texts_by_id, per_corpus_actions)
        assert counts == {"s1": 32, "s2": 11}

    def test_omits_entities_that_never_produced_a_fold(self):
        """An entity present in texts_by_id but absent from
        per_corpus_actions (skipped by _score_corpus_for_g1's own
        `len(texts) < 5` guard) must not appear in the result at all —
        FIX 5's rationale, now covered directly on the extracted helper."""
        texts_by_id = {"s1": ["doc"] * 33, "too_short": ["doc"] * 2}
        per_corpus_actions = {"s1": ["no_action"] * 33}
        counts = _g1_entity_baseline_counts(texts_by_id, per_corpus_actions)
        assert counts == {"s1": 32}
        assert "too_short" not in counts

    def test_empty_per_corpus_actions_yields_empty_counts(self):
        counts = _g1_entity_baseline_counts({"s1": ["doc"] * 33}, {})
        assert counts == {}


class TestG1FlaggedNeverDowngraded:
    """FIX 2: a real flagged rate (flagged > 0) is evidence, not arithmetic
    — an unreachable band must never suppress it, and current_value must
    never grow a zero-rate sentence when the rate isn't zero."""

    def test_flagged_greater_than_zero_stays_pass_and_prints_no_zero_rate_sentence(self):
        # 4 monitor + 212 no_action = 1.9%, a would-be pass, but every
        # entity's baseline count leaves the 0.03 band unreachable.
        actions = ["monitor"] * 4 + ["no_action"] * 212
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 12},
            band_threshold=0.03,
        )
        assert result.verdict == "pass"
        assert result.passed is True
        assert "UNINFORMATIVE" not in result.current_value
        rendered = render([result])
        assert "Observed 0-rate" not in rendered
        assert "n/a" not in rendered

    def test_render_prints_the_rule_of_three_bound_when_flagged_is_zero(self):
        """Sanity companion: when flagged really is zero, the sentence DOES
        print, and the FIX 2 None-guard removal doesn't crash — this is
        never "n/a" because flagged == 0 guarantees rule_of_three_upper(n)
        is computed."""
        actions = ["no_action"] * 216
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 12},
            band_threshold=0.03,
        )
        rendered = render([result])
        assert "Observed 0-rate bounds FPR only above" in rendered
        assert "n/a" not in rendered


class TestG1DisagreeingMechanismsInvariant:
    """FIX 3(b): entity_baseline_counts (any-reachable, i.e. MAX over
    entities) and typicality_ns (binding, i.e. MIN over folds) estimate the
    same reachability question from different data and CAN disagree. A
    "pass" verdict must never coexist with an "UNINFORMATIVE" annotation in
    current_value regardless of which mechanism is the one objecting."""

    def test_entity_counts_reachable_but_typicality_ns_unreachable_stays_uninformative(self):
        actions = ["no_action"] * 100
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"synthetic": actions},
            typicality_ns=[12] * 100,  # worst fold unreachable
            entity_baseline_counts={"s1": 40},  # would be reachable alone
            band_threshold=0.03,
        )
        assert result.verdict == "uninformative"
        assert result.passed is False
        assert "UNINFORMATIVE" in result.current_value

    def test_pass_verdict_never_carries_an_uninformative_annotation(self):
        """Property check across nflag x typicality_ns x
        entity_baseline_counts combinations: whenever the verdict comes back
        "pass", current_value must be clean.

        REPLACES a vacuous predecessor: the old version used
        `["no_action"] * 100` (flagged == 0) in all four scenarios, so no
        scenario could ever produce an annotation in the first place — the
        `if result.verdict == "pass": assert ...` body was unreachable-or-
        trivial and passed identically against the pre-fix code (the exact
        defect class this module exists to catch). This version sweeps
        nflag in {0, 1, 4} so the flagged > 0 path — where the FIX-A defect
        actually lived (a nonzero flagged rate under an unreachable
        typicality band still rendered `G1 [PASS] ... (UNINFORMATIVE:
        ...)`) — is genuinely exercised. Confirmed (see task report) that
        this test fails against the pre-fix code and passes against it."""
        n = 100
        typicality_ns_options = [None, [3] * n, [60] * n]  # unreachable / reachable
        entity_baseline_counts_options: list[dict[str, int] | None] = [
            None,
            {"s": 5},  # unreachable at the 0.03 default band
            {"s": 40},  # reachable at the 0.03 default band
        ]
        for nflag in (0, 1, 4):
            actions = ["monitor"] * nflag + ["no_action"] * (n - nflag)
            for typicality_ns in typicality_ns_options:
                for entity_baseline_counts in entity_baseline_counts_options:
                    result = evaluate_g1_fpr(
                        actions,
                        per_corpus={"synthetic": actions},
                        typicality_ns=typicality_ns,
                        entity_baseline_counts=entity_baseline_counts,
                        band_threshold=0.03,
                    )
                    if result.verdict == "pass":
                        assert "UNINFORMATIVE" not in result.current_value, (
                            f"nflag={nflag} typicality_ns={typicality_ns} "
                            f"entity_baseline_counts={entity_baseline_counts} "
                            f"current_value={result.current_value!r}"
                        )


class TestG1DegenerateEntityCounts:
    """FIX 5: a non-positive per-entity baseline count must never crash the
    gate — band_reachable/conformal_p_floor are undefined below n=1 and
    raise ValueError, so a degenerate count is treated as unreachable
    directly instead."""

    def test_zero_count_entity_does_not_crash_and_is_unreachable(self):
        actions = ["no_action"] * 100
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"synthetic": actions},
            entity_baseline_counts={"s1": 0, "s2": 40},
            band_threshold=0.03,
        )
        # s2 (40) is reachable, so the pass survives — but the zero-count
        # entity must not have crashed the evaluation to get here.
        assert result.verdict == "pass"
        assert result.detail["power"]["entities_total"] == 2
        assert result.detail["power"]["entities_reachable"] == 1

    def test_all_non_positive_counts_do_not_crash_render(self):
        actions = ["no_action"] * 100
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"synthetic": actions},
            entity_baseline_counts={"s1": 0, "s2": -1},
            band_threshold=0.03,
        )
        assert result.verdict == "uninformative"
        assert result.detail["power"]["max_entity_n"] == 0
        assert result.detail["power"]["min_conformal_p_at_max_n"] is None
        rendered = render([result])  # must not raise
        assert "n/a" in rendered


class TestGateResultConsistencyValidation:
    """FIX 6: passed and verdict must always agree — closes the drift class
    that let `passed=False, verdict="pass"` and `passed=True,
    verdict="fail"` both through (only the uninformative/passed=True
    combination was rejected before)."""

    def test_passed_false_with_pass_verdict_is_rejected(self):
        with pytest.raises(ValueError):
            GateResult(
                name="X", passed=False, criterion="c", current_value="v", verdict="pass"
            )

    def test_passed_true_with_fail_verdict_is_rejected(self):
        with pytest.raises(ValueError):
            GateResult(
                name="X", passed=True, criterion="c", current_value="v", verdict="fail"
            )

    def test_passed_true_with_uninformative_verdict_is_still_rejected(self):
        """Regression: the narrower pre-existing check this replaces must
        still catch its original case."""
        with pytest.raises(ValueError):
            GateResult(
                name="X",
                passed=True,
                criterion="c",
                current_value="v",
                verdict="uninformative",
            )


class TestMainExitCodes:
    """main()'s exit-code contract (FIX 4): a fail gate always exits 1; an
    uninformative gate exits 0 by default and 1 with --strict (a deliberate
    lenient default); all-pass exits 0 either way. render()/main() were
    previously untested, which is how FIX 2 and FIX 4's bugs shipped."""

    @staticmethod
    def _pass(name="G_ok"):
        return GateResult(name=name, passed=True, criterion="c", current_value="v")

    @staticmethod
    def _fail(name="G_fail"):
        return GateResult(name=name, passed=False, criterion="c", current_value="v")

    @staticmethod
    def _uninformative(name="G_uninf"):
        return GateResult(
            name=name,
            passed=False,
            criterion="c",
            current_value="v",
            verdict="uninformative",
        )

    def test_fail_gate_exits_1_in_both_modes(self, monkeypatch):
        monkeypatch.setattr(
            calibration_gate, "run_all", lambda: [self._pass(), self._fail()]
        )
        assert calibration_gate.main([]) == 1
        assert calibration_gate.main(["--strict"]) == 1

    def test_uninformative_gate_exits_0_by_default_and_1_with_strict(self, monkeypatch):
        monkeypatch.setattr(
            calibration_gate, "run_all", lambda: [self._pass(), self._uninformative()]
        )
        assert calibration_gate.main([]) == 0
        assert calibration_gate.main(["--strict"]) == 1

    def test_all_pass_exits_0_in_both_modes(self, monkeypatch):
        monkeypatch.setattr(
            calibration_gate,
            "run_all",
            lambda: [self._pass("G1"), self._pass("G2")],
        )
        assert calibration_gate.main([]) == 0
        assert calibration_gate.main(["--strict"]) == 0

    def test_uninformative_summary_line_names_the_right_gates(self, monkeypatch, capsys):
        monkeypatch.setattr(
            calibration_gate,
            "run_all",
            lambda: [
                self._pass("G3"),
                self._uninformative("G1"),
                self._uninformative("G6"),
            ],
        )
        calibration_gate.main([])
        out = capsys.readouterr().out
        assert "2 gate(s) UNINFORMATIVE (G1, G6)" in out
        assert "re-run with --strict" in out

    def test_uninformative_summary_line_prints_in_strict_mode_too(self, monkeypatch, capsys):
        """FIX 4: the summary must never be silent in EITHER mode — a
        --strict run that fails for other reasons must still name which
        gates were uninformative.

        FIX D: under --strict these gates WERE folded into `failing`, so
        the non-strict tail ("not counted as failure; re-run with
        --strict...") is false and self-referential when printed here too.
        Assert the strict tail says what actually happened instead, and
        that the non-strict wording is absent."""
        monkeypatch.setattr(
            calibration_gate, "run_all", lambda: [self._uninformative("G6")]
        )
        calibration_gate.main(["--strict"])
        out = capsys.readouterr().out
        assert "1 gate(s) UNINFORMATIVE (G6)" in out
        assert "counted as a failure because --strict is set" in out
        assert "not counted as failure" not in out
        assert "re-run with --strict" not in out

    def test_uninformative_summary_line_non_strict_wording_is_unchanged(
        self, monkeypatch, capsys
    ):
        """Companion to the strict-mode test above: the non-strict tail
        keeps its original wording exactly (FIX D only branches the tail on
        args.strict, it doesn't touch the non-strict sentence)."""
        monkeypatch.setattr(
            calibration_gate, "run_all", lambda: [self._uninformative("G6")]
        )
        calibration_gate.main([])
        out = capsys.readouterr().out
        assert (
            "not counted as failure; re-run with --strict to fail on these." in out
        )
        assert "counted as a failure because --strict is set" not in out

    def test_no_summary_line_when_nothing_is_uninformative(self, monkeypatch, capsys):
        monkeypatch.setattr(
            calibration_gate, "run_all", lambda: [self._pass(), self._fail()]
        )
        calibration_gate.main([])
        out = capsys.readouterr().out
        assert "gate(s) UNINFORMATIVE" not in out


class TestMainOutSpecG1ScoredSubset:
    """
    FIX 2: the calibration_suite experiment spec's "corpora" block used to
    report only the three LOADED corpora (43 authors / 271 documents in the
    real corpus) — but G1 actually scores a narrower pool, since
    _score_corpus_for_g1 skips any entity with < 5 texts (24 entities / 216
    folds on the real corpus). A reader of the report's "experiment" block
    could not tell G1's flagged rate came from 216 folds, not 271
    documents — exactly the raw-vs-measured conflation this validation
    layer exists to prevent. main()'s --out path now adds a "g1_scored"
    sub-block, narrowed to entities with >= 5 texts, alongside (not instead
    of) the loaded totals — those remain the correct denominator for G4
    (full Plato early/middle/late grouping) and G6 (fairness slice), which
    apply no such filter.
    """

    def test_out_spec_g1_scored_subset_matches_the_ge5_filter(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            calibration_gate,
            "run_all",
            lambda: [
                GateResult(name="G1", passed=True, criterion="c", current_value="v")
            ],
        )
        # "sem_short" and "plato_short" have < 5 texts each and must be
        # excluded from g1_scored, but still counted in the loaded totals.
        monkeypatch.setattr(
            calibration_gate,
            "_load_seminary_texts",
            lambda: {"sem_a": ["t"] * 5, "sem_short": ["t"] * 2},
        )
        monkeypatch.setattr(
            calibration_gate,
            "_load_public_authors_baseline_texts",
            lambda: {"pa_a": ["t"] * 6},
        )
        monkeypatch.setattr(
            calibration_gate,
            "_load_plato_texts_by_dialogue",
            lambda: {"plato_short": ["t"] * 3},
        )

        out_path = tmp_path / "report.json"
        calibration_gate.main(["--out", str(out_path)])
        report = json.loads(out_path.read_text())
        corpora = report["experiment"]["corpora"]

        assert set(corpora) == {"seminary", "public_authors", "plato", "g1_scored"}
        # Loaded totals are untouched — still the correct denominator for
        # G4/G6, which is why they're kept rather than narrowed in place.
        assert corpora["seminary"]["n_authors"] == 2
        assert corpora["seminary"]["n_documents"] == 7
        assert corpora["plato"]["n_authors"] == 1
        # g1_scored narrows to entities with >= 5 texts, pooled across all
        # three corpora, matching _score_corpus_for_g1's own `< 5` skip.
        assert corpora["g1_scored"]["n_authors"] == 2  # sem_a + pa_a only
        assert corpora["g1_scored"]["docs_per_author"] == {"pa_a": 6, "sem_a": 5}
        assert corpora["g1_scored"]["n_documents"] == 11
        assert corpora["g1_scored"]["provenance"] == "g1_loo_eligible_subset"
# ── Wiring-gap regression tests (review of commit 34d8ceb6) ────────────────────
#
# The pure evaluators (evaluate_g1_fpr's reachability annotation,
# evaluate_g6_fairness's Welch caveat, _g6_unreachable_threshold_result,
# _g6_short_group_message, _uniformity_slice_summary) were already unit-tested
# above and confirmed correct. What was NOT tested — and turned out to be
# unwired — is the orchestration code in validation/calibration_gate.py that
# is supposed to CALL them with real data. These tests exercise that
# orchestration with fake HTTP clients so a regression back to "machinery
# built but never invoked" fails loudly.


class _FakeG1Response:
    """Minimal stand-in for fastapi.testclient.TestClient's response object,
    scoped to what _score_corpus_for_g1 reads: .status_code and .json()."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeG1Client:
    """Minimal stand-in for the scoring client, scoped to what
    _score_corpus_for_g1 calls: .post(url, json=...) for both the
    /baseline and /score endpoints. Every /score call returns the next
    canned payload in sequence. `fail_baseline_urls` (exact-URL match) lets
    a test simulate one fold's baseline upload silently failing (a generic
    500, i.e. a genuine machinery failure), without affecting any other
    fold's baseline calls.

    `drift_baseline_urls` (exact-URL match -> status code, 202 or 409) is
    the drift-shaped equivalent: simulates the Phase-8 drift gate
    (original/routers/students_baseline.py's add_baseline) rejecting EVERY
    baseline upload for one fold as pending_review/rebaseline_required.

    `baseline_overrides` (exact (url, text) match -> status code) is the
    finest-grained control, for simulating a single fold whose baseline
    uploads are a MIX of drift-rejected and genuine failures (or a mix of
    failure and success) — something URL-only matching can't express, since
    every upload within one fold shares the same destination URL."""

    def __init__(
        self,
        score_payloads,
        fail_baseline_urls=frozenset(),
        drift_baseline_urls=None,
        baseline_overrides=None,
    ):
        self._score_payloads = list(score_payloads)
        self._score_calls = 0
        self._fail_baseline_urls = frozenset(fail_baseline_urls)
        self._drift_baseline_urls = dict(drift_baseline_urls or {})
        self._baseline_overrides = dict(baseline_overrides or {})

    @staticmethod
    def _body_for_status(status_code):
        if status_code == 202:
            return {"detail": "pending_review"}
        if status_code == 409:
            return {"detail": "rebaseline_required"}
        return {}

    def post(self, url, json=None):
        if url.endswith("/score"):
            payload = self._score_payloads[self._score_calls]
            self._score_calls += 1
            return _FakeG1Response(200, payload)
        text = (json or {}).get("text")
        if (url, text) in self._baseline_overrides:
            status = self._baseline_overrides[(url, text)]
            return _FakeG1Response(status, self._body_for_status(status))
        if url in self._drift_baseline_urls:
            status = self._drift_baseline_urls[url]
            return _FakeG1Response(status, self._body_for_status(status))
        if url in self._fail_baseline_urls:
            return _FakeG1Response(500, {})
        return _FakeG1Response(200, {})


class TestScoreCorpusForG1TypicalityWiring:
    """Gap 1: _score_corpus_for_g1 posts to /score and reads
    payload["authorship"]["deviation_score"] but, before this fix, never read
    the top-level payload["typicality_n"] — so evaluate_g1_fpr's reachability
    annotation (already correct) never received real data from run_all()."""

    def _five_fold_payloads(self, typicality_n=4):
        return [
            {
                "recommendation": {"action": "no_action"},
                "authorship": {"deviation_score": 0.1 * (i + 1)},
                "typicality_n": typicality_n,
            }
            for i in range(5)
        ]

    def test_returns_six_tuple_with_pooled_typicality_ns(self):
        client = _FakeG1Client(self._five_fold_payloads(typicality_n=4))
        texts_by_id = {"author_a": ["t0", "t1", "t2", "t3", "t4"]}

        result = _score_corpus_for_g1(client, "g1test", texts_by_id)

        assert len(result) == 6
        pooled, per_corpus, deviations, n_errors, typicality_ns, n_drift_rejected = result
        assert pooled == ["no_action"] * 5
        assert per_corpus == {"author_a": ["no_action"] * 5}
        assert n_errors == 0
        assert n_drift_rejected == 0
        assert typicality_ns == [4, 4, 4, 4, 4]
        # Index-aligned with pooled_actions/pooled_deviations, per the
        # docstring's contract.
        assert len(typicality_ns) == len(pooled) == len(deviations)

    def test_typicality_ns_omitted_for_entities_below_the_five_text_minimum(self):
        client = _FakeG1Client(self._five_fold_payloads(typicality_n=4))
        # Only 4 texts -- below the >= 5 LOO minimum, so no folds are scored
        # and nothing is appended for this entity.
        texts_by_id = {"author_b": ["t0", "t1", "t2", "t3"]}

        pooled, per_corpus, deviations, n_errors, typicality_ns, n_drift_rejected = (
            _score_corpus_for_g1(client, "g1test", texts_by_id)
        )

        assert pooled == []
        assert typicality_ns == []
        assert n_drift_rejected == 0


class TestRunAllG1Wiring:
    """run_all() must unpack _score_corpus_for_g1's new 5-tuple and forward
    the collected typicality_ns into evaluate_g1_fpr — the whole point of
    Gap 1. run_all() itself is too heavy for a fast unit test (it stands up
    the real FastAPI app and scores the full seminary+public_authors+Plato
    corpus), so this pins the wiring at the one seam that matters: calling
    evaluate_g1_fpr with a keyword argument evaluate_g1_fpr already knows how
    to use is what makes the reachability annotation fire in production."""

    def test_evaluate_g1_fpr_reachability_fires_with_real_typicality_ns(self):
        """Regression pin at the evaluator boundary: when run_all() forwards
        genuine typicality_ns (as opposed to the omitted-argument default),
        an unreachable-threshold corpus must annotate current_value -- this
        is the exact mechanism Gap 1's fix makes reachable from run_all()."""
        from original.quantum.typicality import NO_ACTION_FAR_THRESHOLD

        pooled_actions = ["no_action"] * 10
        per_corpus = {"synthetic": pooled_actions}
        # n=1 is far below what NO_ACTION_FAR_THRESHOLD needs -- unreachable.
        typicality_ns = [1] * 10

        without_ns = evaluate_g1_fpr(pooled_actions, per_corpus)
        with_ns = evaluate_g1_fpr(pooled_actions, per_corpus, typicality_ns=typicality_ns)

        assert "UNINFORMATIVE" not in without_ns.current_value
        assert "UNINFORMATIVE" in with_ns.current_value
        assert with_ns.detail["reachability"]["observed"] is True
        assert with_ns.detail["reachability"]["reachable"] is False
        assert NO_ACTION_FAR_THRESHOLD  # sanity: the threshold this hinges on exists


class TestScoreCorpusForG1BaselineFailureSkipsFold:
    """Site #1 of the RP-3c unchecked-baseline-POST audit: before this fix,
    a failed /baseline upload for one held-out fold was never checked, so
    that fold's score call proceeded against a silently undersized
    baseline. This is the representative test for the "per-fold
    skip-and-count" shape shared by _score_corpus_for_g1, G2b's holdout
    leg, and G6 (see TestComputeG2QValuesImpostorSharedPoolRaise's
    docstring for the contrasting "shared pool, raise immediately" shape)."""

    def _five_fold_payloads(self):
        return [
            {
                "recommendation": {"action": "no_action"},
                "authorship": {"deviation_score": 0.1 * (i + 1)},
                "typicality_n": 4,
            }
            for i in range(5)
        ]

    def test_fold_is_skipped_and_counted_when_its_baseline_upload_fails(self):
        texts_by_id = {"author_a": ["t0", "t1", "t2", "t3", "t4"]}
        # held_out_idx=2's fold uploads t0,t1,t3,t4 as baseline to this sid;
        # failing every /baseline POST to it means that ONE fold's baseline
        # is incomplete -- the other four folds' baselines are untouched.
        failing_sid = "demo:gate_g1test_author_a_2"
        client = _FakeG1Client(
            self._five_fold_payloads(),
            fail_baseline_urls={f"/students/{failing_sid}/baseline"},
        )

        pooled, per_corpus, deviations, n_errors, typicality_ns, n_drift_rejected = (
            _score_corpus_for_g1(client, "g1test", texts_by_id)
        )

        # Before the fix: n_errors == 0 and all 5 folds are scored (the
        # broken fold's /score call still fires and consumes a payload) --
        # this assertion is the RED signal.
        assert n_errors == 1
        assert len(pooled) == 4
        assert len(per_corpus["author_a"]) == 4
        assert len(deviations) == 4
        assert len(typicality_ns) == 4
        # A plain 500 is a genuine failure, not a drift-gate rejection.
        assert n_drift_rejected == 0


class TestScoreCorpusForG1DriftRejection:
    """Diagnosis (validation/calibration_report_2026-07-31.json, commit
    5160b396): G5's shuffled-G1 leg builds cross-author grab-bag baselines
    by design, and the Phase-8 drift gate
    (original/routers/students_baseline.py's add_baseline) correctly
    rejects many of them as 202 pending_review / 409 rebaseline_required --
    not a crash, not a malformed request. _score_corpus_for_g1 must keep
    treating a drift-rejected baseline as "this fold's baseline is known
    incomplete, skip it and count an error" (RP-3c's existing fix, which
    must NOT change) while ALSO reporting the rejection distinctly via the
    new n_drift_rejected return, so a caller (run_g5) can tell a
    drift-rejection apart from a genuine machinery failure."""

    def _five_fold_payloads(self):
        return [
            {
                "recommendation": {"action": "no_action"},
                "authorship": {"deviation_score": 0.1 * (i + 1)},
                "typicality_n": 4,
            }
            for i in range(5)
        ]

    @pytest.mark.parametrize("drift_status", [202, 409])
    def test_drift_rejected_fold_is_excluded_and_counted_separately(self, drift_status):
        texts_by_id = {"author_a": ["t0", "t1", "t2", "t3", "t4"]}
        failing_sid = "demo:gate_g1test_author_a_2"
        client = _FakeG1Client(
            self._five_fold_payloads(),
            drift_baseline_urls={f"/students/{failing_sid}/baseline": drift_status},
        )

        pooled, per_corpus, deviations, n_errors, typicality_ns, n_drift_rejected = (
            _score_corpus_for_g1(client, "g1test", texts_by_id)
        )

        # (a) the drift-rejected fold is excluded from the deviation
        # computation exactly like a genuine failure would be -- its
        # baseline genuinely wasn't built.
        assert len(pooled) == 4
        assert len(per_corpus["author_a"]) == 4
        assert len(deviations) == 4
        assert len(typicality_ns) == 4
        # n_errors is UNCHANGED from before n_drift_rejected existed: the
        # real (non-shuffled) G1 leg's own health accounting must keep
        # counting a drift-rejection as an error, same as today.
        assert n_errors == 1
        # ...but it is now ALSO visible as specifically a drift-rejection.
        assert n_drift_rejected == 1

    def test_genuine_failure_is_not_counted_as_drift_rejected(self):
        """A plain 500 (or any non-202/409 non-200) must count toward
        n_errors but NOT n_drift_rejected -- only the drift gate's specific
        status codes qualify, per add_baseline's contract (422/503/200 are
        its only other outcomes on this endpoint)."""
        texts_by_id = {"author_a": ["t0", "t1", "t2", "t3", "t4"]}
        failing_sid = "demo:gate_g1test_author_a_2"
        client = _FakeG1Client(
            self._five_fold_payloads(),
            fail_baseline_urls={f"/students/{failing_sid}/baseline"},
        )

        _pooled, _per_corpus, _deviations, n_errors, _typicality_ns, n_drift_rejected = (
            _score_corpus_for_g1(client, "g1test", texts_by_id)
        )

        assert n_errors == 1
        assert n_drift_rejected == 0

    def test_fold_with_both_drift_and_genuine_failure_is_not_drift_only(self):
        """A fold where one baseline upload is drift-rejected and another is
        a genuine 500 is not "purely" a drift-rejection -- the genuine
        failure means real machinery trouble happened too, so this fold
        must count toward n_errors (as always) but NOT toward
        n_drift_rejected, so a caller excluding drift-rejections from its
        health check still sees this fold's genuine trouble."""
        texts_by_id = {"author_a": ["t0", "t1", "t2", "t3", "t4"]}
        failing_sid = "demo:gate_g1test_author_a_2"
        baseline_url = f"/students/{failing_sid}/baseline"
        # held_out_idx=2's fold uploads t0, t1, t3, t4 as baseline: make
        # t0's upload drift-rejected and t1's a genuine 500, leaving t3/t4
        # (and every OTHER fold's uploads) untouched.
        client = _FakeG1Client(
            self._five_fold_payloads(),
            baseline_overrides={
                (baseline_url, "t0"): 202,
                (baseline_url, "t1"): 500,
            },
        )

        _pooled, _per_corpus, _deviations, n_errors, _typicality_ns, n_drift_rejected = (
            _score_corpus_for_g1(client, "g1test", texts_by_id)
        )

        assert n_errors == 1
        assert n_drift_rejected == 0


class TestRunG5ShuffledG1LegDriftRejection:
    """Full wiring test for the diagnosed defect: run_g5's shuffled-G1 leg
    must NOT let drift-rejections (see TestScoreCorpusForG1DriftRejection)
    trip _require_healthy_leg's >10% threshold, while a leg with genuine
    machinery failures over 10% must still raise exactly as before.

    These monkeypatch every heavy dependency run_g5() has besides the
    seam under test:
      - the three corpus loaders (content is irrelevant -- _score_corpus_for_g1
        itself is faked below, so nothing ever reads the shuffled corpus)
      - run.load_legacy_demo_app (swapped for a bare FastAPI() -- the real
        app from original/api.py is expensive and, again, nothing issues a
        real HTTP call once _score_corpus_for_g1 is faked)
      - _shuffled_public_authors_top1 and _compute_g4_group_means (G3/G4's
        shuffled legs -- canned healthy+instant, since these tests are only
        about the shuffled-G1 leg)
    This keeps the test fast while exercising the REAL run_g5 code path
    that wires _score_corpus_for_g1's n_drift_rejected return into the
    "G5 shuffled G1 leg" _require_healthy_leg call -- not just the
    arithmetic in isolation.
    """

    def _patch_common(self, monkeypatch):
        import run as _run_module
        from fastapi import FastAPI

        import validation.calibration_gate as cg

        monkeypatch.setattr(cg, "_load_seminary_texts", lambda: {})
        monkeypatch.setattr(cg, "_load_public_authors_baseline_texts", lambda: {})
        monkeypatch.setattr(
            cg, "_load_plato_texts_by_dialogue", lambda: {"d": [f"c{i}" for i in range(6)]}
        )
        monkeypatch.setattr(_run_module, "load_legacy_demo_app", lambda: FastAPI())
        monkeypatch.setattr(
            cg,
            "_shuffled_public_authors_top1",
            lambda rng: (0.1, {"shuffled_g3_n_essays": 1}),
        )
        monkeypatch.setattr(
            cg,
            "_compute_g4_group_means",
            lambda **kwargs: (
                {"early": 0.1, "middle": 0.2, "late": 0.3},
                {"n_scored": 10, "n_errors": 0},
            ),
        )
        return cg

    def test_high_drift_rejection_rate_does_not_raise(self, monkeypatch):
        """0 genuine machinery failures, 15 drift-rejected out of 35
        attempted folds (42.9% raw rejection rate -- well over the 10%
        threshold if miscounted as machinery failures). Must NOT raise, and
        the drift-rejection count must be visible in detail."""
        cg = self._patch_common(monkeypatch)

        def fake_score_corpus(client, sid_prefix, texts_by_id):
            return (
                ["no_action"] * 20,
                {"synthetic": ["no_action"] * 20},
                [0.5] * 20,
                15,  # n_errors (all drift)
                [4] * 20,
                15,  # n_drift_rejected
            )

        monkeypatch.setattr(cg, "_score_corpus_for_g1", fake_score_corpus)

        result = cg.run_g5(real_g1_deviations=[0.1] * 20, real_g1_n_errors=0)

        assert result.detail["shuffled_g1_n_scoring_errors"] == 15
        assert result.detail["shuffled_g1_n_genuine_scoring_errors"] == 0
        assert result.detail["shuffled_g1_drift_rejected_count"] == 15
        assert result.detail["shuffled_g1_drift_rejected_rate"] == pytest.approx(15 / 35)

    def test_genuine_failures_over_threshold_still_raises(self, monkeypatch):
        """Genuine (non-drift) failures alone over 10% of attempted folds
        must still raise -- the fix must not make this leg's health check
        toothless against real machinery breakage."""
        cg = self._patch_common(monkeypatch)

        def fake_score_corpus(client, sid_prefix, texts_by_id):
            return (
                ["no_action"] * 20,
                {"synthetic": ["no_action"] * 20},
                [0.5] * 20,
                15,  # n_errors (all genuine)
                [4] * 20,
                0,  # n_drift_rejected
            )

        monkeypatch.setattr(cg, "_score_corpus_for_g1", fake_score_corpus)

        with pytest.raises(RuntimeError, match="G5 shuffled G1 leg"):
            cg.run_g5(real_g1_deviations=[0.1] * 20, real_g1_n_errors=0)

    def test_mixed_drift_and_genuine_failures_only_genuine_counts_toward_threshold(
        self, monkeypatch
    ):
        """A mix of drift-rejections and a small number of genuine failures
        (here 9/(90+9) = 9.09%, under 10%) must not raise, even though the
        RAW failure rate (39/129 ~= 30.2%) would trip the old, undifferentiated
        threshold."""
        cg = self._patch_common(monkeypatch)

        def fake_score_corpus(client, sid_prefix, texts_by_id):
            return (
                ["no_action"] * 90,
                {"synthetic": ["no_action"] * 90},
                [0.5] * 90,
                39,  # n_errors: 9 genuine + 30 drift
                [4] * 90,
                30,  # n_drift_rejected
            )

        monkeypatch.setattr(cg, "_score_corpus_for_g1", fake_score_corpus)

        result = cg.run_g5(real_g1_deviations=[0.1] * 90, real_g1_n_errors=0)

        assert result.detail["shuffled_g1_n_genuine_scoring_errors"] == 9
        assert result.detail["shuffled_g1_drift_rejected_count"] == 30

    def test_real_g1_anchor_leg_health_check_is_unaffected_by_this_change(self, monkeypatch):
        """The REAL G1 leg's own health accounting (real_g1_n_errors, fed by
        run_all() from _score_corpus_for_g1's UNCHANGED n_errors return —
        see TestScoreCorpusForG1DriftRejection) must still raise exactly as
        before when it alone exceeds 10%, regardless of anything about the
        shuffled leg's drift handling: this is "G5 real G1 anchor leg", a
        separate _require_healthy_leg call this change does not touch."""
        cg = self._patch_common(monkeypatch)
        # Never reached -- the anchor-leg check raises first.
        monkeypatch.setattr(
            cg,
            "_score_corpus_for_g1",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
        )

        with pytest.raises(RuntimeError, match="G5 real G1 anchor leg"):
            cg.run_g5(real_g1_deviations=[0.4] * 89, real_g1_n_errors=11)


class _FakeG6Response:
    """Minimal stand-in for the scoring client's response object, scoped to
    what _compute_g6_fairness_data reads."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeG6Client:
    """Minimal stand-in for the scoring client, scoped to what
    _compute_g6_fairness_data calls. /score calls are routed by the
    submission_id's filename suffix (submission_id is always
    f"g6_{held_out['filename']}") to a canned payload. `fail_baseline_urls`
    (exact-URL match) lets a test fail one held-out fold's baseline uploads
    without touching any other fold's."""

    def __init__(self, payload_by_filename, fail_baseline_urls=frozenset()):
        self._payload_by_filename = payload_by_filename
        self._fail_baseline_urls = frozenset(fail_baseline_urls)

    def post(self, url, json=None):
        if url.endswith("/score"):
            filename = json["submission_id"][len("g6_") :]
            return _FakeG6Response(200, self._payload_by_filename[filename])
        if url in self._fail_baseline_urls:
            return _FakeG6Response(500, {})
        return _FakeG6Response(200, {})


def _g6_payload(*, p_central, typicality_n=4, deviation_score=0.5, action="no_action"):
    from original.constants import ALL_FEATURE_CODES

    return {
        "typicality_p_central": p_central,
        "typicality_n": typicality_n,
        "authorship": {"deviation_score": deviation_score, "authorship_probability": 0.5},
        "recommendation": {"action": action},
        # dict keyed by feature code, matching the real API response shape
        # (original/schemas.py: feature_vector: dict[str, float]) — a
        # previous version of this fixture used a positional list, which
        # let a `feature_vector[ALL_FEATURE_CODES.index(c)]` bug in
        # production code pass every test while crashing on every real
        # scoring call (KeyError against the actual dict).
        "feature_vector": {c: 0.5 for c in ALL_FEATURE_CODES},
    }


def _write_g6_fixture(tmp_path, entries_by_group):
    """Writes a tmp validation/manifest.json + validation/corpus/*.txt tree
    shaped like the real one, for one author per group. `entries_by_group`
    is {native_english_bool: [filename, ...]}; every filename gets a trivial
    corpus file and a manifest entry under a single per-group author_id."""
    import json as _json

    corpus_dir = tmp_path / "validation" / "corpus"
    corpus_dir.mkdir(parents=True)
    entries = []
    for native_english, filenames in entries_by_group.items():
        author_id = f"author_{'native' if native_english else 'nonnative'}"
        for filename in filenames:
            (corpus_dir / filename).write_text(f"Sample text for {filename}.\n" * 20)
            entries.append(
                {
                    "author_id": author_id,
                    "filename": filename,
                    "label": "authentic",
                    "native_english": native_english,
                    "word_count": 100,
                }
            )
    manifest_path = tmp_path / "validation" / "manifest.json"
    manifest_path.write_text(_json.dumps({"entries": entries}))
    return tmp_path


class TestComputeG6FairnessDataWiring:
    """Gap 2/3/4: _compute_g6_fairness_data computes p_central per fold but,
    before this fix, never read typicality_n (so the already-correct
    _threshold_reachable/_g6_unreachable_threshold_result were dead code),
    hand-rolled a short-group message that misattributes counts when BOTH
    groups are short (_g6_short_group_message already existed and was
    correct), and never wired the Welch caveat or _uniformity_slice_summary
    into the result. These integration tests drive the real function with a
    fake HTTP client and a temp manifest/corpus tree."""

    def test_returns_unreachable_skip_instead_of_a_vacuous_zero_ratio(self, tmp_path, monkeypatch):
        """CRITICAL: this is the literal vacuous-pass bug's production path.
        5 folds per group, every fold typicality_n=4 (the LOO-of-5 case the
        design spec warns about) -- the 0.02 flag threshold cannot be
        crossed by construction, so both group flagged rates come out 0%.
        Before Gap 2's fix this reached evaluate_g6_fairness's "both zero ->
        UNDEFINED" fail, which is at least not a silent pass but is the
        wrong diagnosis: the real problem is a structurally unreachable
        threshold, not "no fairness demonstrated by this data". After the
        fix it must short-circuit to the louder, more specific skip."""
        import validation.calibration_gate as cg

        native_files = [f"native_{i}.txt" for i in range(5)]
        non_native_files = [f"nonnative_{i}.txt" for i in range(5)]
        _write_g6_fixture(tmp_path, {True: native_files, False: non_native_files})
        monkeypatch.setattr(cg, "_ROOT", tmp_path)

        payload_by_filename = {
            f: _g6_payload(p_central=0.5, typicality_n=4)
            for f in native_files + non_native_files
        }
        client = _FakeG6Client(payload_by_filename)

        result = cg._compute_g6_fairness_data(client)

        assert result.passed is False
        assert result.current_value.startswith("SKIPPED (threshold unreachable):")
        assert result.detail["min_typicality_n"] == 4
        assert result.detail["n_native_scored"] == 5
        assert result.detail["n_non_native_scored"] == 5

    def test_short_group_message_names_both_groups_when_both_are_short(
        self, tmp_path, monkeypatch
    ):
        """Gap 3: native gets 3 folds (1 skipped -> n_native=2), non_native
        gets 3 folds (2 skipped -> n_non_native=1). Both counts are below
        _G6_MIN_PER_GROUP=5 and DIFFERENT -- the old hand-rolled message
        named only one group and mislabeled its count as min(2, 1)=1 under
        native_english=true. The fix must name both groups with their own
        correct counts (matching the already-correct
        _g6_short_group_message)."""
        import validation.calibration_gate as cg

        native_files = ["native_0.txt", "native_1.txt", "native_2.txt"]
        non_native_files = ["nonnative_0.txt", "nonnative_1.txt", "nonnative_2.txt"]
        _write_g6_fixture(tmp_path, {True: native_files, False: non_native_files})
        monkeypatch.setattr(cg, "_ROOT", tmp_path)

        payload_by_filename = {
            "native_0.txt": _g6_payload(p_central=0.5),
            "native_1.txt": _g6_payload(p_central=0.5),
            "native_2.txt": _g6_payload(p_central=None),  # skipped
            "nonnative_0.txt": _g6_payload(p_central=0.5),
            "nonnative_1.txt": _g6_payload(p_central=None),  # skipped
            "nonnative_2.txt": _g6_payload(p_central=None),  # skipped
        }
        client = _FakeG6Client(payload_by_filename)

        result = cg._compute_g6_fairness_data(client)

        assert result.passed is False
        assert result.current_value.startswith("SKIPPED (insufficient data):")
        assert result.detail["n_native_scored"] == 2
        assert result.detail["n_non_native_scored"] == 1
        missing = result.detail["missing"]
        assert "native_english=true group has 2 scored authentic entries" in missing
        assert "native_english=false group has 1 scored authentic entry" in missing

    def test_wires_welch_caveat_and_uniformity_slice_into_a_reachable_result(
        self, tmp_path, monkeypatch
    ):
        """Gap 4a/4b: on a leg that clears both the short-group and
        reachability guards, the final evaluate_g6_fairness call must
        receive the already-computed Welch effect magnitude/d (so a
        medium/large effect surfaces as a caveat) and the informational
        dict must carry _uniformity_slice_summary's output under
        "uniformity_slice" (so the spec's per-group Tier-18 comparison is
        actually recorded, not just computed and discarded)."""
        import validation.calibration_gate as cg

        native_files = [f"native_{i}.txt" for i in range(5)]
        non_native_files = [f"nonnative_{i}.txt" for i in range(5)]
        _write_g6_fixture(tmp_path, {True: native_files, False: non_native_files})
        monkeypatch.setattr(cg, "_ROOT", tmp_path)

        # typicality_n=60 clears the n>=49 reachability floor for the 0.02
        # threshold (see TestG6Fairness.test_unreachable_threshold_...).
        payload_by_filename = {}
        for i, f in enumerate(native_files):
            flagged = i == 0  # 1/5 flagged
            payload_by_filename[f] = _g6_payload(
                p_central=0.01 if flagged else 0.5, typicality_n=60
            )
        for i, f in enumerate(non_native_files):
            flagged = i < 2  # 2/5 flagged -- within the 2x band of 1/5
            payload_by_filename[f] = _g6_payload(
                p_central=0.01 if flagged else 0.5, typicality_n=60
            )
        client = _FakeG6Client(payload_by_filename)

        result = cg._compute_g6_fairness_data(client)

        assert not result.current_value.startswith("SKIPPED")
        assert result.detail["welch_effect_magnitude"] is not None
        assert "uniformity_slice" in result.detail
        uniformity = result.detail["uniformity_slice"]
        assert uniformity["gated"] is False
        assert uniformity["n_native"] == 5
        assert uniformity["n_non_native"] == 5


class TestComputeG6FairnessDataBaselineFailureSkipsFold:
    """Site #6 of the RP-3c audit: same per-fold shape as G1 (see
    TestScoreCorpusForG1BaselineFailureSkipsFold) — a failed /baseline
    upload for one held-out fold must skip that fold and count it in
    n_errors, not silently score against an undersized baseline. Uses 6
    native essays (one author) so that losing one fold to the failure still
    leaves 5 -- exactly _G6_MIN_PER_GROUP -- so the short-group skip doesn't
    mask the assertion."""

    def test_fold_skipped_and_counted_when_baseline_upload_fails(self, tmp_path, monkeypatch):
        import validation.calibration_gate as cg

        native_files = [f"native_{i}.txt" for i in range(6)]
        non_native_files = [f"nonnative_{i}.txt" for i in range(5)]
        _write_g6_fixture(tmp_path, {True: native_files, False: non_native_files})
        monkeypatch.setattr(cg, "_ROOT", tmp_path)

        payload_by_filename = {
            f: _g6_payload(p_central=0.5, typicality_n=60)
            for f in native_files + non_native_files
        }
        # held_out_idx=0 within the single native author is native_0.txt;
        # its baseline sid is demo:gate_g6_author_native_0.
        failing_sid = "demo:gate_g6_author_native_0"
        client = _FakeG6Client(
            payload_by_filename, fail_baseline_urls={f"/students/{failing_sid}/baseline"}
        )

        result = cg._compute_g6_fairness_data(client)

        # Before the fix: n_scoring_errors == 0 and n_native_scored == 6
        # (the broken fold's /score call still fires) -- this is the RED
        # signal.
        assert result.detail["n_scoring_errors"] == 1
        assert result.detail["n_native_scored"] == 5
        assert result.detail["n_non_native_scored"] == 5


class TestG6ReachabilityPrecheck:
    """Direct unit coverage of the pure helper extracted from
    _compute_g6_fairness_data (Gap 2) specifically so the reachability
    short-circuit can be pinned without a live scoring client, independent
    of the fuller integration tests above."""

    def test_returns_skip_when_binding_n_cannot_reach_the_threshold(self):
        from validation.calibration_gate import _g6_reachability_precheck

        results_by_group = {
            True: [{"typicality_n": 4}, {"typicality_n": 4}],
            False: [{"typicality_n": 4}, {"typicality_n": 60}],
        }
        result = _g6_reachability_precheck(
            results_by_group, 0.02, n_native_scored=2, n_non_native_scored=2
        )
        assert result is not None
        assert result.current_value.startswith("SKIPPED (threshold unreachable):")
        # Binding n is the SMALLEST across both groups.
        assert result.detail["min_typicality_n"] == 4

    def test_returns_none_when_the_binding_n_reaches_the_threshold(self):
        from validation.calibration_gate import _g6_reachability_precheck

        results_by_group = {
            True: [{"typicality_n": 60}, {"typicality_n": 60}],
            False: [{"typicality_n": 60}, {"typicality_n": 60}],
        }
        result = _g6_reachability_precheck(
            results_by_group, 0.02, n_native_scored=2, n_non_native_scored=2
        )
        assert result is None

    def test_returns_none_when_no_fold_reports_a_typicality_n(self):
        """Zero typicality_n means the action came from the deviation path,
        not the conformal band -- the floor doesn't apply (mirrors
        _reachability_block's "observed=False" convention)."""
        from validation.calibration_gate import _g6_reachability_precheck

        results_by_group = {True: [{"typicality_n": 0}], False: [{"typicality_n": 0}]}
        result = _g6_reachability_precheck(
            results_by_group, 0.02, n_native_scored=1, n_non_native_scored=1
        )
        assert result is None


class TestCorpusDeterminism:
    """Coverage for the 2026-07-28 vs 2026-07-30 calibration report drift:
    G2's individual q values changed denominators (n=5 -> n=11 for some
    dialogues) and G4's group means drifted ~0.005 on corpora the G3 repairs
    never touched. See docs/superpowers/plans/2026-07-31-pilot-scale-
    reachability.md Task 3.

    Diagnosis (validation/calibration_gate.py's _load_plato_texts_by_dialogue,
    read directly): the loader already sorts both the dialogue directory
    listing (`sorted(corpus_dir.iterdir())`) and each dialogue's chunk glob
    (`sorted(dialogue_dir.glob("*.txt"))`) -- filesystem enumeration order was
    never the hazard here. The untracked Plato caches
    (_features_cache*.npz, corpus/_raw_cache/pg*.txt) are read only by
    validation/plato/features.py and validation/plato/build_corpus.py; this
    loader imports neither module and never touches those paths, so a
    regenerated cache cannot explain the drift either. `git diff` between the
    commits that produced the two reports (50bb0a76 -> a78ac6dd) shows ZERO
    changes under validation/plato/corpus/jowett/**, so the checked-in corpus
    content was also byte-identical across the two runs. This test exists to
    pin the loader's own determinism so it can be ruled out with evidence
    rather than assumption -- see the corpus_fingerprint tests below for the
    safety net that catches the actual failure mode.
    """

    def test_plato_loader_is_order_stable(self):
        """Chunk counts and ordering must not depend on filesystem
        enumeration order — two loads must agree exactly."""
        from validation.calibration_gate import _load_plato_texts_by_dialogue

        a = _load_plato_texts_by_dialogue()
        b = _load_plato_texts_by_dialogue()
        assert list(a.keys()) == sorted(a.keys())
        assert {k: len(v) for k, v in a.items()} == {k: len(v) for k, v in b.items()}
        assert a == b


class TestCorpusFingerprint:
    """_corpus_fingerprint is the safety net for the case
    TestCorpusDeterminism's passing loader test implies: the drift is not in
    load order, so it must be caught by content-level comparison instead."""

    def test_identical_corpora_fingerprint_identically(self):
        from validation.calibration_gate import _corpus_fingerprint

        corpus = {"a": ["hello", "world"], "b": ["one chunk"]}
        assert _corpus_fingerprint(corpus) == _corpus_fingerprint(dict(corpus))

    def test_is_independent_of_dict_insertion_order(self):
        from validation.calibration_gate import _corpus_fingerprint

        forward = {"a": ["x"], "b": ["y", "z"]}
        backward = {"b": ["y", "z"], "a": ["x"]}
        assert _corpus_fingerprint(forward) == _corpus_fingerprint(backward)

    def test_changed_chunk_count_changes_the_fingerprint(self):
        """This is the exact failure mode from the 07-28/07-30 drift: same
        entity_id, different len(texts) — e.g. a dialogue whose effective
        n went from 5 to 11 between two runs on paper-identical inputs."""
        from validation.calibration_gate import _corpus_fingerprint

        five_chunks = {"plato_cratylus": ["chunk"] * 5}
        eleven_chunks = {"plato_cratylus": ["chunk"] * 11}
        assert _corpus_fingerprint(five_chunks) != _corpus_fingerprint(eleven_chunks)

    def test_changed_content_same_count_changes_the_fingerprint(self):
        from validation.calibration_gate import _corpus_fingerprint

        original = {"plato_meno": ["short text"]}
        regenerated = {"plato_meno": ["a completely different, longer text body"]}
        assert _corpus_fingerprint(original) != _corpus_fingerprint(regenerated)

    def test_plato_loader_output_is_fingerprintable_and_stable(self):
        """Ties the fingerprint helper to the real loader: two loads of the
        actual Plato corpus must fingerprint identically, matching
        TestCorpusDeterminism's own guarantee."""
        from validation.calibration_gate import (
            _corpus_fingerprint,
            _load_plato_texts_by_dialogue,
        )

        a = _corpus_fingerprint(_load_plato_texts_by_dialogue())
        b = _corpus_fingerprint(_load_plato_texts_by_dialogue())
        assert a == b
        assert isinstance(a, str) and len(a) > 0


class TestG6NativeEnglishLoader:
    """_load_g6_native_english_texts mirrors the entry/author bucketing
    _compute_g6_fairness_data does internally, so run_all() can fingerprint
    G6's corpus (validation/manifest.json + validation/corpus/*) the same
    way it fingerprints seminary/public_authors/Plato."""

    def test_returns_only_native_english_annotated_authentic_entries(self):
        from validation.calibration_gate import _load_g6_native_english_texts

        by_author = _load_g6_native_english_texts()
        assert isinstance(by_author, dict)
        for author_id, texts in by_author.items():
            assert isinstance(author_id, str)
            assert all(isinstance(t, str) and t for t in texts)

    def test_is_stable_across_repeated_loads(self):
        from validation.calibration_gate import _load_g6_native_english_texts

        a = _load_g6_native_english_texts()
        b = _load_g6_native_english_texts()
        assert a == b


# ── Task 9: corpus-group-scoped pooled calibration (G1/G6 payoff) ──────────────
#
# Pure helpers only. _score_corpus_for_g1's real G1 leg scores THREE
# different corpora (seminary + public_authors + Plato) under one flat
# "demo:" sid prefix, so collect_tenant_distances's tenant-string matching
# cannot separate them -- a naive pooled call would mix 5 modern seminary
# students, 19 ancient-Greek-in-translation dialogues, and a handful of
# 19th-century public authors into one reference set, silently violating the
# only exchangeability evidence that exists (Task 7 validated within-seminary
# and within-Plato separately, never their union, and never public_authors at
# all). These helpers make the group boundary an explicit, testable value
# instead of an implicit property of sid strings.


class TestGroupEntitiesForPooling:
    def test_entities_from_different_loaders_land_in_different_groups(self):
        from validation.calibration_gate import _group_entities_for_pooling

        seminary = {"seminary_group_0": ["a"], "seminary_group_1": ["b"]}
        plato = {"plato_republic": ["c"]}
        public_authors = {"augustine": ["d"]}

        group_of = _group_entities_for_pooling(seminary, plato, public_authors)

        assert group_of["seminary_group_0"] == "seminary"
        assert group_of["seminary_group_1"] == "seminary"
        assert group_of["plato_republic"] == "plato"
        assert group_of["augustine"] == "public_authors"

    def test_entity_ids_with_no_distinguishing_prefix_are_grouped_by_loader_membership(self):
        """Public-author entity ids ("augustine", "mill", ...) carry no
        prefix that a sid-parsing approach could use to infer their group --
        this must come purely from which loader dict produced them."""
        from validation.calibration_gate import _group_entities_for_pooling

        group_of = _group_entities_for_pooling({}, {}, {"augustine": ["x"], "mill": ["y"]})

        assert group_of == {"augustine": "public_authors", "mill": "public_authors"}

    def test_every_loaded_entity_is_present_exactly_once(self):
        from validation.calibration_gate import _group_entities_for_pooling

        seminary = {"s0": ["a"]}
        plato = {"p0": ["b"], "p1": ["c"]}
        public_authors = {"pa0": ["d"]}

        group_of = _group_entities_for_pooling(seminary, plato, public_authors)

        assert set(group_of) == {"s0", "p0", "p1", "pa0"}


class TestPoolPeersForEntity:
    def test_same_group_pool_excludes_other_groups(self):
        from validation.calibration_gate import _pool_peers_for_entity

        group_of = {
            "seminary_group_0": "seminary",
            "seminary_group_1": "seminary",
            "plato_republic": "plato",
        }
        entity_states = {
            "seminary_group_0": "state0",
            "seminary_group_1": "state1",
            "plato_republic": "state_plato",
        }

        pool = _pool_peers_for_entity("seminary_group_0", group_of, entity_states)

        assert pool == {"seminary_group_1": "state1"}
        assert "plato_republic" not in pool

    def test_pool_excludes_the_entity_itself(self):
        from validation.calibration_gate import _pool_peers_for_entity

        group_of = {"a": "g", "b": "g", "c": "g"}
        entity_states = {"a": 1, "b": 2, "c": 3}

        pool = _pool_peers_for_entity("a", group_of, entity_states)

        assert "a" not in pool
        assert pool == {"b": 2, "c": 3}

    def test_pool_is_empty_when_entity_is_alone_in_its_group(self):
        from validation.calibration_gate import _pool_peers_for_entity

        group_of = {"solo": "public_authors", "other": "plato"}
        entity_states = {"solo": 1, "other": 2}

        pool = _pool_peers_for_entity("solo", group_of, entity_states)

        assert pool == {}

    def test_entity_missing_from_entity_states_still_excludes_self_by_id(self):
        """entity_states need not contain every group member (e.g. an entity
        that failed to build a reference state) -- the exclusion is keyed on
        entity_id, not on membership in entity_states."""
        from validation.calibration_gate import _pool_peers_for_entity

        group_of = {"a": "g", "b": "g"}
        entity_states = {"b": "state_b"}  # "a" never built a reference state

        pool = _pool_peers_for_entity("a", group_of, entity_states)

        assert pool == {"b": "state_b"}


class TestPooledReferenceArithmetic:
    """Step 1's reachability arithmetic, worked out purely from text counts
    -- no HTTP, no scoring -- so reachability can be asserted before any
    real corpus run. Mirrors original/quantum/state.py's loo_distances:
    each qualifying peer entity contributes exactly len(texts) leave-one-out
    distances once pooled (one per its own contributing baseline sample)."""

    def test_seminary_shaped_group_is_unreachable_at_g1_threshold(self):
        from original.quantum.typicality import NO_ACTION_FAR_THRESHOLD
        from validation.calibration_gate import (
            _group_entities_for_pooling,
            _pooled_reference_arithmetic,
            _threshold_reachable,
        )

        seminary = {f"seminary_group_{i}": ["t"] * 5 for i in range(5)}
        group_of = _group_entities_for_pooling(seminary, {}, {})
        sizes = {k: len(v) for k, v in seminary.items()}

        arithmetic = _pooled_reference_arithmetic(group_of, sizes)

        assert len(arithmetic) == 5
        for entity_id, info in arithmetic.items():
            assert info["pool_n"] == 20  # 4 peers x 5 texts each
            assert info["n_peers"] == 4
            assert _threshold_reachable(info["pool_n"], NO_ACTION_FAR_THRESHOLD) is False

    def test_larger_group_can_be_reachable(self):
        from original.quantum.typicality import NO_ACTION_FAR_THRESHOLD
        from validation.calibration_gate import (
            _pooled_reference_arithmetic,
            _threshold_reachable,
        )

        group_of = {f"e{i}": "plato" for i in range(19)}
        sizes = {f"e{i}": 10 for i in range(19)}

        arithmetic = _pooled_reference_arithmetic(group_of, sizes)

        for info in arithmetic.values():
            assert info["pool_n"] == 180  # 18 peers x 10 texts each
            assert _threshold_reachable(info["pool_n"], NO_ACTION_FAR_THRESHOLD) is True

    def test_entities_below_min_size_do_not_participate_as_scored_or_peer(self):
        from validation.calibration_gate import _pooled_reference_arithmetic

        group_of = {"a": "g", "b": "g"}
        sizes = {"a": 5, "b": 3}  # "b" below the default min_size=5 LOO bar

        arithmetic = _pooled_reference_arithmetic(group_of, sizes)

        assert "b" not in arithmetic  # never scored
        assert arithmetic["a"]["pool_n"] == 0  # and never usable as a peer
        assert arithmetic["a"]["n_peers"] == 0

    def test_disjoint_groups_never_pool_together(self):
        from validation.calibration_gate import _pooled_reference_arithmetic

        group_of = {"s0": "seminary", "p0": "plato", "p1": "plato"}
        sizes = {"s0": 5, "p0": 6, "p1": 7}

        arithmetic = _pooled_reference_arithmetic(group_of, sizes)

        assert arithmetic["s0"]["pool_n"] == 0  # sole seminary entity: no peers
        assert arithmetic["p0"]["pool_n"] == 7  # only the other Plato entity
        assert arithmetic["p1"]["pool_n"] == 6


class _FakePooledResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def json(self):
        return {}


class _FakePooledClient:
    """Stand-in scoring client for the pooled G1/G6 orchestration tests.
    Only .post() for /baseline is exercised -- the pooled-mode functions
    score by calling original.quantum.scoring.score() directly (see their
    docstrings for why: original/routers/students_scoring.py never threads
    pooled_states into quantum_score()), so no /score URL is ever hit here.
    """

    def post(self, url, json=None):
        assert not url.endswith("/score"), "pooled-mode scoring must bypass the HTTP /score endpoint"
        return _FakePooledResponse(200)


class TestScoreCorpusForG1PooledGroupSegregation:
    """The trap this task exists to catch, exercised at the orchestration
    level (not just the pure helper in isolation): a fold's pooled
    reference, as actually passed to score(), must never include another
    corpus group's entities -- even though every sid in this leg shares the
    flat "demo:" tenant prefix that collect_tenant_distances alone cannot
    use to tell the corpora apart."""

    def test_pooled_states_passed_to_score_never_cross_a_group_boundary(self, monkeypatch):
        import types

        from validation import calibration_gate as gate

        calls = []

        def fake_get(sid):
            return sid  # non-None sentinel; identity is all this test needs

        def fake_extract_features(text, keystroke_data=None):
            return {}

        def fake_feature_vector(text, keystroke_data=None):
            return [0.5]

        def fake_score(
            *,
            state,
            submission_vector,
            feature_dict,
            submission_id,
            scoring_config,
            pooled_states,
            student_id,
        ):
            calls.append({"student_id": student_id, "pooled_states": dict(pooled_states)})
            result = types.SimpleNamespace()
            result.recommendation = types.SimpleNamespace(action="no_action")
            result.authorship = types.SimpleNamespace(deviation_score=0.0)
            result.typicality_n = len(pooled_states)
            result.typicality_calibration = "pooled" if pooled_states else "self"
            return result

        monkeypatch.setattr("original.store.get", fake_get)
        monkeypatch.setattr("original.features.pipeline.extract_features", fake_extract_features)
        monkeypatch.setattr("original.features.pipeline.feature_vector", fake_feature_vector)
        monkeypatch.setattr("original.quantum.scoring.score", fake_score)

        texts_by_id = {
            "seminary_group_0": ["s"] * 5,
            "seminary_group_1": ["s"] * 5,
            "plato_republic": ["p"] * 6,
            "plato_timaeus": ["p"] * 6,
        }
        group_of = {
            "seminary_group_0": "seminary",
            "seminary_group_1": "seminary",
            "plato_republic": "plato",
            "plato_timaeus": "plato",
        }
        client = _FakePooledClient()

        out = gate._score_corpus_for_g1_pooled(client, "g1pooledtest", texts_by_id, group_of)

        assert calls, "expected at least one fold to be scored"
        for call in calls:
            if "seminary" in call["student_id"]:
                assert call["pooled_states"], "seminary fold should have same-group peers"
                assert all("seminary" in k for k in call["pooled_states"])
            elif "plato" in call["student_id"]:
                assert call["pooled_states"], "plato fold should have same-group peers"
                assert all("plato" in k for k in call["pooled_states"])
            else:
                pytest.fail(f"unexpected student_id shape: {call['student_id']}")

        # Sanity on the returned aggregate shape.
        assert set(out["per_corpus_actions"]) == set(texts_by_id)
        assert len(out["pooled_actions"]) == 5 + 5 + 6 + 6

    def test_entity_below_five_texts_is_skipped_and_not_offered_as_a_peer(self, monkeypatch):
        import types

        from validation import calibration_gate as gate

        calls = []

        def fake_get(sid):
            return sid

        def fake_score(**kwargs):
            calls.append(kwargs)
            result = types.SimpleNamespace()
            result.recommendation = types.SimpleNamespace(action="no_action")
            result.authorship = types.SimpleNamespace(deviation_score=0.0)
            result.typicality_n = len(kwargs["pooled_states"])
            result.typicality_calibration = "pooled" if kwargs["pooled_states"] else "self"
            return result

        monkeypatch.setattr("original.store.get", fake_get)
        monkeypatch.setattr(
            "original.features.pipeline.extract_features", lambda text, keystroke_data=None: {}
        )
        monkeypatch.setattr(
            "original.features.pipeline.feature_vector", lambda text, keystroke_data=None: [0.5]
        )
        monkeypatch.setattr("original.quantum.scoring.score", fake_score)

        texts_by_id = {
            "seminary_group_0": ["s"] * 5,
            "seminary_group_1": ["s"] * 4,  # below the 5-text LOO minimum
        }
        group_of = {"seminary_group_0": "seminary", "seminary_group_1": "seminary"}
        client = _FakePooledClient()

        out = gate._score_corpus_for_g1_pooled(client, "g1pooledtest2", texts_by_id, group_of)

        # seminary_group_1 never scored (below minimum)...
        assert "seminary_group_1" not in out["per_corpus_actions"]
        # ...and never offered as a peer to seminary_group_0 either, so
        # seminary_group_0 (alone in its group once the short entity is
        # excluded) falls back to self-calibration.
        assert all(call["pooled_states"] == {} for call in calls)


# ── G7 — cross-topic same-author FPR ──────────────────────────────────────────
#
# Spec: docs/superpowers/specs/2026-08-06-topic-invariant-scoring-design.md
# §Validation. Three-way CONJUNCTION, deliberately — the acceptance bar was
# written this way because LLR_ACTION_MODE=blend looked excellent on the
# false-positive leg alone and was caught only because someone also checked
# the catch rate at a matched severity bar.


class TestG7Conjunction:
    """All three legs must hold. No single leg may carry a pass."""

    def test_passes_when_all_three_legs_clear_their_bars(self):
        result = evaluate_g7_cross_topic_fpr(0.20, 0.35, 0.70)
        assert result.verdict == "pass"
        assert result.passed is True
        assert result.name == "G7"

    def test_fails_when_cross_topic_false_positive_rate_exceeds_bar(self):
        result = evaluate_g7_cross_topic_fpr(0.30, 0.35, 0.70)
        assert result.verdict == "fail"
        assert result.detail["fp_leg_passed"] is False
        assert result.detail["catch_leg_passed"] is True
        assert result.detail["auc_leg_passed"] is True

    def test_fails_when_catch_rate_collapses_even_though_fp_looks_excellent(self):
        """The `blend` shape: a spectacular false-positive rate bought by
        suppressing genuine impostor severity. The whole reason G7 is a
        conjunction rather than an FP threshold."""
        result = evaluate_g7_cross_topic_fpr(0.05, 0.03, 0.70)
        assert result.verdict == "fail"
        assert result.detail["fp_leg_passed"] is True
        assert result.detail["catch_leg_passed"] is False

    def test_fails_when_auc_stays_at_or_below_chance_despite_good_rates(self):
        """The score-compression shape: inflation squashes everything toward
        the middle, so the FP rate falls while the ranking stays inverted.
        An inverted AUC *is* the defect G7 exists to detect."""
        result = evaluate_g7_cross_topic_fpr(0.05, 0.35, 0.45)
        assert result.verdict == "fail"
        assert result.detail["auc_leg_passed"] is False
        assert result.detail["fp_leg_passed"] is True
        assert result.detail["catch_leg_passed"] is True

    def test_bars_are_inclusive_exactly_at_the_spec_values(self):
        """Spec reads `<= 25%`, `>= 29%`, `>= 0.60`. Pin the boundary so a
        `<` / `<=` mutation cannot survive."""
        result = evaluate_g7_cross_topic_fpr(0.25, 0.29, 0.60)
        assert result.verdict == "pass"

    def test_just_outside_each_bar_fails(self):
        assert evaluate_g7_cross_topic_fpr(0.2501, 0.29, 0.60).verdict == "fail"
        assert evaluate_g7_cross_topic_fpr(0.25, 0.2899, 0.60).verdict == "fail"
        assert evaluate_g7_cross_topic_fpr(0.25, 0.29, 0.5999).verdict == "fail"

    def test_current_value_names_every_measured_leg_and_its_bar(self):
        result = evaluate_g7_cross_topic_fpr(0.30, 0.35, 0.70)
        # A reader must be able to see WHICH leg failed without opening
        # detail — the conjunction is worthless if the report only says
        # "G7 [FAIL]". Every measured value is rendered, and the failing leg
        # is named.
        assert "30.0%" in result.current_value
        assert "35.0%" in result.current_value
        assert "0.700" in result.current_value
        assert "FAILED: FP" in result.current_value
        assert "catch" not in result.current_value.split("FAILED:")[1]

    def test_all_three_bars_travel_in_the_criterion_string(self):
        result = evaluate_g7_cross_topic_fpr(0.20, 0.35, 0.70)
        assert "25" in result.criterion
        assert "29" in result.criterion
        assert "0.60" in result.criterion

    def test_measured_values_are_recorded_in_detail(self):
        result = evaluate_g7_cross_topic_fpr(0.20, 0.35, 0.70)
        assert result.detail["cross_topic_fp_rate"] == 0.20
        assert result.detail["impostor_catch_rate"] == 0.35
        assert result.detail["mean_cross_genre_dev_auc"] == 0.70


class TestG7FoldCount:
    """A mean over genre folds is only a cross-genre claim if there is more
    than one fold."""

    def test_single_fold_downgrades_a_would_be_pass_to_uninformative(self):
        result = evaluate_g7_cross_topic_fpr(0.20, 0.35, 0.70, n_genre_folds=1)
        assert result.verdict == "uninformative"
        assert result.passed is False

    def test_two_folds_leave_a_pass_intact(self):
        result = evaluate_g7_cross_topic_fpr(0.20, 0.35, 0.70, n_genre_folds=2)
        assert result.verdict == "pass"

    def test_single_fold_never_upgrades_a_genuine_failure(self):
        """Only a would-be pass can become uninformative — a measured
        failure is evidence regardless of how few folds produced it."""
        result = evaluate_g7_cross_topic_fpr(0.90, 0.01, 0.10, n_genre_folds=1)
        assert result.verdict == "fail"

    def test_zero_folds_is_uninformative_not_a_pass(self):
        result = evaluate_g7_cross_topic_fpr(0.20, 0.35, 0.70, n_genre_folds=0)
        assert result.verdict == "uninformative"


class TestG7SamplingUncertainty:
    """G3's Wilson-interval argument, applied to G7's two proportion legs: a
    point estimate that clears its bar on a corpus too small to distinguish
    it from the other side is not evidence of a pass."""

    def test_pass_with_undecidable_fp_rate_is_uninformative(self):
        result = evaluate_g7_cross_topic_fpr(
            0.20, 0.35, 0.70, n_genuine=10, n_impostor=500, n_genre_folds=6
        )
        assert result.verdict == "uninformative"
        assert result.detail["power"]["fp_bar_decidable"] == "undecided"

    def test_pass_with_undecidable_catch_rate_is_uninformative(self):
        result = evaluate_g7_cross_topic_fpr(
            0.10, 0.40, 0.70, n_genuine=500, n_impostor=10, n_genre_folds=6
        )
        assert result.verdict == "uninformative"
        assert result.detail["power"]["catch_bar_decidable"] == "undecided"

    def test_a_well_powered_pass_stays_a_pass(self):
        result = evaluate_g7_cross_topic_fpr(
            0.10, 0.50, 0.70, n_genuine=500, n_impostor=500, n_genre_folds=6
        )
        assert result.verdict == "pass"
        assert result.detail["power"]["fp_bar_decidable"] == "below"
        assert result.detail["power"]["catch_bar_decidable"] == "above"

    def test_sampling_uncertainty_never_downgrades_a_measured_failure(self):
        result = evaluate_g7_cross_topic_fpr(
            0.90, 0.01, 0.10, n_genuine=10, n_impostor=10, n_genre_folds=6
        )
        assert result.verdict == "fail"

    def test_omitting_both_counts_preserves_two_valued_behaviour(self):
        result = evaluate_g7_cross_topic_fpr(0.20, 0.35, 0.70)
        assert result.verdict == "pass"
        assert "power" not in result.detail

    def test_the_fp_leg_needs_its_interval_below_the_bar_not_merely_above(self):
        """The FP bar is an UPPER bound (<= 25%), so a demonstrated pass
        needs the whole interval BELOW it. Binding this leg to "above" — the
        direction G3's lower-bound check uses — would invert the test."""
        result = evaluate_g7_cross_topic_fpr(
            0.10, 0.50, 0.70, n_genuine=500, n_impostor=500
        )
        assert result.detail["power"]["fp_bar_decidable"] == "below"
        assert result.verdict == "pass"


class TestG7MechanismActuallyFired:
    """The GENRE_INVARIANT_WEIGHTS_ENABLED trap, closed at the gate. A
    correction that never fires on the corpus cannot be credited with the
    numbers that corpus produced."""

    def test_pass_is_uninformative_when_the_inflation_never_fired(self):
        result = evaluate_g7_cross_topic_fpr(
            0.20, 0.35, 0.70, n_genre_folds=6, inflation_fire_rate=0.0
        )
        assert result.verdict == "uninformative"
        assert result.detail["inflation_fire_rate"] == 0.0

    def test_pass_survives_when_the_inflation_fired_somewhere(self):
        result = evaluate_g7_cross_topic_fpr(
            0.20, 0.35, 0.70, n_genre_folds=6, inflation_fire_rate=0.42
        )
        assert result.verdict == "pass"

    def test_a_failure_is_never_downgraded_by_a_zero_fire_rate(self):
        result = evaluate_g7_cross_topic_fpr(
            0.90, 0.01, 0.10, n_genre_folds=6, inflation_fire_rate=0.0
        )
        assert result.verdict == "fail"

    def test_omitting_the_fire_rate_preserves_two_valued_behaviour(self):
        result = evaluate_g7_cross_topic_fpr(0.20, 0.35, 0.70, n_genre_folds=6)
        assert result.verdict == "pass"
        assert result.detail["inflation_fire_rate"] is None

    def test_the_reason_for_an_uninformative_verdict_is_stated_in_current_value(self):
        result = evaluate_g7_cross_topic_fpr(
            0.20, 0.35, 0.70, n_genre_folds=6, inflation_fire_rate=0.0
        )
        assert "UNINFORMATIVE" in result.current_value


class TestG7Informational:
    def test_informational_is_merged_first_and_cannot_overwrite_a_verdict_key(self):
        result = evaluate_g7_cross_topic_fpr(
            0.20,
            0.35,
            0.70,
            informational={"cross_topic_fp_rate": 999.0, "note": "context"},
        )
        assert result.detail["cross_topic_fp_rate"] == 0.20
        assert result.detail["note"] == "context"

    def test_informational_never_changes_the_verdict(self):
        with_info = evaluate_g7_cross_topic_fpr(
            0.20, 0.35, 0.70, informational={"anything": "at all"}
        )
        without = evaluate_g7_cross_topic_fpr(0.20, 0.35, 0.70)
        assert with_info.verdict == without.verdict == "pass"


class TestG7FoldMetrics:
    """The pure reduction from per-fold scoring output to G7's three headline
    numbers. Must reproduce action_mode_sweep.py's own arithmetic exactly —
    if it doesn't, the gate is measuring something subtly different from the
    harness that produced the 42.4% / 31.9% / 0.387 baseline it is judged
    against."""

    @staticmethod
    def _fold(genre, genuine, impostor, dev_auc=0.7, fired=0):
        return {
            "genre": genre,
            "genuine_actions": genuine,
            "impostor_actions": impostor,
            "dev_auc": dev_auc,
            "genuine_inflation_fired": fired,
        }

    def test_counts_schedule_conversation_and_escalate_but_not_lower(self):
        fold = self._fold(
            "theology",
            ["no_action", "monitor", "schedule_conversation", "escalate"],
            ["no_action", "escalate"],
        )
        out = calibration_gate._g7_fold_metrics([fold])
        assert out["cross_topic_fp_rate"] == 0.5  # 2 of 4 at sched+
        assert out["impostor_catch_rate"] == 0.5  # 1 of 2 at sched+

    def test_averages_per_fold_rates_unweighted_not_pooled(self):
        """action_mode_sweep.py takes np.mean over the per-GENRE rates, so a
        small genre bucket counts as much as a large one. Pooling the chunks
        instead would silently reweight toward the biggest bucket."""
        folds = [
            # 1 of 1 flagged -> fold rate 1.0
            self._fold("narnia", ["escalate"], ["escalate"]),
            # 1 of 9 flagged -> fold rate 0.111...
            self._fold("essays", ["escalate"] + ["no_action"] * 8, ["no_action"]),
        ]
        out = calibration_gate._g7_fold_metrics(folds)
        # Unweighted mean of the two fold rates: (1.0 + 1/9) / 2
        assert out["cross_topic_fp_rate"] == pytest.approx((1.0 + 1.0 / 9.0) / 2)
        # Pooled would be 2/10 = 0.2 — pin that we did NOT do that.
        assert out["cross_topic_fp_rate"] != pytest.approx(0.2)

    def test_reports_pooled_counts_for_the_power_check(self):
        folds = [
            self._fold("narnia", ["escalate"], ["escalate", "no_action"]),
            self._fold("essays", ["no_action"] * 8, ["no_action"]),
        ]
        out = calibration_gate._g7_fold_metrics(folds)
        assert out["n_genuine"] == 9
        assert out["n_impostor"] == 3
        assert out["n_genre_folds"] == 2

    def test_skips_none_aucs_and_reports_how_many_folds_contributed(self):
        folds = [
            self._fold("narnia", ["no_action"], ["escalate"], dev_auc=0.8),
            self._fold("essays", ["no_action"], ["escalate"], dev_auc=None),
            self._fold("satire", ["no_action"], ["escalate"], dev_auc=0.6),
        ]
        out = calibration_gate._g7_fold_metrics(folds)
        assert out["mean_cross_genre_dev_auc"] == pytest.approx(0.7)
        assert out["n_auc_folds"] == 2
        assert out["n_genre_folds"] == 3

    def test_all_aucs_none_yields_none_rather_than_a_fabricated_number(self):
        folds = [self._fold("narnia", ["no_action"], ["escalate"], dev_auc=None)]
        out = calibration_gate._g7_fold_metrics(folds)
        assert out["mean_cross_genre_dev_auc"] is None
        assert out["n_auc_folds"] == 0

    def test_inflation_fire_rate_is_the_share_of_genuine_submissions(self):
        folds = [
            self._fold("narnia", ["no_action"] * 4, ["escalate"], fired=1),
            self._fold("essays", ["no_action"] * 6, ["escalate"], fired=4),
        ]
        out = calibration_gate._g7_fold_metrics(folds)
        assert out["n_genuine"] == 10
        assert out["inflation_fire_rate"] == pytest.approx(0.5)

    def test_no_folds_does_not_crash_and_reports_nothing_measured(self):
        out = calibration_gate._g7_fold_metrics([])
        assert out["n_genre_folds"] == 0
        assert out["n_genuine"] == 0
        assert out["n_impostor"] == 0
        assert out["mean_cross_genre_dev_auc"] is None

    def test_a_fold_with_no_scored_chunks_contributes_no_rate(self):
        """An empty bucket must not be averaged in as a 0% false-positive
        rate — that would look like the best possible result."""
        folds = [
            self._fold("narnia", [], [], dev_auc=None),
            self._fold("essays", ["escalate"], ["escalate"]),
        ]
        out = calibration_gate._g7_fold_metrics(folds)
        assert out["cross_topic_fp_rate"] == 1.0
        assert out["n_genre_folds"] == 1

    def test_severity_bar_tracks_production_not_a_local_copy(self):
        """The bar is schedule_conversation+, defined by production's own
        _ACTION_SEVERITY ordering. A local duplicate could drift out of
        sync with it silently."""
        from original.quantum.scoring import _ACTION_SEVERITY

        assert _ACTION_SEVERITY.index("schedule_conversation") == 2
        at_or_above = _ACTION_SEVERITY[2:]
        fold = self._fold("theology", list(at_or_above), list(_ACTION_SEVERITY))
        out = calibration_gate._g7_fold_metrics([fold])
        assert out["cross_topic_fp_rate"] == 1.0
        assert out["impostor_catch_rate"] == pytest.approx(2 / 4)


def _write_g7_corpus(tmp_path, genres=("theology", "narnia"), n_per_genre=8, n_impostor=10):
    """Synthetic stand-in for validation/genre_crossgenre_2026-08/'s cached
    vectors. The real corpus is not committed (the Lewis/Chesterton texts are
    still under copyright), so the end-to-end orchestration is exercised here
    on a generated one of the same shape."""
    import numpy as np

    from original.constants import FEATURE_DIM

    rng = np.random.RandomState(1729)
    vectors, meta = [], []

    for genre in genres:
        for i in range(n_per_genre):
            vectors.append(np.clip(rng.normal(0.5, 0.05, FEATURE_DIM), 0.0, 1.0))
            meta.append(
                {
                    "author": "genuine_author",
                    "work": f"{genre}_work",
                    "genre": genre,
                    "chunk_id": f"{genre}_work_{i}",
                    "word_count": 500,
                }
            )
    for i in range(n_impostor):
        vectors.append(np.clip(rng.normal(0.62, 0.05, FEATURE_DIM), 0.0, 1.0))
        meta.append(
            {
                "author": "impostor_author",
                "work": "impostor_work",
                "genre": "essays",
                "chunk_id": f"impostor_work_{i}",
                "word_count": 500,
            }
        )

    np.save(tmp_path / "vectors.npy", np.stack(vectors))
    (tmp_path / "vectors_meta.json").write_text(json.dumps(meta))
    return tmp_path


class TestG7CorpusAbsent:
    """The Lewis/Chesterton corpus is NOT committed. A gate whose corpus is
    missing must say so loudly — never a silent pass, and never omitted from
    the suite (an absent gate reads as 'topic invariance is covered')."""

    def test_missing_corpus_is_uninformative_not_a_pass(self, tmp_path):
        result = calibration_gate._compute_g7_cross_topic_data(corpus_dir=tmp_path)
        assert result.name == "G7"
        assert result.verdict == "uninformative"
        assert result.passed is False

    def test_missing_corpus_reads_as_skipped_not_as_a_measurement(self, tmp_path):
        result = calibration_gate._compute_g7_cross_topic_data(corpus_dir=tmp_path)
        assert "SKIPPED" in result.current_value
        assert "vectors.npy" in result.current_value

    def test_missing_corpus_names_the_command_that_regenerates_it(self, tmp_path):
        result = calibration_gate._compute_g7_cross_topic_data(corpus_dir=tmp_path)
        assert "extract_vectors" in result.detail["remediation"]

    def test_metadata_without_vectors_is_also_a_skip(self, tmp_path):
        (tmp_path / "vectors_meta.json").write_text("[]")
        result = calibration_gate._compute_g7_cross_topic_data(corpus_dir=tmp_path)
        assert result.verdict == "uninformative"


class TestG7CorpusMeasurement:
    def test_measures_a_real_corpus_end_to_end(self, tmp_path):
        _write_g7_corpus(tmp_path)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.name == "G7"
        assert result.verdict in ("pass", "fail", "uninformative")
        # Two genre buckets, held out one at a time.
        assert result.detail["n_genre_folds"] == 2
        assert 0.0 <= result.detail["cross_topic_fp_rate"] <= 1.0
        assert 0.0 <= result.detail["impostor_catch_rate"] <= 1.0

    def test_records_which_scoring_configuration_it_measured(self, tmp_path):
        _write_g7_corpus(tmp_path)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        config = result.detail["scoring_config"]
        # The spec's baseline numbers were measured against the impostor null
        # with llr_action_mode=gate; a G7 number measured under a different
        # configuration is not comparable to the bar and must say so.
        assert config["null_model"] == "impostor"
        assert "llr_action_mode" in config
        assert "topic_variance_inflation" in config

    def test_a_corpus_with_no_impostor_author_is_a_loud_skip(self, tmp_path):
        _write_g7_corpus(tmp_path, n_impostor=0)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.verdict == "uninformative"
        assert "SKIPPED" in result.current_value

    def test_a_single_genre_corpus_cannot_measure_cross_genre(self, tmp_path):
        _write_g7_corpus(tmp_path, genres=("theology",))
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        # Leaving out the only genre leaves no baseline at all, so there is
        # no cross-genre fold to measure.
        assert result.verdict == "uninformative"

    def test_inflation_off_does_not_downgrade_on_a_zero_fire_rate(self, tmp_path):
        """With TOPIC_VARIANCE_INFLATION off, sigma is never widened and a 0
        fire rate is correct — not a reason to distrust the run. The
        'mechanism never fired' downgrade must apply only when the mechanism
        was supposed to be active."""
        _write_g7_corpus(tmp_path)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.detail["scoring_config"]["topic_variance_inflation"] == "off"
        # fire rate is measured for the record but not forwarded as a downgrade
        assert result.detail["inflation_fire_rate"] is None
        reasons = result.detail.get("uninformative_reasons") or []
        assert not any("never fired" in r for r in reasons)


class TestG7InflationCanActuallyFire:
    """The gate is worthless if the mechanism it judges can never fire under
    it. Topic-variance inflation reads manifest["topic"]["baseline_distance"],
    and the cached vectors carry no text — so this pins that the orchestration
    really does build a manifest from the optional chunks.json, and that a
    genuinely distant topic crosses TOPIC_NOVELTY_BOUNDS["low"]."""

    @staticmethod
    def _corpus_with_text(tmp_path):
        import numpy as np

        from original.constants import FEATURE_DIM

        rng = np.random.RandomState(4242)
        # Two genres with disjoint vocabularies, so the held-out genre sits
        # far from the baseline centroid in TF-IDF space.
        vocab = {
            "theology": (
                "grace covenant atonement justification sanctification doctrine "
                "scripture epistle apostle redemption righteousness faith"
            ).split(),
            "narnia": (
                "lion wardrobe snow queen beaver castle sword badger sledge "
                "forest lamppost centaur"
            ).split(),
        }
        vectors, meta, chunks = [], [], []
        for genre, words in vocab.items():
            for i in range(8):
                vectors.append(np.clip(rng.normal(0.5, 0.05, FEATURE_DIM), 0.0, 1.0))
                chunk_id = f"{genre}_work_{i}"
                meta.append(
                    {
                        "author": "genuine_author",
                        "work": f"{genre}_work",
                        "genre": genre,
                        "chunk_id": chunk_id,
                        "word_count": 500,
                    }
                )
                # Deterministic but varied sentences from the genre's vocabulary.
                body = " ".join(words[(i + k) % len(words)] for k in range(60))
                chunks.append({"chunk_id": chunk_id, "text": body})
        for i in range(10):
            vectors.append(np.clip(rng.normal(0.62, 0.05, FEATURE_DIM), 0.0, 1.0))
            chunk_id = f"impostor_work_{i}"
            meta.append(
                {
                    "author": "impostor_author",
                    "work": "impostor_work",
                    "genre": "essays",
                    "chunk_id": chunk_id,
                    "word_count": 500,
                }
            )
            chunks.append(
                {"chunk_id": chunk_id, "text": " ".join(["essay prose commentary"] * 20)}
            )

        np.save(tmp_path / "vectors.npy", np.stack(vectors))
        (tmp_path / "vectors_meta.json").write_text(json.dumps(meta))
        (tmp_path / "chunks.json").write_text(json.dumps(chunks))
        return tmp_path

    def test_without_text_the_mechanism_cannot_fire_at_all(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOPIC_VARIANCE_INFLATION", "on")
        _write_g7_corpus(tmp_path)  # vectors only, no chunks.json
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.detail["topic_texts_available"] is False
        assert result.detail["measured_inflation_fire_rate"] == 0.0
        # ...and with the flag ON, that zero is forwarded, so the run can
        # never be quoted as evidence about the correction.
        assert result.detail["inflation_fire_rate"] == 0.0
        assert result.verdict != "pass"

    def test_with_text_a_distant_topic_actually_widens_sigma(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOPIC_VARIANCE_INFLATION", "on")
        self._corpus_with_text(tmp_path)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.detail["topic_texts_available"] is True
        assert result.detail["scoring_config"]["topic_variance_inflation"] == "on"
        assert result.detail["measured_inflation_fire_rate"] > 0.0, (
            "the leave-one-genre-out folds never crossed the 0.25 topic-"
            "distance floor — G7 cannot judge a mechanism that never fires"
        )


class TestG7ImpostorCountIsNotDoubleCounted:
    """The impostor test split is scored against EVERY fold's state, so the
    pooled count is n_distinct x n_folds. Feeding that to the Wilson interval
    would shrink the CI by ~sqrt(n_folds) and make the gate over-confident in
    exactly the direction that lets a weak pass through — the same chunks
    re-scored under a different baseline are not independent draws."""

    def test_power_check_uses_distinct_impostor_chunks_not_pooled_scorings(self, tmp_path):
        # 10 impostor chunks -> parity split -> 5 calibration / 5 test.
        # 2 genres -> 2 folds -> 10 pooled impostor scorings, 5 distinct.
        _write_g7_corpus(tmp_path, genres=("theology", "narnia"), n_impostor=10)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.detail["n_genre_folds"] == 2
        assert result.detail["n_impostor_scorings"] == 10
        assert result.detail["power"]["n_impostor"] == 5

    def test_genuine_chunks_are_each_held_out_once_so_pooling_is_honest(self, tmp_path):
        _write_g7_corpus(tmp_path, genres=("theology", "narnia"), n_per_genre=8)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        # Every genuine chunk is scored in exactly one fold, so the pooled
        # count IS the distinct count here — no correction needed.
        assert result.detail["power"]["n_genuine"] == 16


class TestG7StaleCorpusWidth:
    """vectors.npy is a CACHE, regenerated by hand and not committed. This
    repo's FEATURE_DIM has been 74, 89, 96, 102 and 109 at various points, so
    a stale cache of the wrong width is a live hazard. Zipping it against
    ALL_FEATURE_CODES would silently truncate to the shorter of the two and
    score a partial feature dict — a plausible-looking number measured on the
    wrong instrument, which is precisely what this validation layer exists to
    prevent."""

    def test_a_stale_width_cache_is_a_loud_skip_not_a_silent_measurement(self, tmp_path):
        import numpy as np

        from original.constants import FEATURE_DIM

        _write_g7_corpus(tmp_path)
        stale = np.load(tmp_path / "vectors.npy")[:, : FEATURE_DIM - 13]
        np.save(tmp_path / "vectors.npy", stale)

        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.verdict == "uninformative"
        assert "SKIPPED" in result.current_value
        assert str(FEATURE_DIM) in result.current_value
        assert result.detail["vector_dim"] == FEATURE_DIM - 13

    def test_a_correct_width_cache_still_measures(self, tmp_path):
        _write_g7_corpus(tmp_path)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert "SKIPPED" not in result.current_value


class TestG7UnmeasuredLegs:
    """A leg that could not be measured must never rescue a failure, and must
    never be mistaken for a leg that passed. Reachable for real: _g7_auc
    returns None when sklearn is missing (it is absent from the base
    requirements.txt) or when one side scores a single class."""

    def test_a_measured_failure_still_fails_when_the_auc_is_unavailable(self):
        result = evaluate_g7_cross_topic_fpr(0.90, 0.35, None)
        assert result.verdict == "fail"
        assert result.detail["failed_legs"] == ["FP"]
        assert result.detail["unmeasured_legs"] == ["AUC"]

    def test_all_measured_legs_passing_with_an_unmeasured_auc_is_uninformative(self):
        result = evaluate_g7_cross_topic_fpr(0.20, 0.35, None)
        assert result.verdict == "uninformative"
        assert result.passed is False
        assert result.detail["unmeasured_legs"] == ["AUC"]

    def test_an_unmeasured_leg_is_not_reported_as_a_failed_leg(self):
        result = evaluate_g7_cross_topic_fpr(0.20, 0.35, None)
        assert "AUC" not in result.detail["failed_legs"]
        assert result.detail["auc_leg_passed"] is False

    def test_every_leg_unmeasured_is_uninformative_not_a_pass(self):
        result = evaluate_g7_cross_topic_fpr(None, None, None)
        assert result.verdict == "uninformative"
        assert set(result.detail["unmeasured_legs"]) == {"FP", "catch", "AUC"}

    def test_current_value_marks_an_unmeasured_leg_rather_than_printing_a_number(self):
        result = evaluate_g7_cross_topic_fpr(0.20, 0.35, None)
        assert "not measured" in result.current_value.lower()


class TestG7ShadowModeCannotPass:
    """TOPIC_VARIANCE_INFLATION=shadow leaves deviation_score and
    recommendation untouched by construction, so all three G7 legs describe
    the UN-corrected pipeline. The prescribed workflow is 'run shadow first',
    so a G7 [PASS] under shadow is the exact GENRE_INVARIANT_WEIGHTS_ENABLED
    misreading this gate exists to prevent."""

    def test_shadow_downgrades_a_would_be_pass(self):
        result = evaluate_g7_cross_topic_fpr(
            0.20, 0.35, 0.70, n_genre_folds=6, inflation_mode="shadow"
        )
        assert result.verdict == "uninformative"
        assert any("shadow" in r for r in result.detail["uninformative_reasons"])

    def test_shadow_never_upgrades_a_failure(self):
        result = evaluate_g7_cross_topic_fpr(
            0.90, 0.01, 0.10, n_genre_folds=6, inflation_mode="shadow"
        )
        assert result.verdict == "fail"

    def test_on_mode_with_a_live_fire_rate_still_passes(self):
        result = evaluate_g7_cross_topic_fpr(
            0.20, 0.35, 0.70, n_genre_folds=6, inflation_mode="on", inflation_fire_rate=0.4
        )
        assert result.verdict == "pass"

    def test_off_mode_is_an_honest_measurement_of_the_shipped_pipeline(self):
        """With the flag off nobody is claiming to have measured the
        correction, so an off-mode pass is a true statement about the
        pipeline as shipped and is not downgraded."""
        result = evaluate_g7_cross_topic_fpr(
            0.20, 0.35, 0.70, n_genre_folds=6, inflation_mode="off"
        )
        assert result.verdict == "pass"


class TestG7AucFoldGuard:
    def test_a_single_auc_fold_downgrades_a_pass(self):
        result = evaluate_g7_cross_topic_fpr(
            0.20, 0.35, 0.99, n_genre_folds=6, n_auc_folds=1
        )
        assert result.verdict == "uninformative"

    def test_two_auc_folds_leave_a_pass_intact(self):
        result = evaluate_g7_cross_topic_fpr(
            0.20, 0.35, 0.99, n_genre_folds=6, n_auc_folds=2
        )
        assert result.verdict == "pass"

    def test_the_auc_fold_guard_never_upgrades_a_failure(self):
        result = evaluate_g7_cross_topic_fpr(
            0.90, 0.01, 0.10, n_genre_folds=6, n_auc_folds=1
        )
        assert result.verdict == "fail"


class TestG7DegenerateRatesDoNotCrash:
    """evaluate_g7_cross_topic_fpr is a public gate API registered in
    gate_contracts.py, so a malformed direct call must degrade rather than
    raise out of the gate suite (validation.power raises on successes > n)."""

    def test_an_out_of_range_rate_does_not_raise(self):
        result = evaluate_g7_cross_topic_fpr(1.5, 0.35, 0.70, n_genuine=10)
        assert result.verdict in ("pass", "fail", "uninformative")

    def test_a_nan_rate_does_not_raise(self):
        result = evaluate_g7_cross_topic_fpr(float("nan"), 0.35, 0.70, n_genuine=10)
        assert result.verdict in ("pass", "fail", "uninformative")


class TestG7RejectsUnknownActions:
    """An unrecognised action name silently ranked below no_action, so it was
    counted as NOT flagged — biasing the false-positive leg toward passing.
    The gate must refuse to score a vocabulary it does not understand."""

    def test_an_unknown_action_is_refused_rather_than_counted_as_unflagged(self):
        with pytest.raises(ValueError, match="unrecognised|unknown"):
            calibration_gate._g7_fold_metrics(
                [
                    {
                        "genre": "theology",
                        "genuine_actions": ["escalate", "suspend_account"],
                        "impostor_actions": ["escalate"],
                        "dev_auc": 0.7,
                        "genuine_inflation_fired": 0,
                    }
                ]
            )

    def test_production_action_names_are_all_accepted(self):
        from original.quantum.scoring import _ACTION_SEVERITY

        out = calibration_gate._g7_fold_metrics(
            [
                {
                    "genre": "theology",
                    "genuine_actions": list(_ACTION_SEVERITY),
                    "impostor_actions": list(_ACTION_SEVERITY),
                    "dev_auc": 0.7,
                    "genuine_inflation_fired": 0,
                }
            ]
        )
        assert out["cross_topic_fp_rate"] == pytest.approx(0.5)


class TestG7OrchestrationDoesNotBuryFailures:
    def test_a_measured_failure_is_reported_even_when_the_auc_is_unavailable(
        self, tmp_path, monkeypatch
    ):
        """sklearn is absent from the base requirements.txt, so every fold's
        AUC can legitimately be None. Short-circuiting to a SKIP in that case
        discarded whatever the two action legs had already measured — here a
        100% cross-topic false-positive rate, the exact failure G7 exists to
        catch, reported as 'nothing measurable'."""
        _write_g7_corpus(tmp_path)
        monkeypatch.setattr(
            calibration_gate,
            "_g7_fold_metrics",
            lambda folds: {
                "cross_topic_fp_rate": 1.0,
                "impostor_catch_rate": 1.0,
                "mean_cross_genre_dev_auc": None,
                "n_genre_folds": 2,
                "n_catch_folds": 2,
                "n_auc_folds": 0,
                "n_genuine": 16,
                "n_impostor": 10,
                "n_inflation_fired": 0,
                "inflation_fire_rate": 0.0,
                "per_fold": [],
            },
        )
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.verdict == "fail"
        assert result.detail["failed_legs"] == ["FP"]
        assert result.detail["unmeasured_legs"] == ["AUC"]

    def test_nothing_measured_at_all_is_still_a_skip(self, tmp_path, monkeypatch):
        _write_g7_corpus(tmp_path)
        monkeypatch.setattr(
            calibration_gate,
            "_g7_fold_metrics",
            lambda folds: {
                "cross_topic_fp_rate": None,
                "impostor_catch_rate": None,
                "mean_cross_genre_dev_auc": None,
                "n_genre_folds": 0,
                "n_catch_folds": 0,
                "n_auc_folds": 0,
                "n_genuine": 0,
                "n_impostor": 0,
                "n_inflation_fired": None,
                "inflation_fire_rate": None,
                "per_fold": [],
            },
        )
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.verdict == "uninformative"
        assert "SKIPPED" in result.current_value

    def test_an_unknown_action_name_becomes_a_loud_skip_not_a_machinery_error(
        self, tmp_path, monkeypatch
    ):
        _write_g7_corpus(tmp_path)

        def _boom(folds):
            raise calibration_gate._G7UnknownActionError(
                "unrecognised action name(s) ['suspend_account']"
            )

        monkeypatch.setattr(calibration_gate, "_g7_fold_metrics", _boom)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.verdict == "uninformative"
        assert "SKIPPED" in result.current_value


class TestG7OrchestrationForwardsMode:
    def test_shadow_mode_cannot_produce_a_pass(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOPIC_VARIANCE_INFLATION", "shadow")
        _write_g7_corpus(tmp_path)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.detail["inflation_mode"] == "shadow"
        assert result.verdict != "pass"

    def test_the_auc_fold_denominator_is_forwarded(self, tmp_path):
        _write_g7_corpus(tmp_path)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.detail["n_auc_folds"] == 2


class TestG7ManifestCoverageSymmetry:
    """A chunks.json covering the genuine chunks but not the impostor ones
    gives the genuine side a widened sigma while the impostors are scored
    against an un-widened band. Since sigma_eff >= sigma that can only lower
    the false-positive leg and inflate the catch leg — manufacturing exactly
    the 'clean FP that costs nothing' artifact G7 exists to be immune to."""

    @staticmethod
    def _corpus(tmp_path, cover_impostors: bool):
        import numpy as np

        from original.constants import FEATURE_DIM

        rng = np.random.RandomState(99)
        vectors, meta, chunks = [], [], []
        for genre, words in (
            ("theology", "grace covenant atonement justification doctrine epistle"),
            ("narnia", "lion wardrobe queen beaver castle lamppost"),
        ):
            for i in range(8):
                vectors.append(np.clip(rng.normal(0.5, 0.05, FEATURE_DIM), 0, 1))
                cid = f"{genre}_w_{i}"
                meta.append({"author": "g", "work": f"{genre}_w", "genre": genre,
                             "chunk_id": cid, "word_count": 500})
                chunks.append({"chunk_id": cid, "text": (words + " ") * 12})
        for i in range(10):
            vectors.append(np.clip(rng.normal(0.62, 0.05, FEATURE_DIM), 0, 1))
            cid = f"imp_w_{i}"
            meta.append({"author": "i", "work": "imp_w", "genre": "essays",
                         "chunk_id": cid, "word_count": 500})
            if cover_impostors:
                chunks.append({"chunk_id": cid, "text": "essay prose commentary " * 12})

        np.save(tmp_path / "vectors.npy", np.stack(vectors))
        (tmp_path / "vectors_meta.json").write_text(json.dumps(meta))
        (tmp_path / "chunks.json").write_text(json.dumps(chunks))
        return tmp_path

    def test_asymmetric_text_coverage_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOPIC_VARIANCE_INFLATION", "on")
        self._corpus(tmp_path, cover_impostors=False)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path, genuine_author="g", impostor_author="i"
        )
        assert result.verdict == "uninformative"
        assert "SKIPPED" in result.current_value
        assert result.detail["n_records_with_text"] < result.detail["n_records_total"]

    def test_symmetric_text_coverage_is_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOPIC_VARIANCE_INFLATION", "on")
        self._corpus(tmp_path, cover_impostors=True)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path, genuine_author="g", impostor_author="i"
        )
        assert "SKIPPED" not in result.current_value
        assert result.detail["topic_texts_available"] is True


class TestG7CorpusHygiene:
    def test_a_genuine_record_without_a_genre_is_refused(self, tmp_path):
        """A genre-less record can never be held out, so it would sit in
        EVERY fold's baseline unnoticed — and _g7_make_state would then crash
        on the missing key, surfacing as a G7 machinery error that blames the
        gate for a malformed corpus. The second hold-out corpus the spec
        requires is exactly this shape: multi_author_extract.py writes
        pa_meta.json with no genre field at all."""
        _write_g7_corpus(tmp_path)
        meta = json.loads((tmp_path / "vectors_meta.json").read_text())
        del meta[0]["genre"]
        (tmp_path / "vectors_meta.json").write_text(json.dumps(meta))

        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.verdict == "uninformative"
        assert "SKIPPED" in result.current_value
        assert "genre" in result.current_value

    def test_the_corpus_is_fingerprinted_so_two_reports_are_comparable(self, tmp_path):
        """G7 is the one gate whose corpus is uncommitted and regenerated by
        hand, so 'is this report comparable to the last one?' is least
        answerable by inspection."""
        _write_g7_corpus(tmp_path)
        first = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert first.detail["corpus_fingerprint"]

        meta = json.loads((tmp_path / "vectors_meta.json").read_text())
        meta[0]["work"] = "a_different_work"
        (tmp_path / "vectors_meta.json").write_text(json.dumps(meta))
        second = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert second.detail["corpus_fingerprint"] != first.detail["corpus_fingerprint"]


class TestG7SecondRoundReviewFixes:
    """Follow-ups from the second adversarial review pass."""

    def test_a_record_without_a_chunk_id_is_a_loud_skip_not_a_machinery_error(self, tmp_path):
        """c1: `submission_id=r["chunk_id"]` survived the .get() conversion,
        so a record carrying a genre but no chunk_id still crashed inside
        scoring and surfaced as 'ERROR (machinery)' — blaming the gate for a
        malformed corpus, the exact outcome the genre guard exists to
        prevent."""
        _write_g7_corpus(tmp_path)
        meta = json.loads((tmp_path / "vectors_meta.json").read_text())
        del meta[0]["chunk_id"]
        (tmp_path / "vectors_meta.json").write_text(json.dumps(meta))

        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.verdict == "uninformative"
        assert "SKIPPED" in result.current_value
        assert "chunk_id" in result.current_value

    def test_blank_text_does_not_count_as_topic_coverage(self, tmp_path, monkeypatch):
        """c2: coverage tested key presence, so whitespace-only text counted
        as covered while resolve_topic degraded on it — reinstating exactly
        the one-sided inflation the coverage check was added to prevent."""
        monkeypatch.setenv("TOPIC_VARIANCE_INFLATION", "on")
        _write_g7_corpus(tmp_path)
        meta = json.loads((tmp_path / "vectors_meta.json").read_text())
        chunks = []
        for m in meta:
            real = m["author"] == "genuine_author"
            chunks.append(
                {
                    "chunk_id": m["chunk_id"],
                    "text": ("grace covenant doctrine " * 12) if real else "   \n  ",
                }
            )
        (tmp_path / "chunks.json").write_text(json.dumps(chunks))

        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.verdict == "uninformative"
        assert "SKIPPED" in result.current_value

    def test_one_sided_degraded_topic_resolution_is_refused(self, tmp_path, monkeypatch):
        """c2, the half a coverage check cannot see: text that is non-blank
        but unusable (stop words only) sends resolve_topic down its degraded
        path, so sigma widens on one side only with coverage fully
        satisfied."""
        monkeypatch.setenv("TOPIC_VARIANCE_INFLATION", "on")
        _write_g7_corpus(tmp_path)
        meta = json.loads((tmp_path / "vectors_meta.json").read_text())
        (tmp_path / "chunks.json").write_text(
            json.dumps([{"chunk_id": m["chunk_id"], "text": "grace covenant doctrine " * 12}
                        for m in meta])
        )
        real_resolve = calibration_gate_resolve_topic()

        def fake_resolve(text, baseline_texts):
            out = dict(real_resolve(text, baseline_texts))
            # Impostor chunks degrade; genuine ones resolve normally.
            if "impostor" in text:
                out["degraded"] = True
            return out

        import original.context.resolvers as resolvers

        monkeypatch.setattr(resolvers, "resolve_topic", fake_resolve)
        # Impostor texts are tagged so fake_resolve can spot them.
        chunks = json.loads((tmp_path / "chunks.json").read_text())
        for c in chunks:
            if c["chunk_id"].startswith("impostor"):
                c["text"] = "impostor " + c["text"]
        (tmp_path / "chunks.json").write_text(json.dumps(chunks))

        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="genuine_author",
            impostor_author="impostor_author",
        )
        assert result.verdict == "uninformative"
        assert "SKIPPED" in result.current_value

    def test_every_skip_after_the_corpus_loads_carries_a_fingerprint(self, tmp_path):
        """Finding 5: 'the cache is inconsistent' / 'no chunks for author X'
        are claims about one specific corpus state, and were the reports
        least able to identify it."""
        _write_g7_corpus(tmp_path)
        result = calibration_gate._compute_g7_cross_topic_data(
            corpus_dir=tmp_path,
            genuine_author="nobody_by_this_name",
            impostor_author="impostor_author",
        )
        assert "SKIPPED" in result.current_value
        assert result.detail["corpus_fingerprint"]
        assert result.detail["corpus_dir"]

    def test_the_inflation_mode_travels_in_the_rendered_line(self):
        """(b): render() prints only current_value, so an off-mode pass was
        indistinguishable from an on-mode pass in a console line, a quoted
        result, or a PR comment. off remains passable — but self-labelling."""
        result = evaluate_g7_cross_topic_fpr(
            0.10, 0.50, 0.70, n_genre_folds=6, n_auc_folds=6, inflation_mode="off"
        )
        assert result.verdict == "pass"
        assert "TOPIC_VARIANCE_INFLATION=off" in result.current_value

    def test_a_rate_outside_the_unit_interval_is_unmeasured_not_a_pass(self):
        """c3: -0.4 <= 0.25 is True, so a nonsense rate read as a PASSING
        false-positive leg."""
        result = evaluate_g7_cross_topic_fpr(-0.4, 0.35, 0.70)
        assert result.detail["fp_leg_passed"] is False
        assert "FP" in result.detail["unmeasured_legs"]
        assert result.verdict != "pass"

    def test_the_catch_fold_denominator_is_guarded_like_the_others(self):
        result = evaluate_g7_cross_topic_fpr(
            0.20, 0.35, 0.70, n_genre_folds=6, n_auc_folds=6, n_catch_folds=1
        )
        assert result.verdict == "uninformative"

    def test_an_unrelated_value_error_is_not_mislabelled_as_a_bad_vocabulary(
        self, tmp_path, monkeypatch
    ):
        """`statistics.StatisticsError` subclasses ValueError, so a broad
        except would file any of them under 'unrecognised action
        vocabulary'."""
        _write_g7_corpus(tmp_path)

        def _boom(folds):
            raise ValueError("something else entirely")

        monkeypatch.setattr(calibration_gate, "_g7_fold_metrics", _boom)
        with pytest.raises(ValueError, match="something else entirely"):
            calibration_gate._compute_g7_cross_topic_data(
                corpus_dir=tmp_path,
                genuine_author="genuine_author",
                impostor_author="impostor_author",
            )


def calibration_gate_resolve_topic():
    from original.context.resolvers import resolve_topic

    return resolve_topic


# ── G8 — genre discrimination ─────────────────────────────────────────────────
#
# Spec: docs/superpowers/specs/2026-08-08-genre-resolution-design.md.
# Three-leg conjunction, and the third leg is the one that matters: the
# corpus confounds genre with author (every Dickens document is one author
# AND one genre), so a classifier could score well by recognising writers.


class TestG8GenreDiscrimination:
    def test_passes_when_all_three_legs_clear(self):
        r = calibration_gate.evaluate_g8_genre_discrimination(0.85, 0.40, 0.22)
        assert r.verdict == "pass"
        assert r.name == "G8"

    def test_fails_on_a_single_weak_class(self):
        """MINIMUM per-class precision, not macro-average: an average lets one
        class sit at 0.4 while the mean clears the bar, and the consequence of
        a wrong label is per-class — creative_fiction mutes tier 16, the
        academic genres expand the anchor set."""
        r = calibration_gate.evaluate_g8_genre_discrimination(0.55, 0.40, 0.22)
        assert r.verdict == "fail"
        assert r.detail["precision_leg_passed"] is False
        assert r.detail["abstention_leg_passed"] is True
        assert r.detail["control_leg_passed"] is True

    def test_fails_when_it_abstains_on_almost_everything(self):
        """Perfect precision by classifying nothing is the degenerate win."""
        r = calibration_gate.evaluate_g8_genre_discrimination(1.0, 0.95, 0.22)
        assert r.verdict == "fail"
        assert r.detail["abstention_leg_passed"] is False

    def test_fails_when_the_shuffled_control_still_predicts(self):
        r = calibration_gate.evaluate_g8_genre_discrimination(0.85, 0.40, 0.75)
        assert r.verdict == "fail"
        assert r.detail["control_leg_passed"] is False

    def test_bars_are_inclusive_at_the_spec_values(self):
        r = calibration_gate.evaluate_g8_genre_discrimination(0.80, 0.50, 0.35)
        assert r.verdict == "pass"

    def test_a_perfect_precision_score_still_needs_the_other_legs(self):
        """1.000 precision bought by abstaining on nearly everything is the
        degenerate win the conjunction exists to refuse."""
        r = calibration_gate.evaluate_g8_genre_discrimination(1.000, 0.90, 0.20)
        assert r.verdict == "fail"

    def test_just_outside_each_bar_fails(self):
        assert calibration_gate.evaluate_g8_genre_discrimination(0.799, 0.50, 0.35).verdict == "fail"
        assert calibration_gate.evaluate_g8_genre_discrimination(0.80, 0.501, 0.35).verdict == "fail"
        assert calibration_gate.evaluate_g8_genre_discrimination(0.80, 0.50, 0.351).verdict == "fail"

    def test_the_control_bar_tracks_the_class_count(self):
        """Chance is 1/n_classes, so the bar cannot be a constant. A shuffled
        accuracy of 0.55 is far above chance for 4 classes (0.25) and at
        chance for 2 (0.50) — the same number must fail one and pass the
        other, or the leg is not measuring 'collapsed to chance' at all."""
        r4 = calibration_gate.evaluate_g8_genre_discrimination(0.85, 0.4, 0.55, n_classes=4)
        r2 = calibration_gate.evaluate_g8_genre_discrimination(0.85, 0.4, 0.55, n_classes=2)
        assert r4.detail["chance"] == 0.25
        assert r4.verdict == "fail"
        assert r4.detail["control_leg_passed"] is False
        assert r2.detail["chance"] == 0.5
        assert r2.verdict == "pass"

    def test_current_value_names_every_leg(self):
        r = calibration_gate.evaluate_g8_genre_discrimination(0.55, 0.40, 0.22)
        assert "0.550" in r.current_value
        assert "FAILED" in r.current_value

    def test_a_thin_holdout_downgrades_a_pass(self):
        r = calibration_gate.evaluate_g8_genre_discrimination(0.85, 0.40, 0.22, n_holdout=8)
        assert r.verdict == "uninformative"

    def test_a_thin_holdout_never_upgrades_a_failure(self):
        r = calibration_gate.evaluate_g8_genre_discrimination(0.20, 0.99, 0.90, n_holdout=8)
        assert r.verdict == "fail"

    def test_a_well_powered_pass_stays_a_pass(self):
        r = calibration_gate.evaluate_g8_genre_discrimination(0.97, 0.40, 0.22, n_holdout=400)
        assert r.verdict == "pass"

    def test_the_measured_state_of_the_shipped_model_passes(self):
        """Recorded as measurement on the three-class taxonomy: minimum
        per-class precision 1.000 over 36 claimed hold-out documents,
        abstention 0.333, shuffled control 0.353 against 0.333 chance.

        The four-class version failed here at 0.706, and every error was
        first-person fiction predicted as autobiography. That boundary was
        defined by TRUTH CLAIM, which text cannot carry; redefining the axis
        as mode of discourse removed it. Pinned so a regression in the
        classifier, the corpus or the selector shows up as a gate failure."""
        r = calibration_gate.evaluate_g8_genre_discrimination(
            1.000, 0.333, 0.353, n_classes=3
        )
        assert r.verdict == "pass"
        assert r.detail["failed_legs"] == []


class TestG8SkipsWhenSklearnIsMissing:
    """G8's author-shuffled control re-fits a LogisticRegression, but sklearn
    is absent from the base requirements.txt — the very fact that motivated
    keeping genre inference numpy-only. A missing dependency is a can't-know,
    not a gate failure."""

    def test_missing_sklearn_is_uninformative_not_a_machinery_error(self, monkeypatch):
        monkeypatch.setattr(calibration_gate, "_sklearn_available", lambda: False)
        result = calibration_gate._compute_g8_genre_data()
        assert result.name == "G8"
        assert result.verdict == "uninformative"
        assert result.passed is False
        assert "scikit-learn" in result.current_value

    def test_the_skip_names_sklearn_as_the_missing_piece(self, monkeypatch):
        monkeypatch.setattr(calibration_gate, "_sklearn_available", lambda: False)
        result = calibration_gate._compute_g8_genre_data()
        assert "sklearn" in result.detail["missing"] or "scikit-learn" in str(
            result.detail["missing"]
        )
