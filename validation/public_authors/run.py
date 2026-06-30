"""
validation/public_authors/run.py — Test 2 orchestrator (real-documents validation).

Reads the public-author corpus + manifest, builds a baseline for each
author, scores every held-out essay against ALL author baselines, and
reports the attribution matrix + confusion matrix + per-author metrics.

Correct attribution = the lowest deviation against the true author's
baseline. Top-1 accuracy ≥ 0.7 across the corpus is the pass criterion.

Run:
    python -m validation.public_authors.run
    python -m validation.public_authors.run --report-dir /tmp/my_run
    python -m validation.public_authors.run --only chesterton,emerson

Authors with fewer than 3 baseline samples are skipped with a clear
warning. The corpus can be expanded by adding URLs to build_corpus.py.

The math is unchanged: every score comes from
``original.quantum.scoring.score()`` via the in-memory FastAPI client.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Resolve project root so original.* imports work.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

# Lock the env BEFORE any original.* import.
from validation.benchmark.reproducibility import lock_environment       # noqa: E402

_MANIFEST = _HERE / "manifest.json"
_CORPUS_DIR = _HERE / "corpus"


# ── Data ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AttributionResult:
    """One held-out essay scored against every author baseline."""
    filename: str
    true_author: str
    predicted_author: str
    correct: bool
    deviations: Dict[str, float] = field(default_factory=dict)   # per-author deviation
    rank_of_true: int = 0    # 1 = correct, 2 = runner-up, …
    word_count: int = 0
    scoring_time_ms: float = 0.0
    error: Optional[str] = None


# ── The orchestrator ────────────────────────────────────────────────────────

def run(*, manifest_path: Path = _MANIFEST,
        corpus_dir: Path = _CORPUS_DIR,
        only: Optional[Set[str]] = None,
        report_dir: Optional[Path] = None) -> dict:
    """
    Run Test 2 end-to-end. Returns a report dict.

    Args:
        manifest_path: path to the public-authors manifest.
        corpus_dir: root of the corpus tree.
        only: optional set of author_ids to include; others are skipped.
        report_dir: where to write the report.{json,md} + CSVs. Defaults
                    to validation/benchmarks/<YYYY-MM-DD>/public_authors/.
    """
    env = lock_environment()

    # Late import — must be after env lock.
    import run as _run_module      # the project's run.py at repo root
    from fastapi.testclient import TestClient

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Group entries by author.
    by_author: Dict[str, dict] = defaultdict(lambda: {"baseline": [], "scored": []})
    for e in manifest["entries"]:
        key = "baseline" if e["is_baseline"] else "scored"
        by_author[e["author_id"]][key].append(e)

    # Filter to authors with the required minimum AND any --only filter.
    eligible: List[str] = []
    skipped_authors: List[Tuple[str, str]] = []
    for aid, items in sorted(by_author.items()):
        if only is not None and aid not in only:
            skipped_authors.append((aid, "filtered by --only"))
            continue
        if len(items["baseline"]) < 3:
            skipped_authors.append(
                (aid, f"only {len(items['baseline'])} baseline samples (need ≥3)")
            )
            continue
        if not items["scored"]:
            skipped_authors.append((aid, "no held-out scored essays"))
            continue
        eligible.append(aid)

    if len(eligible) < 2:
        msg = (f"Need at least 2 eligible authors for an attribution test; "
               f"got {len(eligible)}. Expand the corpus by adding URLs to "
               f"validation/public_authors/build_corpus.py and re-running.")
        print(f"\n⚠ {msg}\n", file=sys.stderr)
        if not eligible:
            return {"error": msg, "skipped_authors": skipped_authors}

    client = TestClient(_run_module.load_legacy_demo_app())

    # ── 1. Build each author's baseline. We use a unique student_id per
    #      author so the scorer can address each one separately.
    print(f"Eligible authors: {eligible}", file=sys.stderr)
    print(f"Skipped: {skipped_authors}", file=sys.stderr)
    print(f"\nBuilding baselines…", file=sys.stderr)
    for aid in eligible:
        sid = f"demo:pa_{aid}"
        for entry in by_author[aid]["baseline"]:
            text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
            r = client.post(f"/students/{sid}/baseline", json={
                "text": text,
                "provenance": "verified",
                "assignment": entry["prompt"],
                "submitted_at": "2026-01-01",
            })
            if r.status_code != 200:
                print(f"  ⚠ {aid} baseline {entry['filename']}: {r.status_code} {r.text[:120]}",
                      file=sys.stderr)
        print(f"  {aid}: {len(by_author[aid]['baseline'])} baseline samples uploaded",
              file=sys.stderr)

    # ── 2. For each held-out essay, score it against EVERY author baseline.
    print(f"\nScoring {sum(len(by_author[a]['scored']) for a in eligible)} held-out essays "
          f"against {len(eligible)} authors…", file=sys.stderr)
    results: List[AttributionResult] = []
    for true_author in eligible:
        for entry in by_author[true_author]["scored"]:
            text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
            wc = entry["word_count"]
            t0 = time.perf_counter()
            devs: Dict[str, float] = {}
            err: Optional[str] = None
            for candidate in eligible:
                cand_sid = f"demo:pa_{candidate}"
                rr = client.post(f"/students/{cand_sid}/score", json={
                    "text": text, "assignment": entry["prompt"],
                    "submission_id": entry["filename"],
                })
                if rr.status_code != 200:
                    err = f"{candidate}: {rr.status_code}"
                    devs[candidate] = float("nan")
                else:
                    devs[candidate] = float(rr.json()["authorship"]["deviation_score"])
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            # Sort by deviation ascending — lowest = best match.
            ranked = sorted(devs.items(), key=lambda kv: kv[1])
            predicted = ranked[0][0]
            rank_of_true = next((i + 1 for i, (a, _) in enumerate(ranked) if a == true_author),
                                0)
            results.append(AttributionResult(
                filename=entry["filename"],
                true_author=true_author,
                predicted_author=predicted,
                correct=(predicted == true_author),
                deviations={a: round(d, 4) for a, d in devs.items()},
                rank_of_true=rank_of_true,
                word_count=wc,
                scoring_time_ms=round(elapsed_ms, 2),
                error=err,
            ))
            print(f"  {entry['filename']}: true={true_author}, "
                  f"predicted={predicted} {'✓' if predicted==true_author else '✗'} "
                  f"(rank {rank_of_true})", file=sys.stderr)

    # ── 3. Aggregate metrics.
    top1_accuracy = sum(1 for r in results if r.correct) / max(1, len(results))
    mean_rank = sum(r.rank_of_true for r in results) / max(1, len(results))
    per_author = defaultdict(lambda: {"n": 0, "correct": 0})
    for r in results:
        per_author[r.true_author]["n"] += 1
        if r.correct:
            per_author[r.true_author]["correct"] += 1

    confusion: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        confusion[r.true_author][r.predicted_author] += 1

    # ── 4. Build report dict + write to disk.
    if report_dir is None:
        import datetime
        report_dir = _ROOT / "validation" / "benchmarks" / \
                     datetime.date.today().isoformat() / "public_authors"
    report_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "dataset_label": "public_authors",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": env.__dict__,
        "summary": {
            "eligible_authors": eligible,
            "n_eligible_authors": len(eligible),
            "n_held_out_essays": len(results),
            "top1_accuracy": round(top1_accuracy, 4),
            "mean_rank_of_true_author": round(mean_rank, 3),
            "skipped_authors": skipped_authors,
        },
        "per_author": {
            a: {
                "n_scored": c["n"],
                "n_correct": c["correct"],
                "accuracy": round(c["correct"] / max(1, c["n"]), 4),
            }
            for a, c in per_author.items()
        },
        "results": [asdict(r) for r in results],
        "confusion": {true_a: dict(preds) for true_a, preds in confusion.items()},
    }
    (report_dir / "report.json").write_text(json.dumps(report, indent=2))
    _write_attribution_csv(report_dir / "attribution_matrix.csv", results, eligible)
    _write_confusion_csv(report_dir / "confusion.csv", confusion, eligible)
    (report_dir / "report.md").write_text(_render_markdown(report))

    print(f"\n┌─────────────────────────────────────────────────┐", file=sys.stderr)
    print(f"│  Top-1 attribution accuracy: {top1_accuracy:.2%}              │", file=sys.stderr)
    print(f"│  Mean rank of true author:   {mean_rank:.2f}                │", file=sys.stderr)
    print(f"│  Reports: {report_dir}", file=sys.stderr)
    print(f"└─────────────────────────────────────────────────┘", file=sys.stderr)
    return report


# ── Helpers ─────────────────────────────────────────────────────────────────

def _write_attribution_csv(path: Path, results: List[AttributionResult],
                           eligible: List[str]) -> None:
    """Row = held-out essay; cols = deviation to each author baseline + verdict."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filename", "true_author", "predicted_author", "correct",
                    "rank_of_true", "word_count", *[f"dev_to_{a}" for a in eligible]])
        for r in results:
            w.writerow([r.filename, r.true_author, r.predicted_author,
                        "yes" if r.correct else "no", r.rank_of_true, r.word_count,
                        *[r.deviations.get(a, "") for a in eligible]])


def _write_confusion_csv(path: Path, confusion: Dict[str, Dict[str, int]],
                         eligible: List[str]) -> None:
    """Row = true author; col = predicted author."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["true \\ predicted", *eligible])
        for true_a in eligible:
            row = [true_a]
            for pred_a in eligible:
                row.append(confusion.get(true_a, {}).get(pred_a, 0))
            w.writerow(row)


def _render_markdown(report: dict) -> str:
    s = report["summary"]
    lines = []
    lines.append("# Public-author validation — Test 2 report")
    lines.append("")
    lines.append(f"_Generated {report['generated_at']}_")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Top-1 attribution accuracy**: {s['top1_accuracy']:.2%}")
    lines.append(f"- **Mean rank of true author**: {s['mean_rank_of_true_author']}")
    lines.append(f"- **Eligible authors**: {s['n_eligible_authors']} — {', '.join(s['eligible_authors'])}")
    lines.append(f"- **Held-out essays scored**: {s['n_held_out_essays']}")
    if s.get("skipped_authors"):
        lines.append(f"- **Skipped authors**: {len(s['skipped_authors'])} — see report.json for reasons")
    lines.append("")
    lines.append("## Per-author accuracy")
    lines.append("")
    lines.append("| author | n | correct | accuracy |")
    lines.append("|---|---|---|---|")
    for a, c in sorted(report["per_author"].items()):
        lines.append(f"| {a} | {c['n_scored']} | {c['n_correct']} | {c['accuracy']:.2%} |")
    lines.append("")
    lines.append("## Confusion matrix")
    lines.append("")
    authors = s["eligible_authors"]
    lines.append("| true \\ predicted | " + " | ".join(authors) + " |")
    lines.append("|" + "---|" * (len(authors) + 1))
    for ta in authors:
        row = [ta]
        for pa in authors:
            row.append(str(report["confusion"].get(ta, {}).get(pa, 0)))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="Comma-separated list of author_ids to include.")
    ap.add_argument("--report-dir", type=Path,
                    help="Where to write reports. Defaults to "
                         "validation/benchmarks/<YYYY-MM-DD>/public_authors/")
    args = ap.parse_args(argv)
    only = set(a.strip() for a in args.only.split(",")) if args.only else None
    report = run(only=only, report_dir=args.report_dir)
    return 0 if "error" not in report else 1


if __name__ == "__main__":
    sys.exit(main())
