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
from dataclasses import asdict
from pathlib import Path

import pytest

from scripts import propose_thresholds as pt
from validation import calibration_gate, study_eval

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
        {"claimed_student_id": student, "label": "natural", "score": s, "conclusive": True}
        for s in natural
    ]
    rows += [
        {"claimed_student_id": student, "label": "shadow", "score": s, "conclusive": True}
        for s in shadow
    ]
    return rows


# ── the selection rule ────────────────────────────────────────────────────────


class TestSelectThreshold:
    def test_most_catches_within_the_cap(self):
        natural = [50, 80, 85, 90, 95, 96, 97, 98, 99, 100]  # one false flag = 10%
        shadow = [40, 45, 60, 70]
        # cap 0: cannot flag the natural 50, so the cut-off stops at 50.
        assert pt.select_threshold(natural, shadow, 0.0)["threshold"] == 46
        # cap 10%: the natural 50 may be flagged, so everything below 80 can be.
        sel = pt.select_threshold(natural, shadow, 0.10)
        assert sel["threshold"] == 71 and sel["catches"] == 4 and sel["false_flags"] == 1

    def test_ties_go_to_the_lowest_cut_off(self):
        # Every cut-off from 41 to 80 catches the one shadow at 40 and flags
        # no natural attempt; the lowest is chosen (widest margin to natural).
        assert pt.select_threshold([80, 90], [40], 0.05)["threshold"] == 41

    def test_nothing_catchable_flags_nothing(self):
        sel = pt.select_threshold([10, 20], [50, 60], 0.0)
        assert sel["threshold"] == 0 and sel["catches"] == 0 and "flag nothing" in sel["note"]

    def test_empty_side_flags_nothing(self):
        assert pt.select_threshold([], [10], 0.05)["threshold"] == 0
        assert pt.select_threshold([80], [], 0.05)["threshold"] == 0

    def test_leave_one_student_out_judges_each_student_without_them(self):
        # Student b's natural attempt (57) sits below c's shadow attempt (58).
        # Chosen WITH b, the zero cap keeps the cut-off at or under 57; chosen
        # WITHOUT b, it rises to 59 to catch the 58, and b's own natural
        # attempt is falsely flagged out of sample.
        rows = _rows([90, 95], [55], "a") + _rows([57], [50], "b") + _rows([92, 94], [58], "c")
        sel_all = pt.select_threshold([90, 95, 57, 92, 94], [55, 50, 58], 0.0)
        assert sel_all["false_flags"] == 0 and sel_all["threshold"] == 56
        loso = pt.leave_one_student_out(rows, 0.0)
        assert loso["folds"] == 3
        assert loso["false_flags"]["k"] == 1 and loso["false_flags"]["n"] == 5


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

    def test_in_sample_choice_meets_the_cap(self, ev, current):
        for cap in (0.0, 0.02, 0.05, 0.10):
            sel = pt.propose(ev, current, cap=cap)["selection"]["in_sample"]
            assert sel["false_flags"]["k"] / sel["false_flags"]["n"] <= cap + 1e-12

    def test_trade_off_is_named(self, ev, current):
        cand = pt.propose(ev, current)
        text = cand["selection"]["trade_off"]
        assert "at most 5%" in text and "live rule (< 70)" in text
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
        assert gi["n_students"] == 20 and gi["weights_match_scores"] is True

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
        assert "re-score" in cand["gate_preview"]["current_value"]

    def test_fresh_cohort_becomes_the_gate_evidence(self, ev, current, tmp_path):
        src = CSV.read_text().replace("synth-exam-1", "synth-exam-2")  # same students, new bytes
        path = tmp_path / "fresh.csv"
        path.write_text(src)
        fresh = study_eval.run(path, tmp_path / "fresh", charts=False)
        cand = pt.propose(ev, current, fresh=fresh)
        t = cand["flag_rule"]["flag_if_score_below"]
        assert cand["gate_inputs"]["evidence"] == "fresh_cohort"
        assert (
            cand["out_of_sample"]["fresh_cohort"]["false_flags"] == fresh["sweep"][t]["false_flags"]
        )

    def test_fresh_cohort_cannot_be_the_training_csv(self, ev, current):
        with pytest.raises(pt.ProposalError, match="same CSV"):
            pt.propose(ev, current, fresh=ev)

    def test_rejects_something_that_is_not_an_eval(self, current):
        with pytest.raises(pt.ProposalError, match="schema"):
            pt.propose({"schema": "nope"}, current)


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
        t = cand["flag_rule"]["flag_if_score_below"]
        assert f"| `flag_rule.flag_if_score_below` | 70 | {t} |" in md
        assert "```diff" in md and f'"flag_if_score_below": {t}' in md


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
            result.detail["candidate"]["flag_if_score_below"]
            == cand["flag_rule"]["flag_if_score_below"]
        )

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

    def test_fixture_candidate_fails_out_of_sample(self, ev, current):
        # A demonstration of why the gate reads leave-one-student-out: on the
        # fictional fixture the in-sample choice meets the 5% cap, and the
        # out-of-sample re-selection does not.
        cand = pt.propose(ev, current)
        ins = cand["selection"]["in_sample"]["false_flags"]
        assert ins["k"] / ins["n"] <= 0.05
        assert cand["gate_preview"]["verdict"] == "fail"
        assert cand["gate_preview"]["detail"]["legs"]["A"] == "fail"
