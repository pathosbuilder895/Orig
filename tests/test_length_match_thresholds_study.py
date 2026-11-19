"""Failure witnesses for the length-matched cut-point study's verdict and its
once-only hold-out guard (validation/length_match_thresholds/run.py).

The study is a standalone pre-registered diagnostic, not a calibration-gate
leg (a battery leg would reopen the locked partition on every run), but its
verdict decides whether cut points are wired in, so each failure path is
pinned here."""

import json
import sys

import pytest

# The study blocks sentence-transformers on import, as the pilot's lockfile
# does; undo that here so it cannot leak into the rest of the suite.
_HAD_ST = "sentence_transformers" in sys.modules
from validation.length_match_thresholds import run as study  # noqa: E402

if not _HAD_ST and sys.modules.get("sentence_transformers", 0) is None:
    del sys.modules["sentence_transformers"]


def _summary(**kw):
    s = {
        "n_authors": 60,
        "n_honest": 360,
        "engagement": 1.0,
        "action_agreement": 1.0,
        "honest_flagged_ci95_by_author": [0.0, 0.014],
        "honest_escalate_ci95_by_author": [0.0, 0.0],
        "auc_off": 0.767,
        "auc_on": 0.836,
        "on_new_cut_points": {"other_writers_caught": 0.139},
        "off_catch_at_on_new_flag_rate": 0.059,
    }
    s.update(kw)
    return s


def test_importing_the_study_leaves_sentence_transformers_alone():
    assert (
        _HAD_ST
        or "sentence_transformers" not in sys.modules
        or (sys.modules["sentence_transformers"] is not None)
    )


def test_the_committed_hold_out_summary_passes():
    assert study.verdict(_summary())["verdict"] == "pass"


@pytest.mark.parametrize(
    "change",
    [
        {"n_authors": 29},
        {"n_honest": 199},
        {"engagement": 0.89},
        {"action_agreement": 0.99},
    ],
)
def test_too_little_evidence_is_uninformative_never_a_pass(change):
    assert study.verdict(_summary(**change))["verdict"] == "uninformative"


@pytest.mark.parametrize(
    "change, criterion",
    [
        ({"honest_flagged_ci95_by_author": [0.05, 0.11]}, "H1"),
        ({"honest_escalate_ci95_by_author": [0.0, 0.06]}, "H2"),
        ({"auc_on": 0.75}, "C1"),
        ({"off_catch_at_on_new_flag_rate": 0.17}, "C2"),
    ],
)
def test_each_criterion_can_fail(change, criterion):
    v = study.verdict(_summary(**change))
    assert v["verdict"] == "fail"
    assert v[criterion] is False


def test_the_live_on_cut_points_follow_whether_the_match_applied():
    assert study.live_on_cut_points(False) == study.product_cut_points()
    on = study.live_on_cut_points(True)
    assert on["monitor"] < on["schedule_conversation"] < on["escalate"]
    assert on != study.product_cut_points()


def test_a_finished_hold_out_cannot_be_rerun_under_another_output_path(tmp_path):
    """The committed report exists, so a second look is refused wherever the
    new report would go."""
    assert study._already_reported(tmp_path / "elsewhere.json")


def test_an_unrelated_file_does_not_count_as_a_report(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "HERE", tmp_path)
    (tmp_path / "report_x.json").write_text(json.dumps({"study_id": "another-study"}))
    (tmp_path / "report_bad.json").write_text("not json")
    assert not study._already_reported(tmp_path / "out.json")
