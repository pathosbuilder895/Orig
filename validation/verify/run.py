"""
validation/verify/run.py — binary authorship verification orchestrator.

  python -m validation.verify.run --corpus <dir> --manifest <path> --baselines 3

For each author A with ≥ ``--baselines`` baseline essays:
  - Score every A-authored held-out essay against A's baseline
    → y_true = 1 (same-author)
  - Score every OTHER author's held-out essay against A's baseline
    → y_true = 0 (different-author)

Reports per-author AUC + TPR at fixed FPR ∈ {0.01, 0.05, 0.10} with
bootstrap 95% CIs, plus a corpus-level pooled-uncalibrated diagnostic.
See ``binary_auc.VerifyReport`` for why per-author AUC (not the pooled
number) is the headline metric.

The math is unchanged — every score comes from
``original.quantum.scoring.score()`` via the in-memory FastAPI
TestClient (same path Test 2 uses). Env is locked BEFORE any
``original.*`` import so no scoring flag can leak in from the shell.

── KNOWN CORPUS LIMITATION (validation/public_authors) ─────────────────
For 8 of the 9 currently-eligible public-authors corpus entries
(everyone except emerson), the baseline essays and the held-out scoring
essays are consecutive PART-N chunks of a SINGLE Gutenberg work (e.g.
augustine's baseline = Confessions parts 1-3, scoring = Confessions
parts 4-6). That means "same-author" pairs currently measure
within-book topical/stylistic continuity, not just cross-work
authorial voice — a same-author AUC of 1.0 on this corpus is a real
but NARROWER claim than "Original tells this author apart from others
regardless of what they're writing about." A follow-up PR should add a
second, disjoint Gutenberg work per author (mirroring how emerson
already draws baseline vs scoring from different essays) before this
number is quoted as a general verification claim. Track in the
per-author breakdown: authors whose baseline/scoring source_ids
overlap should be flagged in the report once that data is available.
"""

from __future__ import annotations

# Env lock BEFORE any original.* import; TestClient will pull it in.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402
ENV_LOCK = lock_environment()

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional


_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

from validation.verify.binary_auc import _ScoringPair, summarize
from validation.verify.report import paths_for, write_report


def _load_manifest(manifest_path: Path) -> Dict[str, dict]:
    """Load manifest and bucket entries by author + role."""
    manifest = json.loads(manifest_path.read_text())
    by_author: Dict[str, dict] = defaultdict(lambda: {"baseline": [], "scoring": []})
    for e in manifest["entries"]:
        # Skip AI-generated + ghostwritten + paraphrased — these are NOT
        # authored by the person their author_id names, so they don't
        # belong in "score A's own held-outs against A's baseline". They
        # come back in as different-author entries via the cross-author
        # pass, but only when the target A has real baselines elsewhere.
        role = "baseline" if e.get("is_baseline") else "scoring"
        # We still consider non-authentic scoring entries for cross-author
        # pass — but only mark them as same-author if the label says so.
        by_author[e["author_id"]][role].append(e)
    return by_author


def _eligible(by_author: Dict[str, dict], baselines: int) -> List[str]:
    """Authors with ≥N baselines and ≥1 authentic scoring essay."""
    out = []
    for aid, items in sorted(by_author.items()):
        if len(items["baseline"]) < baselines:
            continue
        # Must have at least one AUTHENTIC scoring entry to contribute
        # y_true=1 pairs (i.e., a same-author example against A's baseline).
        authentic = [e for e in items["scoring"] if e.get("label") == "authentic"]
        if not authentic:
            continue
        out.append(aid)
    return out


_WORK_STEM_RE = re.compile(r"_part_\d+$")


def _work_stem(filename: str) -> str:
    """
    Best-effort "which work is this chunk from" key. Strips a numeric
    ``_part_N`` suffix (the pattern build_corpus.py's Gutenberg chunker
    uses) and the file extension, leaving the work title. Two files
    with the same stem are almost certainly chunks of the same source
    text.
    """
    stem = Path(filename).stem
    return _WORK_STEM_RE.sub("", stem)


def _same_work_overlap(by_author: Dict[str, dict], eligible: List[str]) -> List[str]:
    """
    For each eligible author, check whether baseline and (authentic)
    scoring entries share a work stem — i.e. same-author pairs measure
    within-work continuity rather than cross-work authorial voice.
    Returns the list of affected authors, for disclosure in the report.
    """
    affected = []
    for aid in eligible:
        items = by_author[aid]
        baseline_stems = {_work_stem(e["filename"]) for e in items["baseline"]}
        scoring_stems = {_work_stem(e["filename"]) for e in items["scoring"]
                         if e.get("label") == "authentic"}
        if baseline_stems & scoring_stems:
            affected.append(aid)
    return affected


def run(
    *,
    corpus_dir: Path,
    manifest_path: Path,
    baselines: int,
    label: str,
    only: Optional[set] = None,
    report_base: str = "validation/benchmarks",
) -> dict:
    """Run the evaluator end-to-end. Returns the summary dict."""
    import run as _run_module
    from fastapi.testclient import TestClient

    by_author = _load_manifest(manifest_path)
    eligible = _eligible(by_author, baselines)
    if only:
        eligible = [a for a in eligible if a in only]
    if len(eligible) < 2:
        raise RuntimeError(f"Need ≥2 eligible authors; got {len(eligible)}.")

    print(f"[verify] eligible authors ({len(eligible)}): {eligible}",
          file=sys.stderr)

    same_work_authors = _same_work_overlap(by_author, eligible)
    if same_work_authors:
        print(f"[verify] ⚠ {len(same_work_authors)} author(s) have baseline and "
              f"scoring drawn from the SAME source work — same-author AUC for "
              f"them measures within-work continuity, not just cross-work "
              f"authorial voice: {same_work_authors}", file=sys.stderr)

    client = TestClient(_run_module.load_legacy_demo_app())

    # ── 1. Upload the first N baselines for each eligible author. ──
    for aid in eligible:
        sid = f"demo:vr_{aid}"
        for entry in by_author[aid]["baseline"][:baselines]:
            text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
            r = client.post(f"/students/{sid}/baseline", json={
                "text": text,
                "provenance": "verified",
                "assignment": entry.get("prompt", "n/a"),
                "submitted_at": "2026-01-01",
            })
            if r.status_code != 200:
                print(f"  ⚠ baseline {aid} {entry['filename']}: "
                      f"{r.status_code} {r.text[:120]}", file=sys.stderr)

    # ── 2. Build the scoring set.
    # For each eligible author A:
    #   same-pairs   = A's AUTHENTIC scoring essays scored against A
    #   diff-pairs   = every OTHER eligible author's AUTHENTIC scoring
    #                  essays scored against A
    # Non-authentic scoring entries (ghostwritten / AI) are not in scope
    # here — this is per-author binary verification, not label discovery.
    pairs: List[_ScoringPair] = []
    t0 = time.perf_counter()
    for target in eligible:
        target_sid = f"demo:vr_{target}"
        n_pairs_for_target = 0
        for source in eligible:
            source_authentic = [e for e in by_author[source]["scoring"]
                                if e.get("label") == "authentic"]
            for entry in source_authentic:
                text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
                rr = client.post(f"/students/{target_sid}/score", json={
                    "text": text,
                    "assignment": entry.get("prompt", "n/a"),
                    "submission_id": f"{entry['filename']}@{target}",
                })
                if rr.status_code != 200:
                    print(f"  ⚠ score {entry['filename']} vs {target}: "
                          f"{rr.status_code}", file=sys.stderr)
                    continue
                payload = rr.json()["authorship"]
                pairs.append(_ScoringPair(
                    baseline_author=target,
                    submission_author=source,
                    deviation=float(payload["deviation_score"]),
                    probability=float(payload["authorship_probability"]),
                ))
                n_pairs_for_target += 1
        print(f"  {target}: {n_pairs_for_target} scoring pairs",
              file=sys.stderr)
    elapsed_s = time.perf_counter() - t0
    print(f"[verify] {len(pairs)} pairs in {elapsed_s:.1f}s", file=sys.stderr)

    # ── 3. Summarise + write.
    report = summarize(pairs)
    paths = paths_for(f"{label}_N{baselines}", base=report_base)
    write_report(paths, label=f"{label}_N{baselines}",
                 report=report, env_lock=ENV_LOCK,
                 corpus_dir=str(corpus_dir), manifest_path=str(manifest_path),
                 baselines=baselines,
                 extra={"eligible_authors": eligible,
                        "same_work_authors": same_work_authors})

    print()
    print(f"┌───────────────────────────────────────────────────────────────┐")
    print(f"│  {label:>32} @ N={baselines:<2} baselines            │")
    print(f"│  Median per-author AUC: {report.median_per_author_auc:.4f}"
          f"  IQR [{report.iqr_per_author_auc[0]:.4f}, {report.iqr_per_author_auc[1]:.4f}]  ← headline │")
    print(f"│  Same-author pairs: {report.total_same_pairs:<5}   Different: {report.total_different_pairs:<5}          │")
    if report.skipped_authors:
        print(f"│  Skipped ({len(report.skipped_authors)}): "
              f"{', '.join(report.skipped_authors)}")
    print(f"│  ── secondary / diagnostic ──                                    │")
    print(f"│  Pooled-uncalibrated AUC: {report.pooled_uncalibrated_auc:.4f}  "
          f"CI [{report.pooled_uncalibrated_auc_ci_lo:.4f}, {report.pooled_uncalibrated_auc_ci_hi:.4f}]  │")
    print(f"│  Pooled-uncalibrated Brier: {report.pooled_uncalibrated_brier:.4f}                          │")
    for fpr, tpr in (("0.01", report.pooled_uncalibrated_tpr_at_fpr_01),
                     ("0.05", report.pooled_uncalibrated_tpr_at_fpr_05),
                     ("0.10", report.pooled_uncalibrated_tpr_at_fpr_10)):
        print(f"│  Pooled TPR @ FPR={fpr}:  {(f'{tpr:.4f}' if tpr is not None else 'n/a')}                             │")
    print(f"│  Report: {paths.root}")
    print(f"└───────────────────────────────────────────────────────────────┘")
    return {"report_dir": str(paths.root),
            "median_per_author_auc": report.median_per_author_auc,
            "pooled_uncalibrated_auc": report.pooled_uncalibrated_auc,
            "n_authors": report.n_authors}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True, type=Path,
                    help="Corpus directory (e.g. validation/public_authors/corpus)")
    ap.add_argument("--manifest", required=True, type=Path,
                    help="Manifest JSON (e.g. validation/public_authors/manifest.json)")
    ap.add_argument("--baselines", type=int, default=3,
                    help="Baseline essays per author (default 3).")
    ap.add_argument("--label", default=None,
                    help="Label for the output dir (default: parent dir name).")
    ap.add_argument("--only", default=None,
                    help="Comma-separated author_ids to keep.")
    ap.add_argument("--out-dir", default="validation/benchmarks",
                    help="Base for the dated output directory.")
    args = ap.parse_args(argv)

    label = args.label or args.corpus.resolve().parent.name
    only = set(a.strip() for a in args.only.split(",")) if args.only else None
    try:
        run(corpus_dir=args.corpus, manifest_path=args.manifest,
            baselines=args.baselines, label=label,
            only=only, report_base=args.out_dir)
    except Exception as e:
        print(f"[verify] FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
