"""scripts/propose_thresholds.py and gate G-S1, end to end from the FICTIONAL
study fixture (tests/fixtures/study_synthetic.csv).

What must hold: the selection rule does what its docstring says, the
out-of-sample check is really out of sample, the live artifact is never
written, the output is deterministic, and the candidate drops straight into
validation/calibration_gate.py.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

import pytest

from scripts import propose_thresholds as pt
from validation import calibration_gate, study_eval
from validation.study_contract import SCORE_COLUMN
from validation.study_eval import FLAG_NOTHING

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CSV = FIXTURES / "study_synthetic.csv"
CURRENT = pt.CURRENT_ARTIFACT


@pytest.fixture(scope="module")
def ev(tmp_path_factory) -> dict:
    return study_eval.run(CSV, tmp_path_factory.mktemp("eval") / "out", charts=False)


@pytest.fixture(scope="module")
def current() -> dict:
    return json.loads(CURRENT.read_text())


def _rows(natural: list[float], shadow: list[float], student: str = "s") -> list[dict]:
    rows = [
        {"claimed_student_id": student, "label": "natural", SCORE_COLUMN: s, "conclusive": True}
        for s in natural
    ]
    rows += [
        {"claimed_student_id": student, "label": "shadow", SCORE_COLUMN: s, "conclusive": True}
        for s in shadow
    ]
    return rows


# ── the selection rule ────────────────────────────────────────────────────────
#
# deviation_score: higher = less consistent, flagged when >= the cut-off.


class TestSelectThreshold:
    def test_most_catches_within_the_cap(self):
        natural = [0.50, 0.20, 0.15, 0.10, 0.05, 0.04, 0.03, 0.02, 0.01, 0.00]  # one at 0.50 = 10%
        shadow = [0.60, 0.55, 0.40, 0.30]
        # cap 0: cannot flag the natural 0.50, so the cut-off stays above it.
        assert pt.select_threshold(natural, shadow, 0.0)["threshold"] == 0.55
        # cap 10%: the natural 0.50 may be flagged, so everything above 0.20 can be.
        sel = pt.select_threshold(natural, shadow, 0.10)
        assert sel["threshold"] == 0.30 and sel["catches"] == 4 and sel["false_flags"] == 1

    def test_flags_at_or_above_the_cut_off(self):
        # A shadow attempt exactly at the cut-off is caught; ACTION_THRESHOLDS
        # bands are [lower, upper) the same way.
        sel = pt.select_threshold([0.10], [0.60], 0.0)
        assert sel["threshold"] == 0.60 and sel["catches"] == 1

    def test_ties_go_to_the_highest_cut_off(self):
        # Every cut-off from 0.21 to 0.60 catches the one shadow at 0.60 and
        # flags no natural attempt; the highest is chosen (widest margin to natural).
        assert pt.select_threshold([0.20, 0.10], [0.60], 0.05)["threshold"] == 0.60

    def test_nothing_catchable_flags_nothing(self):
        sel = pt.select_threshold([0.90, 0.80], [0.50, 0.40], 0.0)
        assert sel["threshold"] == FLAG_NOTHING and sel["catches"] == 0
        assert "flag nothing" in sel["note"]

    def test_empty_side_flags_nothing(self):
        assert pt.select_threshold([], [0.9], 0.05)["threshold"] == FLAG_NOTHING
        assert pt.select_threshold([0.2], [], 0.05)["threshold"] == FLAG_NOTHING

    def test_leave_one_student_out_judges_each_student_without_them(self):
        # Student b's natural attempt (0.43) sits above c's shadow attempt
        # (0.42). Chosen WITH b, the zero cap keeps the cut-off above 0.43;
        # chosen WITHOUT b, it falls to 0.42 to catch c's shadow, and b's own
        # natural attempt is falsely flagged out of sample.
        rows = (
            _rows([0.10, 0.05], [0.45], "a")
            + _rows([0.43], [0.50], "b")
            + _rows([0.08, 0.06], [0.42], "c")
        )
        sel_all = pt.select_threshold([0.10, 0.05, 0.43, 0.08, 0.06], [0.45, 0.50, 0.42], 0.0)
        assert sel_all["false_flags"] == 0 and sel_all["threshold"] == 0.45
        loso = pt.leave_one_student_out(rows, 0.0)
        assert loso["folds"] == 3
        assert loso["false_flags"]["k"] == 1 and loso["false_flags"]["n"] == 5
        assert loso["fold_thresholds"] == {"min": 0.42, "median": 0.45, "max": 0.5}

    def test_folds_get_the_full_cohort_false_flag_allowance(self):
        # 20 students, one natural and one shadow each, so at a 5% cap the
        # candidate may flag 1 of 20 natural attempts. Each fold has 19, and
        # 5% of 19 allows none: held to that, a fold is stricter than the
        # candidate and the out-of-sample count understates it. Here s01's
        # natural attempt (0.45) is flagged only by a fold allowed the
        # candidate's one false flag (the 0.50).
        naturals = {"s00": 0.50, "s01": 0.45, **{f"s{i:02d}": (20 - i) / 100 for i in range(2, 20)}}
        shadows = {f"s{i:02d}": 0.70 for i in range(20)}
        shadows.update({"s05": 0.48, "s06": 0.43, "s07": 0.40})
        rows = []
        for sid in sorted(naturals):
            rows += _rows([naturals[sid]], [shadows[sid]], sid)
        loso = pt.leave_one_student_out(rows, 0.05)
        assert loso["false_flag_allowance"] == 1
        assert loso["false_flags"]["k"] == 2  # s00's 0.50 and s01's 0.45
        # The rate rule on the s01 fold (19 naturals) would have allowed none.
        fold = [r for r in rows if r["claimed_student_id"] != "s01"]
        nat, sh = pt._split(fold)
        assert pt.select_threshold(nat, sh, 0.05)["threshold"] > 0.45
        assert pt.select_threshold(nat, sh, 0.05, max_false_flags=1)["threshold"] <= 0.45


# ── the proposal ──────────────────────────────────────────────────────────────


class TestPropose:
    def test_candidate_keeps_the_current_schema(self, ev, current):
        cand = pt.propose(ev, current)
        assert cand["kind"] == "candidate"
        for key in pt.COMPARED_FIELDS:
            assert key in cand
        assert cand["tier_weights"] == current["tier_weights"]
        assert cand["action_thresholds"] == current["action_thresholds"]
        assert cand["flag_rule"]["source"].startswith("CANDIDATE")

    def test_candidate_flag_rule_names_the_score_it_reads(self, ev, current):
        # The live rule reads the Collections score; the candidate reads
        # deviation_score, so its rule is rewritten rather than edited.
        cand = pt.propose(ev, current)
        assert pt.RULE_KEY == "flag_if_deviation_score_at_least"
        assert cand["score_field"] == "deviation_score" != current["score_field"]
        assert set(cand["flag_rule"]) == {pt.RULE_KEY, "status_when_flagged", "source"}
        assert 0.0 < cand["flag_rule"][pt.RULE_KEY] < 1.0

    def test_in_sample_choice_meets_the_cap(self, ev, current):
        for cap in (0.0, 0.02, 0.05, 0.10):
            sel = pt.propose(ev, current, cap=cap)["selection"]["in_sample"]
            assert sel["false_flags"]["k"] / sel["false_flags"]["n"] <= cap + 1e-12

    def test_trade_off_is_named(self, ev, current):
        cand = pt.propose(ev, current)
        text = cand["selection"]["trade_off"]
        assert "at most 5%" in text and "live rule (the exported verdict)" in text
        caps = [r["cap"] for r in cand["selection"]["trade_off_table"]]
        assert caps == sorted(caps) and 0.05 in caps
        catches = [r["catches"]["k"] for r in cand["selection"]["trade_off_table"]]
        assert catches == sorted(catches)  # a looser cap never catches fewer

    def test_gate_inputs_are_the_out_of_sample_numbers(self, ev, current):
        cand = pt.propose(ev, current)
        gi = cand["gate_inputs"]
        loso = cand["out_of_sample"]["leave_one_student_out"]
        assert gi["evidence"] == "leave_one_student_out"
        assert (gi["oos_false_flags"], gi["oos_natural"]) == (
            loso["false_flags"]["k"],
            loso["false_flags"]["n"],
        )
        assert (gi["oos_caught"], gi["oos_shadow"]) == (loso["catches"]["k"], loso["catches"]["n"])
        # 18, not 20: synth-01/02 have thin baselines, so no conclusive attempt
        # is scored against them and they add no evidence to the floor.
        assert gi["n_students"] == loso["folds"] == 18
        assert gi["natural_students"] == gi["shadow_students"] == 18
        assert gi["weights_match_scores"] is True and gi["selection_cap"] == 0.05
        assert gi["candidate_flags_more_than_folds"] is False

    def test_current_numbers_are_the_exported_verdict(self, ev, current):
        cur = pt.propose(ev, current)["selection"]["current_in_sample"]
        cm = ev["confusion_at_verdict"]
        assert cur["false_flags"]["k"] == cm["false_flag_rate_conclusive"]["k"]
        assert cur["catches"]["k"] == cm["catch_rate_conclusive"]["k"]

    def test_a_candidate_below_every_fold_is_marked(self, ev, current, monkeypatch):
        # A LOWER cut-off flags more. Force the in-sample choice under every
        # fold's and the gate input says so.
        real = pt.select_threshold
        calls = {"n": 0}

        def first_call_low(nat, sh, cap, max_false_flags=None):
            calls["n"] += 1
            out = real(nat, sh, cap, max_false_flags)
            if calls["n"] == 1:
                out = {**out, "threshold": 0.01}
            return out

        monkeypatch.setattr(pt, "select_threshold", first_call_low)
        gi = pt.propose(ev, current)["gate_inputs"]
        assert gi["candidate_flags_more_than_folds"] is True

    def test_gate_preview_is_what_calibration_gate_says(self, ev, current):
        cand = pt.propose(ev, current)
        direct = calibration_gate.evaluate_g_s1_study_operating_point(**cand["gate_inputs"])
        assert cand["gate_preview"] == asdict(direct)

    def test_study_weights_preserve_the_active_sum_of_squares(self, ev, current):
        from original.constants import FEATURE_TIER

        cand = pt.propose(ev, current, weights="study")
        w0 = {int(k): v for k, v in current["tier_weights"].items()}
        w1 = {int(k): v for k, v in cand["tier_weights"].items()}
        disabled = set(current["disabled_tiers"])
        for t in disabled:
            assert w1[t] == w0[t]
        counts = {}
        for tier in FEATURE_TIER.values():
            counts[tier] = counts.get(tier, 0) + 1
        before = sum(counts.get(t, 0) * w0[t] ** 2 for t in w0 if t not in disabled)
        after = sum(counts.get(t, 0) * w1[t] ** 2 for t in w1 if t not in disabled)
        assert after == pytest.approx(before, rel=1e-3)
        assert set(cand["weights"]["tiers_with_evidence"]) == {
            1,
            3,
        }  # the fixture's shifted columns
        assert all(0.5 <= f <= 2.0 for f in cand["weights"]["factors"].values())

    def test_changed_weights_make_the_gate_uninformative(self, ev, current):
        cand = pt.propose(ev, current, weights="study")
        assert cand["weights"]["scores_valid_for_candidate"] is False
        assert cand["gate_preview"]["verdict"] == "uninformative"
        assert "FRESH cohort" in cand["gate_preview"]["current_value"]

    def _fresh(self, tmp_path, name, src) -> dict:
        path = tmp_path / f"{name}.csv"
        path.write_text(src)
        return study_eval.run(path, tmp_path / name, charts=False)

    def test_fresh_cohort_becomes_the_gate_evidence(self, ev, current, tmp_path):
        # Different students and submissions (the fixture's numbers reused).
        src = CSV.read_text().replace("synth-", "fresh-").replace("sub-", "fsub-")
        fresh = self._fresh(tmp_path, "fresh", src)
        cand = pt.propose(ev, current, fresh=fresh)
        t = cand["flag_rule"][pt.RULE_KEY]
        assert cand["gate_inputs"]["evidence"] == "fresh_cohort"
        assert cand["gate_preview"]["detail"]["adoption_eligible"] is True
        sweep = {row["threshold"]: row for row in fresh["sweep"]}
        assert cand["out_of_sample"]["fresh_cohort"]["false_flags"] == sweep[t]["false_flags"]

    def test_fresh_cohort_cannot_be_the_training_csv(self, ev, current):
        with pytest.raises(pt.ProposalError, match="same CSV"):
            pt.propose(ev, current, fresh=ev)

    def test_fresh_cohort_cannot_be_the_training_rows_re_exported(self, ev, current, tmp_path):
        # Same students and submissions, new bytes: in-sample again, so its
        # false-flag count meets the cap by construction. Refused.
        fresh = self._fresh(tmp_path, "reexport", CSV.read_text().replace("synth-exam-1", "x"))
        with pytest.raises(pt.ProposalError, match="repeats 80 training submission"):
            pt.propose(ev, current, fresh=fresh)

    def test_fresh_cohort_must_be_different_students(self, ev, current, tmp_path):
        fresh = self._fresh(tmp_path, "samekids", CSV.read_text().replace("sub-", "fsub-"))
        with pytest.raises(pt.ProposalError, match="shares 20 student"):
            pt.propose(ev, current, fresh=fresh)

    def test_current_must_be_the_committed_snapshot(self, ev, current):
        cand = pt.propose(ev, current, weights="study")
        with pytest.raises(pt.ProposalError, match="kind 'current'"):
            pt.propose(ev, cand)

    def test_rejects_something_that_is_not_an_eval(self, current):
        with pytest.raises(pt.ProposalError, match="schema"):
            pt.propose({"schema": "nope"}, current)

    def test_rejects_an_eval_made_under_another_score_direction(self, ev, current):
        flipped = {**ev, "score": {**ev["score"], "direction": "higher_is_more_consistent"}}
        with pytest.raises(pt.ProposalError, match="selects on 'deviation_score'"):
            pt.propose(flipped, current)
        with pytest.raises(pt.ProposalError, match="selects on"):
            pt.propose(ev, current, fresh={**flipped, "input": {"sha256": "other"}})


# ── outputs: deterministic, never the live artifact ──────────────────────────


class TestOutputs:
    def test_end_to_end_is_deterministic(self, ev, tmp_path):
        eval_path = tmp_path / "study_eval.json"
        eval_path.write_text(json.dumps(ev))
        for name in ("a", "b"):
            assert pt.main(["--eval", str(eval_path), "--out-dir", str(tmp_path / name)]) == 0
        for f in (pt.CANDIDATE_NAME, pt.DIFF_NAME):
            assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f

    def test_live_artifact_is_never_modified(self, ev, tmp_path):
        before = hashlib.sha256(CURRENT.read_bytes()).hexdigest()
        eval_path = tmp_path / "study_eval.json"
        eval_path.write_text(json.dumps(ev))
        assert pt.main(["--eval", str(eval_path), "--out-dir", str(tmp_path / "out")]) == 0
        assert hashlib.sha256(CURRENT.read_bytes()).hexdigest() == before

    def test_refuses_to_write_the_live_artifact(self, tmp_path):
        with pytest.raises(pt.ProposalError, match="current .live. artifact"):
            pt.check_out_paths([CURRENT], CURRENT, force=True)
        other = tmp_path / "current.json"
        other.write_text("{}")
        with pytest.raises(pt.ProposalError, match="current .live. artifact"):
            pt.check_out_paths([other], other, force=True)

    @pytest.mark.parametrize("protected", ["original", "demo"])
    def test_refuses_protected_directories(self, ev, tmp_path, capsys, protected):
        eval_path = tmp_path / "study_eval.json"
        eval_path.write_text(json.dumps(ev))
        out = pt._ROOT / protected / "study_candidate_should_not_exist"
        assert pt.main(["--eval", str(eval_path), "--out-dir", str(out)]) == 2
        assert not out.exists()
        assert f"never go under {protected}/" in capsys.readouterr().err

    def test_a_differently_cased_path_to_a_protected_dir_is_refused(self, tmp_path):
        probe = tmp_path / "CaseProbe"
        probe.mkdir()
        if not (tmp_path / "caseprobe").exists():
            pytest.skip("case-sensitive filesystem: the bypass cannot happen here")
        with pytest.raises(pt.ProposalError, match="never go under original/"):
            pt.check_out_paths(
                [pt._ROOT / "ORIGINAL" / "x" / pt.CANDIDATE_NAME], CURRENT, force=True
            )

    def test_a_hard_link_to_the_live_artifact_is_refused_and_never_written_through(self, tmp_path):
        live = tmp_path / "current.json"
        live.write_text('{"kind": "current"}')
        link = tmp_path / "out" / pt.CANDIDATE_NAME
        link.parent.mkdir()
        os.link(live, link)
        with pytest.raises(pt.ProposalError, match="current .live. artifact"):
            pt.check_out_paths([link], live, force=True)
        pt._write_atomic(link, "replaced")  # replaces the directory entry ...
        assert live.read_text() == '{"kind": "current"}'  # ... not the linked file

    def test_existing_candidate_needs_force(self, ev, tmp_path, capsys):
        eval_path = tmp_path / "study_eval.json"
        eval_path.write_text(json.dumps(ev))
        out = tmp_path / "out"
        assert pt.main(["--eval", str(eval_path), "--out-dir", str(out)]) == 0
        assert pt.main(["--eval", str(eval_path), "--out-dir", str(out)]) == 2
        assert "--force" in capsys.readouterr().err
        assert pt.main(["--eval", str(eval_path), "--out-dir", str(out), "--force"]) == 0

    def test_diff_names_the_change_and_is_marked_not_live(self, ev, current):
        cand = pt.propose(ev, current)
        md = pt.render_diff(current, cand)
        assert md.startswith("# Candidate operating point (NOT LIVE)")
        t = cand["flag_rule"][pt.RULE_KEY]
        assert "| `score_field` | consistency_score | deviation_score |" in md
        assert f"| `flag_rule.flag_if_deviation_score_at_least` | None | {t} |" in md
        assert "| `flag_rule.flag_if_score_below` | 70 | None |" in md
        assert "```diff" in md and f'"flag_if_deviation_score_at_least": {t}' in md


# ── the drop-in: calibration_gate reads the candidate ────────────────────────


class TestCalibrationGateDropIn:
    def test_compute_reads_the_written_candidate(self, ev, tmp_path):
        eval_path = tmp_path / "study_eval.json"
        eval_path.write_text(json.dumps(ev))
        assert pt.main(["--eval", str(eval_path), "--out-dir", str(tmp_path / "c")]) == 0
        cand_path = tmp_path / "c" / pt.CANDIDATE_NAME
        cand = json.loads(cand_path.read_text())
        result = calibration_gate._compute_g_s1_study_gate(cand_path)
        assert result.name == "G-S1"
        assert result.verdict == cand["gate_preview"]["verdict"]
        assert (
            result.detail["candidate"]["flag_if_deviation_score_at_least"]
            == cand["flag_rule"][pt.RULE_KEY]
        )
        assert result.detail["candidate"]["score_field"] == "deviation_score"

    def test_env_var_names_the_candidate(self, ev, tmp_path, monkeypatch):
        eval_path = tmp_path / "study_eval.json"
        eval_path.write_text(json.dumps(ev))
        assert pt.main(["--eval", str(eval_path), "--out-dir", str(tmp_path / "c")]) == 0
        monkeypatch.setenv("STUDY_CANDIDATE", str(tmp_path / "c" / pt.CANDIDATE_NAME))
        assert (
            calibration_gate._compute_g_s1_study_gate()
            .detail["candidate"]["path"]
            .endswith(pt.CANDIDATE_NAME)
        )

    def test_gate_checks_weights_against_the_snapshot_not_the_candidate(self, ev, tmp_path):
        eval_path = tmp_path / "study_eval.json"
        eval_path.write_text(json.dumps(ev))
        assert (
            pt.main(
                ["--eval", str(eval_path), "--out-dir", str(tmp_path / "w"), "--weights", "study"]
            )
            == 0
        )
        cand_path = tmp_path / "w" / pt.CANDIDATE_NAME
        cand = json.loads(cand_path.read_text())
        cand["gate_inputs"]["weights_match_scores"] = True  # a hand-edited claim
        cand_path.write_text(json.dumps(cand))
        result = calibration_gate._compute_g_s1_study_gate(cand_path)
        assert (
            result.verdict == "uninformative"
            and result.detail["reason"] == "candidate changes tier weights"
        )

    def test_fixture_candidate_fails_out_of_sample(self, ev, current):
        # A demonstration of why the gate reads leave-one-student-out: on the
        # fictional fixture the in-sample choice meets the 5% cap, and the
        # out-of-sample re-selection does not.
        cand = pt.propose(ev, current)
        ins = cand["selection"]["in_sample"]["false_flags"]
        assert ins["k"] / ins["n"] <= 0.05
        assert cand["gate_preview"]["verdict"] == "fail"
        assert cand["gate_preview"]["detail"]["legs"]["A"] == "fail"
