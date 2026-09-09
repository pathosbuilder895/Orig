"""Aggregate privacy-safe pilot shadow telemetry from logs and the database.

Usage: .venv/bin/python scripts/shadow_soak_report.py --log pilot.log --db DATABASE_URL
The report contains counts/distributions only; it never prints identifiers.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.shadow_report import DEFAULT_ARTIFACT, _load_thresholds  # noqa: E402
from scripts.shadow_report import build_report as build_ai_go_no_go_report  # noqa: E402
from validation.fusion_confound.analyze import analyze_rows  # noqa: E402
from validation.genre_2026_08_compat import genre_summary  # noqa: E402

_TOPIC = re.compile(
    r"topic_inflation\s+mode=(?P<mode>\S+)\s+d=(?P<d>\S+)\s+"
    r"mean_inflation=(?P<mean>\S+)"
)
_CHAR = re.compile(
    r"characteristic_weights\s+mode=(?P<mode>\S+)\s+"
    r"outcome=(?P<outcome>applied|abstain)\s+dispersion=(?P<disp>\S+)"
)
FUSED_ARTIFACT_PATH = ROOT / "original" / "data" / "fused_score_v1.json"


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


def _sermon_watch(genre: dict) -> dict:
    """Cross-reference v1=sermon against v2's out-of-taxonomy labelling.

    v2 carries no `sermon` class (CLAUDE.md's GENRE_RESOLVER_V2 row: one
    author in the training corpus, so leave-one-author-out had nothing to
    train on). A v1 sermon claim landing on `scholarly_essay` or
    `narrative_prose` — rather than `unknown` — is exactly the known
    taxonomy gap CLAUDE.md names as "the first thing to look for in the
    shadow soak."
    """
    shift_matrix = genre.get("shift_matrix") or {}
    hits = sum(
        n
        for key, n in shift_matrix.items()
        if "sermon" in key.lower()
        and ("scholarly_essay" in key or "narrative_prose" in key)
    )
    return {
        "v1_sermon_to_v2_scholarly_or_narrative": hits,
        "note": (
            "metadata is not logged, so a broader homiletic review beyond "
            "explicit v1=sermon claims needs the Plan 02 C6 sermon corpus"
        ),
    }


def summarize_logs(lines: list[str]) -> dict:
    genre = genre_summary(lines)
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
            if d is None or "degraded=True" in line:
                topic_degraded += 1
            if d is not None:
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
    genre_result = dict(genre)
    if not genre.get("no_shadow_lines_found"):
        genre_result["sermon_watch"] = _sermon_watch(genre)
    return {
        "genre": genre_result,
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
                and (
                    abstain_rate is not None
                    and abstain_rate > 0.5
                    or dispersions
                    and statistics.median(dispersions) < 0.01
                )
                else "measure after shadow traffic"
            ),
        },
    }


def _fused_thresholds() -> tuple[float | None, float | None]:
    try:
        artifact = json.loads(FUSED_ARTIFACT_PATH.read_text())
        return float(artifact["threshold_fa5"]), float(artifact["threshold_fa1"])
    except (OSError, KeyError, ValueError):
        return None, None


def _readonly_engine(url: str):
    """Open a read-only engine so this reporter can never write to a live
    pilot database, mirroring scripts/tier17_report.py's guarantee: SQLite
    via a ``file:...?mode=ro`` URI, Postgres via
    ``default_transaction_read_only=on``. The reports here are SELECT-only
    already; this makes that a connection-level guarantee rather than a
    convention, because operators point ``--db "$DATABASE_URL"`` straight at
    the pilot Postgres."""
    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
        return create_engine(
            "sqlite://",
            creator=lambda: sqlite3.connect(f"file:{path}?mode=ro", uri=True),
        )
    if url.startswith(("postgresql", "postgres")):
        return create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    return create_engine(url)


def summarize_database(url: str) -> dict:
    """Read the fused-score and AI-likelihood tables through one SQL dialect
    layer, so SQLite and Postgres take the same code path (unlike two
    separately-hand-maintained query sets, which is how the SQLite path
    once queried a column — ``fused_score`` — that the schema never had;
    the real columns are ``fused_log_odds`` and ``probability``, per
    ``original/store.py``'s ``fused_scores`` DDL)."""
    engine = _readonly_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        with engine.connect() as conn:
            fused = {"signal_absent": True, "rows": 0}
            if "fused_scores" in tables:
                rows = conn.execute(
                    text(
                        "SELECT fused_log_odds, probability, band, channels_json, "
                        "baseline_samples, reference_profiles FROM fused_scores"
                    )
                ).fetchall()
                probabilities = [float(row[1]) for row in rows if row[1] is not None]
                confound_rows = []
                for row in rows:
                    try:
                        channels = json.loads(row[3] or "{}")
                    except (TypeError, json.JSONDecodeError):
                        channels = {}
                    confound_rows.append(
                        {
                            "fused_log_odds": row[0],
                            "channels": channels,
                            "band": row[2],
                            "baseline_samples": row[4],
                            "reference_profiles": row[5],
                        }
                    )
                threshold_fa5, threshold_fa1 = _fused_thresholds()
                fused = {
                    "signal_absent": not rows,
                    "rows": len(rows),
                    "probability": _distribution(probabilities),
                    "bands": dict(Counter(row[2] for row in rows)),
                    "confound_ready_rows": sum(
                        row[4] is not None and row[5] is not None for row in rows
                    ),
                    "baseline_volume_confound": analyze_rows(
                        confound_rows,
                        threshold_fa5=threshold_fa5,
                        threshold_fa1=threshold_fa1,
                    ),
                }

            ai = {"signal_absent": True, "rows": 0}
            if "ai_likelihood_scores" in tables:
                has_fidelity = "fidelity_scores" in tables
                if has_fidelity:
                    rows = conn.execute(
                        text(
                            "SELECT a.submission_id, a.student_id, a.probability, "
                            "a.band, a.model_version, a.created_at, f.is_authentic "
                            "FROM ai_likelihood_scores a "
                            "LEFT JOIN fidelity_scores f "
                            "ON a.submission_id = f.submission_id"
                        )
                    ).fetchall()
                    joined = [
                        {
                            "submission_id": r[0],
                            "student_id": r[1],
                            "probability": float(r[2]),
                            "band": r[3],
                            "model_version": r[4],
                            "created_at": r[5],
                            "is_authentic": (None if r[6] is None else int(r[6])),
                        }
                        for r in rows
                    ]
                    ai = {"signal_absent": not joined, "rows": len(joined)}
                    if joined:
                        thresholds = _load_thresholds(DEFAULT_ARTIFACT)
                        # Aggregate only — no submission_id/student_id survives
                        # into this report; build_report reduces to counts,
                        # distributions, and rates.
                        ai["go_no_go"] = build_ai_go_no_go_report(joined, thresholds)
                else:
                    rows = conn.execute(
                        text("SELECT probability, band FROM ai_likelihood_scores")
                    ).fetchall()
                    ai = {
                        "signal_absent": not rows,
                        "rows": len(rows),
                        "probability": _distribution([float(row[0]) for row in rows]),
                        "bands": dict(Counter(row[1] for row in rows)),
                        "gate_note": (
                            "no fidelity_scores table to join — cannot compute "
                            "real-world FPR against instructor-confirmed authentic work"
                        ),
                    }
            return {"fused_score": fused, "ai_likelihood": ai}
    finally:
        engine.dispose()


def _to_sqlalchemy_url(db: str) -> str:
    if "://" in db:
        if db.startswith("postgres://"):
            return "postgresql://" + db.removeprefix("postgres://")
        return db
    return f"sqlite:///{Path(db).resolve()}"


def _bayesian_prior_scope(db: str) -> dict:
    """Run the offline prior-scope measurement as a subprocess against the
    same database, rather than pointing the operator at a manual command —
    this flag changes scores, so it is never enabled just to collect this
    number; the measurement has to come from a read-only offline pass."""
    env = os.environ.copy()
    url = _to_sqlalchemy_url(db)
    if url.startswith(("postgres://", "postgresql://")):
        env["DATABASE_URL"] = url
        env["REPO_BACKEND"] = "postgres"
    else:
        env["ORIGINAL_DB"] = url.removeprefix("sqlite:///")
        env["REPO_BACKEND"] = "sqlite"
    try:
        proc = subprocess.run(
            [str(ROOT / ".venv" / "bin" / "python"),
             str(ROOT / "scripts" / "measure_genre_prior_scope.py")],
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"changes_scores": True, "error": f"{type(exc).__name__}: {exc}"}
    if proc.returncode != 0:
        stderr_tail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ""
        return {
            "changes_scores": True,
            "error": f"scope measurement unavailable — {stderr_tail}",
        }
    return {"changes_scores": True, "measurement": proc.stdout.strip()}


def build_report(lines: list[str], db: str | None = None) -> dict:
    report = summarize_logs(lines)
    if db is None:
        report.update(
            {
                "fused_score": {"signal_absent": True, "reason": "database not supplied"},
                "ai_likelihood": {"signal_absent": True, "reason": "database not supplied"},
                "bayesian_prior_scope": {
                    "changes_scores": True,
                    "reason": "database not supplied",
                },
            }
        )
        return report
    report.update(summarize_database(_to_sqlalchemy_url(db)))
    report["bayesian_prior_scope"] = _bayesian_prior_scope(db)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--db")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    lines = Path(args.log).read_text(errors="ignore").splitlines()
    report = build_report(lines, args.db)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
