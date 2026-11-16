"""G-WRITERLINE harness and gate (validation/writer_line/harness.py, calibration_gate)."""
from __future__ import annotations

import json
import math

import pytest

from original.constants import WRITER_LINE_Z_THRESHOLDS
from validation.calibration_gate import _compute_g_writerline_data, evaluate_g_writerline
from validation.gate_contracts import GATE_CONTRACTS
from validation.writer_line.harness import (
    WriterPairRecord,
    _action,
    exploratory_split_average,
    load_writer_records,
    rates,
    select_z_thresholds,
    writers_escalate_unreachable,
)

LOO = (0.25, 0.3, 0.35)  # leave-one-out deviations: mean 0.3, std ~0.0408
# Fixed bands so fixtures do not move with the calibrated constant.
BANDS = {
    "no_action": (-math.inf, 1.0),
    "monitor": (1.0, 2.0),
    "schedule_conversation": (2.0, 3.0),
    "escalate": (3.0, math.inf),
}


def _recs(n, *, genuine, deviation, loo=LOO, corpus="c", llr=0.5):
    prefix = "g" if genuine else "i"
    return [
        WriterPairRecord(f"{prefix}{k % 20}", genuine, deviation, llr, corpus, loo_dev=loo)
        for k in range(n)
    ]


def test_pass_when_writer_line_beats_gate():
    # Genuine pairs sit at their writer's own mean (z 0, gate no_action);
    # impostors (deviation 0.55, gate monitor) sit far above the writer's spread.
    holdout = _recs(400, genuine=True, deviation=0.3) + _recs(
        400, genuine=False, deviation=0.55
    )
    res = evaluate_g_writerline(holdout, BANDS)
    assert res.verdict == "pass", res.current_value


def test_witness_fails():
    res = GATE_CONTRACTS["evaluate_g_writerline"].failure_witness()
    assert res.name == "G-WRITERLINE"
    assert res.verdict == "fail"


def test_n_genuine_29_uninformative():
    holdout = _recs(29, genuine=True, deviation=0.3) + _recs(
        40, genuine=False, deviation=0.55
    )
    assert evaluate_g_writerline(holdout, BANDS).verdict == "uninformative"


def test_records_without_loo_dev_raise(tmp_path):
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"label": "old", "extra": {"pairs": [
        {"baseline_author": "a", "submission_author": "a", "deviation": 0.3, "llr": 0.4}
    ]}}))
    with pytest.raises(ValueError, match="re-run validation/verify/run_null_model.py"):
        load_writer_records(p)


def test_load_reads_loo_dev(tmp_path):
    p = tmp_path / "new.json"
    p.write_text(json.dumps({"label": "new", "extra": {"pairs": [
        {"baseline_author": "a", "submission_author": "b", "deviation": 0.3,
         "llr": 0.4, "loo_dev": [0.5, 0.6, 0.7]}
    ]}}))
    (r,) = load_writer_records(p)
    assert r.deviation == 0.3 and r.loo_dev == (0.5, 0.6, 0.7) and not r.genuine


def test_thresholds_use_derivation_genuine_z_only():
    gen = _recs(100, genuine=True, deviation=0.3)
    a = select_z_thresholds(gen + _recs(100, genuine=False, deviation=0.55))
    b = select_z_thresholds(gen + _recs(100, genuine=False, deviation=0.95))
    assert a == b


def test_thresholds_are_contiguous():
    gen = [
        WriterPairRecord(f"g{k}", True, 0.3 + k * 0.001, 0.5, "c", loo_dev=LOO)
        for k in range(100)
    ]
    t = select_z_thresholds(gen)
    names = list(t)
    assert names == ["no_action", "monitor", "schedule_conversation", "escalate"]
    assert t["no_action"][0] == -math.inf and t["escalate"][1] == math.inf
    for lo_name, hi_name in zip(names, names[1:], strict=False):
        assert t[lo_name][1] == t[hi_name][0]
        assert t[lo_name][0] <= t[lo_name][1]


def test_shipped_thresholds_are_contiguous():
    t = WRITER_LINE_Z_THRESHOLDS
    names = list(t)
    assert t[names[0]][0] == -math.inf and t[names[-1]][1] == math.inf
    for lo_name, hi_name in zip(names, names[1:], strict=False):
        assert t[lo_name][1] == t[hi_name][0]


def test_abstaining_pairs_fall_back_to_gate():
    recs = _recs(10, genuine=True, deviation=0.9, loo=(0.5, 0.6))
    r = rates(recs, "writer_line", BANDS)
    assert r["n_fallback"] == 10
    assert r["fa_sc"] == rates(recs, "gate", BANDS)["fa_sc"]


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        rates(_recs(1, genuine=True, deviation=0.3), "nope", BANDS)


def test_writers_escalate_unreachable_counts():
    recs = _recs(2, genuine=True, deviation=0.3) + _recs(
        2, genuine=False, deviation=0.9
    ) + _recs(1, genuine=True, deviation=0.3, loo=(0.5,))
    out = writers_escalate_unreachable(recs, BANDS)
    assert out["of"] == 4 and out["count"] == 2
    assert set(out["writers"]) == {"g0", "g1"}


def test_missing_records_dir_uninformative(tmp_path):
    res = _compute_g_writerline_data(tmp_path / "none")
    assert res.verdict == "uninformative" and "SKIPPED" in res.current_value


def test_writer_line_applies_gate_downgrade():
    # z ~6 puts the writer line at escalate; a confidently genuine llr lowers it one step.
    (plain,) = _recs(1, genuine=False, deviation=0.55)
    (low_llr,) = _recs(1, genuine=False, deviation=0.55, llr=0.2)
    assert _action(plain, "writer_line", BANDS) == ("escalate", False)
    assert _action(low_llr, "writer_line", BANDS) == ("schedule_conversation", False)


def test_exploratory_average_is_labelled_and_runs():
    recs = []
    for a in range(10):
        recs += [WriterPairRecord(f"w{a}", True, 0.3, 0.5, "c", submission_author=f"w{a}",
                                  loo_dev=LOO)]
        recs += [WriterPairRecord(f"w{a}", False, 0.6, 0.5, "c",
                                  submission_author=f"w{(a + 1) % 10}", loo_dev=LOO)]
    out = exploratory_split_average(recs, seeds=range(3))
    assert out["label"].startswith("exploratory")
    assert out["n_splits_used"] == 3
    assert out["writer_line"]["mean_holdout_catch"] == 1.0
