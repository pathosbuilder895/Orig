"""
scripts/shadow_report.py — real-world FPR report for AI-likelihood shadow mode.

During pilot weeks 1-4 the detector runs with AI_LIKELIHOOD_SHADOW=1:
every scored submission gets a persisted probability in the
ai_likelihood_scores table, but nothing is ever surfaced to professors.
This script is how that silent data becomes an enablement decision.

It joins shadow rows against the instructor-corrected ground truth in
fidelity_scores (is_authentic — set by POST /submissions/{id}/correct via
update_fidelity_authenticity) and reports:

  - overall probability distribution (deciles) + per-band counts
  - the authentic-labeled subset's distribution and its flag rate at the
    artifact's t_elevated / t_strong thresholds — the REAL-WORLD FPR the
    MODEL_CARD enablement gate needs
  - would-be flag rates over all shadow rows
  - per-student flag concentration (a detector that always flags the same
    two students is a different problem than a uniform 5%)
  - how many shadow rows have no fidelity join yet (uncorrectable)

Opens the DB read-only, so it is safe against a live pilot database or a
backup copy.

Usage:
    .venv/bin/python scripts/shadow_report.py --db /data/profiles.db
    .venv/bin/python scripts/shadow_report.py --db backups/profiles-XXXX.db \
        --out-md shadow_week3.md --out-json shadow_week3.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARTIFACT = _ROOT / "original" / "data" / "ai_detector_v1.joblib"


def _load_thresholds(model_path: Path) -> Dict[str, float]:
    import joblib
    art = joblib.load(model_path)
    return {k: float(v) for k, v in art["thresholds"].items()}


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _fetch(conn: sqlite3.Connection) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT a.submission_id, a.student_id, a.probability, a.band,
               a.model_version, a.created_at, f.is_authentic
        FROM ai_likelihood_scores a
        LEFT JOIN fidelity_scores f USING (submission_id)
        ORDER BY a.created_at
        """
    ).fetchall()
    return [
        {"submission_id": r[0], "student_id": r[1], "probability": float(r[2]),
         "band": r[3], "model_version": r[4], "created_at": r[5],
         "is_authentic": (None if r[6] is None else int(r[6]))}
        for r in rows
    ]


def _dist(probs: np.ndarray) -> Dict[str, object]:
    if probs.size == 0:
        return {"n": 0}
    deciles = np.percentile(probs, [10, 25, 50, 75, 90])
    return {
        "n": int(probs.size),
        "mean": round(float(probs.mean()), 4),
        "p10": round(float(deciles[0]), 4),
        "p25": round(float(deciles[1]), 4),
        "median": round(float(deciles[2]), 4),
        "p75": round(float(deciles[3]), 4),
        "p90": round(float(deciles[4]), 4),
    }


def _flag_rates(probs: np.ndarray, thresholds: Dict[str, float]) -> Dict[str, Optional[float]]:
    if probs.size == 0:
        return {"at_t_elevated": None, "at_t_strong": None}
    return {
        "at_t_elevated": round(float((probs >= thresholds["elevated"]).mean()), 4),
        "at_t_strong": round(float((probs >= thresholds["strong"]).mean()), 4),
    }


def build_report(rows: List[Dict], thresholds: Dict[str, float]) -> Dict:
    all_p = np.array([r["probability"] for r in rows])
    authentic = [r for r in rows if r["is_authentic"] == 1]
    flagged_anomalous = [r for r in rows if r["is_authentic"] == 0]
    unjoined = [r for r in rows if r["is_authentic"] is None]
    auth_p = np.array([r["probability"] for r in authentic])

    bands: Dict[str, int] = {}
    for r in rows:
        bands[r["band"]] = bands.get(r["band"], 0) + 1

    # Per-student flag concentration at t_elevated.
    per_student: Dict[str, Dict[str, int]] = {}
    for r in rows:
        s = per_student.setdefault(r["student_id"], {"n": 0, "flagged": 0})
        s["n"] += 1
        if r["probability"] >= thresholds["elevated"]:
            s["flagged"] += 1
    concentrated = {sid: s for sid, s in per_student.items()
                    if s["flagged"] > 0}

    return {
        "thresholds": thresholds,
        "totals": {
            "shadow_rows": len(rows),
            "date_range": ([rows[0]["created_at"], rows[-1]["created_at"]]
                           if rows else None),
            "with_authentic_label": len(authentic),
            "with_anomalous_label": len(flagged_anomalous),
            "unjoined_no_ground_truth": len(unjoined),
        },
        "band_counts": bands,
        "overall": {**_dist(all_p), "would_flag": _flag_rates(all_p, thresholds)},
        "authentic_labeled": {
            **_dist(auth_p),
            "real_world_fpr": _flag_rates(auth_p, thresholds),
            "note": ("real_world_fpr.at_t_elevated is the number the "
                     "MODEL_CARD enablement gate compares against 0.05. "
                     "Labels come from instructor corrections — small n "
                     "early in the pilot; do not read percentages off "
                     "fewer than ~30 labeled submissions."),
        },
        "per_student_flag_concentration": concentrated,
        "students_seen": len(per_student),
    }


def to_markdown(report: Dict) -> str:
    t = report["totals"]
    lines = [
        "# AI-likelihood shadow report",
        "",
        f"- Shadow rows: **{t['shadow_rows']}** "
        f"({t['date_range'][0][:10]} → {t['date_range'][1][:10]})"
        if t["date_range"] else "- Shadow rows: **0**",
        f"- Instructor-labeled authentic: {t['with_authentic_label']} · "
        f"labeled anomalous: {t['with_anomalous_label']} · "
        f"no ground truth yet: {t['unjoined_no_ground_truth']}",
        "",
        "## Band counts",
        "",
    ]
    for band in ("low", "elevated", "strong"):
        if band in report["band_counts"]:
            lines.append(f"- {band}: {report['band_counts'][band]}")
    for band, n in report["band_counts"].items():
        if band not in ("low", "elevated", "strong"):
            lines.append(f"- {band}: {n}")

    o = report["overall"]
    lines += [
        "",
        "## All shadow rows",
        "",
        f"- n={o['n']}, median p={o.get('median')}, p90={o.get('p90')}",
        f"- would-flag at elevated: {o['would_flag']['at_t_elevated']}, "
        f"at strong: {o['would_flag']['at_t_strong']}",
        "",
        "## Authentic-labeled subset (the gate input)",
        "",
    ]
    a = report["authentic_labeled"]
    if a.get("n", 0) > 0:
        lines += [
            f"- n={a['n']}, median p={a.get('median')}, p90={a.get('p90')}",
            f"- **real-world FPR at t_elevated: {a['real_world_fpr']['at_t_elevated']}** "
            f"(gate: ≤ 0.05), at t_strong: {a['real_world_fpr']['at_t_strong']}",
        ]
    else:
        lines.append("- no instructor-labeled authentic submissions yet — "
                     "the gate cannot be evaluated. Encourage corrections.")
    lines.append(f"- caveat: {a['note']}")

    conc = report["per_student_flag_concentration"]
    lines += ["", "## Per-student flag concentration (at t_elevated)", ""]
    if conc:
        for sid, s in sorted(conc.items(), key=lambda kv: -kv[1]["flagged"]):
            lines.append(f"- {sid}: {s['flagged']}/{s['n']} flagged")
    else:
        lines.append("- no student has any would-be flags")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="Path to the SQLite database.")
    ap.add_argument("--model", default=str(DEFAULT_ARTIFACT),
                    help="Detector artifact (for thresholds).")
    ap.add_argument("--out-md", default=None, help="Write markdown here (default stdout).")
    ap.add_argument("--out-json", default=None, help="Also write the raw report JSON.")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[shadow-report] DB not found: {db_path}", file=sys.stderr)
        return 1
    try:
        thresholds = _load_thresholds(Path(args.model))
    except Exception as e:
        print(f"[shadow-report] could not load thresholds from {args.model}: {e}",
              file=sys.stderr)
        return 1

    conn = _connect_readonly(db_path)
    try:
        try:
            rows = _fetch(conn)
        except sqlite3.OperationalError as e:
            print(f"[shadow-report] query failed ({e}) — is this a pre-shadow "
                  f"database without the ai_likelihood_scores table?", file=sys.stderr)
            return 1
    finally:
        conn.close()

    report = build_report(rows, thresholds)
    md = to_markdown(report)
    if args.out_md:
        Path(args.out_md).write_text(md)
        print(f"[shadow-report] markdown → {args.out_md}")
    else:
        print(md)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(report, indent=2) + "\n")
        print(f"[shadow-report] json → {args.out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
