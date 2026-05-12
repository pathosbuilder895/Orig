"""
validation/build_similarity_matrix.py — Build cross-author similarity matrix.

Reads calibration_report.json and computes mean deviation_score for every
(baseline_author, scored_author) pair using the 'notes' field in each result
to identify which author wrote the scored text.

Output: validation/similarity_matrix.json
  {
    "authors": [...],          // ordered list of author display names
    "author_ids": [...],       // matching author IDs
    "matrix": [[...], ...],    // NxN mean deviation; row=baseline, col=scored_author
    "min": float,
    "max": float,
    "interpretation": "lower deviation = more stylistically similar"
  }

Usage:
    python -m validation.build_similarity_matrix [--report PATH] [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent

AUTHOR_DISPLAY = {
    "hamilton":             "Hamilton",
    "madison":              "Madison",
    "jay":                  "Jay",
    "disputed_vs_madison":  "Disputed→Madison",
    "paine":                "Paine",
    "burke":                "Burke",
    "lincoln":              "Lincoln",
    "douglass":             "Douglass",
}

# Preferred display order
AUTHOR_ORDER = ["hamilton", "madison", "jay", "paine", "burke", "lincoln", "douglass"]


def extract_scored_author(result: dict) -> Optional[str]:
    """
    Determine which author actually wrote the scored text.
    For authentic entries: scored_author == author_id (baseline author).
    For ghostwritten entries: extract from filename.

    Filename conventions:
      - fed_hamilton_17.txt  → hamilton wrote the text (Federalist)
      - fed_madison_43.txt   → madison wrote the text (Federalist)
      - fed_jay_01.txt       → jay wrote the text (Federalist)
      - paine_003.txt        → paine wrote the text (extended corpus)
      - burke_007.txt        → burke wrote the text (extended corpus)
    """
    if result["label"] == "authentic":
        return result["author_id"]

    filename = result.get("filename", "")
    parts = filename.split("_")

    # Federalist cross-author: "fed_<author>_<num>.txt"
    if parts[0] == "fed" and len(parts) >= 2:
        candidate = parts[1]  # hamilton, madison, jay, disputed, …
        if candidate in AUTHOR_DISPLAY:
            return candidate

    # Extended corpus: "<author>_<num>.txt"
    prefix = parts[0]
    if prefix in AUTHOR_DISPLAY:
        return prefix

    return None


def build_matrix(
    results: list,
    author_ids: List[str],
) -> List[List[float]]:
    """
    Build NxN matrix where matrix[i][j] = mean deviation when
    author_ids[j]'s texts are scored against author_ids[i]'s baseline.
    """
    n = len(author_ids)
    idx = {aid: i for i, aid in enumerate(author_ids)}

    sums   = defaultdict(float)
    counts = defaultdict(int)

    for r in results:
        baseline_author = r["author_id"]
        scored_author   = extract_scored_author(r)

        if baseline_author not in idx or scored_author not in idx:
            continue

        key = (baseline_author, scored_author)
        sums[key]   += r["deviation_score"]
        counts[key] += 1

    matrix = []
    for row_id in author_ids:
        row = []
        for col_id in author_ids:
            key = (row_id, col_id)
            if counts[key] > 0:
                row.append(round(sums[key] / counts[key], 4))
            else:
                row.append(None)   # no data for this pair
        matrix.append(row)

    return matrix


def main():
    parser = argparse.ArgumentParser(description="Build cross-author similarity matrix")
    parser.add_argument("--report", default=str(ROOT / "validation" / "calibration_report.json"))
    parser.add_argument("--output", default=str(ROOT / "validation" / "similarity_matrix.json"))
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    results = report["individual_results"]

    # Collect all author_ids present in results
    present_ids = set(r["author_id"] for r in results)
    # Order by preferred order, append unknowns alphabetically
    author_ids = [a for a in AUTHOR_ORDER if a in present_ids]
    author_ids += sorted(present_ids - set(author_ids) - {"disputed_vs_madison"})

    display_names = [AUTHOR_DISPLAY.get(a, a) for a in author_ids]

    matrix = build_matrix(results, author_ids)

    # Compute min/max for heat-map scaling (ignoring None and diagonal)
    flat = [
        matrix[i][j]
        for i in range(len(author_ids))
        for j in range(len(author_ids))
        if matrix[i][j] is not None and i != j
    ]
    lo = round(min(flat), 4) if flat else 0.0
    hi = round(max(flat), 4) if flat else 1.0

    output = {
        "authors":         display_names,
        "author_ids":      author_ids,
        "matrix":          matrix,
        "min":             lo,
        "max":             hi,
        "interpretation":  "lower deviation = more stylistically similar to baseline author",
        "note":            "diagonal (same author) excluded from min/max range",
    }

    Path(args.output).write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Similarity matrix saved to {args.output}")

    # Pretty-print
    w = max(len(n) for n in display_names) + 2
    print(f"\n{'':>{w}}", end="")
    for name in display_names:
        print(f"  {name[:8]:>8}", end="")
    print()

    for i, row_name in enumerate(display_names):
        print(f"{row_name:>{w}}", end="")
        for j, val in enumerate(matrix[i]):
            if val is None:
                print(f"  {'—':>8}", end="")
            elif i == j:
                print(f"  {'(self)':>8}", end="")
            else:
                print(f"  {val:>8.3f}", end="")
        print()

    print(f"\nDeviation range (cross-author): {lo:.3f} – {hi:.3f}")
    print("Lower = more similar writing style")


if __name__ == "__main__":
    main()
