"""
measure_lift_seminary.py — bigger-N confirmation of the +4.55 pp lift.

The public-authors lift measurement (measure_lift.py) reported +4.55 pp
top-1 attribution on 22 essays truncated to 500 words. N=22 is small
enough that "one essay flipped" moves the number a full 4.5 percentage
points, so a tighter test is called for.

This script runs the same before/after comparison on the seminary
calibration corpus (validation/corpus/, 807 entries, 737 non-baseline
essays). The metric shape is different — the seminary corpus is
labelled authentic/ghostwritten/ai_generated, not "which author" — so
we report AUC + Brier + per-threshold F1 instead of top-1 attribution.

  1. Materialise a truncated corpus at /tmp/seminary_500w/ where every
     SCORED essay is truncated to --n-tokens words. Baselines are
     copied verbatim — a real instructor still has full baseline
     samples; only the submission is short.
  2. Run ``run_calibration`` twice against that truncated corpus:
     once with LENGTH_ADAPTIVE_WEIGHTS=0, once with =1.
  3. Report the AUC + Brier delta.

At N≈737 scored essays a real lift should be easy to see; noise-only
lifts should shrink toward 0.
"""

from __future__ import annotations

# Lock env BEFORE any original.* import; the flag is flipped per-run.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402
ENV_LOCK = lock_environment()

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict


_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent


def _truncate(text: str, n_words: int) -> str:
    words = text.split()
    return " ".join(words[:n_words])


def build_truncated_corpus(
    src_corpus: Path,
    src_manifest: Path,
    dst_root: Path,
    *,
    n_tokens: int,
) -> tuple[Path, Path]:
    """
    Copy ``src_corpus`` into ``dst_root/corpus/`` with each SCORING
    entry's text truncated to ``n_tokens`` words. Baselines are copied
    verbatim so the author profile keeps its fidelity.

    Returns (new_corpus_dir, new_manifest_path).
    """
    if dst_root.exists():
        shutil.rmtree(dst_root)
    dst_corpus = dst_root / "corpus"
    dst_corpus.mkdir(parents=True)
    dst_manifest = dst_root / "manifest.json"

    manifest = json.loads(src_manifest.read_text())
    for entry in manifest["entries"]:
        src = src_corpus / entry["filename"]
        dst = dst_corpus / entry["filename"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
        if not entry.get("is_baseline"):
            text = _truncate(text, n_tokens)
        dst.write_text(text, encoding="utf-8")

    dst_manifest.write_text(json.dumps(manifest, indent=2))
    return dst_corpus, dst_manifest


def run_pair(corpus_dir: Path, manifest_path: Path) -> Dict[str, dict]:
    """
    Run ``run_calibration`` twice on the same corpus: flag off, flag on.
    Returns {"off": summary_dict, "on": summary_dict}.
    """
    from validation.calibration import run_calibration
    from validation.benchmark.metrics import arrays_from_results, brier_score

    out: Dict[str, dict] = {}
    for mode in ("off", "on"):
        os.environ["LENGTH_ADAPTIVE_WEIGHTS"] = "1" if mode == "on" else "0"
        print(f"\n[lift-seminary] running calibration with flag {mode.upper()}…",
              file=sys.stderr, flush=True)
        report = run_calibration(
            corpus_dir=str(corpus_dir),
            manifest_path=str(manifest_path),
        )
        y_true, y_prob = arrays_from_results(report.results)
        out[mode] = {
            "auc": report.auc,
            "brier": round(brier_score(y_true, y_prob), 4),
            "n_scored": report.total_essays_scored,
            "per_label": report.per_label_stats,
            "threshold_metrics": {
                name: {
                    "threshold": m.threshold,
                    "tp": m.true_positives,
                    "fp": m.false_positives,
                    "tn": m.true_negatives,
                    "fn": m.false_negatives,
                    "accuracy": round(m.accuracy, 4),
                    "precision": round(m.precision, 4),
                }
                for name, m in report.threshold_metrics.items()
            },
        }
        print(f"[lift-seminary]  {mode.upper()}: AUC={out[mode]['auc']:.4f} "
              f"Brier={out[mode]['brier']:.4f} n={out[mode]['n_scored']}",
              file=sys.stderr, flush=True)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n-tokens", type=int, default=500,
                   help="Truncate scoring essays to this many words. Default 500.")
    p.add_argument("--tmp-dir", type=Path, default=Path("/tmp/seminary_500w"),
                   help="Where to materialise the truncated corpus.")
    p.add_argument("--out", type=Path,
                   default=_HERE / "lift_seminary_2026-06-30.json",
                   help="Output JSON path for the summary.")
    args = p.parse_args()

    src_corpus = _ROOT / "validation" / "corpus"
    src_manifest = _ROOT / "validation" / "manifest.json"

    print(f"[lift-seminary] building truncated corpus @ {args.n_tokens} words → {args.tmp_dir}",
          file=sys.stderr)
    dst_corpus, dst_manifest = build_truncated_corpus(
        src_corpus, src_manifest, args.tmp_dir, n_tokens=args.n_tokens,
    )

    pair = run_pair(dst_corpus, dst_manifest)

    delta_auc = round(pair["on"]["auc"] - pair["off"]["auc"], 4)
    delta_brier = round(pair["on"]["brier"] - pair["off"]["brier"], 4)

    summary = {
        "n_tokens_truncated_to": args.n_tokens,
        "off": pair["off"],
        "on": pair["on"],
        "delta_auc": delta_auc,
        "delta_brier": delta_brier,
        "env": ENV_LOCK.__dict__,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))

    print()
    print(f"┌─────────────────────────────────────────────────────────────┐")
    print(f"│  seminary corpus, scored essays truncated to {args.n_tokens} words         │")
    print(f"│  n scored: {pair['off']['n_scored']:<6}                                          │")
    print(f"│  flag OFF →  AUC={pair['off']['auc']:.4f}  Brier={pair['off']['brier']:.4f}          │")
    print(f"│  flag ON  →  AUC={pair['on']['auc']:.4f}  Brier={pair['on']['brier']:.4f}          │")
    print(f"│  Δ AUC   :  {delta_auc:+.4f}                                    │")
    print(f"│  Δ Brier :  {delta_brier:+.4f}                                    │")
    print(f"│  Report:    {args.out}")
    print(f"└─────────────────────────────────────────────────────────────┘")
    return 0


if __name__ == "__main__":
    sys.exit(main())
