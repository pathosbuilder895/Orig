#!/usr/bin/env python
"""
scripts/branch_coverage_report.py — Per-cluster / per-file BRANCH coverage report.

CI's coverage gate (--cov-fail-under=78) measures line coverage; this tool
reads a coverage.py JSON report produced with --cov-branch and reports the
branch (conditional) side, which is what the 2026-08 branch-coverage effort
(docs/superpowers/plans/2026-08-17-branch-coverage-*.md) ratchets on.

Produce the input (full suite, local Postgres up so the persistence layer is
measured — see scripts/local_postgres.sh):

    DATABASE_URL=$(bash scripts/local_postgres.sh url) \
      .venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q \
      --cov=original --cov-branch --cov-report=json:coverage.json

Then:

    .venv/bin/python scripts/branch_coverage_report.py coverage.json
    .venv/bin/python scripts/branch_coverage_report.py coverage.json --cluster persistence
    .venv/bin/python scripts/branch_coverage_report.py coverage.json --top 20
"""

from __future__ import annotations

import argparse
import json
import sys

# Cluster boundaries mirror the part decomposition of the branch-coverage
# plan files (docs/superpowers/plans/2026-08-17-branch-coverage-index.md).
CLUSTERS: dict[str, tuple[str, ...]] = {
    "persistence": (
        "original/store.py",
        "original/repository.py",
        "original/postgres_repository.py",
        "original/db/",
        "original/migrate",
    ),
    "quantum": ("original/quantum/",),
    "context": ("original/context/",),
    "features": ("original/features/",),
    "api": (
        "original/api.py",
        "original/routers/",
        "original/schemas.py",
        "original/lti.py",
        "original/run",
    ),
    "integrations": (
        "original/fusion/",
        "original/canvas/",
        "original/bbook_client.py",
        "original/lab/",
        "original/ai_likelihood",
        "original/style_authorship",
    ),
}


def cluster_of(path: str) -> str:
    for name, prefixes in CLUSTERS.items():
        if any(path.startswith(p) for p in prefixes):
            return name
    return "other"


def summarize(report: dict) -> tuple[list[dict], dict[str, dict]]:
    """Return (per-file rows, per-cluster rollups) from a coverage JSON dict."""
    rows = []
    clusters: dict[str, dict] = {}
    for path, data in report.get("files", {}).items():
        s = data.get("summary", {})
        num = s.get("num_branches", 0)
        covered = s.get("covered_branches", 0)
        missing = s.get("missing_branches", num - covered)
        row = {
            "path": path,
            "cluster": cluster_of(path),
            "num_branches": num,
            "covered_branches": covered,
            "missing_branches": missing,
            "branch_pct": (100.0 * covered / num) if num else 100.0,
            "line_pct": s.get("percent_covered", 0.0),
        }
        rows.append(row)
        c = clusters.setdefault(
            row["cluster"], {"num_branches": 0, "covered_branches": 0, "missing_branches": 0, "files": 0}
        )
        c["num_branches"] += num
        c["covered_branches"] += covered
        c["missing_branches"] += missing
        c["files"] += 1
    for c in clusters.values():
        c["branch_pct"] = (
            100.0 * c["covered_branches"] / c["num_branches"] if c["num_branches"] else 100.0
        )
    rows.sort(key=lambda r: (-r["missing_branches"], r["path"]))
    return rows, clusters


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json_path", help="coverage.py JSON report produced with --cov-branch")
    ap.add_argument("--cluster", help="only show files in this cluster")
    ap.add_argument("--top", type=int, default=0, help="only show the N files with most missing branches")
    args = ap.parse_args(argv)

    with open(args.json_path) as f:
        report = json.load(f)
    if not report.get("meta", {}).get("branch_coverage", True):
        print("warning: report was generated WITHOUT --cov-branch; branch numbers are empty", file=sys.stderr)

    rows, clusters = summarize(report)

    total_num = sum(c["num_branches"] for c in clusters.values())
    total_cov = sum(c["covered_branches"] for c in clusters.values())
    print(f"TOTAL branch coverage: {100.0 * total_cov / total_num if total_num else 100.0:.2f}% "
          f"({total_cov}/{total_num}; {total_num - total_cov} missing)\n")

    print(f"{'cluster':<14} {'branch%':>8} {'covered':>8} {'total':>7} {'missing':>8} {'files':>6}")
    for name in sorted(clusters, key=lambda n: clusters[n]["branch_pct"]):
        c = clusters[name]
        print(f"{name:<14} {c['branch_pct']:>7.2f}% {c['covered_branches']:>8} "
              f"{c['num_branches']:>7} {c['missing_branches']:>8} {c['files']:>6}")

    shown = [r for r in rows if not args.cluster or r["cluster"] == args.cluster]
    if args.top:
        shown = shown[: args.top]
    print(f"\n{'file':<52} {'branch%':>8} {'missing':>8} {'line%':>7}")
    for r in shown:
        if r["num_branches"] == 0 and not args.cluster:
            continue  # pure-declaration files add noise to the ranking
        print(f"{r['path']:<52} {r['branch_pct']:>7.2f}% {r['missing_branches']:>8} {r['line_pct']:>6.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
