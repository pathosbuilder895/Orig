from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from original.study_export import EXPORT_COLUMNS, export_csv, pseudonymize_student_id, validate_salt

_ROOT = Path(__file__).resolve().parent
_SALT = "dummy-study-export-salt"


def test_export_matches_golden_csv_without_plain_student_ids():
    rows = [
        {
            "exam_id": "exam-1",
            "id": "sub-1",
            "student_id": "tenant:student-1",
            "study_label": "shadow",
            "imitated_student_id": "tenant:student-2",
            "word_count": 321,
            "style_score": 0.125,
            "style_features": {"feature_z": 0.9, "feature_a": 0.2},
            "style_engine_version": "original-layer7-style-v1",
            "style_threshold_version": "thresholds-sha256:abc123",
        },
        {
            "exam_id": "exam-2",
            "id": "sub-2",
            "student_id": None,
            "study_label": None,
            "imitated_student_id": None,
            "word_count": 0,
            "style_score": None,
            "style_features": {},
            "style_engine_version": None,
            "style_threshold_version": None,
        },
    ]
    actual = export_csv(rows, _SALT)
    expected = (_ROOT / "fixtures" / "study_export_golden.csv").read_text()
    assert actual == expected
    assert "tenant:student-1" not in actual
    assert "tenant:student-2" not in actual
    assert EXPORT_COLUMNS == tuple(next(csv.reader(io.StringIO(actual))))


def test_hmac_pseudonyms_are_stable_and_salt_scoped():
    key = validate_salt(_SALT)
    assert pseudonymize_student_id("student", key) == pseudonymize_student_id("student", key)
    assert pseudonymize_student_id("student", key) != pseudonymize_student_id(
        "student", validate_salt("another-dummy-salt")
    )


@pytest.mark.parametrize("salt", [None, "", "tiny"])
def test_export_requires_a_nontrivial_salt(salt):
    with pytest.raises(ValueError, match="at least 16"):
        export_csv([], salt)


def test_export_cli_combines_repeated_exam_arguments(monkeypatch, capsys):
    from scripts import study_export

    class Repo:
        def get_bluebook_exam(self, exam_id):
            return {"id": exam_id, "tenant_id": f"tenant-{exam_id}"}

        def list_bluebook_study_submissions(self, exam_ids, tenant_id):
            return [
                {
                    "id": f"sub-{exam_ids[0]}",
                    "exam_id": exam_ids[0],
                    "student_id": "student-1",
                    "style_features": {},
                }
            ]

    monkeypatch.setattr(study_export, "get_repository", lambda: Repo())
    monkeypatch.setenv("STUDY_EXPORT_SALT", _SALT)
    assert study_export.main(["--exam", "exam-1", "--exam", "exam-2"]) == 0
    output = capsys.readouterr().out
    rows = list(csv.DictReader(io.StringIO(output)))
    assert [row["exam_id"] for row in rows] == ["exam-1", "exam-2"]
