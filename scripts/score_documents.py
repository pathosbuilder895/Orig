#!/usr/bin/env python
"""
scripts/score_documents.py — one-shot CLI to score real documents.

Fills the gap the Explore agent identified: until now, the only way to score
real PDFs / DOCXs against a student's baseline was to write Python by hand
or curl the FastAPI per document. This CLI does it in batch and produces a
single JSON + CSV report.

The math is unchanged. The CLI uses the EXACT scoring path the live FastAPI
uses — it spins up the demo app in-process via FastAPI's TestClient and
POSTs each document to /students/{id}/baseline (for the baseline corpus)
and /students/{id}/score (for the submissions). Same code, same numbers.

Usage
-----

    # Score a directory of PDFs/DOCXs against a directory of baseline files.
    python scripts/score_documents.py \\
        --baseline-dir my_prior_writing/ \\
        --score-dir    submissions/ \\
        --student-id   andrew \\
        --out          report.json

    # Just one submission, against a single baseline file.
    python scripts/score_documents.py \\
        --baseline-file old_essay.docx \\
        --score-file    new_essay.pdf \\
        --student-id    test

    # Skip the baseline build and score against an EXISTING student in
    # the demo seed (e.g. score against the seeded "whitfield_j").
    python scripts/score_documents.py \\
        --use-existing-student whitfield_j \\
        --score-dir submissions/

Supported file types: .txt, .pdf, .docx, .md
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Resolve project root so `import original.*` works regardless of cwd.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


SUPPORTED_EXTS = {".txt", ".md", ".pdf", ".docx"}


@dataclass
class DocScore:
    """One scored document."""
    filename: str
    student_id: str
    word_count: int
    deviation_score: float
    authorship_probability: float
    recommended_action: str
    catastrophic_drift: bool
    catastrophic_drift_rms_z: float
    scoring_time_ms: float
    error: Optional[str] = None


# ── Text extraction ──────────────────────────────────────────────────────────

def extract_text(path: Path) -> str:
    """Extract plain text from a document. Supports .txt/.md/.pdf/.docx."""
    ext = path.suffix.lower()
    if ext in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except ImportError as e:
            raise RuntimeError("pypdf not installed; pip install pypdf") from e
    if ext == ".docx":
        try:
            from docx import Document
            doc = Document(str(path))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError as e:
            raise RuntimeError("python-docx not installed; pip install python-docx") from e
    raise ValueError(f"Unsupported file type {ext!r}. Use .txt/.md/.pdf/.docx.")


def collect_documents(target: Path) -> List[Path]:
    """Return all supported document paths under `target` (file or dir), sorted."""
    if target.is_file():
        if target.suffix.lower() in SUPPORTED_EXTS:
            return [target]
        raise ValueError(f"{target} has unsupported extension")
    if not target.is_dir():
        raise FileNotFoundError(target)
    out = sorted([
        p for p in target.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    ])
    if not out:
        raise FileNotFoundError(f"No supported documents under {target}")
    return out


# ── In-memory demo app for scoring ───────────────────────────────────────────

def _client():
    """Return a fresh TestClient bound to the demo FastAPI app.

    Reuses the battle-tested `run.load_legacy_demo_app()` helper so we
    don't trip the Pydantic forward-reference issue that a hand-rolled
    importlib loader hits.
    """
    import run as _run_module
    from fastapi.testclient import TestClient
    return TestClient(_run_module.load_legacy_demo_app())


# ── Main scoring loop ────────────────────────────────────────────────────────

def build_baseline(client, student_id: str, baselines: List[Path]) -> Dict[str, object]:
    """POST each baseline file to /students/{id}/baseline. Return a summary dict."""
    added = []
    failed = []
    for p in baselines:
        try:
            text = extract_text(p)
            if not text.strip():
                failed.append({"file": str(p), "error": "empty after extraction"})
                continue
            r = client.post(
                f"/students/{student_id}/baseline",
                json={
                    "text": text,
                    "provenance": "verified",
                    "assignment": p.stem,
                    "submitted_at": "2026-01-01",
                },
            )
            if r.status_code == 200:
                added.append({"file": str(p), "word_count": len(text.split()),
                              "sample_index": r.json().get("sample_index")})
            else:
                failed.append({"file": str(p), "status": r.status_code, "error": r.text[:200]})
        except Exception as e:
            failed.append({"file": str(p), "error": str(e)})
    return {"added": added, "failed": failed, "student_id": student_id}


def score_one(client, student_id: str, path: Path) -> DocScore:
    """Extract text from `path` and score it. Returns a DocScore."""
    try:
        text = extract_text(path)
    except Exception as e:
        return DocScore(filename=str(path), student_id=student_id, word_count=0,
                        deviation_score=float("nan"), authorship_probability=float("nan"),
                        recommended_action="error", catastrophic_drift=False,
                        catastrophic_drift_rms_z=0.0, scoring_time_ms=0.0, error=str(e))
    if not text.strip():
        return DocScore(filename=str(path), student_id=student_id, word_count=0,
                        deviation_score=float("nan"), authorship_probability=float("nan"),
                        recommended_action="error", catastrophic_drift=False,
                        catastrophic_drift_rms_z=0.0, scoring_time_ms=0.0,
                        error="empty text after extraction")
    t0 = time.perf_counter()
    r = client.post(f"/students/{student_id}/score",
                    json={"text": text, "assignment": path.stem, "submission_id": path.stem})
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if r.status_code != 200:
        return DocScore(filename=str(path), student_id=student_id,
                        word_count=len(text.split()), deviation_score=float("nan"),
                        authorship_probability=float("nan"), recommended_action="error",
                        catastrophic_drift=False, catastrophic_drift_rms_z=0.0,
                        scoring_time_ms=elapsed_ms, error=r.text[:200])
    j = r.json()
    return DocScore(
        filename=str(path),
        student_id=student_id,
        word_count=len(text.split()),
        deviation_score=float(j["authorship"]["deviation_score"]),
        authorship_probability=float(j["authorship"]["authorship_probability"]),
        recommended_action=j["recommendation"]["action"],
        catastrophic_drift=bool(j.get("catastrophic_drift", False)),
        catastrophic_drift_rms_z=float(j.get("catastrophic_drift_rms_z", 0.0)),
        scoring_time_ms=round(elapsed_ms, 2),
    )


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Score real documents (PDF / DOCX / TXT) against a baseline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--baseline-dir", type=Path,
                   help="Directory of baseline files (PDF/DOCX/TXT/MD).")
    g.add_argument("--baseline-file", type=Path,
                   help="Single baseline file.")
    g.add_argument("--use-existing-student",
                   help="Skip baseline build; score against an existing seeded student id.")

    s = ap.add_mutually_exclusive_group(required=True)
    s.add_argument("--score-dir", type=Path,
                   help="Directory of submission files to score.")
    s.add_argument("--score-file", type=Path,
                   help="Single submission file to score.")

    ap.add_argument("--student-id", default="cli_test_student",
                    help="Student id to use (must not clash with seeded names if "
                         "you're using a baseline-dir). Default: cli_test_student.")
    ap.add_argument("--out", type=Path, default=Path("report.json"),
                    help="Where to write the JSON report. Default: report.json.")
    ap.add_argument("--csv", type=Path,
                    help="Optionally also write a flat CSV report.")

    args = ap.parse_args(argv)

    # Lock the env so scoring is reproducible (this CLI is itself a benchmark
    # surface). Must happen BEFORE importing the demo app.
    from validation.benchmark.reproducibility import lock_environment
    env = lock_environment()

    client = _client()

    # 1. Baseline build (or skip).
    baseline_summary: Dict[str, object] = {}
    if args.use_existing_student:
        baseline_summary = {"reused_student_id": args.use_existing_student}
        student_id = args.use_existing_student
    else:
        student_id = args.student_id
        baselines: List[Path] = []
        if args.baseline_dir:
            baselines = collect_documents(args.baseline_dir)
        elif args.baseline_file:
            baselines = [args.baseline_file]
        else:
            print("ERROR: either --baseline-dir/--baseline-file or --use-existing-student is required",
                  file=sys.stderr)
            return 2
        if not baselines:
            print("ERROR: no baseline files found", file=sys.stderr)
            return 2
        print(f"Building baseline for {student_id!r} from {len(baselines)} files…", file=sys.stderr)
        baseline_summary = build_baseline(client, student_id, baselines)
        if not baseline_summary["added"]:
            print("ERROR: no baseline files were ingested successfully", file=sys.stderr)
            print(json.dumps(baseline_summary["failed"], indent=2), file=sys.stderr)
            return 1
        print(f"  {len(baseline_summary['added'])} baseline samples added, "
              f"{len(baseline_summary['failed'])} failed", file=sys.stderr)

    # 2. Scoring.
    submissions: List[Path] = []
    if args.score_dir:
        submissions = collect_documents(args.score_dir)
    else:
        submissions = [args.score_file]
    print(f"Scoring {len(submissions)} document(s)…", file=sys.stderr)
    scores: List[DocScore] = []
    for i, p in enumerate(submissions, 1):
        scores.append(score_one(client, student_id, p))
        print(f"  [{i}/{len(submissions)}] {p.name} → "
              f"dev={scores[-1].deviation_score:.3f} "
              f"action={scores[-1].recommended_action}",
              file=sys.stderr)

    # 3. Report.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "environment": env.__dict__,
        "student_id": student_id,
        "baseline": baseline_summary,
        "submissions": [asdict(s) for s in scores],
        "summary": {
            "n_submissions": len(scores),
            "n_errored": sum(1 for s in scores if s.error),
            "n_flagged": sum(1 for s in scores if s.recommended_action not in ("no_action", "monitor")),
            "n_catastrophic_drift": sum(1 for s in scores if s.catastrophic_drift),
            "mean_deviation": (
                round(sum(s.deviation_score for s in scores if s.error is None)
                      / max(1, sum(1 for s in scores if s.error is None)), 4)
            ),
        },
    }, indent=2))
    print(f"\nReport: {args.out}", file=sys.stderr)

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["filename", "student_id", "word_count", "deviation_score",
                        "authorship_probability", "recommended_action",
                        "catastrophic_drift", "scoring_time_ms", "error"])
            for s in scores:
                w.writerow([s.filename, s.student_id, s.word_count,
                            f"{s.deviation_score:.4f}" if s.error is None else "",
                            f"{s.authorship_probability:.4f}" if s.error is None else "",
                            s.recommended_action,
                            "yes" if s.catastrophic_drift else "no",
                            s.scoring_time_ms, s.error or ""])
        print(f"CSV:    {args.csv}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
