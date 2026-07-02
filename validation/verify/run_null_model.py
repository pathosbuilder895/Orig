"""
validation/verify/run_null_model.py — A/B the impostor-null model.

  python -m validation.verify.run_null_model --corpus <dir> --manifest <path> --baselines 3

Companion to ``run.py``. That evaluator scores through the in-memory
FastAPI TestClient (the production-realistic path); this one calls
``original.quantum.scoring.score()`` DIRECTLY, mirroring
``validation/calibration.py``'s pattern, because ``impostor_stats`` is a
function argument to ``score()`` — not something the HTTP API surfaces —
so the null-model comparison needs the lower-level call.

``RANK_REMEDIATION=shrinkage`` does NOT need this script — set it as an
env var and re-run ``run.py`` normally; the density matrix construction
reads that flag internally regardless of call path (HTTP or direct).

This script reports THREE columns per (same-pair, diff-pair): the
baseline deviation_score/authorship_probability (flag off, for a
same-run comparison point) and the llr_deviation_score (NULL_MODEL=
impostor). Both come from the SAME score() call — no double-scoring.
"""

from __future__ import annotations

# Env lock BEFORE any original.* import.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402
ENV_LOCK = lock_environment()

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

from original.features.pipeline import feature_vector
from original.quantum.state import StudentState, BaselineSample
from original.quantum.scoring import score
from validation.verify.binary_auc import _ScoringPair, summarize
from validation.verify.null_models import fit_impostor_gaussian
from validation.verify.report import paths_for, write_report

# Match the exact methodology validation/verify/run.py's HTTP path uses:
# run.py::load_legacy_demo_app() sets CONTEXT_MANIFEST_ENABLED=1 as a
# setdefault before any scoring happens (demo mode), which
# lock_environment() does NOT pin — so the HTTP-based evaluator scores
# through the adaptive-context pipeline (original/context/pipeline.py),
# not bare feature_vector(). Baselines are unaffected (api.py's
# add_baseline endpoint always uses plain feature_vector(), regardless
# of CONTEXT_MANIFEST_ENABLED — see original/api.py:1157) — only the
# SUBMISSION side goes through run_adaptive_pipeline. We replicate that
# exactly here so this script's "baseline" comparison row is measuring
# the SAME thing PR 1's headline numbers already measured, and the A/B
# delta is attributable to the null model alone.
os.environ.setdefault("CONTEXT_MANIFEST_ENABLED", "1")
from original.context.pipeline import run_adaptive_pipeline


def _load_manifest(manifest_path: Path) -> Dict[str, dict]:
    manifest = json.loads(manifest_path.read_text())
    by_author: Dict[str, dict] = defaultdict(lambda: {"baseline": [], "scoring": []})
    for e in manifest["entries"]:
        role = "baseline" if e.get("is_baseline") else "scoring"
        by_author[e["author_id"]][role].append(e)
    return by_author


def _eligible(by_author: Dict[str, dict], baselines: int) -> List[str]:
    out = []
    for aid, items in sorted(by_author.items()):
        if len(items["baseline"]) < baselines:
            continue
        authentic = [e for e in items["scoring"] if e.get("label") == "authentic"]
        if not authentic:
            continue
        out.append(aid)
    return out


def run(
    *,
    corpus_dir: Path,
    manifest_path: Path,
    baselines: int,
    label: str,
    only: Optional[set] = None,
    report_base: str = "validation/benchmarks",
) -> dict:
    """
    Build each eligible author's StudentState directly, fit an impostor
    Gaussian per target author from every OTHER eligible author's
    baseline vectors, then score every (target, source) pair once with
    NULL_MODEL=impostor + impostor_stats supplied. Reports both the
    unmodified deviation_score/authorship_probability AND the
    llr_deviation_score from the same score() call — a true A/B, not a
    re-score.
    """
    os.environ["NULL_MODEL"] = "impostor"

    by_author = _load_manifest(manifest_path)
    eligible = _eligible(by_author, baselines)
    if only:
        eligible = [a for a in eligible if a in only]
    if len(eligible) < 2:
        raise RuntimeError(f"Need ≥2 eligible authors; got {len(eligible)}.")
    print(f"[verify-null] eligible authors ({len(eligible)}): {eligible}",
          file=sys.stderr)

    # ── 1. Build each eligible author's StudentState + collect their raw
    #      (pre-unit-normalised) baseline vectors for the impostor pools. ──
    states: Dict[str, StudentState] = {}
    raw_baseline_vectors: Dict[str, List[np.ndarray]] = {}
    for aid in eligible:
        entries = by_author[aid]["baseline"][:baselines]
        samples = []
        vecs = []
        for entry in entries:
            text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
            fv = feature_vector(text)
            samples.append(BaselineSample(
                text=text, vector=fv, provenance="verified", auth_weight=0.7,
                assignment=entry.get("prompt", "n/a"), submitted_at="2026-01-01",
            ))
            vecs.append(fv)
        states[aid] = StudentState(student_id=aid, samples=samples)
        raw_baseline_vectors[aid] = vecs
        print(f"  baseline built: {aid} ({len(samples)} samples)", file=sys.stderr)

    # ── 2. Fit one impostor Gaussian per target author, from every OTHER
    #      eligible author's baseline vectors. ──
    impostor_stats: Dict[str, tuple] = {}
    for target in eligible:
        pool = [v for src in eligible if src != target for v in raw_baseline_vectors[src]]
        impostor_stats[target] = fit_impostor_gaussian(pool)

    # ── 3. Score every (target, source-authentic-scoring-essay) pair once,
    #      collecting BOTH deviation_score/authorship_probability (baseline,
    #      flag-off semantics for deviation_score itself — untouched) AND
    #      llr_deviation_score (impostor-adjusted) from the same call. ──
    baseline_pairs: List[_ScoringPair] = []
    llr_pairs: List[_ScoringPair] = []
    _enable_manifest = os.environ.get("CONTEXT_MANIFEST_ENABLED") == "1"
    _enable_adaptive = os.environ.get("ADAPTIVE_WEIGHTS_ENABLED") == "1"   # pinned "0" by lock_environment()

    t0 = time.perf_counter()
    for target in eligible:
        state = states[target]
        n_for_target = 0
        for source in eligible:
            source_authentic = [e for e in by_author[source]["scoring"]
                                if e.get("label") == "authentic"]
            for entry in source_authentic:
                text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
                submission_id = f"{entry['filename']}@{target}"
                # Mirror original/api.py:score_submission exactly — the
                # adaptive pipeline short-circuits to plain feature_vector
                # internally when both flags are False, so this is a
                # superset of the bare-feature_vector path, not a
                # divergence from it.
                adaptive = run_adaptive_pipeline(
                    text=text, state=state, submission_id=submission_id,
                    enable_manifest=_enable_manifest,
                    enable_adaptive_weights=_enable_adaptive,
                )
                fv = adaptive.vector
                feature_dict = adaptive.feat_dict
                result = score(
                    state, fv, feature_dict,
                    submission_id=submission_id,
                    adaptive_weights=adaptive.adaptive_weights,
                    manifest=adaptive.manifest.to_dict() if adaptive.manifest is not None else None,
                    impostor_stats=impostor_stats[target],
                )
                baseline_pairs.append(_ScoringPair(
                    baseline_author=target, submission_author=source,
                    deviation=result.authorship.deviation_score,
                    probability=result.authorship.authorship_probability,
                ))
                llr = result.authorship.llr_deviation_score
                llr_pairs.append(_ScoringPair(
                    baseline_author=target, submission_author=source,
                    deviation=llr,
                    probability=1.0 - llr,   # invert: higher = more "authentic-looking"
                ))
                n_for_target += 1
        print(f"  {target}: {n_for_target} scoring pairs", file=sys.stderr)
    elapsed_s = time.perf_counter() - t0
    print(f"[verify-null] {len(baseline_pairs)} pairs in {elapsed_s:.1f}s",
          file=sys.stderr)

    baseline_report = summarize(baseline_pairs)
    llr_report = summarize(llr_pairs)

    paths = paths_for(f"{label}_nullmodel_N{baselines}", base=report_base)
    write_report(paths, label=f"{label}_nullmodel_N{baselines}",
                 report=llr_report, env_lock=ENV_LOCK,
                 corpus_dir=str(corpus_dir), manifest_path=str(manifest_path),
                 baselines=baselines,
                 extra={
                     "eligible_authors": eligible,
                     "comparison": "baseline (flag off) vs impostor-null (NULL_MODEL=impostor)",
                     "baseline_median_per_author_auc": baseline_report.median_per_author_auc,
                     "baseline_iqr_per_author_auc": baseline_report.iqr_per_author_auc,
                     "baseline_pooled_uncalibrated_auc": baseline_report.pooled_uncalibrated_auc,
                 })

    print()
    print(f"┌───────────────────────────────────────────────────────────────┐")
    print(f"│  {label:>28} @ N={baselines:<2} — impostor-null A/B          │")
    print(f"│  baseline  median per-author AUC: {baseline_report.median_per_author_auc:.4f}"
          f"  IQR [{baseline_report.iqr_per_author_auc[0]:.4f}, {baseline_report.iqr_per_author_auc[1]:.4f}] │")
    print(f"│  impostor  median per-author AUC: {llr_report.median_per_author_auc:.4f}"
          f"  IQR [{llr_report.iqr_per_author_auc[0]:.4f}, {llr_report.iqr_per_author_auc[1]:.4f}] │")
    print(f"│  Δ median AUC: {llr_report.median_per_author_auc - baseline_report.median_per_author_auc:+.4f}"
          f"                                            │")
    print(f"│  baseline  pooled-uncalibrated AUC: {baseline_report.pooled_uncalibrated_auc:.4f}    │")
    print(f"│  impostor  pooled-uncalibrated AUC: {llr_report.pooled_uncalibrated_auc:.4f}    │")
    print(f"│  Report: {paths.root}")
    print(f"└───────────────────────────────────────────────────────────────┘")
    return {
        "report_dir": str(paths.root),
        "baseline_median_auc": baseline_report.median_per_author_auc,
        "impostor_median_auc": llr_report.median_per_author_auc,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--baselines", type=int, default=3)
    ap.add_argument("--label", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--out-dir", default="validation/benchmarks")
    args = ap.parse_args(argv)

    label = args.label or args.corpus.resolve().parent.name
    only = set(a.strip() for a in args.only.split(",")) if args.only else None
    try:
        run(corpus_dir=args.corpus, manifest_path=args.manifest,
            baselines=args.baselines, label=label,
            only=only, report_base=args.out_dir)
    except Exception as e:
        print(f"[verify-null] FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
