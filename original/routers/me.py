"""The ADR-005 student read-model (/me/*), moved verbatim from original/api.py.

/me/work calls the /students/{id}/score handler in-process, so this module
imports it from its router exactly as api.py used to call it as a local
function. /me/work never writes a baseline (NORTH_STAR rule 8: only teacher-approved
writing becomes baseline); the piece is compared and not stored.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from .. import voice as voice_mod
from ..consent import policy as consent_policy
from ..schemas import (
    ScoreSubmissionRequest,
    VoiceSubmitRequest,
    VoiceSubmitResult,
    VoiceView,
)
from ._shared import _TRUSTED_PROVENANCE, _repo, _require_student_session
from .students_scoring import _throttle_score, score_submission

router = APIRouter()


# ── ADR-005: the student read-model (redacting, token-resolved, no id in path) ─
# The student dashboard talks ONLY to these /me/* endpoints. They resolve the
# student from the session token (never an id in the path, so id-tampering and
# cross-student reads are structurally impossible) and return display-ready,
# supportive-register documents with every forbidden internal projected away in
# original/voice.py. The rich /students/{id}, /score, and /admin/* surfaces are
# unchanged — they remain the STAFF surface, just unreachable by this client.


@router.get("/me/voice", response_model=VoiceView)
def my_voice(request: Request):
    """
    The complete, redacted VoiceView for the signed-in student.

    Resolves the student from the session token, gathers their internal state
    (baseline vector, scoring manifests, tutor corrections, formation pathway)
    and projects it through original.voice into a display-ready document. No
    feature codes, raw divergence/deviation, purity, sample counts, action
    enums, or thresholds ever cross the wire.
    """
    session = _require_student_session(request)
    sid = str(session["sid"])
    name = str(session.get("name", "") or "")

    state = _repo().get(sid)
    if state is not None:
        from ..constants import ALL_FEATURE_CODES

        baseline_vector = {
            code: float(state.baseline_mean[i]) for i, code in enumerate(ALL_FEATURE_CODES)
        }
        sample_count = state.sample_count
        # Voice Affirmed means a piece a teacher approved is on file. That is the
        # trusted provenances (a supervised sitting, a teacher-verified paper, a
        # course-site import), not authenticated_count, which also counts a
        # student's own upload at half weight.
        approved_count = sum(1 for s in state.samples if s.provenance in _TRUSTED_PROVENANCE)
    else:
        baseline_vector = {}
        sample_count = 0
        approved_count = 0

    manifests = _repo().list_manifests(student_id=sid, limit=50).get("items", [])
    corrections = _repo().list_corrections(student_id=sid, limit=20).get("items", [])
    pathway = _repo().get_formation_pathway(sid)

    view = voice_mod.project_voice_view(
        name=name,
        baseline_vector=baseline_vector,
        sample_count=sample_count,
        approved_count=approved_count,
        manifests=manifests,
        corrections=corrections,
        pathway=pathway,
    )
    return VoiceView(**view)


@router.post("/me/work", response_model=VoiceSubmitResult)
def my_work(request: Request, body: VoiceSubmitRequest):
    """
    Compare a piece of writing with the writing on file in the signed-in
    student's profile (their baseline).

    Scores the text server-side against that baseline, then returns ONLY the
    redacted result (headline + supportive summary + steady-dimension
    affirmations + whether a review opportunity opened). This route never adds
    the piece to the student's baseline, so the student's sample count is the
    same before and after, and the piece itself is not stored. The raw Layer-7
    payload never leaves the server. When the writing on file is too thin to
    rate ready (fewer than five counted samples, or less than three effective),
    the answer is "not enough writing on file to compare yet", with no reading
    of the piece (``voice.project_inconclusive_result``).
    """
    session = _require_student_session(request)
    sid = str(session["sid"])
    name = str(session.get("name", "") or "")
    # Same scoring budget as /students/{id}/score (T-19). Checked here, outside
    # the try below, because that block reports every HTTPException as "no
    # writing on file", which would hide a 429.
    _throttle_score(request)
    # Consent gate, outside the try for the same reason: "not available"
    # is not "no writing on file".
    consent_policy.require_original(sid)

    try:
        layer7 = score_submission(
            sid,
            ScoreSubmissionRequest(
                text=body.text,
                assignment=body.title,
                # Scoring names its audit rows after the sample count when no id
                # is given. Nothing is added to the baseline here, so that count
                # never moves: without a fresh id every comparison would
                # overwrite the last one (and could collide with a teacher's).
                submission_id=f"{sid}_work_{uuid.uuid4().hex[:12]}",
            ),
        )
    except HTTPException:
        # No student record, or no writing on file yet: nothing to compare with.
        return VoiceSubmitResult(**voice_mod.project_no_baseline_result())

    result = voice_mod.project_submission_result(layer7, name)
    return VoiceSubmitResult(**result)


@router.post("/me/formation/advance", response_model=VoiceView)
def my_formation_advance(request: Request):
    """
    Advance the signed-in student's formation pathway by one session, then
    return the refreshed VoiceView. Token-resolved; no id in the path. Opens a
    pathway first if none is active (mirrors the dashboard's idempotent flow).
    """
    session = _require_student_session(request)
    sid = str(session["sid"])

    repo = _repo()
    if not repo.get_formation_pathway(sid):
        repo.open_formation_pathway(sid, submission_id=None, reason=None)
    repo.advance_formation_pathway(sid)
    # Hand back the fresh, redacted view so the client re-renders from one source.
    return my_voice(request)
