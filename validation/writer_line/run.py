"""
validation/writer_line/run.py: G-WRITERLINE calibration report.

  python -m validation.writer_line.run --records <report.json>... --seed 20261116 --out <json>

Splits the records author-disjoint, selects writer z cut-offs on the
derivation split only, and reports hold-out rates for ``gate`` and
``writer_line`` overall and per corpus, the fallback count, the writers whose
escalate line nothing reaches, and the G-WRITERLINE verdict.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from validation.rebind.harness import split_by_author
from validation.writer_line.harness import (
    load_writer_records,
    rates,
    select_z_thresholds,
    writers_escalate_unreachable,
)

_MODES = ("gate", "writer_line")


def _num(x: float):
    return x if math.isfinite(x) else ("inf" if x > 0 else "-inf")


def build_report(record_paths: list[Path], seed: int) -> dict:
    from validation.calibration_gate import evaluate_g_writerline

    records = [r for p in record_paths for r in load_writer_records(p)]
    derivation, holdout = split_by_author(records, seed=seed)
    thresholds = select_z_thresholds(derivation)
    result = evaluate_g_writerline(holdout, thresholds)
    corpora = sorted({r.corpus for r in records})
    return {
        "seed": seed,
        "records": [str(p) for p in record_paths],
        "n_derivation": len(derivation),
        "n_holdout": len(holdout),
        "thresholds": {k: [_num(lo), _num(hi)] for k, (lo, hi) in thresholds.items()},
        "rates": {m: rates(holdout, m, thresholds) for m in _MODES},
        "per_corpus": {
            c: {m: rates([r for r in holdout if r.corpus == c], m, thresholds) for m in _MODES}
            for c in corpora
        },
        "writers_escalate_unreachable": {
            c: writers_escalate_unreachable([r for r in holdout if r.corpus == c], thresholds)
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
    print(f"G-WRITERLINE [{report['verdict']}] {report['current_value']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
