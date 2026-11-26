"""
validation/rebind/run.py — G-REBIND calibration report.

  python -m validation.rebind.run --records <report.json>... --seed 20261116 --out <json>

Splits the records author-disjoint, selects rebind cut-offs on the
derivation split only, and reports hold-out rates for ``gate`` and
``rebind`` overall and per corpus, plus the G-REBIND verdict.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from validation.rebind.harness import load_records, rates, select_thresholds, split_by_author


def build_report(record_paths: list[Path], seed: int) -> dict:
    from validation.calibration_gate import evaluate_g_rebind

    records = [r for p in record_paths for r in load_records(p)]
    derivation, holdout = split_by_author(records, seed=seed)
    thresholds = select_thresholds(derivation)
    result = evaluate_g_rebind(holdout, thresholds)
    corpora = sorted({r.corpus for r in records})
    return {
        "seed": seed,
        "records": [str(p) for p in record_paths],
        "n_derivation": len(derivation),
        "n_holdout": len(holdout),
        "thresholds": {k: list(v) for k, v in thresholds.items()},
        "rates": {m: rates(holdout, m, thresholds) for m in ("gate", "rebind")},
        "per_corpus": {
            c: {
                m: rates([r for r in holdout if r.corpus == c], m, thresholds)
                for m in ("gate", "rebind")
            }
            for c in corpora
        },
        "verdict": result.verdict,
        "current_value": result.current_value,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--records", nargs="+", required=True, type=Path)
    ap.add_argument("--seed", type=int, default=20261116)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    report = build_report(args.records, args.seed)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"G-REBIND [{report['verdict']}] {report['current_value']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
