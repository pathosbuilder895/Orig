#!/usr/bin/env python3
"""Rescore every sealed submission for a Collections exam."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from original.repository import get_repository  # noqa: E402
from original.study_scoring import rescore_exam  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exam", required=True, help="Exam id to rescore")
    args = parser.parse_args(argv)
    repo = get_repository()
    try:
        result = rescore_exam(args.exam, repo=repo)
    except ValueError as exc:
        parser.error(str(exc))
    repo.log_audit(
        action="bluebook_study_rescore",
        tenant_id=(repo.get_bluebook_exam(args.exam) or {}).get("tenant_id"),
        actor="cli:study_rescore",
        details=result,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
