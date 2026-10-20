#!/usr/bin/env python3
"""Export and score an alpha workspace offline; never publish scores to students.

Use ``--from-dir`` for a local export or provide ``--base-url`` and repeated
``--exam`` values with ``ALPHA_TOKEN`` set. Label files have the exact header
``submission_id,label,author_true,writer_true`` (label ``natural``/``shadow``;
legacy ``true_author``/``not_own`` accepted) and one unique row per exported
submission. An optional ``baselines.csv`` in the export root tags split-derived
baselines (see ``load_baseline_sources``); without it all baselines are tagged
``independent`` and the report says so.
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
LABELS = {"natural", "shadow"}
LABEL_ALIASES = {"not_own": "shadow"}
BASELINE_SOURCES = {"independent", "split"}
MIN_BASELINES = 3  # matches the server's insufficient-baseline gate


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
    baseline_texts: dict[str, dict[str, str]] = {}
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
            sample_text = response.json().get("text", "")
            (baseline_dir / f"{index:02d}.txt").write_text(sample_text, encoding="utf-8")
            baseline_texts.setdefault(student_dir.name, {})[f"{index:02d}.txt"] = sample_text
    papers_response = requests.get(f"{base.rstrip('/')}/bluebook/past-papers", headers=headers, timeout=60)
    papers_response.raise_for_status()
    write_baseline_sources(dest, baseline_texts, papers_response.json().get("papers", []))
    (dest / "manifest.json").write_text(json.dumps({"exams": exams, "submissions": len(rows)}, indent=2), encoding="utf-8")
    return dest


def write_baseline_sources(dest: Path, baseline_texts: dict[str, dict[str, str]],
                           shared_papers: list[dict]) -> Path | None:
    """Write ``<export>/baselines.csv`` from the papers students shared in the app.

    A baseline file whose text is an approved shared paper takes that paper's
    tag (``split`` with ``parent_paper_id`` = the student folder plus the
    longer paper's title, so sections of one paper group together); every
    other file is ``independent``. A ``baselines.csv`` already in the export
    (Andrew's hand-tagged imports) is left alone. Returns the path written.
    """
    import hashlib

    path = dest / "baselines.csv"
    if path.exists() or not baseline_texts:
        return None
    tags = {p.get("text_sha256"): p for p in shared_papers
            if p.get("status") == "approved" and p.get("text_sha256")}
    with path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(["student", "baseline_file", "baseline_source", "parent_paper_id"])
        for student in sorted(baseline_texts):
            for filename in sorted(baseline_texts[student]):
                digest = hashlib.sha256(baseline_texts[student][filename].encode()).hexdigest()
                paper = tags.get(digest) or {}
                if paper.get("baseline_source") == "split":
                    parent = " ".join(str(paper.get("parent_title") or paper.get("title") or "").lower().split())
                    writer.writerow([student, filename, "split", f"{student}:{parent}"])
                else:
                    writer.writerow([student, filename, "independent", ""])
    return path


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


SHADOW_KINDS = {"human_partner", "ai_staff", "injected_other", "public_domain"}
LABEL_METADATA_FIELDS = ["shadow_kind", "imitated_student_id", "prompt_id",
                         "paired_submission_id", "shadow_source_paper_id", "generator_tool"]


def validate_labels(path: Path, exported_ids: set[str]) -> dict[str, dict[str, str]]:
    """Validate the complete label CSV before any scoring starts.

    EVALUATION-ONLY / BLIND: this file is read only by this batch process to
    compute rates *after* scores exist. It is never passed to the scoring
    subprocess (``score()`` forwards only baseline/submission directories) and
    never becomes an engine feature or part of any scored text.

    Canonical v2 header:
    ``submission_id,label,author_true,writer_true,shadow_kind,imitated_student_id,prompt_id,paired_submission_id,shadow_source_paper_id,generator_tool``
    ``label`` is ``natural`` or ``shadow``. For a shadow row: ``author_true``
    is the student whose baseline/voice is imitated, ``writer_true`` is who
    actually wrote/generated it (never that same student), ``shadow_kind`` is
    one of ``human_partner|ai_staff|injected_other|public_domain``,
    ``prompt_id`` + ``paired_submission_id`` identify the same-prompt genuine
    paper it pairs with, ``shadow_source_paper_id`` is the one sample paper the
    writer/generator was shown, and ``generator_tool`` is required for
    ``ai_staff``. ``writer_true`` may be blank on natural rows.
    Legacy headers (``true_author`` and/or no metadata columns) and the legacy
    label ``not_own`` are accepted and normalised, with metadata blank.
    """
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        v2 = ["submission_id", "label", "author_true", "writer_true"] + LABEL_METADATA_FIELDS
        legacy = reader.fieldnames in (["submission_id", "label", "true_author"],
                                       ["submission_id", "label", "author_true"],
                                       ["submission_id", "label", "author_true", "writer_true"])
        if not legacy and reader.fieldnames != v2:
            raise ValueError(f"labels CSV header must be exactly: {','.join(v2)} (legacy submission_id,label,true_author also accepted)")
        author_col = "true_author" if (reader.fieldnames and "true_author" in reader.fieldnames) else "author_true"
        result: dict[str, dict[str, str]] = {}
        for line, row in enumerate(reader, start=2):
            submission_id = (row.get("submission_id") or "").strip()
            label = LABEL_ALIASES.get((row.get("label") or "").strip().lower(), (row.get("label") or "").strip().lower())
            if not submission_id:
                raise ValueError(f"labels CSV line {line}: submission_id is required")
            if submission_id in result:
                raise ValueError(f"labels CSV line {line}: duplicate submission_id {submission_id!r}")
            if label not in LABELS:
                raise ValueError(f"labels CSV line {line}: label must be natural or shadow")
            entry = {"label": label, "author_true": (row.get(author_col) or "").strip(),
                     "writer_true": (row.get("writer_true") or "").strip(),
                     **{f: (row.get(f) or "").strip() for f in LABEL_METADATA_FIELDS}}
            if not legacy and label == "shadow":
                if entry["shadow_kind"] not in SHADOW_KINDS:
                    raise ValueError(f"labels CSV line {line}: shadow row needs shadow_kind in {sorted(SHADOW_KINDS)}")
                for field in ("author_true", "writer_true", "imitated_student_id", "prompt_id", "paired_submission_id"):
                    if not entry[field]:
                        raise ValueError(f"labels CSV line {line}: shadow row needs {field}")
                if entry["writer_true"] == entry["author_true"]:
                    raise ValueError(f"labels CSV line {line}: shadow writer must not be the imitated student")
                if entry["shadow_kind"] == "ai_staff" and not entry["generator_tool"]:
                    raise ValueError(f"labels CSV line {line}: ai_staff shadow needs generator_tool")
            entry["shadow"] = "true" if label == "shadow" else "false"
            result[submission_id] = entry
    unknown = sorted(set(result) - exported_ids)
    missing = sorted(exported_ids - set(result))
    if unknown:
        raise ValueError(f"labels CSV contains unknown submission ids: {', '.join(unknown[:5])}")
    if missing:
        raise ValueError(f"labels CSV is missing submission ids: {', '.join(missing[:5])}")
    return result


def load_baseline_sources(export_dir: Path, student_names: set[str]) -> tuple[dict[str, dict[str, tuple[str, str]]], bool]:
    """Load optional split-baseline tagging from ``<export>/baselines.csv``.

    Header exactly ``student,baseline_file,baseline_source,parent_paper_id``.
    ``student`` is the export folder name, ``baseline_file`` a basename inside
    that student's ``baseline/`` folder, ``baseline_source`` is ``independent``
    or ``split``. Split-derived files must name their ``parent_paper_id`` (the
    single long paper they were cut from); sections of one paper are correlated
    and must never be silently pooled with genuinely independent papers.
    Returns ``(mapping, present)``; absent file -> ``({}, False)`` and callers
    tag everything ``independent`` and say so in the report.
    """
    path = export_dir / "baselines.csv"
    if not path.is_file():
        return {}, False
    required = ["student", "baseline_file", "baseline_source", "parent_paper_id"]
    mapping: dict[str, dict[str, tuple[str, str]]] = {}
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != required:
            raise ValueError(f"baselines CSV header must be exactly: {','.join(required)}")
        for line, row in enumerate(reader, start=2):
            student = (row.get("student") or "").strip()
            filename = Path((row.get("baseline_file") or "").strip()).name
            source_name = (row.get("baseline_source") or "").strip().lower()
            parent = (row.get("parent_paper_id") or "").strip()
            if not student or not filename:
                raise ValueError(f"baselines CSV line {line}: student and baseline_file are required")
            if student not in student_names:
                raise ValueError(f"baselines CSV line {line}: unknown student folder {student!r}")
            if source_name not in BASELINE_SOURCES:
                raise ValueError(f"baselines CSV line {line}: baseline_source must be independent or split")
            if source_name == "split" and not parent:
                raise ValueError(f"baselines CSV line {line}: split-derived baseline needs parent_paper_id")
            if not (export_dir / student / "baseline" / filename).is_file():
                raise ValueError(f"baselines CSV line {line}: no such baseline file {student}/baseline/{filename}")
            per_student = mapping.setdefault(student, {})
            if filename in per_student:
                raise ValueError(f"baselines CSV line {line}: duplicate baseline {student}/{filename}")
            per_student[filename] = (source_name, parent)
    return mapping, True


def baseline_tagging(student_name: str, baseline_files: list[Path],
                     sources: dict[str, dict[str, tuple[str, str]]], tags_present: bool) -> dict:
    """Per-student split/independent counts; the gate counts papers, this does not hide splits."""
    per_student = sources.get(student_name, {})
    n_split = sum(1 for f in baseline_files if per_student.get(f.name, ("independent", ""))[0] == "split")
    parents = sorted({per_student[f.name][1] for f in baseline_files
                      if per_student.get(f.name, ("independent", ""))[0] == "split" and per_student[f.name][1]})
    group = "independent" if n_split == 0 else ("split" if n_split == len(baseline_files) else "mixed")
    return {"baseline_source": group, "n_split_baselines": n_split,
            "n_independent_baselines": len(baseline_files) - n_split,
            "baseline_parent_ids": ";".join(parents),
            "baseline_tags": "baselines.csv" if tags_present else "default-independent"}


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
    not_own = [row for row in rows if row.get("label") == "shadow" and not row.get("inconclusive") and not bad(row.get("deviation"))]
    return [{
        "threshold": step / 20,
        "caught": sum(row["deviation"] >= step / 20 for row in not_own),
        "not_own_total": len(not_own), "shadow_total": len(not_own),
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


def _baseline_source_summary(rows: list[dict]) -> str:
    per_student = {}
    for row in rows:  # one entry per student (rows repeat baselines per submission)
        per_student[row["student"]] = row
    parts = []
    for group in ("independent", "split", "mixed"):
        members = [r for r in per_student.values() if r.get("baseline_source", "independent") == group]
        if members:
            parts.append(f"{group}: {len(members)} student(s), {sum(r.get('n_split_baselines', 0) for r in members)} split paper(s)")
    tagged = any(r.get("baseline_tags") == "baselines.csv" for r in rows)
    return "; ".join(parts or ["independent: 0 student(s), 0 split paper(s)"]) + (
        " [tagged in baselines.csv]" if tagged else " [no baselines.csv: all tagged independent by staff attestation]")


def build_report(rows: list[dict], problems: list[str], timings: list[float], *, has_labels: bool,
                 no_rerun: bool, max_false_flag_rate: float, min_catch_rate: float) -> tuple[str, int]:
    scored = [row for row in rows if not bad(row.get("deviation"))]
    deviations = [row["deviation"] for row in scored]
    effect = [abs(row["deviation"] - row["deviation_first3"]) for row in scored if not bad(row.get("deviation_first3"))]
    lines = ["# Alpha batch scoring report (internal; never shown to students)", "",
             f"- submissions: {len(rows)}; scored: {len(scored)}; errors: {sum(bool(row.get('error')) for row in rows)}",
             f"- INCONCLUSIVE (baseline below minimum): {rate(sum(bool(row.get('inconclusive')) for row in rows), len(rows))}",
             "- insufficient baseline (fewer than " + str(MIN_BASELINES) + " papers, not scored): "
             + (", ".join(sorted({row['student'] for row in rows if row.get('insufficient_baseline')})) or "none"),
             "- baseline sources (gate counts papers; splits shown separately, never silently pooled): " + _baseline_source_summary(rows),
             (f"- deviation min/median/max: {min(deviations):.3f} / {statistics.median(deviations):.3f} / {max(deviations):.3f}" if deviations else "- no scores"),
             f"- deterministic on rerun: {sum(row.get('deterministic') is True for row in scored)}/{len(scored)}" + (" (rerun skipped)" if no_rerun else ""),
             f"- scoring time: per paper max {max((row.get('score_ms') or 0 for row in scored), default=0):.0f} ms; per student run max {max(timings, default=0):.1f} s",
             (f"- baseline-size effect |dev(all) - dev(first3)|: mean {statistics.mean(effect):.3f}, max {max(effect):.3f} (n={len(effect)})" if effect else "- baseline-size effect: n/a")]
    passed = None
    if has_labels:
        labeled = [row for row in scored if row.get("label") and not row.get("inconclusive")]
        natural = [row for row in labeled if row["label"] == "natural"]
        not_own = [row for row in labeled if row["label"] == "shadow"]
        false_flags = sum(bool(row["strict_flag"]) for row in natural)
        caught = sum(bool(row["strict_flag"]) for row in not_own)
        groups = {}
        for row in labeled:
            groups.setdefault(row["student"], []).append(row)
        def fraction(sample, label):
            subset = [row for row in sample if row["label"] == label]
            return sum(bool(row["strict_flag"]) for row in subset) / len(subset) if subset else None
        f_lo, f_hi = boot_ci(groups, lambda sample: fraction(sample, "natural"))
        c_lo, c_hi = boot_ci(groups, lambda sample: fraction(sample, "shadow"))
        passed = bool(natural and not_own and false_flags / len(natural) <= max_false_flag_rate and caught / len(not_own) >= min_catch_rate)
        f_wilson = wilson(false_flags, len(natural)); c_wilson = wilson(caught, len(not_own))
        lines += ["", "## Accuracy against labels (strict = schedule_conversation/escalate; INCONCLUSIVE excluded)",
                  f"- False flags on natural work: {rate(false_flags, len(natural))}; Wilson {format_interval(f_wilson)}; student-bootstrap {format_interval((f_lo, f_hi))}",
                  f"- Caught shadow work: {rate(caught, len(not_own))}; Wilson {format_interval(c_wilson)}; student-bootstrap {format_interval((c_lo, c_hi))}",
                  "", "### Deviation threshold sweep (flag if deviation >= t)", "| t | caught | false flags |", "|---|---|---|"]
        for row in threshold_sweep(labeled):
            lines.append(f"| {row['threshold']:.2f} | {rate(row['caught'], row['not_own_total'])} | {rate(row['false_flags'], row['natural_total'])} |")
        lines += ["", "### Baseline-source breakout (split-derived never pooled silently)",
                  "> Sections cut from one long paper are correlated, not independent papers. Compare these rows before trusting the pooled rates above; a different false-flag rate for split-derived baselines is a calibration finding, not a student finding.",
                  "| baseline source | students | natural | false flags | shadow | caught |", "|---|---:|---:|---:|---:|---:|"]
        for group in ("independent", "split", "mixed"):
            grows = [row for row in labeled if row.get("baseline_source", "independent") == group]
            if not grows:
                continue
            gn = [row for row in grows if row["label"] == "natural"]
            gs = [row for row in grows if row["label"] == "shadow"]
            lines.append(f"| {group} | {len({row['student'] for row in grows})} | {len(gn)} | {rate(sum(bool(r['strict_flag']) for r in gn), len(gn))} | {len(gs)} | {rate(sum(bool(r['strict_flag']) for r in gs), len(gs))} |")
        lines += ["", f"Pre-registered criteria: false-flag rate <= {max_false_flag_rate:.0%} and catch rate >= {min_catch_rate:.0%}",
                  f"**{'PASS' if passed else 'FAIL'}** on point estimates.",
                  "", "> Small-sample results are not validation. Do not tune thresholds against this same set and re-score it."]
    lines += ["", "## Problems", *(f"- {item}" for item in problems or ["none"]), "",
              "| student | submission | label | baselines | split baselines | baseline source | words | deviation | action | strict flag | deterministic |",
              "|---|---|---|---:|---:|---|---:|---:|---|---|---|"]
    for row in rows:
        value = row.get("deviation")
        lines.append(f"| {row['student'][-8:]} | {row['submission_id'][:10]} | {row.get('label', '')} | {row['n_baselines']} | {row.get('n_split_baselines', 0)} | {row.get('baseline_source', 'independent')} | {row['baseline_words']} | "
                     f"{'-' if bad(value) else f'{value:.3f}'} | {'INSUFFICIENT BASELINE' if row.get('insufficient_baseline') else 'INCONCLUSIVE' if row.get('inconclusive') else row.get('action', row.get('error', '-'))} | "
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
    sources, tags_present = load_baseline_sources(export_dir, {d.name for d, _, _ in files.values()})
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
        enough = len(baseline_files) >= MIN_BASELINES and baseline_words >= 300
        relevant = [(sid, path) for sid, (directory, _, _) in files.items() if directory == student_dir
                    for path in [submission_dir / f"{sid}.txt"]]
        base = {"student": student_dir.name, "n_baselines": len(baseline_files), "baseline_words": baseline_words,
                **baseline_tagging(student_dir.name, baseline_files, sources, tags_present)}
        if len(baseline_files) < MIN_BASELINES:
            # Not scored at all: Original returns "insufficient baseline", not a number.
            for sid, _ in relevant:
                meta = labels.get(sid, {})
                rows.append({**base, "submission_id": sid, "label": meta.get("label", ""), "true_author": meta.get("author_true", ""), **{k: meta.get(k, "") for k in ("author_true", "writer_true", "shadow", *LABEL_METADATA_FIELDS)},
                             "error": f"insufficient baseline ({len(baseline_files)} of {MIN_BASELINES} papers)",
                             "inconclusive": True, "insufficient_baseline": True})
            problems.append(f"{student_dir.name}: INSUFFICIENT BASELINE ({len(baseline_files)} of {MIN_BASELINES} papers) -> not scored")
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
            meta = labels.get(sid, {})
            deviation, probability = item.get("deviation_score"), item.get("authorship_probability")
            row = {**base, "submission_id": sid, "label": meta.get("label", ""), "true_author": meta.get("author_true", ""), **{k: meta.get(k, "") for k in ("author_true", "writer_true", "shadow", *LABEL_METADATA_FIELDS)},
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
    parser.add_argument("--labels", type=Path, help="evaluation-only CSV: submission_id,label,author_true,writer_true,shadow_kind,imitated_student_id,prompt_id,paired_submission_id,shadow_source_paper_id,generator_tool")
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
