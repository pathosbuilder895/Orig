"""Fail the weekly calibration battery on ERROR, never on a measurement.

    python scripts/battery_gate.py REPORT [--legs G1,G1p] [--exit-status N]

`.github/workflows/calibration-battery.yml` runs this twice: once per leg on
that leg's report (with `--legs` and the battery's `--exit-status`), and once,
through `merge_calibration_reports.py --fail-on-error-only`, on the merged
report (every leg expected).

A gate verdict of `fail` or `uninformative` is a MEASUREMENT. Several gates
legitimately return one today; they are printed and listed, and exit 0, so the
weekly schedule is not permanently red and a red run still means something.

An ERROR is the battery not measuring, and exits 1:
  - no report, or one that is unreadable or has no `gates` list (the leg
    crashed before `validation/calibration_gate.py`'s main() wrote it -- a
    crash in G1, G3 or T, or outside any gate, is not caught inside
    run_all(), so it kills the process);
  - a requested leg that reported none of its gates (crashed, cut off, or
    never ran);
  - a gate that raised instead of returning a verdict: run_all() turns such
    a crash into a `fail` whose `detail` carries `machinery_error` and whose
    `current_value` starts "ERROR (machinery)" (`_machinery_error_result`);
  - a gate whose verdict is not pass / fail / uninformative;
  - a battery exit status other than 0 or 1 (124 = the step's `timeout`,
    2 = usage error, 128+N = killed by signal N), or exit 1 with a report in
    which every gate passed.

Why the report and not the exit code alone: `--strict` exits 1 when any gate
is fail or uninformative, and Python also exits 1 on an uncaught exception, so
exit 1 cannot tell a measurement from a crash. The report can, because main()
writes it only after run_all() has returned a verdict for every requested gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.merge_calibration_reports import LEG_GATES  # noqa: E402

VERDICTS = ("pass", "fail", "uninformative")


def parse_legs(spec: str | None) -> list[str] | None:
    """`"G1,g1p"` -> `["G1", "G1p"]` (case-insensitive, like `--only`);
    None/empty -> None (every leg). Unknown names raise ValueError."""
    if not spec or not spec.strip():
        return None
    by_lower = {leg.lower(): leg for leg in LEG_GATES}
    legs = []
    for raw in spec.split(","):
        name = raw.strip()
        if not name:
            continue
        if name.lower() not in by_lower:
            raise ValueError(f"unknown leg {name!r}; valid: {', '.join(LEG_GATES)}")
        legs.append(by_lower[name.lower()])
    return legs or None


def gate_error(gate: object) -> str | None:
    """Why this gate entry is an ERROR rather than a verdict, or None."""
    if not isinstance(gate, dict) or not gate.get("name"):
        return f"malformed gate entry: {gate!r}"
    name = gate["name"]
    detail = gate.get("detail")
    if isinstance(detail, dict) and "machinery_error" in detail:
        return f"{name} raised instead of returning a verdict: {detail['machinery_error']}"
    if str(gate.get("current_value", "")).startswith("ERROR"):
        return f"{name} reports an error: {gate['current_value']}"
    if gate.get("verdict") not in VERDICTS:
        return f"{name} has no verdict (got {gate.get('verdict')!r})"
    return None


def find_errors(
    report: object, legs: list[str] | None = None, exit_status: int | None = None
) -> list[str]:
    """Every ERROR in one calibration report (a leg's, or the merged one).
    `legs` are the legs it must cover (None = all of LEG_GATES); `exit_status`
    is the battery process's, when known. An empty list means every requested
    gate returned a verdict -- pass, fail or uninformative."""
    errors = []
    if exit_status is not None and exit_status not in (0, 1):
        errors.append(
            f"battery exited {exit_status}: only 0 and 1 mean it finished "
            "(124 = step timeout, 2 = usage error, 128+N = killed by signal N)"
        )
    if not isinstance(report, dict) or not isinstance(report.get("gates"), list):
        errors.append(
            "no calibration report (missing, unreadable, or without a 'gates' list): "
            "the battery crashed or never wrote one"
        )
        return errors
    gates = report["gates"]
    errors.extend(e for e in map(gate_error, gates) if e)
    seen = {g.get("name") for g in gates if isinstance(g, dict)}
    for leg in LEG_GATES if legs is None else legs:
        missing = [n for n in LEG_GATES[leg] if n not in seen]
        if missing:
            errors.append(
                f"leg {leg} reported nothing for {', '.join(missing)} "
                "(crashed, cut off, or never ran)"
            )
    if (
        exit_status == 1
        and gates
        and all(isinstance(g, dict) and g.get("verdict") == "pass" for g in gates)
    ):
        errors.append(
            "battery exited 1 but every gate in its report passed: under --strict "
            "exit 1 must mean a gate did not pass, so something else failed"
        )
    return errors


def measurements(report: object) -> list[str]:
    """`NAME verdict` for each gate that returned fail/uninformative as a real
    verdict (an errored gate is listed by find_errors instead)."""
    gates = report.get("gates") if isinstance(report, dict) else None
    if not isinstance(gates, list):
        return []
    return [
        f"{g['name']} {g['verdict']}"
        for g in gates
        if gate_error(g) is None and g["verdict"] != "pass"
    ]


def render(report: object, errors: list[str]) -> str:
    lines = []
    gates = report.get("gates") if isinstance(report, dict) else None
    for g in gates if isinstance(gates, list) else []:
        if isinstance(g, dict):
            verdict = str(g.get("verdict", "")).upper()
            lines.append(f"{str(g.get('name')):5s} [{verdict:13s}] {g.get('current_value', '')}")
    not_passing = measurements(report)
    lines.append(f"not passing (measurements, not errors): {', '.join(not_passing) or 'none'}")
    lines.extend(f"ERROR: {e}" for e in errors)
    if errors:
        lines.append(f"battery_gate: {len(errors)} ERROR(s) -- the battery did not measure")
    else:
        lines.append("battery_gate: no ERROR -- every requested gate returned a verdict")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exit 1 on a calibration-battery ERROR; 0 when every gate returned "
        "a verdict, whether pass, fail or uninformative."
    )
    parser.add_argument("report", help="a leg's or the merged calibration report (JSON)")
    parser.add_argument(
        "--legs",
        help=f"comma-separated legs the report must cover (valid: {', '.join(LEG_GATES)}); "
        "default every leg",
    )
    parser.add_argument(
        "--exit-status", type=int, help="the battery process's exit status, for a leg report"
    )
    args = parser.parse_args(argv)
    try:
        legs = parse_legs(args.legs)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        report = json.loads(Path(args.report).read_text())
    except (OSError, ValueError) as exc:
        print(f"could not read {args.report}: {exc}")
        report = None
    errors = find_errors(report, legs, args.exit_status)
    print(render(report, errors))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
