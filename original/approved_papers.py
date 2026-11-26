"""What an approved past paper is (rule B, 2026-11), defined once.

A sample counts toward the minimum-baseline floor and the readiness report
when a teacher or a supervised sitting stands behind it:

* its provenance is one of ``TRUSTED_PROVENANCE`` (proctored, verified,
  canvas): a supervised sitting, a teacher-verified paper, a course-site
  import; or
* it is a past paper the student shared and a teacher approved
  (``routers/past_papers.py``; it enters the baseline as ``unverified``); or
* it is a take-home Collections sitting a teacher approved into the baseline
  (``routers/bluebook_baselines.py``; also ``unverified``); or
* its provenance is none of ``AUTH_WEIGHTS`` (``unknown``, e.g. the legacy
  ``instructor_verified``): the baseline routes refuse those, so the server
  or a script wrote it, never a student.

Only a student's own self-upload that no teacher approved is left out: an
``unverified`` sample that is neither of the two approvals above. The
sample's provenance and weight are untouched: this decides the floor and the
readiness wording only, never which samples enter the baseline or how much
they weigh (``AUTH_WEIGHTS``).

How each sample got in is not stored, so :func:`sample_sources` derives it at
read time from the audit rows the take-home approve/undo routes write and
from the student's approved past papers. Cost per call: nothing at all when
no contributing sample is ``unverified``; otherwise one audit read and one
past-papers read, plus one submissions read only when a take-home approval
exists. A request computes it once and passes the result along
(``students_scoring``), so the floor, the readiness report, the preliminary
chip and the evidence's per-paper source share those reads.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from . import principal as principal_mod
from .baseline_integrity import APPROVED_SOURCES, count_approved
from .constants import TRUSTED_PROVENANCE

log = logging.getLogger(__name__)

__all__ = [
    "APPROVED_SOURCES",
    "approved_paper_count",
    "approved_submission_ids",
    "count_approved",
    "gate_sources",
    "sample_sources",
]

# What POST/DELETE /bluebook/submissions/{id}/baseline record
# (routers/bluebook_baselines.py). Only an approval that wrote a sample
# ("added") stands behind one. "already_in_baseline" found the text there
# already, possibly as the student's own self-upload posted beforehand, so it
# vouches for nothing; "held" and the refusals approved nothing.
_APPROVED_RESULTS = frozenset({"added"})

_APPROVAL_ACTIONS = [
    "baseline_approve",
    "baseline_remove",
    "past_paper_approve",
    "past_paper_unapprove",
]


def _repo():
    from .routers._shared import _repo as repo

    return repo()


def approved_submission_ids(repo, student_id: str) -> set[str]:
    """Submission ids whose approval wrote a sample into this student's
    baseline and that a teacher has not since removed, replayed oldest first
    from the audit log."""
    return _approval_records(repo, student_id)[0]


def _approval_records(repo, student_id: str) -> tuple[set[str], set[str]]:
    """One audit read: (take-home submission ids whose approval wrote a
    sample and was not undone, shared past-paper ids whose latest approval
    wrote nothing). A shared paper's approval goes through the baseline route
    with a submission_uuid, which skips a text already there (e.g. the
    student's own earlier upload of it); past_paper_approve records that as
    ``added: false``. Rows written before that field existed say nothing and
    are taken as written, as they always were."""
    approved: set[str] = set()
    unwritten_papers: set[str] = set()
    rows = repo.list_audit_actions_for_student(student_id, _APPROVAL_ACTIONS)
    for row in rows:
        details = row.get("details") or {}
        paper_id = details.get("paper_id")
        if row["action"] == "past_paper_approve" and paper_id:
            if details.get("added") is False:
                unwritten_papers.add(paper_id)
            else:
                unwritten_papers.discard(paper_id)
            continue
        if row["action"] == "past_paper_unapprove":
            if paper_id:
                unwritten_papers.discard(paper_id)
            continue
        sub_id = details.get("submission_id")
        if not sub_id:
            continue
        if row["action"] == "baseline_approve" and row.get("result") in _APPROVED_RESULTS:
            approved.add(sub_id)
        sub_id = (row.get("details") or {}).get("submission_id")
        if not sub_id:
            continue
        if row["action"] == "baseline_approve" and row.get("result") in _APPROVED_RESULTS:
            approved.add(sub_id)
        elif row["action"] == "baseline_remove" and row.get("result") == "removed":
            approved.discard(sub_id)
    return approved, unwritten_papers


def sample_sources(student_id: str, samples: Sequence) -> list[str]:
    """How each sample got into the baseline, one entry per sample.

    ``staff_or_supervised`` for a trusted provenance; for an ``unverified``
    sample, ``take_home`` when its text hash is one of the approval's own
    text forms (``bluebook_baselines._fingerprints``) of a Collections
    submission of this student that a teacher approved and has not since
    taken out, ``shared_paper`` when it is the text of one of their approved
    past papers, else ``student_upload``; ``unknown`` for any other
    provenance. Read-only; nothing here reaches scoring.

    An approval counts only when it wrote a sample itself: a take-home
    approval recorded as ``added`` (not ``already_in_baseline``), a shared
    paper whose approval was not skipped as a duplicate. Each approval stands
    behind one sample only (the oldest match), and one piece of writing counts
    once however many approvals cover it: a further copy of an already
    counted text is ``student_upload``. So a student who posts the text of an
    approved paper or their own take-home answer, before or after the
    approval, cannot raise the count.
    """
    from .routers.bluebook_baselines import _fingerprints
    from .routers.past_papers import _sha
    from .routers.students_baseline import _hashes_from_samples

    unverified = [s.provenance == "unverified" for s in samples]
    # Text hash -> the approval it belongs to (a take-home submission id, or a
    # shared past paper's id), so each approval can be spent once.
    take_home: dict[str, str] = {}
    shared: dict[str, str] = {}
    if any(unverified):
        repo = _repo()
        approved, unwritten_papers = _approval_records(repo, student_id)
        if approved:
            for rec in repo.list_bluebook_submission_texts_for_student(student_id):
                if rec.get("id") in approved:
                    for h in _fingerprints(rec):
                        take_home.setdefault(h, f"take_home:{rec['id']}")
        tenant = principal_mod.tenant_of(student_id)
        if tenant:
            for p in repo.list_past_papers(tenant, student_id):
                if (
                    p.get("status") == "approved"
                    and p.get("text")
                    and p.get("paper_id") not in unwritten_papers
                ):
                    shared.setdefault(_sha(p["text"]), f"shared:{p.get('paper_id')}")
    used: set[str] = set()  # approvals already spent
    counted: set[str] = set()  # text hashes already counted as approved

    def _claim(hashes: set[str], approvals: dict[str, str]) -> bool:
        if hashes & counted:
            return False
        for h in sorted(hashes):
            key = approvals.get(h)
            if key is not None and key not in used:
                used.add(key)
                counted.update(hashes)
                return True
        return False

    out = []
    for s, is_unverified in zip(samples, unverified, strict=True):
        if s.provenance in TRUSTED_PROVENANCE:
            out.append("staff_or_supervised")
        elif not is_unverified:
            out.append("unknown")
        else:
            hashes = _hashes_from_samples([s])
            if _claim(hashes, take_home):
                out.append("take_home")
            elif _claim(hashes, shared):
                out.append("shared_paper")
            else:
                out.append("student_upload")
    return out


def gate_sources(student_id: str, samples: Sequence) -> list[str] | None:
    """:func:`sample_sources` for a gate, or ``None`` when the lookup failed.

    ``None`` makes :func:`count_approved` count no ``unverified`` sample,
    the part of rule B that needs no record: a failed read can only make the
    count smaller, never let a self-upload through."""
    try:
        return sample_sources(student_id, samples)
    except Exception:
        log.exception("approved-paper lookup failed; counting no unverified sample")
        return None


def approved_paper_count(student_id: str, samples: Sequence) -> int:
    """Approved past papers among ``samples`` under rule B (module docstring)."""
    return count_approved(samples, gate_sources(student_id, samples))
