#!/usr/bin/env python3
"""Report baseline and label completeness for one or more study exams."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from original.study_readiness import study_readiness  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--exam", action="append", required=True, help="Exam id; repeat for multiple exams"
    )
    args = parser.parse_args(argv)
    try:
        report = study_readiness(args.exam)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
