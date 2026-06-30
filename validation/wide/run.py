"""
validation/wide/run.py — wide-dataset benchmark orchestrator.

  python -m validation.wide.run --dataset raid --sample 800
  python -m validation.wide.run --dataset pan --pan-year 2021 --sample-pairs 300
  python -m validation.wide.run --dataset m4 --sample 800
  python -m validation.wide.run --dataset all --include-ablation

Each invocation:

  1. Locks the environment (SECRET_KEY, ADAPTIVE_WEIGHTS_ENABLED=0,
     ORIGINAL_DB=":memory:", random/numpy seeded). Must happen BEFORE
     anything in ``original.*`` is imported — see reproducibility.py.

  2. Calls the dataset adapter (``raid.py`` / ``pan_av.py`` / ``m4.py``)
     to materialise a corpus directory + manifest.json from the cached
     public dataset.

  3. Runs ``validation.calibration.run_calibration`` against that corpus.
     This is the **same** call the existing 808-essay calibration uses
     — only the corpus differs.

  4. Computes the richer metrics (Brier + calibration curve + F1 at each
     action threshold) via ``validation.benchmark.metrics``.

  5. Optionally runs per-tier ablation (--include-ablation; expensive,
     adds ~18× the calibration cost).

  6. Slices the results by ai_provider + word_count_bucket via
     ``validation.benchmark.bias_slicer``.

  7. Writes the report family (report.json / report.md / roc_curve.svg /
     calibration_curve.svg / ablation.csv / bias.csv) under
     ``validation/benchmarks/<YYYY-MM-DD>/<dataset_label>/``.
"""

from __future__ import annotations

# Lock the environment FIRST — the imports below pull original.* in.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402
ENV_LOCK = lock_environment()

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Optional

from validation.benchmark.bias_slicer import slice_by
from validation.benchmark.metrics import arrays_from_results, metrics_dict
from validation.benchmark.report import paths_for, write_report
from validation.calibration import run_calibration
from validation.wide._adapter import manifest_lookup_for


DATASETS = {"raid", "pan", "m4", "all"}


def _build_corpus_for(
    dataset: str,
    *,
    sample: int,
    pan_year: int,
    sample_pairs: int,
    tmpdir: Path,
) -> tuple[Path, Path, str]:
    """Run the right adapter; return (corpus_dir, manifest_path, label)."""
    corpus_dir = tmpdir / f"corpus_{dataset}"
    manifest_path = tmpdir / f"manifest_{dataset}.json"

    if dataset == "raid":
        from validation.wide.raid import build_corpus
        print(f"[wide] building RAID corpus (sample={sample})…")
        stats = build_corpus(
            corpus_dir=corpus_dir,
            manifest_path=manifest_path,
            sample_size=sample,
        )
        label = "raid"
    elif dataset == "pan":
        from validation.wide.pan_av import build_corpus
        print(f"[wide] building PAN {pan_year} corpus (pairs={sample_pairs})…")
        stats = build_corpus(
            year=pan_year,
            corpus_dir=corpus_dir,
            manifest_path=manifest_path,
            sample_pairs=sample_pairs,
        )
        label = f"pan_av_{pan_year}"
    elif dataset == "m4":
        from validation.wide.m4 import build_corpus
        print(f"[wide] building M4 corpus (sample={sample})…")
        stats = build_corpus(
            corpus_dir=corpus_dir,
            manifest_path=manifest_path,
            sample_size=sample,
        )
        label = "m4_en"
    else:
        raise ValueError(f"unknown dataset {dataset!r}")

    print(f"[wide] {label}: {stats}")
    return corpus_dir, manifest_path, label


def _bench_one(
    dataset: str,
    *,
    sample: int,
    pan_year: int,
    sample_pairs: int,
    max_scoring: Optional[int],
    include_ablation: bool,
    out_base: Path,
) -> Path:
    """Run the full pipeline for one dataset; return the JSON report path."""
    with tempfile.TemporaryDirectory(prefix="wide_") as tmp:
        tmpdir = Path(tmp)
        corpus_dir, manifest_path, label = _build_corpus_for(
            dataset,
            sample=sample,
            pan_year=pan_year,
            sample_pairs=sample_pairs,
            tmpdir=tmpdir,
        )

        print(f"[wide] {label}: running calibration…")
        report = run_calibration(
            corpus_dir=str(corpus_dir),
            manifest_path=str(manifest_path),
            max_scoring=max_scoring,
        )

        # Richer metrics on top of CalibrationReport.
        y_true, y_prob = arrays_from_results(report.results)
        y_dev = [r.deviation_score for r in report.results]
        metrics = metrics_dict(y_true, y_prob, y_dev)

        # Bias slices.
        ml = manifest_lookup_for(manifest_path)
        bias = {
            "ai_provider":  slice_by(report.results, "ai_provider",  manifest_lookup=ml),
            "word_count_bucket": slice_by(report.results, "word_count_bucket"),
            "label":        slice_by(report.results, "label",        manifest_lookup=ml),
        }

        # Optional per-tier ablation (the expensive one).
        ablation = None
        if include_ablation:
            from validation.benchmark.ablation import per_tier_ablation
            print(f"[wide] {label}: running per-tier ablation (this takes a while)…")
            ablation = per_tier_ablation(
                run_calibration,
                {
                    "corpus_dir": str(corpus_dir),
                    "manifest_path": str(manifest_path),
                    "max_scoring": max_scoring,
                },
            )

        paths = paths_for(label, base=str(out_base))
        write_report(
            paths,
            dataset_label=label,
            env_lock=ENV_LOCK,
            calibration_report=report,
            metrics=metrics,
            ablation=ablation,
            bias_slices=bias,
            extra={"dataset_family": "wide", "source": dataset},
        )
        print(f"[wide] {label}: report → {paths.root}")
        print(f"[wide] {label}: AUC={report.auc} brier={metrics['brier']:.4f}")
        return paths.json_path


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", required=True, choices=sorted(DATASETS),
                   help="Which dataset to benchmark. 'all' runs raid + pan + m4.")
    p.add_argument("--sample", type=int, default=800,
                   help="Row cap for RAID + M4 (default: 800).")
    p.add_argument("--pan-year", type=int, default=2021,
                   choices=[2021, 2022, 2023], help="PAN edition to use.")
    p.add_argument("--sample-pairs", type=int, default=400,
                   help="Pair cap for PAN (default: 400).")
    p.add_argument("--max-scoring", type=int, default=None,
                   help="Cap on scoring entries per author. Useful for laptop runs.")
    p.add_argument("--include-ablation", action="store_true",
                   help="Run per-tier ablation. Slow (~18× cost).")
    p.add_argument("--out-base", default="validation/benchmarks",
                   help="Output root for report directories.")
    args = p.parse_args()

    targets = (["raid", "pan", "m4"] if args.dataset == "all" else [args.dataset])
    paths = []
    for d in targets:
        try:
            paths.append(_bench_one(
                d,
                sample=args.sample,
                pan_year=args.pan_year,
                sample_pairs=args.sample_pairs,
                max_scoring=args.max_scoring,
                include_ablation=args.include_ablation,
                out_base=Path(args.out_base),
            ))
        except FileNotFoundError as e:
            print(f"[wide] SKIP {d}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[wide] FAIL {d}: {e}", file=sys.stderr)

    if not paths:
        sys.exit(1)


if __name__ == "__main__":
    main()
