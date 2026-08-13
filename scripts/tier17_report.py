"""
scripts/tier17_report.py — Tier 17 (behavioral biometrics) shadow-readiness report.

Tier 17 (typing_speed_cv, burst_ratio, deletion_rate, pause_density,
paste_event_rate, revision_depth) stays in DISABLED_FEATURE_GROUPS until
live pilot keystroke data proves the six distributions are non-degenerate.
This script is the validation gate: run it weekly against the production DB
(or a backup) to see whether enough proctored keystroke data has
accumulated to justify the separate, human-approved enable decision.

Data shape note: it reads the raw `student_profiles` JSON looking for a
`keystroke_data` blob on each proctored sample — the shape Bbook's
`buildKeystrokeData()` (demo/bluebook/Exam.jsx) sends to
POST /students/{id}/baseline. That endpoint
(original/routers/students_baseline.py:add_baseline) now persists the blob
on the `BaselineSample` it builds (see `original/quantum/state.py`'s
`keystroke_data` field and `original/store.py` / `original/postgres_repository.py`'s
serializers), so this script starts reporting real distributions once
proctored sittings accumulate after that change shipped. Any row written
before then predates the field and is silently treated the same as a sample
with no keystroke data (no crash, no backfill) — this script was written
forward-compatible for exactly that transition, so no further changes were
needed here.

READY rule: >= 20 proctored samples with keystroke data, across >= 5
distinct students, with non-degenerate distributions (p10 != p90) on at
least 4 of the 6 features.

SQLite mode opens the DB file read-only (?mode=ro); Postgres mode is
read-only by construction — it only calls PostgresRepository.all_states()
(a SELECT), never get_or_create()/put(). Both are safe against a live
pilot database or a backup copy.

Usage:
    .venv/bin/python -m scripts.tier17_report
    .venv/bin/python -m scripts.tier17_report --db /data/profiles.db
    .venv/bin/python -m scripts.tier17_report --db backups/profiles-X.db \
        --out-md tier17_week3.md --out-json tier17_week3.json
    DATABASE_URL=postgresql://... .venv/bin/python -m scripts.tier17_report \
        --backend postgres
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from pathlib import Path

from original.features.tier17 import extract_tier17

_ROOT = Path(__file__).resolve().parent.parent

FEATURES = (
    "typing_speed_cv",
    "burst_ratio",
    "deletion_rate",
    "pause_density",
    "paste_event_rate",
    "revision_depth",
)

MIN_SAMPLES = 20
MIN_STUDENTS = 5
MIN_NONDEGENERATE_FEATURES = 4


def _default_db_path() -> Path:
    return Path(os.environ.get("ORIGINAL_DB", _ROOT / "profiles.db"))


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def _fetch_keystroke_samples(conn: sqlite3.Connection) -> list[dict]:
    """Every proctored sample carrying a non-empty keystroke_data blob."""
    if not _table_exists(conn, "student_profiles"):
        return []
    rows = conn.execute("SELECT student_id, data FROM student_profiles").fetchall()
    out: list[dict] = []
    for student_id, data in rows:
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            continue
        for sample in parsed.get("samples", []):
            if sample.get("provenance") != "proctored":
                continue
            keystroke_data = sample.get("keystroke_data")
            if not keystroke_data:
                continue
            out.append({"student_id": student_id, "keystroke_data": keystroke_data})
    return out


def _samples_from_states(states) -> list[dict]:
    """Postgres-mode twin of _fetch_keystroke_samples: same filter
    (provenance == "proctored", truthy keystroke_data), same output shape,
    applied to StudentState objects instead of raw JSON rows."""
    out: list[dict] = []
    for state in states:
        for sample in state.samples:
            if sample.provenance != "proctored" or not sample.keystroke_data:
                continue
            out.append(
                {"student_id": state.student_id, "keystroke_data": sample.keystroke_data}
            )
    return out


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (pct / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def build_report(samples: list[dict]) -> dict:
    per_student: dict[str, int] = {}
    per_feature_values: dict[str, list[float]] = {f: [] for f in FEATURES}

    for s in samples:
        t17 = extract_tier17(s["keystroke_data"])
        per_student[s["student_id"]] = per_student.get(s["student_id"], 0) + 1
        for f in FEATURES:
            per_feature_values[f].append(float(t17[f]))

    n_samples = sum(per_student.values())
    n_students = len(per_student)

    feature_stats: dict[str, dict | None] = {}
    nondegenerate = 0
    for f in FEATURES:
        vals = sorted(per_feature_values[f])
        if not vals:
            feature_stats[f] = None
            continue
        p10 = _percentile(vals, 10)
        p50 = _percentile(vals, 50)
        p90 = _percentile(vals, 90)
        degenerate = p10 == p90
        if not degenerate:
            nondegenerate += 1
        feature_stats[f] = {
            "n": len(vals),
            "p10": round(p10, 4),
            "p50": round(p50, 4),
            "p90": round(p90, 4),
            "degenerate": degenerate,
        }

    ready = (
        n_samples >= MIN_SAMPLES
        and n_students >= MIN_STUDENTS
        and nondegenerate >= MIN_NONDEGENERATE_FEATURES
    )

    return {
        "totals": {
            "proctored_samples_with_keystroke_data": n_samples,
            "distinct_students": n_students,
        },
        "per_student": per_student,
        "features": feature_stats,
        "gate": {
            "min_samples": MIN_SAMPLES,
            "min_students": MIN_STUDENTS,
            "min_nondegenerate_features": MIN_NONDEGENERATE_FEATURES,
            "nondegenerate_features": nondegenerate,
        },
        "verdict": "READY" if ready else "NOT READY",
    }


def to_markdown(report: dict) -> str:
    t = report["totals"]
    g = report["gate"]
    lines = [
        "# Tier 17 (behavioral biometrics) shadow-readiness report",
        "",
        "- Cohort: proctored samples with keystroke data: "
        f"**{t['proctored_samples_with_keystroke_data']}** (gate: >= {g['min_samples']})",
        f"- Cohort: distinct students: **{t['distinct_students']}** (gate: >= {g['min_students']})",
        f"- Non-degenerate features: **{g['nondegenerate_features']}**/{len(FEATURES)} "
        f"(gate: >= {g['min_nondegenerate_features']})",
        "",
        f"## Verdict: **{report['verdict']}**",
        "",
        "## Feature distributions (raw units, p10 / p50 / p90)",
        "",
    ]
    for f in FEATURES:
        stats = report["features"][f]
        if stats is None:
            lines.append(f"- {f}: no data")
            continue
        flag = " (degenerate)" if stats["degenerate"] else ""
        lines.append(
            f"- {f}: n={stats['n']}, p10={stats['p10']}, p50={stats['p50']}, "
            f"p90={stats['p90']}{flag}"
        )

    lines += ["", "## Per-student sample counts", ""]
    if report["per_student"]:
        for sid, n in sorted(report["per_student"].items()):
            lines.append(f"- {sid}: {n}")
    else:
        lines.append("- no proctored samples carry keystroke data yet")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--backend",
        choices=("sqlite", "postgres"),
        default="sqlite",
        help="Where the student_profiles data lives. postgres reads DATABASE_URL "
        "(like scripts/migrate_sqlite_to_pg.py); --db applies to sqlite only.",
    )
    ap.add_argument(
        "--db", default=str(_default_db_path()), help="Path to the SQLite database (sqlite backend only)."
    )
    ap.add_argument("--out-md", default=None, help="Write markdown here (default stdout).")
    ap.add_argument("--out-json", default=None, help="Also write the raw report JSON.")
    args = ap.parse_args(argv)

    if args.backend == "postgres":
        if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
            print(
                "[tier17-report] --backend postgres requires DATABASE_URL to "
                "point at a postgresql:// instance",
                file=sys.stderr,
            )
            return 2
        # Deferred import (house pattern, see original/postgres_repository.py's
        # module docstring): sqlite mode must not require sqlalchemy.
        from original.db import postgres_session

        try:
            with postgres_session.get_engine().connect():
                pass
        except Exception as e:
            print(f"[tier17-report] cannot reach Postgres: {e}", file=sys.stderr)
            return 1
        from original.postgres_repository import PostgresRepository

        samples = _samples_from_states(PostgresRepository().all_states())
    else:
        db_path = Path(args.db)
        if not db_path.exists():
            print(f"[tier17-report] DB not found: {db_path}", file=sys.stderr)
            return 1

        conn = _connect_readonly(db_path)
        try:
            samples = _fetch_keystroke_samples(conn)
        finally:
            conn.close()

    report = build_report(samples)
    md = to_markdown(report)
    if args.out_md:
        Path(args.out_md).write_text(md)
        print(f"[tier17-report] markdown -> {args.out_md}")
    else:
        print(md)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(report, indent=2) + "\n")
        print(f"[tier17-report] json -> {args.out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
