"""Aggregate privacy-safe pilot shadow telemetry from logs and SQLite.

Usage: .venv/bin/python scripts/shadow_soak_report.py --log pilot.log --db profiles.db
The report contains counts/distributions only; it never prints identifiers.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
from collections import Counter
from pathlib import Path

from validation.fusion_confound.analyze import analyze_rows
from validation.genre_2026_08_compat import genre_summary

_TOPIC = re.compile(
    r"topic_inflation\s+mode=(?P<mode>\S+)\s+d=(?P<d>\S+)\s+"
    r"mean_inflation=(?P<mean>\S+)"
)
_CHAR = re.compile(
    r"characteristic_weights\s+mode=(?P<mode>\S+)\s+"
    r"outcome=(?P<outcome>applied|abstain)\s+dispersion=(?P<disp>\S+)"
)


def _number(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _distribution(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)

    def percentile(q: float) -> float:
        return ordered[round((len(ordered) - 1) * q)]

    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p10": percentile(0.10),
        "p90": percentile(0.90),
    }


def summarize_logs(lines: list[str]) -> dict:
    topic_seen = 0
    topic_distances: list[float] = []
    topic_degraded = 0
    characteristic_seen = 0
    characteristic_outcomes: Counter = Counter()
    dispersions: list[float] = []
    for line in lines:
        topic = _TOPIC.search(line)
        if topic:
            topic_seen += 1
            d = _number(topic.group("d"))
            if d is None:
                topic_degraded += 1
            else:
                topic_distances.append(d)
        char = _CHAR.search(line)
        if char:
            characteristic_seen += 1
            characteristic_outcomes[char.group("outcome")] += 1
            dispersion = _number(char.group("disp"))
            if dispersion is not None:
                dispersions.append(dispersion)

    topic_mass = (
        sum(value > 0.25 for value in topic_distances) / len(topic_distances)
        if topic_distances
        else None
    )
    applied = characteristic_outcomes["applied"]
    abstain_rate = (
        characteristic_outcomes["abstain"] / characteristic_seen
        if characteristic_seen
        else None
    )
    return {
        "genre": genre_summary(lines),
        "topic": {
            "signal_absent": topic_seen == 0,
            "observations": topic_seen,
            "distance": _distribution(topic_distances),
            "share_above_0_25": topic_mass,
            "degraded_share": topic_degraded / topic_seen if topic_seen else None,
            "verdict": (
                "production no-op: approximately no mass exceeds 0.25"
                if topic_mass is not None and topic_mass < 0.01
                else "measure after shadow traffic"
            ),
        },
        "characteristic_weights": {
            "signal_absent": characteristic_seen == 0,
            "observations": characteristic_seen,
            "applied": applied,
            "abstain_rate": abstain_rate,
            "dispersion": _distribution(dispersions),
            "verdict": (
                "inert: abstention dominates or active-feature dispersion is near zero"
                if characteristic_seen
                and (abstain_rate is not None and abstain_rate > 0.5
                     or dispersions and statistics.median(dispersions) < 0.01)
                else "measure after shadow traffic"
            ),
        },
    }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def summarize_sqlite(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        fused = {"signal_absent": True, "rows": 0}
        if _table_exists(conn, "fused_scores"):
            rows = conn.execute(
                "SELECT fused_score, band, channels_json, baseline_samples, "
                "reference_profiles FROM fused_scores"
            ).fetchall()
            scores = [float(row[0]) for row in rows if row[0] is not None]
            bands = Counter(row[1] for row in rows)
            confound_rows = []
            for row in rows:
                try:
                    channels = json.loads(row[2] or "{}")
                except (TypeError, json.JSONDecodeError):
                    channels = {}
                confound_rows.append(
                    {
                        "fused_score": row[0],
                        "channels": channels,
                        "baseline_samples": row[3],
                        "reference_profiles": row[4],
                    }
                )
            fused = {
                "signal_absent": len(rows) == 0,
                "rows": len(rows),
                "score": _distribution(scores),
                "bands": dict(bands),
                "confound_ready_rows": sum(
                    row[3] is not None and row[4] is not None for row in rows
                ),
                "baseline_volume_confound": analyze_rows(confound_rows),
            }

        ai = {"signal_absent": True, "rows": 0}
        if _table_exists(conn, "ai_likelihood_scores"):
            rows = conn.execute(
                "SELECT probability, band FROM ai_likelihood_scores"
            ).fetchall()
            ai = {
                "signal_absent": len(rows) == 0,
                "rows": len(rows),
                "probability": _distribution([float(row[0]) for row in rows]),
                "bands": dict(Counter(row[1] for row in rows)),
                "gate_note": "join instructor labels; require at least 30 before quoting FPR",
            }
        return {"fused_score": fused, "ai_likelihood": ai}
    finally:
        conn.close()


def build_report(lines: list[str], db_path: Path | None = None) -> dict:
    report = summarize_logs(lines)
    if db_path is None:
        report.update(
            {
                "fused_score": {"signal_absent": True, "reason": "database not supplied"},
                "ai_likelihood": {"signal_absent": True, "reason": "database not supplied"},
            }
        )
    else:
        report.update(summarize_sqlite(db_path))
    report["bayesian_prior_scope"] = {
        "changes_scores": True,
        "instruction": "run scripts/measure_genre_prior_scope.py offline against the same DB",
    }
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--db")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    lines = Path(args.log).read_text(errors="ignore").splitlines()
    db_path = Path(args.db) if args.db and "://" not in args.db else None
    report = build_report(lines, db_path)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
