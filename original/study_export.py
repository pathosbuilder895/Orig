"""Stable, privacy-limited CSV contract for Original style evaluations."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json

EXPORT_COLUMNS = (
    "exam_id",
    "submission_id",
    "student_hash",
    "study_label",
    "imitated_student_hash",
    "word_count",
    "style_score",
    "style_features_json",
    "engine_version",
    "threshold_version",
)


def validate_salt(salt: str | None) -> bytes:
    value = (salt or "").encode("utf-8")
    if len(value) < 16:
        raise ValueError("study export salt must be at least 16 UTF-8 bytes")
    return value


def pseudonymize_student_id(student_id: str | None, salt: bytes) -> str:
    if not student_id:
        return ""
    digest = hmac.new(salt, student_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


def export_csv(rows: list[dict], salt: str | bytes) -> str:
    key = validate_salt(salt.decode("utf-8") if isinstance(salt, bytes) else salt)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        features = row.get("style_features") or {}
        writer.writerow(
            {
                "exam_id": row.get("exam_id") or "",
                "submission_id": row.get("id") or "",
                "student_hash": pseudonymize_student_id(row.get("student_id"), key),
                "study_label": row.get("study_label") or "",
                "imitated_student_hash": pseudonymize_student_id(
                    row.get("imitated_student_id"), key
                ),
                "word_count": row.get("word_count") or 0,
                "style_score": "" if row.get("style_score") is None else row["style_score"],
                "style_features_json": json.dumps(
                    features, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
                "engine_version": row.get("style_engine_version") or "",
                "threshold_version": row.get("style_threshold_version") or "",
            }
        )
    return output.getvalue()
