from __future__ import annotations

import json


def test_study_rescore_cli_runs_shared_exam_rescorer_and_audits(monkeypatch, capsys):
    from scripts import study_rescore

    calls = []

    class Repo:
        def get_bluebook_exam(self, exam_id):
            return {"id": exam_id, "tenant_id": "tenant-1"}

        def log_audit(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(study_rescore, "get_repository", lambda: Repo())
    monkeypatch.setattr(
        study_rescore,
        "rescore_exam",
        lambda exam_id, repo: {"exam_id": exam_id, "scored": 2, "skipped": 1, "total": 3},
    )
    assert study_rescore.main(["--exam", "exam-1"]) == 0
    assert json.loads(capsys.readouterr().out)["scored"] == 2
    assert calls[0]["action"] == "bluebook_study_rescore"
    assert calls[0]["tenant_id"] == "tenant-1"
