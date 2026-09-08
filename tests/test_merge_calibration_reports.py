import json

import pytest

from scripts.merge_calibration_reports import LEG_GATES, main, merge


def _report(gates, sha="abc", only=None):
    return {
        "experiment": {"git_sha": sha},
        "vector_cache": None,
        "only": only,
        "gates": [{"name": n, "verdict": v} for n, v in gates],
    }


def test_merges_in_leg_order_and_records_provenance():
    a = _report([("G5", "pass"), ("G2", "pass")], only=["G2", "G5"])
    b = _report([("G1", "pass")], only=["G1"])
    m = merge([a, b])
    assert [g["name"] for g in m["gates"]] == ["G1", "G2", "G5"]
    assert m["merged_from"] == [
        {"only": ["G2", "G5"], "gates": ["G5", "G2"]},
        {"only": ["G1"], "gates": ["G1"]},
    ]
    assert "G3" in m["missing_legs"] and "T" in m["missing_legs"]


def test_complete_set_has_no_missing_legs():
    gates = [(n, "pass") for names in LEG_GATES.values() for n in names]
    m = merge([_report(gates)])
    assert m["missing_legs"] == []


def test_mixed_commits_are_refused():
    with pytest.raises(ValueError):
        merge([_report([("G1", "pass")], sha="a"), _report([("G2", "pass")], sha="b")])


def test_cli_exit_codes(tmp_path):
    full = tmp_path / "full.json"
    full.write_text(json.dumps(_report([(n, "pass") for ns in LEG_GATES.values() for n in ns])))
    out = tmp_path / "out.json"
    assert main([str(out), str(full)]) == 0
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps(_report([("G1", "uninformative")])))
    assert main([str(out), str(partial)]) == 1
    assert json.loads(out.read_text())["missing_legs"]
