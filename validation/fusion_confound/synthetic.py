"""Committed, deterministic reproduction of the known baseline-volume channel."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from validation.fusion_confound.analyze import analyze_rows


def build_rows() -> list[dict]:
    slope = (0.730 - 0.799) / (48 - 3)
    rows = []
    for baseline in range(3, 49):
        references = 8 + baseline % 5
        compression = 0.799 + slope * (baseline - 3) + 0.002 * (references - 11)
        rows.append({"channels": {"compression": compression},
                     "fused_log_odds": 0.12 + 0.65 * compression + 0.001 * references,
                     "baseline_samples": baseline, "reference_profiles": references,
                     "band": "inconclusive"})
    return rows


def report() -> dict:
    rows = build_rows()
    result = analyze_rows(rows)
    result["fixture"] = {"compression_at_3": rows[0]["channels"]["compression"],
                         "compression_at_48": rows[-1]["channels"]["compression"],
                         "source": "deterministic synthetic reproduction, not pilot evidence"}
    result["recommendation"] = (
        "Prefer mean per-baseline-document compression distance, then refit the fusion "
        "artifact and thresholds; validate against real shadow rows before enablement."
    )
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    rendered = json.dumps(report(), indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
