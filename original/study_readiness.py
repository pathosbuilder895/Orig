"""Read-only readiness findings for sealed Original style study data."""

from __future__ import annotations

from .repository import get_repository

MIN_BASELINE_PAPERS = 3
MIN_BASELINE_WORDS = 300
_TRUSTED_PROVENANCE = frozenset({"proctored", "verified"})


def study_readiness(exam_ids: list[str], repo=None) -> dict:
    repo = repo or get_repository()
    exams = []
    for exam_id in dict.fromkeys(exam_ids):
        exam = repo.get_bluebook_exam(exam_id)
        if exam is None:
            raise ValueError(f"exam not found: {exam_id}")
        rows = repo.list_bluebook_study_submissions([exam_id], exam.get("tenant_id"))
        students: dict[str, dict] = {}
        for row in rows:
            student_id = row.get("student_id")
            if not student_id or student_id in students:
                continue
            state = repo.get(student_id)
            samples = [
                sample
                for sample in (getattr(state, "samples", []) if state is not None else [])
                if getattr(sample, "provenance", None) in _TRUSTED_PROVENANCE
            ]
            words = sum(len((getattr(sample, "text", "") or "").split()) for sample in samples)
            students[student_id] = {
                "student_id": student_id,
                "baseline_papers": len(samples),
                "baseline_words": words,
                "minimum_papers": MIN_BASELINE_PAPERS,
                "minimum_words": MIN_BASELINE_WORDS,
                "papers_ready": len(samples) >= MIN_BASELINE_PAPERS,
                "words_ready": words >= MIN_BASELINE_WORDS,
                "ready": len(samples) >= MIN_BASELINE_PAPERS and words >= MIN_BASELINE_WORDS,
            }

        missing_labels = [row["id"] for row in rows if not (row.get("study_label") or "").strip()]
        unscored = [row["id"] for row in rows if row.get("style_score") is None]
        shadow_without_imitation = [
            row["id"]
            for row in rows
            if (row.get("study_label") or "").strip().casefold() == "shadow"
            and not (row.get("imitated_student_id") or "").strip()
        ]
        exams.append(
            {
                "exam_id": exam_id,
                "feature_enabled": (exam.get("conditions") or {}).get("aiDetect") is True,
                "students": list(students.values()),
                "missing_labels": missing_labels,
                "unscored_submissions": unscored,
                "shadow_without_imitated_student": shadow_without_imitation,
            }
        )
    return {
        "minimum_baseline_papers": MIN_BASELINE_PAPERS,
        "minimum_baseline_words": MIN_BASELINE_WORDS,
        "exams": exams,
    }
