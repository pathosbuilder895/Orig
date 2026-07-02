"""
scripts/pilot_report.py — weekly ops summary for a pilot deployment.

One markdown page per week, fed from the SQLite store alone (read-only
URI — safe against the live DB or a backup copy). Fills the
success-criteria table in docs/PILOT_RUNBOOK.md §5.

Sections:
  Activity           audit_log rows by action × day, distinct active students
  Scoring outcomes   fidelity rows + is_authentic split; manifests by action
  Corrections        count, correction rate, is_correct split
  AI-likelihood      shadow row count, band counts, median/p90 probability
                     (bands were computed at scoring time from the artifact's
                     thresholds, so elevated+strong counts ARE the would-be
                     flag counts — no artifact load needed here;
                     scripts/shadow_report.py does the deep FPR analysis)
  Data hygiene       students below the 5-authenticated-sample readiness bar

Usage:
    .venv/bin/python scripts/pilot_report.py --db /data/profiles.db --since-days 7
    .venv/bin/python scripts/pilot_report.py --db backups/profiles-X.db --out week3.md --json week3.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def collect(conn: sqlite3.Connection, since_iso: str) -> Dict:
    data: Dict = {"since": since_iso}

    # ── Activity ──
    if _table_exists(conn, "audit_log"):
        rows = conn.execute(
            "SELECT action, substr(created_at, 1, 10) AS day, COUNT(*) "
            "FROM audit_log WHERE created_at >= ? GROUP BY action, day "
            "ORDER BY day, action", (since_iso,)).fetchall()
        data["activity_by_action_day"] = [
            {"action": r[0], "day": r[1], "n": r[2]} for r in rows]
        data["active_students"] = conn.execute(
            "SELECT COUNT(DISTINCT student_id) FROM audit_log "
            "WHERE created_at >= ? AND student_id IS NOT NULL",
            (since_iso,)).fetchone()[0]
    else:
        data["activity_by_action_day"] = []
        data["active_students"] = 0

    # ── Scoring outcomes ──
    scored = auth_n = anom_n = 0
    if _table_exists(conn, "fidelity_scores"):
        scored, auth_n = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(is_authentic), 0) FROM fidelity_scores "
            "WHERE created_at >= ?", (since_iso,)).fetchone()
        anom_n = scored - auth_n
    data["scoring"] = {"fidelity_rows": scored, "labeled_authentic": auth_n,
                       "labeled_anomalous": anom_n}
    if _table_exists(conn, "submission_manifests"):
        rows = conn.execute(
            "SELECT COALESCE(action, 'unknown'), COUNT(*) FROM submission_manifests "
            "WHERE created_at >= ? GROUP BY action", (since_iso,)).fetchall()
        data["scoring"]["manifests_by_action"] = {r[0]: r[1] for r in rows}
        data["scoring"]["manifests_total"] = sum(r[1] for r in rows)
    else:
        data["scoring"]["manifests_by_action"] = {}
        data["scoring"]["manifests_total"] = 0

    # ── Corrections ──
    n_corr = n_correct = 0
    if _table_exists(conn, "corrections"):
        n_corr, n_correct = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(is_correct), 0) FROM corrections "
            "WHERE created_at >= ?", (since_iso,)).fetchone()
    denominator = max(data["scoring"]["manifests_total"],
                      data["scoring"]["fidelity_rows"], 1)
    data["corrections"] = {
        "count": n_corr,
        "verdict_confirmed": n_correct,
        "verdict_overturned": n_corr - n_correct,
        "correction_rate": round(n_corr / denominator, 4),
    }

    # ── AI-likelihood (shadow or enabled) ──
    ai: Dict = {"rows": 0}
    if _table_exists(conn, "ai_likelihood_scores"):
        rows = conn.execute(
            "SELECT probability, band FROM ai_likelihood_scores "
            "WHERE created_at >= ?", (since_iso,)).fetchall()
        probs = [float(r[0]) for r in rows]
        bands: Dict[str, int] = {}
        for _, band in rows:
            bands[band] = bands.get(band, 0) + 1
        ai = {
            "rows": len(rows),
            "band_counts": bands,
            "median_probability": (round(statistics.median(probs), 4)
                                   if probs else None),
            "p90_probability": (round(sorted(probs)[int(0.9 * (len(probs) - 1))], 4)
                                if probs else None),
            "would_flag_at_elevated": bands.get("elevated", 0) + bands.get("strong", 0),
            "would_flag_at_strong": bands.get("strong", 0),
        }
    data["ai_likelihood"] = ai

    # ── Data hygiene: baseline readiness from the profile blobs ──
    below_ready: List[str] = []
    n_students = 0
    if _table_exists(conn, "student_profiles"):
        for sid, blob in conn.execute(
                "SELECT student_id, data FROM student_profiles").fetchall():
            n_students += 1
            try:
                samples = json.loads(blob).get("samples", [])
            except (json.JSONDecodeError, AttributeError):
                samples = []
            if len(samples) < 5:
                below_ready.append(sid)
    data["hygiene"] = {"students_total": n_students,
                       "students_below_5_samples": len(below_ready),
                       "below_ready_ids": sorted(below_ready)[:25]}
    return data


def to_markdown(d: Dict, since_days: int) -> str:
    lines = [
        f"# Original pilot — weekly ops report (last {since_days} days)",
        "",
        "## Activity",
        "",
        f"- Distinct active students: **{d['active_students']}**",
    ]
    by_day: Dict[str, Dict[str, int]] = {}
    for row in d["activity_by_action_day"]:
        by_day.setdefault(row["day"], {})[row["action"]] = row["n"]
    if by_day:
        actions = sorted({a for v in by_day.values() for a in v})
        lines += ["", "| day | " + " | ".join(actions) + " |",
                  "|---|" + "---|" * len(actions)]
        for day in sorted(by_day):
            lines.append(f"| {day} | " + " | ".join(
                str(by_day[day].get(a, 0)) for a in actions) + " |")
    else:
        lines.append("- no audit activity in window")

    s = d["scoring"]
    lines += [
        "", "## Scoring outcomes", "",
        f"- Submissions scored (fidelity rows): **{s['fidelity_rows']}** "
        f"(labeled authentic: {s['labeled_authentic']}, anomalous: {s['labeled_anomalous']})",
        f"- Manifests by action: {s['manifests_by_action'] or '—'}",
    ]

    c = d["corrections"]
    lines += [
        "", "## Corrections", "",
        f"- Count: **{c['count']}** (confirmed: {c['verdict_confirmed']}, "
        f"overturned: {c['verdict_overturned']})",
        f"- Correction rate: {c['correction_rate']} of scored submissions",
    ]

    ai = d["ai_likelihood"]
    lines += ["", "## AI-likelihood (shadow)", ""]
    if ai["rows"]:
        lines += [
            f"- Rows: **{ai['rows']}**, bands: {ai['band_counts']}",
            f"- median p={ai['median_probability']}, p90={ai['p90_probability']}",
            f"- Would-be flags: {ai['would_flag_at_elevated']} at elevated, "
            f"{ai['would_flag_at_strong']} at strong "
            f"(deep FPR analysis: scripts/shadow_report.py)",
        ]
    else:
        lines.append("- no shadow rows in window (is AI_LIKELIHOOD_SHADOW set?)")

    h = d["hygiene"]
    lines += [
        "", "## Data hygiene", "",
        f"- Students below the 5-sample readiness bar: "
        f"**{h['students_below_5_samples']}** of {h['students_total']}",
    ]
    if h["below_ready_ids"]:
        lines.append(f"- Needing baselines: {', '.join(h['below_ready_ids'])}")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--since-days", type=int, default=7)
    ap.add_argument("--out", default=None, help="Write markdown here (default stdout).")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[pilot-report] DB not found: {db_path}", file=sys.stderr)
        return 1
    since_iso = (datetime.now(timezone.utc)
                 - timedelta(days=args.since_days)).isoformat()

    conn = _connect_readonly(db_path)
    try:
        data = collect(conn, since_iso)
    finally:
        conn.close()

    md = to_markdown(data, args.since_days)
    if args.out:
        Path(args.out).write_text(md)
        print(f"[pilot-report] markdown → {args.out}")
    else:
        print(md)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(data, indent=2) + "\n")
        print(f"[pilot-report] json → {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
