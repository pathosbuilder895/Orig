#!/usr/bin/env python3
"""
calibrate_bounds.py — Derive empirical NORM_BOUNDS from a labelled text corpus.

Usage:
    cd original_backend
    python scripts/calibrate_bounds.py path/to/corpus/
    python scripts/calibrate_bounds.py path/to/corpus/ --percentile 5 95
    python scripts/calibrate_bounds.py path/to/corpus/ --suggest-bounds
    python scripts/calibrate_bounds.py path/to/corpus/ --suggest-bounds --margin 0.10

Corpus format:
    corpus/
      essay_001.txt
      essay_002.txt
      ...

All .txt files are loaded recursively.  Files with fewer than 50 words are skipped.
Files whose extraction fails entirely are counted as errors and skipped.

Output (stdout):
  1. A formatted percentile table per feature (all 60 base features)
  2. (--suggest-bounds) A Python snippet ready to paste into constants.py

Recommended corpus composition for Original's theological-essay domain:
  • ≥ 20 authenticated student essays (proctored or verified)
  • ≥ 10 published academic-theology texts (books, journal articles)
  • ≥ 10 AI-generated essays (GPT-4, Claude, etc.) for AI-marker calibration
  • ≥ 10 Non-Native English (NNE) essays for diversity
  Total: ≥ 50 texts, each 800–5 000 words.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Path setup — allow running from the repo root or from original_backend/
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent          # scripts/
_BACKEND = _HERE.parent                          # original_backend/
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

try:
    from original.features.tier1 import TextDoc, extract_tier1
    from original.features.tier2 import extract_tier2
    from original.features.tier3 import extract_tier3
    from original.features.tier4 import extract_tier4
    from original.features.tier5 import extract_tier5
    from original.features.tier6 import extract_tier6
    from original.features.tier7 import extract_tier7
    from original.constants import (
        BASE_FEATURE_CODES, FEATURE_TIER, FEATURE_NAMES, NORM_BOUNDS,
    )
except ImportError as exc:
    print(
        f"Import error: {exc}\n"
        "Run this script from original_backend/ or from the repo root.\n"
        "  cd original_backend && python scripts/calibrate_bounds.py corpus/",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_raw(text: str) -> Dict[str, float]:
    """Return a dict of raw (un-normalised) feature values for *text*."""
    doc = TextDoc(text)
    raw: Dict[str, float] = {}
    raw.update(extract_tier1(doc))
    raw.update(extract_tier2(doc))
    raw.update(extract_tier3(doc))
    raw.update(extract_tier4(doc))
    raw.update(extract_tier5(doc))
    raw.update(extract_tier6(doc))
    raw.update(extract_tier7(doc))
    return raw


def load_corpus(corpus_dir: str) -> List[Tuple[Path, str]]:
    """Yield (path, text) tuples from *.txt files under *corpus_dir*."""
    root = Path(corpus_dir)
    if not root.exists():
        print(f"Error: corpus directory '{corpus_dir}' not found.", file=sys.stderr)
        sys.exit(1)

    paths = sorted(root.rglob("*.txt"))
    if not paths:
        print(f"Warning: no .txt files found in '{corpus_dir}'.", file=sys.stderr)

    result: List[Tuple[Path, str]] = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="replace").strip()
            words = text.split()
            if len(words) >= 50:
                result.append((p, text))
                print(f"  ✓ {p.relative_to(root)}  ({len(words):,} words)")
            else:
                print(f"  ⚠ {p.relative_to(root)}  skipped — {len(words)} words < 50")
        except Exception as exc:
            print(f"  ✗ {p.relative_to(root)}  read error: {exc}")
    return result


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

_TIER_LABELS: Dict[int, str] = {
    1: "Tier 1 — Surface Stylometry",
    2: "Tier 2 — Discourse Structure",
    3: "Tier 3 — Rhetorical & Register",
    4: "Tier 4 — Character & Punctuation",
    5: "Tier 5 — POS & Shallow Syntax",
    6: "Tier 6 — Idiosyncratic Patterns",
    7: "Tier 7 — AI Detection Markers",
}


def compute_stats(
    data: Dict[str, List[float]],
    p_lo: int,
    p_hi: int,
) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for code, vals in data.items():
        if not vals:
            continue
        arr = np.array(vals, dtype=float)
        out[code] = {
            "n":   float(len(arr)),
            "min": float(arr.min()),
            "p01": float(np.percentile(arr, 1)),
            "p05": float(np.percentile(arr, p_lo)),
            "p25": float(np.percentile(arr, 25)),
            "med": float(np.median(arr)),
            "p75": float(np.percentile(arr, 75)),
            "p95": float(np.percentile(arr, p_hi)),
            "p99": float(np.percentile(arr, 99)),
            "max": float(arr.max()),
        }
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_W = 110  # line width


def _section(title: str) -> None:
    print()
    print("=" * _W)
    print(f"  {title}")
    print("=" * _W)


def print_report(
    stats: Dict[str, Dict[str, float]],
    p_lo: int,
    p_hi: int,
) -> None:
    _section(
        f"ORIGINAL — NORM_BOUNDS CALIBRATION REPORT  "
        f"(P{p_lo:02d} = suggested lo,  P{p_hi:02d} = suggested hi)"
    )

    col = f"  {'Feature':<36} {'N':>4}  {'min':>8}  "
    col += f"{'P05':>8}  {'P25':>8}  {'med':>8}  {'P75':>8}  "
    col += f"{'P95':>8}  {'max':>8}  {'curLo':>8}  {'curHi':>8}  Notes"

    current_tier: int | None = None
    flagged_total = 0

    for code in BASE_FEATURE_CODES:
        if code not in stats:
            continue

        tier = FEATURE_TIER.get(code, 0)
        if tier != current_tier:
            current_tier = tier
            print()
            print(f"  {_TIER_LABELS.get(tier, f'Tier {tier}')}")
            print("  " + "─" * (_W - 2))
            print(col)
            print("  " + "─" * (_W - 2))

        s = stats[code]
        cur_lo, cur_hi = NORM_BOUNDS.get(code, (0.0, 1.0))

        notes: List[str] = []
        if s["p05"] < cur_lo:
            notes.append("LO_TOO_TIGHT")
        if s["p95"] > cur_hi:
            notes.append("HI_TOO_TIGHT")
        if cur_hi > 0 and (s["p95"] / cur_hi) < 0.40:
            notes.append("HI_TOO_LOOSE")
        if cur_lo > 0 and s["p05"] > cur_lo * 3:
            notes.append("LO_TOO_LOOSE")
        if s["n"] < 5:
            notes.append("LOW_N")

        icon = "⚠" if notes else "✓"
        if notes:
            flagged_total += 1

        name = FEATURE_NAMES.get(code, code)[:35]
        note_str = " | ".join(notes) if notes else "OK"

        print(
            f"  {icon} {name:<35} {int(s['n']):>4}  "
            f"{s['min']:>8.3f}  {s['p05']:>8.3f}  {s['p25']:>8.3f}  "
            f"{s['med']:>8.3f}  {s['p75']:>8.3f}  {s['p95']:>8.3f}  "
            f"{s['max']:>8.3f}  {cur_lo:>8.3f}  {cur_hi:>8.3f}  {note_str}"
        )

    print()
    n_features = len([c for c in BASE_FEATURE_CODES if c in stats])
    print(f"  Summary: {n_features} features analysed, {flagged_total} need attention.")


def print_suggested_bounds(
    stats: Dict[str, Dict[str, float]],
    p_lo: int,
    p_hi: int,
    margin: float,
) -> None:
    _section(
        f"SUGGESTED NORM_BOUNDS  "
        f"(lo = P{p_lo:02d} × (1 − {margin:.0%}),  hi = P{p_hi:02d} × (1 + {margin:.0%}))"
    )
    print()
    print("# ── Paste this block into original/constants.py → NORM_BOUNDS ───────────────")
    print("NORM_BOUNDS: Dict[str, Tuple[float, float]] = {")

    current_tier: int | None = None
    for code in BASE_FEATURE_CODES:
        if code not in stats:
            continue

        tier = FEATURE_TIER.get(code, 0)
        if tier != current_tier:
            current_tier = tier
            print(f"    # {_TIER_LABELS.get(tier, f'Tier {tier}')}")

        s = stats[code]
        raw_lo = s["p05"]
        raw_hi = s["p95"]
        sug_lo = max(0.0, raw_lo * (1.0 - margin))
        sug_hi = raw_hi * (1.0 + margin)

        # Determine sensible rounding precision
        def _round(v: float) -> str:
            if v == 0.0:
                return "0.0"
            mag = abs(v)
            if mag >= 10:
                return f"{v:.1f}"
            if mag >= 1:
                return f"{v:.2f}"
            return f"{v:.3f}"

        name_str = f'# P{p_lo:02d}={raw_lo:.4f}, P{p_hi:02d}={raw_hi:.4f}  ← {FEATURE_NAMES.get(code, code)}'
        pad = max(1, 44 - len(code))
        print(f'    "{code}":{" " * pad}({_round(sug_lo)}, {_round(sug_hi)}),  {name_str}')

    print("}")
    print()
    print("# NOTE: Review all ⚠ entries in the calibration report before deploying.")
    print("# Re-run with --margin 0.10 for a 10% safety buffer on small corpora.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="calibrate_bounds",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "corpus_dir",
        help="Directory containing .txt corpus files (searched recursively)",
    )
    parser.add_argument(
        "--percentile",
        nargs=2, type=int, default=[5, 95], metavar=("P_LO", "P_HI"),
        help="Lower and upper percentile bounds (default: 5 95)",
    )
    parser.add_argument(
        "--suggest-bounds",
        action="store_true",
        help="Print a Python snippet with suggested NORM_BOUNDS values",
    )
    parser.add_argument(
        "--margin",
        type=float, default=0.05,
        help="Safety margin applied to suggested bounds (default: 0.05 = 5%%)",
    )
    args = parser.parse_args()
    p_lo, p_hi = args.percentile

    # ── Load corpus ──────────────────────────────────────────────────────────
    print(f"\nLoading corpus from: {args.corpus_dir}")
    corpus = load_corpus(args.corpus_dir)
    if not corpus:
        print("\nNo usable texts found. Exiting.", file=sys.stderr)
        sys.exit(1)
    print(f"\n  {len(corpus)} texts loaded.")

    # ── Extract features ─────────────────────────────────────────────────────
    print(f"\nExtracting raw features from {len(corpus)} texts...")
    data: Dict[str, List[float]] = {code: [] for code in BASE_FEATURE_CODES}
    errors = 0

    for i, (path, text) in enumerate(corpus, 1):
        try:
            raw = extract_raw(text)
            for code in BASE_FEATURE_CODES:
                val = raw.get(code)
                if val is not None and np.isfinite(val):
                    data[code].append(float(val))
        except Exception as exc:
            print(f"  ✗ [{i}/{len(corpus)}] extraction error in {path.name}: {exc}")
            errors += 1

    print(f"  Extraction complete — {len(corpus) - errors} OK, {errors} errors.")

    # ── Compute & report ─────────────────────────────────────────────────────
    stats = compute_stats(data, p_lo=p_lo, p_hi=p_hi)
    print_report(stats, p_lo=p_lo, p_hi=p_hi)

    if args.suggest_bounds:
        print_suggested_bounds(stats, p_lo=p_lo, p_hi=p_hi, margin=args.margin)
    else:
        print()
        print("  Tip: add --suggest-bounds to generate a paste-ready NORM_BOUNDS block.")
        print()


if __name__ == "__main__":
    main()
