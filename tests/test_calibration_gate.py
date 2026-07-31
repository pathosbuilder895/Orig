"""
tests/test_calibration_gate.py — pure-math unit tests for the calibration
gate criteria. The full corpus-driven run (validation/calibration_gate.py
executed as a script against seminary+public_authors+Plato) is slow and
belongs in CI's validation job, not the fast unit-test suite — this file
only tests the gate LOGIC on small synthetic inputs.
"""

from __future__ import annotations

import pytest

from validation.calibration_gate import (
    GateResult,
    _compute_g6_fairness_data,
    _conformal_p_floor,
    _g5_machinery_error_result,
    _g6_insufficient_data_result,
    _g6_short_group_message,
    _g6_unreachable_threshold_result,
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
    evaluate_g5_permutation_null,
    evaluate_g6_fairness,
    run_g5,
)


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
        assert _conformal_p_floor(0) == pytest.approx(1.0)

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
    """G1's flagged rate is genuinely defined, so its verdict is unchanged —
    but a 0.0% rate produced at an N where no flag is structurally possible
    must never read as demonstrated discrimination."""

    def test_unreachable_threshold_annotates_current_value_without_changing_verdict(self):
        actions = ["no_action"] * 100
        result = evaluate_g1_fpr(
            actions, per_corpus={"synthetic": actions}, typicality_ns=[12] * 100
        )
        assert result.passed is True  # verdict unchanged
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
        never collapse to ratio 1.0."""
        result = evaluate_g6_fairness(native_fpr=0.0, non_native_fpr=0.05)
        assert result.passed is False
        assert result.detail["ratio_status"] == "one_group_zero"
        assert result.detail["ratio"] == float("inf")
        assert "infinite" in result.current_value.lower()
        # Direction-symmetric.
        mirrored = evaluate_g6_fairness(native_fpr=0.05, non_native_fpr=0.0)
        assert mirrored.passed is False

    def test_both_rates_zero_is_undefined_not_a_pass(self):
        """Zero flags in both groups demonstrates no fairness — it is an
        absence of evidence, and must not render as a green gate."""
        result = evaluate_g6_fairness(native_fpr=0.0, non_native_fpr=0.0)
        assert result.passed is False
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
    /baseline (fire-and-forget) and /score (response read) endpoints. Every
    /score call returns the next canned payload in sequence."""

    def __init__(self, score_payloads):
        self._score_payloads = list(score_payloads)
        self._score_calls = 0

    def post(self, url, json=None):
        if url.endswith("/score"):
            payload = self._score_payloads[self._score_calls]
            self._score_calls += 1
            return _FakeG1Response(200, payload)
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

    def test_returns_five_tuple_with_pooled_typicality_ns(self):
        client = _FakeG1Client(self._five_fold_payloads(typicality_n=4))
        texts_by_id = {"author_a": ["t0", "t1", "t2", "t3", "t4"]}

        result = _score_corpus_for_g1(client, "g1test", texts_by_id)

        assert len(result) == 5
        pooled, per_corpus, deviations, n_errors, typicality_ns = result
        assert pooled == ["no_action"] * 5
        assert per_corpus == {"author_a": ["no_action"] * 5}
        assert n_errors == 0
        assert typicality_ns == [4, 4, 4, 4, 4]
        # Index-aligned with pooled_actions/pooled_deviations, per the
        # docstring's contract.
        assert len(typicality_ns) == len(pooled) == len(deviations)

    def test_typicality_ns_omitted_for_entities_below_the_five_text_minimum(self):
        client = _FakeG1Client(self._five_fold_payloads(typicality_n=4))
        # Only 4 texts -- below the >= 5 LOO minimum, so no folds are scored
        # and nothing is appended for this entity.
        texts_by_id = {"author_b": ["t0", "t1", "t2", "t3"]}

        pooled, per_corpus, deviations, n_errors, typicality_ns = _score_corpus_for_g1(
            client, "g1test", texts_by_id
        )

        assert pooled == []
        assert typicality_ns == []


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
    f"g6_{held_out['filename']}") to a canned payload; /baseline calls are
    fire-and-forget."""

    def __init__(self, payload_by_filename):
        self._payload_by_filename = payload_by_filename

    def post(self, url, json=None):
        if url.endswith("/score"):
            filename = json["submission_id"][len("g6_") :]
            return _FakeG6Response(200, self._payload_by_filename[filename])
        return _FakeG6Response(200, {})


def _g6_payload(*, p_central, typicality_n=4, deviation_score=0.5, action="no_action"):
    from original.constants import FEATURE_DIM

    return {
        "typicality_p_central": p_central,
        "typicality_n": typicality_n,
        "authorship": {"deviation_score": deviation_score, "authorship_probability": 0.5},
        "recommendation": {"action": action},
        "feature_vector": [0.5] * FEATURE_DIM,
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
