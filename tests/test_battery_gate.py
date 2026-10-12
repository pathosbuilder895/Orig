"""scripts/battery_gate.py and the weekly battery workflow that calls it (T-14).

A fail or uninformative gate verdict is a measurement and must not turn the
weekly run red; a crashed leg, a missing report or a gate that raised is an
ERROR and must. Fake reports below stand in for the battery's output.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from scripts import merge_calibration_reports
from scripts.battery_gate import LEG_GATES, find_errors, main, parse_legs

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "calibration-battery.yml"

ALL_GATES = [n for names in LEG_GATES.values() for n in names]

# The verdicts of weekly run 37346489159 (2026-10-05): seven gates not passing,
# every one of them a measurement.
NOT_PASSING_2026_10_05 = {
    "G1": "uninformative",
    "G1p": "fail",
    "G3": "uninformative",
    "G6": "uninformative",
    "G7": "uninformative",
    "T-1": "fail",
    "T-3": "fail",
}


def _gate(name, verdict="pass", **extra):
    return {"name": name, "verdict": verdict, "criterion": "c", "current_value": "v", **extra}


def _report(gates, only=None):
    return {"experiment": {"git_sha": "abc"}, "vector_cache": None, "only": only, "gates": gates}


def _full(overrides=None):
    overrides = overrides or {}
    return _report([_gate(n, overrides.get(n, "pass")) for n in ALL_GATES])


def _machinery_error(name):
    return _gate(
        name,
        "fail",
        current_value="ERROR (machinery): boom",
        detail={"machinery_error": "boom"},
    )


def _write(tmp_path, report, name="report.json"):
    path = tmp_path / name
    path.write_text(json.dumps(report))
    return str(path)


# -- find_errors -------------------------------------------------------------


def test_all_pass_has_no_errors():
    assert find_errors(_full()) == []


def test_fail_and_uninformative_are_measurements_not_errors():
    assert find_errors(_full(NOT_PASSING_2026_10_05)) == []


def test_machinery_error_entry_is_an_error():
    report = _full()
    report["gates"][2] = _machinery_error(report["gates"][2]["name"])
    errors = find_errors(report)
    assert len(errors) == 1 and "raised instead of returning a verdict" in errors[0]


def test_error_current_value_without_detail_is_an_error():
    report = _full()
    report["gates"][0]["current_value"] = "ERROR (machinery): boom"
    assert "reports an error" in find_errors(report)[0]


@pytest.mark.parametrize("verdict", [None, "", "ERROR", "skipped"])
def test_gate_without_a_valid_verdict_is_an_error(verdict):
    report = _full()
    report["gates"][0]["verdict"] = verdict
    assert "has no verdict" in find_errors(report)[0]


@pytest.mark.parametrize("entry", ["G1", {"verdict": "pass"}])
def test_malformed_gate_entry_is_an_error(entry):
    report = _full()
    report["gates"].append(entry)
    assert "malformed gate entry" in find_errors(report)[0]


def test_missing_leg_is_an_error():
    report = _report([_gate(n) for n in ALL_GATES if n != "G5"])
    assert find_errors(report) == [
        "leg G5 reported nothing for G5 (crashed, cut off, or never ran)"
    ]


def test_partial_termsim_leg_names_the_missing_gates():
    report = _report([_gate(n) for n in ALL_GATES if n not in ("T-2", "T-4")])
    assert "leg T reported nothing for T-2, T-4" in find_errors(report)[0]


@pytest.mark.parametrize("report", [None, [], {}, {"gates": "G1"}])
def test_no_report_is_an_error(report):
    assert "no calibration report" in find_errors(report)[0]


def test_leg_report_is_only_held_to_its_own_legs():
    report = _report([_gate("G1", "uninformative"), _gate("G1p", "fail")], only=["G1", "G1p"])
    assert find_errors(report, legs=["G1", "G1p"], exit_status=1) == []
    assert "leg G1p" in find_errors(_report([_gate("G1")]), legs=["G1", "G1p"])[0]


@pytest.mark.parametrize("status", [2, 124, 137, -1])
def test_exit_status_other_than_0_or_1_is_an_error_even_with_a_clean_report(status):
    errors = find_errors(_full(), exit_status=status)
    assert len(errors) == 1 and f"battery exited {status}" in errors[0]


def test_exit_1_with_a_measurement_is_not_an_error():
    assert find_errors(_full({"G7": "uninformative"}), exit_status=1) == []


def test_exit_1_with_every_gate_passing_is_an_error():
    assert "every gate in its report passed" in find_errors(_full(), exit_status=1)[0]


def test_exit_0_with_every_gate_passing_is_clean():
    assert find_errors(_full(), exit_status=0) == []


def test_crash_without_report_reports_both_the_status_and_the_missing_report():
    errors = find_errors(None, legs=["G3", "G4"], exit_status=124)
    assert len(errors) == 2
    assert "battery exited 124" in errors[0] and "no calibration report" in errors[1]


def test_recognises_the_batterys_own_machinery_error_shape():
    # Contract with the producer: whatever validation/calibration_gate.py
    # writes for a gate that raised must read as an ERROR here.
    from validation.calibration_gate import GateResult, _machinery_error_result

    report = _report(
        [
            asdict(_machinery_error_result("G2", "criterion", RuntimeError("leg unhealthy"))),
            asdict(GateResult("G2b", False, "c", "SKIPPED", verdict="uninformative")),
        ]
    )
    errors = find_errors(report, legs=["G2", "G2b"])
    assert errors == ["G2 raised instead of returning a verdict: leg unhealthy"]


# -- parse_legs --------------------------------------------------------------


def test_parse_legs_is_case_insensitive_and_skips_blanks():
    assert parse_legs("g1, G1P,,t") == ["G1", "G1p", "T"]
    assert parse_legs(None) is None and parse_legs(" ") is None and parse_legs(",") is None


def test_parse_legs_rejects_unknown_names():
    with pytest.raises(ValueError, match="unknown leg 'G9'"):
        parse_legs("G1,G9")


# -- CLI -----------------------------------------------------------------------


def test_cli_all_pass_exits_0(tmp_path, capsys):
    assert main([_write(tmp_path, _full())]) == 0
    out = capsys.readouterr().out
    assert "not passing (measurements, not errors): none" in out
    assert "battery_gate: no ERROR" in out


def test_cli_measurements_exit_0_and_are_listed(tmp_path, capsys):
    assert main([_write(tmp_path, _full(NOT_PASSING_2026_10_05))]) == 0
    out = capsys.readouterr().out
    assert (
        "not passing (measurements, not errors): G1 uninformative, G1p fail, "
        "G3 uninformative, G6 uninformative, G7 uninformative, T-1 fail, T-3 fail"
    ) in out
    assert "G1p   [FAIL         ] v" in out
    assert "ERROR:" not in out and "battery_gate: no ERROR" in out


def test_cli_missing_report_file_exits_1(tmp_path, capsys):
    path = str(tmp_path / "calibration-report-g5.json")
    assert main([path, "--legs", "G5", "--exit-status", "1"]) == 1
    out = capsys.readouterr().out
    assert f"could not read {path}" in out and "ERROR: no calibration report" in out
    assert "battery_gate: 1 ERROR(s)" in out


def test_cli_unparseable_report_exits_1(tmp_path, capsys):
    path = tmp_path / "truncated.json"
    path.write_text('{"gates": [{"name": "G1"')
    assert main([str(path)]) == 1
    assert "ERROR: no calibration report" in capsys.readouterr().out


def test_cli_report_with_error_entry_exits_1_and_keeps_measurements(tmp_path, capsys):
    report = _full({"G7": "uninformative"})
    report["gates"][ALL_GATES.index("G4")] = _machinery_error("G4")
    assert main([_write(tmp_path, report)]) == 1
    out = capsys.readouterr().out
    assert "ERROR: G4 raised instead of returning a verdict: boom" in out
    assert "not passing (measurements, not errors): G7 uninformative" in out


def test_cli_leg_mode(tmp_path):
    leg = _write(tmp_path, _report([_gate("G3", "uninformative"), _gate("G4")], only=["G3", "G4"]))
    assert main([leg, "--legs", "G3,G4", "--exit-status", "1"]) == 0
    assert main([leg, "--legs", "G3,G4", "--exit-status", "124"]) == 1
    assert main([leg, "--legs", "G3,G4,G5", "--exit-status", "1"]) == 1


def test_cli_unknown_leg_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main([_write(tmp_path, _full()), "--legs", "G9"])
    assert exc.value.code == 2


# -- merge_calibration_reports.py --fail-on-error-only -------------------------


def _legs(tmp_path, overrides=None, drop=(), error=None):
    """One report per CI matrix leg group, as the workflow's merge job sees them."""
    overrides = overrides or {}
    groups = [("G1", "G1p"), ("G2",), ("G2b",), ("G3", "G4"), ("G5",), ("G6", "G7", "G8", "T")]
    paths = []
    for i, legs in enumerate(groups):
        names = [n for leg in legs if leg not in drop for n in LEG_GATES[leg]]
        if not names:
            continue
        gates = [
            _machinery_error(n) if n == error else _gate(n, overrides.get(n, "pass")) for n in names
        ]
        paths.append(_write(tmp_path, _report(gates, only=list(legs)), f"leg{i}.json"))
    return paths


def test_merge_fail_on_error_only_passes_measurements(tmp_path, capsys):
    out = str(tmp_path / "merged.json")
    inputs = _legs(tmp_path, NOT_PASSING_2026_10_05)
    assert merge_calibration_reports.main(["--fail-on-error-only", out, *inputs]) == 0
    merged = json.loads(Path(out).read_text())
    assert merged["missing_legs"] == [] and len(merged["gates"]) == len(ALL_GATES)
    assert "not passing: ['G1', 'G1p', 'G3', 'G6', 'G7', 'T-1', 'T-3']" in capsys.readouterr().out
    # Without the flag the merge keeps mirroring --strict.
    assert merge_calibration_reports.main([out, *inputs]) == 1


def test_merge_fail_on_error_only_fails_on_a_missing_leg(tmp_path, capsys):
    out = str(tmp_path / "merged.json")
    assert (
        merge_calibration_reports.main(["--fail-on-error-only", out, *_legs(tmp_path, drop={"G5"})])
        == 1
    )
    assert "ERROR: leg G5 reported nothing for G5" in capsys.readouterr().out
    assert json.loads(Path(out).read_text())["missing_legs"] == ["G5"]


def test_merge_fail_on_error_only_fails_on_a_machinery_error(tmp_path, capsys):
    out = str(tmp_path / "merged.json")
    assert (
        merge_calibration_reports.main(["--fail-on-error-only", out, *_legs(tmp_path, error="G6")])
        == 1
    )
    assert "ERROR: G6 raised instead of returning a verdict" in capsys.readouterr().out


def test_merge_fail_on_error_only_still_needs_inputs():
    assert merge_calibration_reports.main(["--fail-on-error-only", "out.json"]) == 2


# -- the workflow wiring -------------------------------------------------------


def _jobs():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def _step(job, prefix):
    return next(s for s in _jobs()[job]["steps"] if s.get("name", "").startswith(prefix))


def test_workflow_does_not_hide_a_failed_job():
    for name, job in _jobs().items():
        assert "continue-on-error" not in job, name


def test_leg_step_hands_the_exit_status_to_battery_gate():
    run = _step("battery", "Run strict battery legs")["run"]
    assert "--strict" in run and "|| status=$?" in run
    assert "scripts/battery_gate.py" in run
    assert '--legs "${{ matrix.legs }}" --exit-status "$status"' in run
    assert "|| true" not in run


def test_merge_step_fails_on_error_only():
    run = _step("merge", "Merge into one report")["run"]
    assert "merge_calibration_reports.py --fail-on-error-only" in run
    assert "set -o pipefail" in run and "|| true" not in run
