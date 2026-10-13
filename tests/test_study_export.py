from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from original.study_export import EXPORT_COLUMNS, export_csv, pseudonymize_student_id, validate_salt

_ROOT = Path(__file__).resolve().parent
_SALT = "dummy-study-export-salt"


def _rows():
    return [
        {
            "exam_id": "exam-1",
            "id": "sub-1",
            "student_id": "tenant:student-1",
            "study_label": "natural",
            "imitated_student_id": None,
            "word_count": 321,
            "style_score": 0.125,
            "authorship_probability": 0.82,
            "recommended_action": "monitor",
            "verdict": "monitor",
            "baseline_count": 3,
            "baseline_words": 421,
            "style_features": {"feature_z": 0.9, "feature_a": 0.2},
            "style_engine_version": "original-layer7-style-v1",
            "style_threshold_version": "thresholds-sha256:abc123",
            "style_scored_at": "2026-10-13T12:00:00+00:00",
        },
        {
            "exam_id": "exam-1",
            "id": "sub-2",
            "student_id": "tenant:student-2",
            "study_label": "shadow",
            "imitated_student_id": "tenant:student-3",
            "word_count": 200,
            "style_score": None,
            "authorship_probability": None,
            "style_features": {},
        },
        {
            "exam_id": "exam-1",
            "id": "sub-3",
            "student_id": "tenant:student-4",
            "study_label": None,
            "authorship_probability": 0.4,
            "style_features": {"feature_a": 1.0},
        },
    ]


def test_export_matches_golden_contract_and_omits_unlabeled_or_unscored_rows():
    actual = export_csv(_rows(), _SALT, "study-2026-01")
    expected = (_ROOT / "fixtures" / "study_export_golden.csv").read_text()
    assert actual == expected
    assert "tenant:student-1" not in actual
    assert "tenant:student-3" not in actual
    header = tuple(next(csv.reader(io.StringIO(actual))))
    assert header[: len(EXPORT_COLUMNS)] == EXPORT_COLUMNS
    assert header[len(EXPORT_COLUMNS) :] == ("f_feature_a", "f_feature_z")
    assert "student_hash" not in actual
    assert "style_features_json" not in actual


def test_include_unscored_keeps_labeled_rows_for_readiness_debugging():
    output = export_csv(_rows(), _SALT, "study-2026-01", include_unscored=True)
    rows = list(csv.DictReader(io.StringIO(output)))
    assert [row["submission_id"] for row in rows] == ["sub-1", "sub-2"]
    assert rows[1]["authorship_probability"] == ""


def test_probability_without_a_stored_score_does_not_make_a_row_scored():
    row = {"id": "partial-score", "study_label": "natural", "authorship_probability": 0.6}
    output = export_csv([row], _SALT, "study")
    assert list(csv.DictReader(io.StringIO(output))) == []


def test_hmac_pseudonyms_are_stable_and_salt_scoped():
    key = validate_salt(_SALT)
    assert pseudonymize_student_id("student", key) == pseudonymize_student_id("student", key)
    assert pseudonymize_student_id("student", key) != pseudonymize_student_id(
        "student", validate_salt("another-dummy-salt")
    )


@pytest.mark.parametrize("salt", [None, "", "tiny"])
def test_export_requires_a_nontrivial_salt(salt):
    with pytest.raises(ValueError, match="at least 16"):
        export_csv([], salt, "study-2026-01")


def test_export_requires_study_id():
    with pytest.raises(ValueError, match="study_id is required"):
        export_csv([], _SALT, "")


def test_export_cli_combines_repeated_exam_arguments_and_study_id(monkeypatch, capsys):
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
                    "study_label": "natural",
                    "style_score": 0.2,
                    "authorship_probability": 0.6,
                    "style_features": {},
                }
            ]

    monkeypatch.setattr(study_export, "get_repository", lambda: Repo())
    monkeypatch.setenv("STUDY_EXPORT_SALT", _SALT)
    monkeypatch.setenv("STUDY_ID", "env-study")
    assert study_export.main(["--exam", "exam-1", "--exam", "exam-2"]) == 0
    output = capsys.readouterr().out
    rows = list(csv.DictReader(io.StringIO(output)))
    assert [row["exam_id"] for row in rows] == ["exam-1", "exam-2"]
    assert {row["study_id"] for row in rows} == {"env-study"}

    assert (
        study_export.main(["--exam", "exam-1", "--study-id", "cli-study", "--include-unscored"])
        == 0
    )
    assert "cli-study" in capsys.readouterr().out
