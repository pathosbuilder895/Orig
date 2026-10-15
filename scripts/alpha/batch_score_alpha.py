#!/usr/bin/env python3
"""Export and score an alpha workspace offline; never publish scores to students.

Use ``--from-dir`` for a local export or provide ``--base-url`` and repeated
``--exam`` values with ``ALPHA_TOKEN`` set. Label files have the exact header
``submission_id,label,true_author`` and one unique row per exported submission.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DROP_ENV = ("DATABASE_URL", "REPO_BACKEND", "REPO_SHADOW", "ORIGINAL_DB", "SHADOW_DATABASE_URL")
STRICT = {"schedule_conversation", "escalate"}
LENIENT = STRICT | {"monitor"}
LABELS = {"natural", "not_own"}


def export(base: str, token: str, exams: list[str], dest: Path) -> Path:
    """Copy selected exam exports and each submitter's baselines from the API."""
    import requests

    if not exams:
        raise ValueError("provide at least one --exam")
    dest.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}
    rows = []
    for exam_id in exams:
        response = requests.get(f"{base.rstrip('/')}/bluebook/exams/{exam_id}/export", headers=headers, timeout=60)
        response.raise_for_status()
        rows.extend(csv.DictReader(io.StringIO(response.text)))
    roster_response = requests.get(f"{base.rstrip('/')}/students", headers=headers, timeout=60)
    roster_response.raise_for_status()
    counts = {row["id"]: int(row.get("sample_count", 0)) for row in roster_response.json().get("roster", [])}
    for row in rows:
        sid = row["student_id"]
        student_dir = dest / sid.replace(":", "_")
        baseline_dir = student_dir / "baseline"
        submission_dir = student_dir / "submission"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        submission_dir.mkdir(parents=True, exist_ok=True)
        (submission_dir / f"{row['submission_id']}.txt").write_text(row.get("text") or "", encoding="utf-8")
        for index in range(counts.get(sid, 0)):
            response = requests.get(f"{base.rstrip('/')}/students/{sid}/samples/{index}/text", headers=headers, timeout=60)
            response.raise_for_status()
            (baseline_dir / f"{index:02d}.txt").write_text(response.json().get("text", ""), encoding="utf-8")
    (dest / "manifest.json").write_text(json.dumps({"exams": exams, "submissions": len(rows)}, indent=2), encoding="utf-8")
    return dest


def score(repo: Path, baseline_dir: Path, submission_dir: Path, student_id: str):
    """Run one student's scoring in an isolated SQLite child process."""
    env = {key: value for key, value in os.environ.items() if key not in DROP_ENV}
    with tempfile.TemporaryDirectory(prefix="alpha_score_") as temp_dir:
        env.update(ORIGINAL_DB=str(Path(temp_dir) / "profiles.db"), ORIGINAL_ENV="demo", PYTHONPATH=str(repo))
        env.update({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"})
        out_path = Path(temp_dir) / "result.json"
        started = time.monotonic()
        proc = subprocess.run(
            [sys.executable, str(repo / "scripts/score_documents.py"), "--baseline-dir", str(baseline_dir),
             "--score-dir", str(submission_dir), "--student-id", "alpha_" + student_id[-12:], "--out", str(out_path)],
            cwd=repo, env=env, capture_output=True, text=True,
        )
        elapsed = time.monotonic() - started
        if proc.returncode or not out_path.exists():
            return None, elapsed, proc.stderr[-400:] or proc.stdout[-400:]
        return json.loads(out_path.read_text(encoding="utf-8")), elapsed, ""


def bad(value) -> bool:
    return value is None or (isinstance(value, (int, float)) and not math.isfinite(value))


def validate_labels(path: Path, exported_ids: set[str]) -> dict[str, tuple[str, str]]:
    """Validate the complete label CSV before any scoring starts."""
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        required = ["submission_id", "label", "true_author"]
        if reader.fieldnames != required:
            raise ValueError(f"labels CSV header must be exactly: {','.join(required)}")
        result = {}
        for line, row in enumerate(reader, start=2):
            submission_id = (row.get("submission_id") or "").strip()
            label = (row.get("label") or "").strip().lower()
            if not submission_id:
                raise ValueError(f"labels CSV line {line}: submission_id is required")
            if submission_id in result:
                raise ValueError(f"labels CSV line {line}: duplicate submission_id {submission_id!r}")
            if label not in LABELS:
                raise ValueError(f"labels CSV line {line}: label must be natural or not_own")
            result[submission_id] = (label, (row.get("true_author") or "").strip())
    unknown = sorted(set(result) - exported_ids)
    missing = sorted(exported_ids - set(result))
    if unknown:
        raise ValueError(f"labels CSV contains unknown submission ids: {', '.join(unknown[:5])}")
    if missing:
        raise ValueError(f"labels CSV is missing submission ids: {', '.join(missing[:5])}")
    return result


def find_submissions(export_dir: Path) -> dict[str, tuple[Path, Path, str]]:
    found = {}
    for student_dir in sorted(p for p in export_dir.iterdir() if p.is_dir()):
        baseline_dir, submission_dir = student_dir / "baseline", student_dir / "submission"
        if not submission_dir.is_dir():
            continue
        for file in sorted(submission_dir.glob("*.txt")):
            if file.stem in found:
                raise ValueError(f"duplicate submission id across export folders: {file.stem}")
            found[file.stem] = (student_dir, baseline_dir, file.stem)
    if not found:
        raise ValueError(f"no submission .txt files found under {export_dir}")
    return found


def threshold_sweep(rows: list[dict]) -> list[dict]:
    natural = [row for row in rows if row.get("label") == "natural" and not row.get("inconclusive") and not bad(row.get("deviation"))]
    not_own = [row for row in rows if row.get("label") == "not_own" and not row.get("inconclusive") and not bad(row.get("deviation"))]
    return [{
        "threshold": step / 20,
        "caught": sum(row["deviation"] >= step / 20 for row in not_own),
        "not_own_total": len(not_own),
        "false_flags": sum(row["deviation"] >= step / 20 for row in natural),
        "natural_total": len(natural),
    } for step in range(1, 20)]


def rate(count: int, total: int) -> str:
    return f"{count}/{total} ({100 * count / total:.0f}%)" if total else "0/0"


def wilson(count: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if not total:
        return (float("nan"), float("nan"))
    p = count / total
    denominator = 1 + z * z / total
    center = p + z * z / (2 * total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return max(0.0, (center - half) / denominator), min(1.0, (center + half) / denominator)


def format_interval(interval: tuple[float, float]) -> str:
    if any(not math.isfinite(value) for value in interval):
        return "n/a"
    return f"{interval[0]:.0%}–{interval[1]:.0%}"


def boot_ci(items: dict[str, list[dict]], stat: Callable[[list[dict]], float | None], n: int = 2000, seed: int = 0):
    """Deterministic student-cluster bootstrap percentile interval."""
    import random
    rng = random.Random(seed)
    keys = sorted(items)
    values = []
    if not keys:
        return (float("nan"), float("nan"))
    for _ in range(n):
        sample = [row for _ in keys for row in items[rng.choice(keys)]]
        value = stat(sample)
        if value is not None and math.isfinite(value):
            values.append(value)
    if not values:
        return (float("nan"), float("nan"))
    values.sort()
    return values[int(.025 * len(values))], values[max(0, int(.975 * len(values)) - 1)]


def build_report(rows: list[dict], problems: list[str], timings: list[float], *, has_labels: bool,
                 no_rerun: bool, max_false_flag_rate: float, min_catch_rate: float) -> tuple[str, int]:
    scored = [row for row in rows if not bad(row.get("deviation"))]
    deviations = [row["deviation"] for row in scored]
    effect = [abs(row["deviation"] - row["deviation_first3"]) for row in scored if not bad(row.get("deviation_first3"))]
    lines = ["# Alpha batch scoring report (internal; never shown to students)", "",
             f"- submissions: {len(rows)}; scored: {len(scored)}; errors: {sum(bool(row.get('error')) for row in rows)}",
             f"- INCONCLUSIVE (baseline below minimum): {rate(sum(bool(row.get('inconclusive')) for row in rows), len(rows))}",
             (f"- deviation min/median/max: {min(deviations):.3f} / {statistics.median(deviations):.3f} / {max(deviations):.3f}" if deviations else "- no scores"),
             f"- deterministic on rerun: {sum(row.get('deterministic') is True for row in scored)}/{len(scored)}" + (" (rerun skipped)" if no_rerun else ""),
             f"- scoring time: per paper max {max((row.get('score_ms') or 0 for row in scored), default=0):.0f} ms; per student run max {max(timings, default=0):.1f} s",
             (f"- baseline-size effect |dev(all) - dev(first3)|: mean {statistics.mean(effect):.3f}, max {max(effect):.3f} (n={len(effect)})" if effect else "- baseline-size effect: n/a")]
    passed = None
    if has_labels:
        labeled = [row for row in scored if row.get("label") and not row.get("inconclusive")]
        natural = [row for row in labeled if row["label"] == "natural"]
        not_own = [row for row in labeled if row["label"] == "not_own"]
        false_flags = sum(bool(row["strict_flag"]) for row in natural)
        caught = sum(bool(row["strict_flag"]) for row in not_own)
        groups = {}
        for row in labeled:
            groups.setdefault(row["student"], []).append(row)
        def fraction(sample, label):
            subset = [row for row in sample if row["label"] == label]
            return sum(bool(row["strict_flag"]) for row in subset) / len(subset) if subset else None
        f_lo, f_hi = boot_ci(groups, lambda sample: fraction(sample, "natural"))
        c_lo, c_hi = boot_ci(groups, lambda sample: fraction(sample, "not_own"))
        passed = bool(natural and not_own and false_flags / len(natural) <= max_false_flag_rate and caught / len(not_own) >= min_catch_rate)
        f_wilson = wilson(false_flags, len(natural)); c_wilson = wilson(caught, len(not_own))
        lines += ["", "## Accuracy against labels (strict = schedule_conversation/escalate; INCONCLUSIVE excluded)",
                  f"- False flags on natural work: {rate(false_flags, len(natural))}; Wilson {format_interval(f_wilson)}; student-bootstrap {format_interval((f_lo, f_hi))}",
                  f"- Caught not-own work: {rate(caught, len(not_own))}; Wilson {format_interval(c_wilson)}; student-bootstrap {format_interval((c_lo, c_hi))}",
                  "", "### Deviation threshold sweep (flag if deviation >= t)", "| t | caught | false flags |", "|---|---|---|"]
        for row in threshold_sweep(labeled):
            lines.append(f"| {row['threshold']:.2f} | {rate(row['caught'], row['not_own_total'])} | {rate(row['false_flags'], row['natural_total'])} |")
        lines += ["", f"Pre-registered criteria: false-flag rate <= {max_false_flag_rate:.0%} and catch rate >= {min_catch_rate:.0%}",
                  f"**{'PASS' if passed else 'FAIL'}** on point estimates.",
                  "", "> Small-sample results are not validation. Do not tune thresholds against this same set and re-score it."]
    lines += ["", "## Problems", *(f"- {item}" for item in problems or ["none"]), "",
              "| student | submission | label | baselines | words | deviation | action | strict flag | deterministic |",
              "|---|---|---|---:|---:|---:|---|---|---|"]
    for row in rows:
        value = row.get("deviation")
        lines.append(f"| {row['student'][-8:]} | {row['submission_id'][:10]} | {row.get('label', '')} | {row['n_baselines']} | {row['baseline_words']} | "
                     f"{'-' if bad(value) else f'{value:.3f}'} | {'INCONCLUSIVE' if row.get('inconclusive') else row.get('action', row.get('error', '-'))} | "
                     f"{row.get('strict_flag', '-')} | {row.get('deterministic', '-')} |")
    hard_error = any(any(marker in item for marker in ("non-finite", "rerun differs", "outside [0,1]")) for item in problems)
    return "\n".join(lines) + "\n", 2 if hard_error else (0 if passed in (None, True) else 1)


def run_batch(export_dir: Path, out_dir: Path, repo: Path, labels_path: Path | None, *, no_rerun: bool,
              throttle_seconds: float = 1.0, max_false_flag_rate: float = 1 / 20, min_catch_rate: float = .75,
              scorer: Callable = score) -> tuple[int, list[dict], list[str]]:
    if throttle_seconds < 0:
        raise ValueError("--throttle-seconds must be >= 0")
    files = find_submissions(export_dir)
    labels = validate_labels(labels_path, set(files)) if labels_path else {}
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    problems: list[str] = []
    timings: list[float] = []
    scoring_calls = 0

    def run_scorer(baseline_dir: Path, submission_dir: Path, student_id: str):
        nonlocal scoring_calls
        if scoring_calls and throttle_seconds:
            time.sleep(throttle_seconds)
        scoring_calls += 1
        return scorer(repo, baseline_dir, submission_dir, student_id)

    students = sorted({student_dir for student_dir, _, _ in files.values()}, key=lambda path: path.name)
    for student_dir in students:
        baseline_dir = student_dir / "baseline"
        submission_dir = student_dir / "submission"
        baseline_files = sorted(baseline_dir.glob("*.txt")) if baseline_dir.is_dir() else []
        baseline_words = sum(len(path.read_text(encoding="utf-8", errors="replace").split()) for path in baseline_files)
        enough = len(baseline_files) >= 3 and baseline_words >= 300
        relevant = [(sid, path) for sid, (directory, _, _) in files.items() if directory == student_dir
                    for path in [submission_dir / f"{sid}.txt"]]
        base = {"student": student_dir.name, "n_baselines": len(baseline_files), "baseline_words": baseline_words}
        if not baseline_files:
            for sid, _ in relevant:
                label, author = labels.get(sid, ("", ""))
                rows.append({**base, "submission_id": sid, "label": label, "true_author": author, "error": "no baselines", "inconclusive": True})
            continue
        result, elapsed, error = run_scorer(baseline_dir, submission_dir, student_dir.name)
        timings.append(elapsed)
        rerun = None
        if result and not no_rerun:
            rerun, _, _ = run_scorer(baseline_dir, submission_dir, student_dir.name)
        first3 = None
        if result and len(baseline_files) > 3:
            with tempfile.TemporaryDirectory(prefix="alpha_b3_") as temp_dir:
                first3_dir = Path(temp_dir)
                for path in baseline_files[:3]:
                    (first3_dir / path.name).write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                first3, _, _ = run_scorer(first3_dir, submission_dir, student_dir.name)
        def scores_by_id(payload):
            return {Path(item.get("filename", "")).stem: item for item in (payload or {}).get("submissions", [])}
        scored = scores_by_id(result)
        rerun_scores, first3_scores = scores_by_id(rerun), scores_by_id(first3)
        for sid, path in relevant:
            item = scored.get(path.stem, {})
            label, author = labels.get(sid, ("", ""))
            deviation, probability = item.get("deviation_score"), item.get("authorship_probability")
            row = {**base, "submission_id": sid, "label": label, "true_author": author,
                   "deviation": deviation, "authorship_probability": probability,
                   "action": item.get("recommended_action"), "score_ms": item.get("scoring_time_ms"),
                   "inconclusive": not enough, "error": item.get("error") or (error if not result else "")}
            row["strict_flag"] = row["action"] in STRICT and enough
            row["lenient_flag"] = row["action"] in LENIENT and enough
            if not no_rerun and result:
                second = rerun_scores.get(sid)
                deterministic = bool(second and second.get("deviation_score") == deviation and second.get("authorship_probability") == probability)
                row["deterministic"] = deterministic
                if not deterministic:
                    problems.append(f"{student_dir.name}/{sid}: deterministic rerun differs")
            if sid in first3_scores:
                first3_deviation = first3_scores[sid].get("deviation_score")
                row["deviation_first3"] = first3_deviation if not bad(first3_deviation) else None
                if bad(first3_deviation):
                    problems.append(f"{student_dir.name}/{sid}: first-three deviation is missing or non-finite")
            for key, value in (("deviation", deviation), ("authorship_probability", probability)):
                if bad(value):
                    problems.append(f"{student_dir.name}/{sid}: {key} is missing or non-finite")
                    row[key] = None
                elif not 0 <= value <= 1:
                    problems.append(f"{student_dir.name}/{sid}: {key}={value} is outside [0,1]")
                    row[key] = None
            rows.append(row)
        if not enough:
            problems.append(f"{student_dir.name}: baseline below minimum ({len(baseline_files)} samples, {baseline_words} words) -> INCONCLUSIVE")
    report, code = build_report(rows, problems, timings, has_labels=labels_path is not None,
                                no_rerun=no_rerun, max_false_flag_rate=max_false_flag_rate,
                                min_catch_rate=min_catch_rate)
    csv_path = out_dir / "per_submission.csv"
    columns = sorted({key for row in rows for key in row})
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote {out_dir / 'report.md'} and {csv_path}")
    return code, rows, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", help="staff API base URL for an export")
    parser.add_argument("--exam", action="append", default=[], help="exam id to export; may be repeated")
    parser.add_argument("--from-dir", type=Path, help="score an existing local export")
    parser.add_argument("--labels", type=Path, help="CSV with submission_id,label,true_author")
    parser.add_argument("--repo", type=Path, default=ROOT, help="repository root (default: detected from this script)")
    parser.add_argument("--out", type=Path, default=Path("alpha_scores"))
    parser.add_argument("--max-false-flag-rate", type=float, default=1 / 20)
    parser.add_argument("--min-catch-rate", type=float, default=.75)
    parser.add_argument("--no-rerun", action="store_true", help="skip the determinism rerun")
    parser.add_argument("--throttle-seconds", type=float, default=1.0,
                        help="pause between isolated scoring subprocesses to leave CPU for the web service (default: 1)")
    args = parser.parse_args(argv)
    try:
        if args.from_dir:
            export_dir = args.from_dir.resolve()
        else:
            if not args.base_url:
                parser.error("--base-url is required unless --from-dir is used")
            token = os.environ.get("ALPHA_TOKEN")
            if not token:
                parser.error("set ALPHA_TOKEN in the shell")
            export_dir = export(args.base_url, token, args.exam, args.out.resolve() / "export")
        code, _, _ = run_batch(export_dir, args.out.resolve(), args.repo.resolve(), args.labels,
                               no_rerun=args.no_rerun, throttle_seconds=args.throttle_seconds,
                               max_false_flag_rate=args.max_false_flag_rate, min_catch_rate=args.min_catch_rate)
        return code
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"batch_score_alpha: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
