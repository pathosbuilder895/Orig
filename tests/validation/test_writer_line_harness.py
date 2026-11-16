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
    load_writer_records,
    rates,
    select_z_thresholds,
    writers_escalate_unreachable,
)

LOO = (0.5, 0.6, 0.7)  # mean 0.6, std ~0.0816
# Fixed bands so fixtures do not move with the calibrated constant.
BANDS = {
    "no_action": (-math.inf, 1.0),
    "monitor": (1.0, 2.0),
    "schedule_conversation": (2.0, 3.0),
    "escalate": (3.0, math.inf),
}


def _recs(n, *, genuine, rms_z, deviation, loo=LOO, corpus="c"):
    prefix = "g" if genuine else "i"
    return [
        WriterPairRecord(f"{prefix}{k % 20}", genuine, deviation, 0.5, corpus,
                         rms_z=rms_z, loo=loo)
        for k in range(n)
    ]


def test_pass_when_writer_line_beats_gate():
    # Gate leaves everyone at no_action (deviation 0.2); the writer line puts
    # genuine pairs at z 0 and impostors far above their writer's spread.
    holdout = _recs(400, genuine=True, rms_z=0.6, deviation=0.2) + _recs(
        400, genuine=False, rms_z=1.6, deviation=0.2
    )
    res = evaluate_g_writerline(holdout, BANDS)
    assert res.verdict == "pass", res.current_value


def test_witness_fails():
    res = GATE_CONTRACTS["evaluate_g_writerline"].failure_witness()
    assert res.name == "G-WRITERLINE"
    assert res.verdict == "fail"


def test_n_genuine_29_uninformative():
    holdout = _recs(29, genuine=True, rms_z=0.6, deviation=0.2) + _recs(
        40, genuine=False, rms_z=1.6, deviation=0.2
    )
    assert evaluate_g_writerline(holdout, BANDS).verdict == "uninformative"


def test_records_without_loo_raise(tmp_path):
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"label": "old", "extra": {"pairs": [
        {"baseline_author": "a", "submission_author": "a", "deviation": 0.3, "llr": 0.4}
    ]}}))
    with pytest.raises(ValueError, match="re-run validation/verify/run_null_model.py"):
        load_writer_records(p)


def test_load_reads_rms_z_and_loo(tmp_path):
    p = tmp_path / "new.json"
    p.write_text(json.dumps({"label": "new", "extra": {"pairs": [
        {"baseline_author": "a", "submission_author": "b", "deviation": 0.3,
         "llr": 0.4, "rms_z": 1.2, "loo": [0.5, 0.6, 0.7]}
    ]}}))
    (r,) = load_writer_records(p)
    assert r.rms_z == 1.2 and r.loo == (0.5, 0.6, 0.7) and not r.genuine


def test_thresholds_use_derivation_genuine_z_only():
    gen = _recs(100, genuine=True, rms_z=0.6, deviation=0.2)
    a = select_z_thresholds(gen + _recs(100, genuine=False, rms_z=1.6, deviation=0.2))
    b = select_z_thresholds(gen + _recs(100, genuine=False, rms_z=9.0, deviation=0.2))
    assert a == b


def test_thresholds_are_contiguous():
    gen = [
        WriterPairRecord(f"g{k}", True, 0.2, 0.5, "c", rms_z=0.4 + k * 0.01, loo=LOO)
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
    recs = _recs(10, genuine=True, rms_z=5.0, deviation=0.2, loo=(0.5, 0.6))
    r = rates(recs, "writer_line", BANDS)
    assert r["n_fallback"] == 10
    assert r["fa_sc"] == rates(recs, "gate", BANDS)["fa_sc"]


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        rates(_recs(1, genuine=True, rms_z=0.6, deviation=0.2), "nope", BANDS)


def test_writers_escalate_unreachable_counts():
    recs = _recs(2, genuine=True, rms_z=0.6, deviation=0.2) + _recs(
        2, genuine=False, rms_z=9.0, deviation=0.2
    ) + _recs(1, genuine=True, rms_z=0.6, deviation=0.2, loo=(0.5,))
    out = writers_escalate_unreachable(recs, BANDS)
    assert out["of"] == 4 and out["count"] == 2
    assert set(out["writers"]) == {"g0", "g1"}


def test_missing_records_dir_uninformative(tmp_path):
    res = _compute_g_writerline_data(tmp_path / "none")
    assert res.verdict == "uninformative" and "SKIPPED" in res.current_value
