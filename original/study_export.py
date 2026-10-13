"""Stable, privacy-limited CSV contract for labeled Collections studies."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io

EXPORT_COLUMNS = (
    "study_id",
    "exam_id",
    "submission_id",
    "writer_key",
    "study_label",
    "claimed_student_key",
    "word_count",
    "authorship_probability",
    "recommended_action",
    "verdict",
    "baseline_count",
    "baseline_words",
    "engine_version",
    "threshold_version",
    "scored_at",
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


def _feature_columns(rows: list[dict]) -> tuple[list[str], dict[str, str]]:
    keys = {str(key) for row in rows for key in (row.get("style_features") or {}).keys()}
    mapping = {key: f"f_{key}" for key in sorted(keys)}
    if len(set(mapping.values())) != len(mapping) or set(mapping.values()) & set(EXPORT_COLUMNS):
        raise ValueError("feature names collide with the study export contract")
    return [mapping[key] for key in sorted(keys)], mapping


def export_csv(
    rows: list[dict],
    salt: str | bytes,
    study_id: str,
    *,
    include_unscored: bool = False,
) -> str:
    key = validate_salt(salt.decode("utf-8") if isinstance(salt, bytes) else salt)
    if not study_id or not study_id.strip():
        raise ValueError("study_id is required")
    selected = [
        row
        for row in rows
        if (row.get("study_label") or "").strip().casefold() in {"natural", "shadow"}
        and (include_unscored or row.get("style_score") is not None)
    ]
    feature_columns, feature_names = _feature_columns(selected)
    columns = (*EXPORT_COLUMNS, *feature_columns)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in selected:
        values = {
            "study_id": study_id.strip(),
            "exam_id": row.get("exam_id") or "",
            "submission_id": row.get("id") or row.get("submission_id") or "",
            "writer_key": pseudonymize_student_id(row.get("student_id"), key),
            "study_label": (row.get("study_label") or "").strip().casefold(),
            "claimed_student_key": pseudonymize_student_id(row.get("imitated_student_id"), key),
            "word_count": row.get("word_count") or 0,
            "authorship_probability": (
                "" if row.get("authorship_probability") is None else row["authorship_probability"]
            ),
            "recommended_action": row.get("recommended_action") or "",
            "verdict": row.get("verdict") or "",
            "baseline_count": row.get("baseline_count") or 0,
            "baseline_words": row.get("baseline_words") or 0,
            "engine_version": row.get("style_engine_version") or "",
            "threshold_version": row.get("style_threshold_version") or "",
            "scored_at": row.get("style_scored_at") or "",
        }
        features = row.get("style_features") or {}
        for name, column in feature_names.items():
            values[column] = features.get(name, "")
        writer.writerow(values)
    return output.getvalue()
