from __future__ import annotations

from types import SimpleNamespace

from original.study_readiness import study_readiness


class _Repo:
    def __init__(self):
        self.rows = [
            {
                "id": "sub-1",
                "student_id": "tenant:student-1",
                "study_label": "shadow",
                "imitated_student_id": None,
                "style_score": None,
            },
            {
                "id": "sub-2",
                "student_id": "tenant:student-1",
                "study_label": "human",
                "imitated_student_id": None,
                "style_score": 0.2,
            },
            {
                "id": "sub-3",
                "student_id": "tenant:student-2",
                "study_label": None,
                "imitated_student_id": None,
                "style_score": None,
            },
        ]

    def get_bluebook_exam(self, exam_id):
        return {"id": exam_id, "tenant_id": "tenant", "conditions": {"aiDetect": True}}

    def list_bluebook_study_submissions(self, exam_ids, tenant_id):
        return self.rows

    def get(self, student_id):
        if student_id.endswith("student-1"):
            samples = [
                SimpleNamespace(provenance="proctored", text="one two three " * 100),
                SimpleNamespace(provenance="verified", text="four five six " * 100),
                SimpleNamespace(provenance="proctored", text="seven eight nine " * 100),
                SimpleNamespace(provenance="unverified", text="must not count"),
            ]
        else:
            samples = [SimpleNamespace(provenance="proctored", text="only three words")]
        return SimpleNamespace(samples=samples)


def test_readiness_reports_baselines_labels_scores_and_imitation_links():
    result = study_readiness(["exam-1"], repo=_Repo())
    exam = result["exams"][0]
    assert result["minimum_baseline_papers"] == 3
    first, second = exam["students"]
    assert (first["baseline_papers"], first["baseline_words"], first["ready"]) == (3, 900, True)
    assert (second["baseline_papers"], second["baseline_words"], second["ready"]) == (1, 3, False)
    assert exam["missing_labels"] == ["sub-3"]
    assert exam["unscored_submissions"] == ["sub-1", "sub-3"]
    assert exam["shadow_without_imitated_student"] == ["sub-1"]
    assert exam["feature_enabled"] is True


def test_readiness_requires_each_exam_to_exist():
    class Missing(_Repo):
        def get_bluebook_exam(self, exam_id):
            return None

    try:
        study_readiness(["absent"], repo=Missing())
    except ValueError as exc:
        assert "exam not found" in str(exc)
    else:
        raise AssertionError("missing exam should fail readiness")


def test_readiness_cli_reports_requested_exams(monkeypatch, capsys):
    import json

    from scripts import study_readiness as cli

    expected = {"minimum_baseline_papers": 3, "exams": [{"exam_id": "exam-1"}]}
    monkeypatch.setattr(cli, "study_readiness", lambda exam_ids: expected)
    assert cli.main(["--exam", "exam-1"]) == 0
    assert json.loads(capsys.readouterr().out) == expected
