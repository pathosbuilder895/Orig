"""Gate G-S1 (validation/calibration_gate.py) and the committed snapshot of
the live operating point it is proposed against.

The snapshot (validation/study/current_operating_point.json) is not read by
any live path; it mirrors code so a candidate has something exact to diff
against. These tests fail the moment it drifts from the code it mirrors.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from validation import calibration_gate
from validation.calibration_gate import (
    GATE_LEGS,
    _compute_g_s1_study_gate,
    _parse_only,
)
from validation.calibration_gate import (
    evaluate_g_s1_study_operating_point as g_s1,
)

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "validation" / "study" / "current_operating_point.json"

GOOD = dict(auc=0.9, auc_ci95=(0.82, 0.96), n_students=60)


class TestSnapshotMirrorsCode:
    @pytest.fixture(scope="class")
    def snap(self):
        return json.loads(SNAPSHOT.read_text())

    def test_flag_rule_matches_exam_jsx(self, snap):
        src = (ROOT / "demo" / "bluebook" / "Exam.jsx").read_text()
        cutoffs = re.findall(r"seal\.aiScore\s*<\s*(\d+)", src)
        assert cutoffs == [str(snap["flag_rule"]["flag_if_score_below"])]

    def test_tier_weights_match_constants(self, snap):
        from original.constants import TIER_WEIGHTS

        assert {int(k): v for k, v in snap["tier_weights"].items()} == TIER_WEIGHTS

    def test_action_thresholds_match_constants(self, snap):
        from original.constants import ACTION_THRESHOLDS

        assert {k: tuple(v) for k, v in snap["action_thresholds"].items()} == ACTION_THRESHOLDS

    def test_disabled_tiers_match_constants(self, snap):
        from original.constants import DISABLED_FEATURE_GROUPS, FEATURE_GROUPS, FEATURE_TIER

        disabled_codes = {c for g in DISABLED_FEATURE_GROUPS for c in FEATURE_GROUPS[g]}
        assert sorted({FEATURE_TIER[c] for c in disabled_codes}) == snap["disabled_tiers"]

    def test_inconclusive_rule_matches_baseline_readiness(self, snap):
        from original.style_authorship import MIN_BASELINES
        from validation.study_contract import MIN_READY_BASELINE

        assert snap["inconclusive_rule"]["min_approved_reference_samples"] == MIN_BASELINES
        assert MIN_READY_BASELINE == MIN_BASELINES

    def test_snapshot_is_marked_current(self, snap):
        assert snap["kind"] == "current"


class TestGateLegs:
    def test_a_well_powered_clean_result_passes(self):
        r = g_s1(0, 120, 70, 100, **GOOD)
        assert r.verdict == "pass" and r.passed
        assert r.detail["legs"] == {"A": "pass", "B": "pass", "C": "pass"}

    def test_observed_false_flags_over_the_cap_fail(self):
        r = g_s1(3, 40, 30, 40, **GOOD)  # 7.5%
        assert r.verdict == "fail" and r.detail["legs"]["A"] == "fail"

    def test_twenty_students_with_zero_false_flags_is_uninformative_not_pass(self):
        # 0/40: Wilson 95% upper bound 8.8%, so 5% cannot be demonstrated.
        r = g_s1(0, 40, 30, 40, auc=0.9, auc_ci95=(0.8, 0.97), n_students=20)
        assert r.verdict == "uninformative" and not r.passed
        assert r.detail["legs"]["A"] == "undecided"

    def test_auc_at_chance_fails(self):
        r = g_s1(0, 120, 70, 100, auc=0.5, auc_ci95=(0.4, 0.6), n_students=60)
        assert r.verdict == "fail" and r.detail["legs"]["B"] == "fail"

    def test_auc_interval_touching_chance_is_undecided(self):
        r = g_s1(0, 120, 70, 100, auc=0.6, auc_ci95=(0.49, 0.7), n_students=60)
        assert r.verdict == "uninformative" and r.detail["legs"]["B"] == "undecided"

    def test_a_flag_that_never_fires_on_shadow_fails(self):
        r = g_s1(0, 120, 2, 100, **GOOD)
        assert r.verdict == "fail" and r.detail["legs"]["C"] == "fail"

    def test_a_fail_is_never_downgraded_by_a_small_cohort(self):
        r = g_s1(5, 20, 10, 20, auc=0.8, auc_ci95=(0.6, 0.9), n_students=4)
        assert r.verdict == "fail"

    def test_too_few_students_cannot_pass(self):
        r = g_s1(0, 120, 70, 100, auc=0.9, auc_ci95=(0.82, 0.96), n_students=5)
        assert r.verdict == "uninformative" and "student floor" in r.current_value

    def test_in_sample_evidence_is_refused(self):
        r = g_s1(0, 120, 70, 100, evidence="in_sample", **GOOD)
        assert r.verdict == "uninformative" and "by construction" in r.current_value

    def test_changed_weights_are_refused(self):
        r = g_s1(0, 120, 70, 100, weights_match_scores=False, **GOOD)
        assert r.verdict == "uninformative" and "FRESH cohort" in r.current_value

    def test_no_conclusive_attempts_is_uninformative(self):
        assert g_s1(0, 0, 0, 10, **GOOD).verdict == "uninformative"

    def test_missing_auc_is_undecided_not_failed(self):
        r = g_s1(0, 120, 70, 100, auc=None, n_students=60)
        assert r.verdict == "uninformative" and r.detail["legs"]["B"] == "undecided"

    def test_a_reversed_auc_interval_is_refused(self):
        with pytest.raises(ValueError, match="reversed"):
            g_s1(0, 120, 70, 100, auc=0.6, auc_ci95=(0.7, 0.45), n_students=60)

    def test_repeated_attempts_do_not_buy_confidence(self):
        # 0/120 natural attempts would demonstrate the cap, but they come from
        # 20 students: counted once each, 0/20 has a 16.1% upper bound.
        assert g_s1(0, 120, 70, 100, **GOOD).detail["legs"]["A"] == "pass"
        r = g_s1(0, 120, 70, 100, natural_students=20, **GOOD)
        assert r.detail["legs"]["A"] == "undecided" and r.detail["false_flags"]["wilson_n"] == 20
        assert r.verdict == "uninformative"

    def test_a_cap_other_than_the_pre_registered_one_cannot_pass(self):
        r = g_s1(0, 120, 70, 100, selection_cap=0.02, **GOOD)
        assert r.verdict == "uninformative" and "pre-registered" in r.current_value
        # ... but a failure at that cap is still a failure.
        assert g_s1(10, 120, 70, 100, selection_cap=0.02, **GOOD).verdict == "fail"

    def test_a_candidate_flagging_more_than_every_fold_cannot_pass_on_folds(self):
        r = g_s1(0, 120, 70, 100, candidate_flags_more_than_folds=True, **GOOD)
        assert r.verdict == "uninformative" and "understates" in r.current_value
        assert (
            g_s1(10, 120, 70, 100, candidate_flags_more_than_folds=True, **GOOD).verdict == "fail"
        )

    def test_only_a_fresh_cohort_pass_is_adoption_evidence(self):
        loso = g_s1(0, 120, 70, 100, **GOOD)
        fresh = g_s1(0, 120, 70, 100, evidence="fresh_cohort", **GOOD)
        assert loso.verdict == fresh.verdict == "pass"
        assert (
            loso.detail["adoption_eligible"] is False and fresh.detail["adoption_eligible"] is True
        )
        assert "not adoption evidence" in loso.current_value
        assert "not adoption evidence" not in fresh.current_value
        assert "not adoption evidence" in calibration_gate.render([loso])


class TestBatteryWiring:
    def test_s_is_a_leg(self):
        assert "S" in GATE_LEGS
        assert _parse_only("s") == {"S"}

    def test_merge_script_knows_the_leg(self):
        from scripts.merge_calibration_reports import LEG_GATES

        assert LEG_GATES["S"] == ("G-S1",)
        assert list(LEG_GATES) == list(GATE_LEGS)

    def test_weekly_workflow_runs_the_leg(self):
        import yaml

        wf = yaml.safe_load(
            (ROOT / ".github" / "workflows" / "calibration-battery.yml").read_text()
        )
        legs = {
            leg
            for job in wf["jobs"]["battery"]["strategy"]["matrix"]["include"]
            for leg in job["legs"].split(",")
        }
        assert legs == set(GATE_LEGS)

    def test_missing_candidate_is_a_loud_uninformative(self, tmp_path, monkeypatch):
        monkeypatch.delenv("STUDY_CANDIDATE", raising=False)
        r = _compute_g_s1_study_gate(tmp_path / "absent.json")
        assert r.verdict == "uninformative"
        assert "STUDY_PROTOCOL_2026-10.md" in r.current_value

    def test_a_file_that_is_not_a_candidate_raises(self, tmp_path):
        p = tmp_path / "current.json"
        p.write_text(SNAPSHOT.read_text())  # the live snapshot is kind "current"
        with pytest.raises(ValueError, match="not a study candidate"):
            _compute_g_s1_study_gate(p)

    def test_run_all_reports_g_s1_for_the_s_leg(self, monkeypatch, tmp_path):
        # Only the S leg: everything before it is skipped by _want(), but the
        # corpora are still loaded, as for the T leg. Keep it cheap by
        # stubbing the corpus loaders and the client.
        monkeypatch.setattr(calibration_gate, "_load_seminary_texts", lambda: {})
        monkeypatch.setattr(calibration_gate, "_load_public_authors_baseline_texts", lambda: {})
        monkeypatch.setattr(calibration_gate, "_load_plato_texts_by_dialogue", lambda: {})
        monkeypatch.setattr(calibration_gate, "_load_g6_native_english_texts", lambda: {})
        monkeypatch.setenv("STUDY_CANDIDATE", str(tmp_path / "absent.json"))
        results = calibration_gate._run_all_gates({"S"})
        assert [r.name for r in results] == ["G-S1"]
        assert results[0].verdict == "uninformative"
