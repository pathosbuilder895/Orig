#!/usr/bin/env python3
"""Export the fixed study CSV contract for one or more Collections exams."""

from __future__ import annotations

import argparse
import os
import sys

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from original.repository import get_repository  # noqa: E402
from original.study_export import export_csv  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--exam", action="append", required=True, help="Exam id; repeat to combine exams"
    )
    parser.add_argument(
        "--salt",
        default=os.environ.get("STUDY_EXPORT_SALT", ""),
        help="Pseudonymization salt (or STUDY_EXPORT_SALT environment variable)",
    )
    parser.add_argument(
        "--study-id",
        default=os.environ.get("STUDY_ID", ""),
        help="Study identifier (or STUDY_ID environment variable)",
    )
    parser.add_argument(
        "--include-unscored",
        action="store_true",
        help="Include labeled rows without a stored score for readiness debugging",
    )
    args = parser.parse_args(argv)
    repo = get_repository()
    exam_ids = list(dict.fromkeys(args.exam))
    rows = []
    for exam_id in exam_ids:
        exam = repo.get_bluebook_exam(exam_id)
        if exam is None:
            parser.error(f"exam not found: {exam_id}")
        rows.extend(repo.list_bluebook_study_submissions([exam_id], exam.get("tenant_id")))
    try:
        csv_text = export_csv(
            rows, args.salt, args.study_id, include_unscored=args.include_unscored
        )
    except ValueError as exc:
        parser.error(str(exc))
    sys.stdout.write(csv_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
