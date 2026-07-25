"""The ADR-005 student read-model (/me/*), moved verbatim from original/api.py.

/me/work and /me/formation/advance call the /students* handlers in-process, so
this module imports them from their routers exactly as api.py used to call them
as local functions.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .. import voice as voice_mod
from ..schemas import (
    AddSampleRequest,
    ScoreSubmissionRequest,
    VoiceSubmitRequest,
    VoiceSubmitResult,
    VoiceView,
)
from ._shared import _repo, _require_student_session
from .students_baseline import add_baseline
from .students_scoring import score_submission

router = APIRouter()


# ── ADR-005: the student read-model (redacting, token-resolved, no id in path) ─
# The student dashboard talks ONLY to these /me/* endpoints. They resolve the
# student from the session token (never an id in the path, so id-tampering and
# cross-student reads are structurally impossible) and return display-ready,
# formation-register documents with every forbidden internal projected away in
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
        authenticated_count = state.authenticated_count
    else:
        baseline_vector = {}
        sample_count = 0
        authenticated_count = 0

    manifests = _repo().list_manifests(student_id=sid, limit=50).get("items", [])
    corrections = _repo().list_corrections(student_id=sid, limit=20).get("items", [])
    pathway = _repo().get_formation_pathway(sid)

    view = voice_mod.project_voice_view(
        name=name,
        baseline_vector=baseline_vector,
        sample_count=sample_count,
        authenticated_count=authenticated_count,
        manifests=manifests,
        corrections=corrections,
        pathway=pathway,
    )
    return VoiceView(**view)


@router.post("/me/work", response_model=VoiceSubmitResult)
def my_work(request: Request, body: VoiceSubmitRequest):
    """
    Submit a piece of writing as the signed-in student.

    Adds the text to the student's body of work and scores it server-side, then
    returns ONLY the redacted formation-register result (headline + supportive
    summary + steady-dimension affirmations + whether a review opportunity
    opened). The raw Layer-7 payload never leaves the server.
    """
    session = _require_student_session(request)
    sid = str(session["sid"])
    name = str(session.get("name", "") or "")

    # Ensure a record exists, then add this piece to the body of work. The
    # student-submitted piece is always 'unverified' (self-upload trust), so the
    # provenance gate is a no-op here — pass the request through for its signature.
    _repo().get_or_create(sid)
    try:
        add_baseline(
            sid,
            AddSampleRequest(text=body.text, assignment=body.title, provenance="unverified"),
            request,
        )
    except HTTPException:
        # A too-short or otherwise rejected sample shouldn't 500 the student; the
        # scoring step below will simply return the "not yet analysed" result.
        pass

    try:
        layer7 = score_submission(
            sid, ScoreSubmissionRequest(text=body.text, assignment=body.title)
        )
    except HTTPException:
        # No authenticated baseline yet (or student not scorable) — saved, not scored.
        return VoiceSubmitResult(
            headline="Saved to your body of work.",
            summary="This piece has been added to your formation record. Your voice "
            "profile builds as you submit more work.",
            steady=[],
            review_opportunity=False,
        )

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
