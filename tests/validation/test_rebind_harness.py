"""G-REBIND harness and gate (validation/rebind/harness.py, calibration_gate)."""
from __future__ import annotations

import json

import pytest

from original.quantum.scoring import LLR_REBIND_THRESHOLDS
from validation.calibration_gate import (
    _compute_g_rebind_data,
    evaluate_g_rebind,
)
from validation.rebind.harness import (
    PairRecord,
    load_records,
    rates,
    select_thresholds,
    split_by_author,
)


def _recs(n, *, genuine, llr, deviation, corpus="c", prefix=None):
    prefix = prefix or ("g" if genuine else "i")
    return [
        PairRecord(author=f"{prefix}{k % 20}", genuine=genuine, deviation=deviation,
                   llr=llr, corpus=corpus)
        for k in range(n)
    ]


def _separable(n):
    # Genuine papers sit high on deviation (gate leaves them at
    # schedule_conversation+), impostors low (gate never reaches it); llr
    # separates them cleanly, so rebind beats gate on every leg.
    return _recs(n, genuine=True, llr=0.1, deviation=0.8) + _recs(
        n, genuine=False, llr=0.9, deviation=0.5
    )


def test_split_refuses_shared_author():
    records = [
        PairRecord("shared", True, 0.5, 0.5, "x"),
        PairRecord("shared", True, 0.5, 0.5, "y"),
    ]
    with pytest.raises(ValueError, match="both sides"):
        split_by_author(records, seed=1)


def test_split_is_author_disjoint():
    records = _separable(40)
    d, h = split_by_author(records, seed=20261116)
    assert d and h and len(d) + len(h) == len(records)
    assert not ({r.author for r in d} & {r.author for r in h})


def test_select_thresholds_respects_fpr():
    gen = [PairRecord(f"a{k}", True, 0.5, k * 0.5 / 99, "c") for k in range(100)]
    imp = [PairRecord(f"b{k}", False, 0.5, 0.5 + k * 0.5 / 99, "c") for k in range(100)]
    th = select_thresholds(gen + imp)
    assert rates(gen + imp, "rebind", th)["fa_sc"] <= 0.05
    assert rates(gen + imp, "rebind", th)["fa_esc"] <= 0.01
    sc = th["schedule_conversation"][0]
    assert th["monitor"] == (pytest.approx(sc - 0.15), sc)
    assert th["escalate"][0] >= sc


def test_select_thresholds_floor_and_no_genuine():
    th = select_thresholds([PairRecord("a", True, 0.5, 0.05, "c")])
    assert th["monitor"][0] == 0.0
    with pytest.raises(ValueError):
        select_thresholds(_recs(3, genuine=False, llr=0.5, deviation=0.5))


def test_rates_unknown_mode_and_empty():
    with pytest.raises(ValueError):
        rates(_separable(2), "blend", LLR_REBIND_THRESHOLDS)
    r = rates([], "gate", LLR_REBIND_THRESHOLDS)
    assert r["catch_sc"] is None and r["n_genuine"] == 0


def test_gate_passes_on_separable():
    res = evaluate_g_rebind(_separable(400), LLR_REBIND_THRESHOLDS)
    assert res.name == "G-REBIND"
    assert res.verdict == "pass" and res.passed
    assert set(res.detail["rates"]) == {"gate", "rebind"}


def test_gate_fails_when_rebind_worse():
    records = _recs(400, genuine=True, llr=0.9, deviation=0.8) + _recs(
        400, genuine=False, llr=0.1, deviation=0.5
    )
    assert evaluate_g_rebind(records, LLR_REBIND_THRESHOLDS).verdict == "fail"


def test_gate_uninformative_small_n():
    assert evaluate_g_rebind(_separable(10), LLR_REBIND_THRESHOLDS).verdict == "uninformative"


def test_gate_uninformative_no_impostors():
    records = _recs(400, genuine=True, llr=0.1, deviation=0.8)
    assert evaluate_g_rebind(records, LLR_REBIND_THRESHOLDS).verdict == "uninformative"


def test_gate_uninformative_no_genuine():
    records = _recs(400, genuine=False, llr=0.9, deviation=0.5)
    assert evaluate_g_rebind(records, LLR_REBIND_THRESHOLDS).verdict == "uninformative"


def _write_report(path, label, records):
    pairs = [
        {
            "baseline_author": r.author,
            "submission_author": r.author if r.genuine else r.author + "_other",
            "deviation": r.deviation,
            "llr": r.llr,
        }
        for r in records
    ]
    path.write_text(json.dumps({"label": label, "extra": {"pairs": pairs}}))


def test_load_records_round_trip(tmp_path):
    src = _separable(3)
    p = tmp_path / "report.json"
    _write_report(p, "seminary", src)
    out = load_records(p)
    def key(rs):
        return [(r.author, r.genuine, r.llr) for r in rs]

    assert key(out) == key(src)
    assert {r.corpus for r in out} == {"seminary"}


def test_load_records_requires_pairs(tmp_path):
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"label": "x", "extra": {}}))
    with pytest.raises(ValueError, match="extra.pairs"):
        load_records(p)


def test_compute_missing_corpus_is_uninformative(tmp_path):
    res = _compute_g_rebind_data(records_dir=tmp_path / "absent")
    assert res.verdict == "uninformative" and not res.passed


def test_compute_runs_on_records(tmp_path):
    _write_report(tmp_path / "a.json", "seminary", _separable(400))
    res = _compute_g_rebind_data(records_dir=tmp_path)
    assert res.name == "G-REBIND"
    assert res.verdict in {"pass", "fail", "uninformative"}
    assert "thresholds" in res.detail and "seminary" in res.detail["per_corpus"]


def test_run_all_registers_g_rebind(monkeypatch, tmp_path):
    import validation.calibration_gate as cg

    monkeypatch.setattr(cg, "_G_REBIND_RECORDS_DIR", tmp_path / "absent")
    results = cg.run_all(only={"G-REBIND"})
    (res,) = [r for r in results if r.name == "G-REBIND"]
    assert res.verdict == "uninformative"


def test_run_all_g_rebind_crash_is_machinery_error(monkeypatch):
    import validation.calibration_gate as cg

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(cg, "_compute_g_rebind_data", boom)
    (res,) = [r for r in cg.run_all(only={"G-REBIND"}) if r.name == "G-REBIND"]
    assert res.verdict != "pass" and not res.passed
