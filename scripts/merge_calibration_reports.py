"""Merge per-leg calibration battery reports (from `--only` runs, e.g. the CI
matrix) into one report with the full-battery shape.

    python scripts/merge_calibration_reports.py OUT.json IN1.json IN2.json ...

Every input must come from the same git SHA (the experiment spec's
`git_sha`); the merged file keeps the first input's `experiment` and
`vector_cache`, concatenates `gates` in GATE_LEGS order, lists the legs each
input covered under `merged_from`, and records `missing_legs` -- legs that
no input reported (a cut-off matrix job) -- so a merged report can never
read as complete when it is not. Exit code 1 when any leg is missing or a
gate is fail/uninformative, mirroring `--strict`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Leg -> gate names it reports, mirroring validation/calibration_gate.py's run_all.
LEG_GATES: dict[str, tuple[str, ...]] = {
    "G1": ("G1",),
    "G1p": ("G1p",),
    "G2": ("G2",),
    "G2b": ("G2b",),
    "G3": ("G3",),
    "G4": ("G4",),
    "G5": ("G5",),
    "G6": ("G6",),
    "G7": ("G7",),
    "G8": ("G8",),
    "T": ("T-1", "T-2", "T-3", "T-4"),
}


def merge(reports: list[dict]) -> dict:
    if not reports:
        raise ValueError("no reports to merge")
    shas = {r.get("experiment", {}).get("git_sha") for r in reports}
    if len(shas) != 1:
        raise ValueError(f"reports come from different commits: {sorted(map(str, shas))}")
    by_name: dict[str, dict] = {}
    merged_from: list[dict] = []
    for r in reports:
        names = [g["name"] for g in r.get("gates", [])]
        merged_from.append({"only": r.get("only"), "gates": names})
        for g in r.get("gates", []):
            by_name.setdefault(g["name"], g)
    ordered = [by_name[n] for leg in LEG_GATES for n in LEG_GATES[leg] if n in by_name]
    missing = [leg for leg, names in LEG_GATES.items() if any(n not in by_name for n in names)]
    return {
        "experiment": reports[0].get("experiment"),
        "vector_cache": reports[0].get("vector_cache"),
        "only": None,
        "merged_from": merged_from,
        "missing_legs": missing,
        "gates": ordered,
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    out, *inputs = argv
    merged = merge([json.loads(Path(p).read_text()) for p in inputs])
    Path(out).write_text(json.dumps(merged, indent=2))
    not_pass = [g["name"] for g in merged["gates"] if g.get("verdict") != "pass"]
    print(
        f"merged {len(inputs)} report(s): {len(merged['gates'])} gates; "
        f"missing legs: {merged['missing_legs'] or 'none'}; "
        f"not passing: {not_pass or 'none'}"
    )
    return 1 if (merged["missing_legs"] or not_pass) else 0


if __name__ == "__main__":
    raise SystemExit(main())
