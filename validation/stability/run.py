"""
validation/stability/run.py — length-stability study orchestrator.

  python -m validation.stability.run
  python -m validation.stability.run --lengths 250,500,1000,2000,5000
  python -m validation.stability.run --min-words 40000 --report-dir /tmp/x

For each public-author full-work fixture
(``validation/public_authors/corpus/<author>/_full_work_cache.txt``):

  1. Drop authors below ``--min-words`` (default 40,000 — admits Boethius
     at 42k; adjust upward if more authors are added).
  2. For each window length L, slice into non-overlapping L-word windows
     and compute ``feature_vector(window)`` per window.
  3. Compute Fisher's discriminant ratio per (feature, length) bucket.
  4. Write the report family to
     ``validation/stability/<YYYY-MM-DD>/`` —
     ``report.json``, ``report.md``, ``length_stability.csv``,
     ``per_tier_summary.csv``.

The math is unchanged. ``feature_vector`` only reads — no scoring state
is written. ``lock_environment()`` is called BEFORE any ``original.*``
import so the keyed random unitary in quantum/scoring.py is deterministic.
"""

from __future__ import annotations

# Lock the environment BEFORE importing anything that pulls original.*.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402
ENV_LOCK = lock_environment()

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from validation.stability.report import paths_for, write_report
from validation.stability.stability import per_feature_stability


_HERE = Path(__file__).resolve().parent
_CORPUS_DIR = _HERE.parent / "public_authors" / "corpus"

DEFAULT_LENGTHS = (250, 500, 1000, 2000, 5000)
DEFAULT_MIN_WORDS = 40_000           # admits Boethius at 42k
DEFAULT_MAX_WINDOWS = 12              # ~650ms per feature_vector → finishes in ~7 min


log = logging.getLogger("stability")


def load_corpus(
    corpus_dir: Path = _CORPUS_DIR,
    *,
    min_words: int = DEFAULT_MIN_WORDS,
    only: Optional[set] = None,
) -> Dict[str, str]:
    """
    Walk the public-authors corpus and return ``{author_id: full_text}``
    for every author with a ``_full_work_cache.txt`` at or above ``min_words``.
    Drops the rest with a printed reason.
    """
    if not corpus_dir.exists():
        raise FileNotFoundError(
            f"No public-authors corpus at {corpus_dir}. "
            f"Run `python -m validation.public_authors.build_corpus` first."
        )

    out: Dict[str, str] = {}
    skipped: List[str] = []
    for author_dir in sorted(corpus_dir.iterdir()):
        if not author_dir.is_dir():
            continue
        cache = author_dir / "_full_work_cache.txt"
        if not cache.exists():
            skipped.append(f"{author_dir.name} (no _full_work_cache.txt)")
            continue
        if only is not None and author_dir.name not in only:
            continue
        text = cache.read_text(encoding="utf-8")
        wc = len(text.split())
        if wc < min_words:
            skipped.append(f"{author_dir.name} ({wc:,} words < {min_words:,})")
            continue
        out[author_dir.name] = text

    if skipped:
        print(f"[stability] skipped: {skipped}", file=sys.stderr)
    print(f"[stability] eligible authors: {sorted(out.keys())}", file=sys.stderr)
    return out


def run(
    *,
    lengths: Sequence[int] = DEFAULT_LENGTHS,
    min_words: int = DEFAULT_MIN_WORDS,
    max_windows_per_author: int = DEFAULT_MAX_WINDOWS,
    only: Optional[set] = None,
    report_base: str = "validation/stability",
    corpus_dir: Path = _CORPUS_DIR,
) -> dict:
    """End-to-end study. Returns a small summary dict."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")

    author_texts = load_corpus(corpus_dir, min_words=min_words, only=only)
    if len(author_texts) < 2:
        raise RuntimeError(
            f"Need ≥2 eligible authors for between-author variance; "
            f"got {len(author_texts)}. Lower --min-words or extend the corpus."
        )

    report = per_feature_stability(
        author_texts,
        lengths=tuple(lengths),
        max_windows_per_author=max_windows_per_author,
    )
    paths = paths_for(base=report_base)
    write_report(paths, report=report, env_lock=ENV_LOCK)

    # ── Compact CLI summary so a user can sanity-check at a glance. ──
    measured = [
        (report.feature_codes[idx],
         report.fisher_matrix[idx][report.lengths.index(500)] if 500 in report.lengths else float("nan"),
         report.fisher_matrix[idx][report.lengths.index(5000)] if 5000 in report.lengths else float("nan"))
        for idx in range(len(report.feature_codes))
    ]
    import math
    eligible_ratios = []
    for code, f500, f5000 in measured:
        if math.isnan(f500) or math.isnan(f5000) or f5000 <= 0:
            continue
        eligible_ratios.append((code, f500 / f5000))
    eligible_ratios.sort(key=lambda kv: -kv[1])
    top10 = eligible_ratios[:10]
    bot10 = eligible_ratios[-10:]

    print("", file=sys.stderr)
    print(f"[stability] report → {paths.root}", file=sys.stderr)
    print(f"[stability] {len(author_texts)} authors, lengths={list(report.lengths)}",
          file=sys.stderr)
    print(f"[stability] top 10 length-robust features (ratio F(500)/F(5000)):",
          file=sys.stderr)
    for code, r in top10:
        print(f"    {r:6.3f}  {code}", file=sys.stderr)
    print(f"[stability] bottom 10 length-fragile features:", file=sys.stderr)
    for code, r in bot10:
        print(f"    {r:6.3f}  {code}", file=sys.stderr)

    return {
        "report_dir": str(paths.root),
        "n_authors": len(author_texts),
        "lengths": list(report.lengths),
        "top10_robust": top10,
        "bottom10_fragile": bot10,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lengths", default=",".join(str(L) for L in DEFAULT_LENGTHS),
                    help="Comma-separated window sizes (words). "
                         f"Default: {','.join(str(L) for L in DEFAULT_LENGTHS)}")
    ap.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS,
                    help=f"Drop authors below this word count. "
                         f"Default {DEFAULT_MIN_WORDS}.")
    ap.add_argument("--max-windows-per-author", type=int, default=DEFAULT_MAX_WINDOWS,
                    help=f"Cap windows per (author, length). Trade-off: more "
                         f"windows tighten the within-author variance estimate "
                         f"at quadratic cost. Default {DEFAULT_MAX_WINDOWS}.")
    ap.add_argument("--only", default=None,
                    help="Comma-separated author_ids to include (others dropped).")
    ap.add_argument("--report-dir", default="validation/stability",
                    help="Base dir for the dated report folder. "
                         "Default: validation/stability")
    args = ap.parse_args(argv)

    lengths = [int(x) for x in args.lengths.split(",") if x.strip()]
    only = set(a.strip() for a in args.only.split(",")) if args.only else None
    try:
        run(lengths=lengths, min_words=args.min_words,
            max_windows_per_author=args.max_windows_per_author,
            only=only, report_base=args.report_dir)
    except Exception as e:
        print(f"[stability] FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
