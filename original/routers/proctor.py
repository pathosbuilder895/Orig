"""QR phone-park — proctoring deterrence (T8).

What this is
------------
No software can stop a student's phone from reaching an AI chatbot, and this
feature does not pretend to. It converts "please put your phones away" from an
unenforceable request into a per-student, timestamped, auditable ritual: each
student scans a QR at exam start, their phone opens a parked page, and the
proctor watches one tile per phone. Pulling the phone out to open a browser
kills the page's visibility, the tile flips, and the change is recorded against
the exam timeline.

It is **deterrence and signal, never proof.** A second phone or airplane mode
defeats it completely — a beacon that stops beating is itself the signal, and
what it signals is "a human should look up", not "this student cheated". Hence
there is deliberately no punitive automation anywhere in this module: nothing
here flags a submission, changes a score, or touches a student's profile. The
tiles inform a person, who decides.

Privacy (docs/STUDENT_DISCLOSURE.md — a design constraint, not a nice-to-have)
-----------------------------------------------------------------------------
The persisted footprint is an opaque ``park_token``, the professor's
``exam_session_id``, a free-text ``student_hint`` the student types on their own
phone, UTC timestamps, and state transitions. That is all of it.

**No IP address, no user-agent, no location, no device fingerprint, no roster
identifier.** Note what these handlers do NOT do with the ``Request`` objects
they receive: nothing is read off them but the principal (for the staff gate)
and ``base_url`` (to build the QR link). No handler logs a request, and the
persistence layer has no column that could hold one — see ``store.py``'s
``park_*`` block and the ``ParkSession``/``ParkBeat`` models.

``student_hint`` is the only student-supplied value stored. It exists so a
proctor can tell "M.R." from "J.T." on a wall of tiles; it is never one of our
student ids and never an email. Rows purge after 24h.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

from ..schemas import ParkBeatRequest, ParkOpenRequest
from ._shared import _bluebook_tenant, _repo, _require_staff

router = APIRouter()

#: A park session stays scannable for one sitting. After this the QR is dead
#: and re-opening the same exam mints a fresh token.
PARK_TTL_SECONDS = 6 * 3600

#: Retention. ``open`` sweeps anything older opportunistically, so a deployment
#: needs no scheduler for this feature.
PARK_RETENTION_SECONDS = 24 * 3600

#: A phone beats every ~10s; miss three and the tile reads "dropped".
PARK_DROPPED_AFTER_SECONDS = 30

#: Minimum spacing between accepted beats for one (token, hint).
PARK_MIN_BEAT_INTERVAL_SECONDS = 1.0

STUDENT_HINT_MAX_LEN = 64
EXAM_SESSION_ID_MAX_LEN = 128

#: Page-visibility states a phone may report. Nothing richer is collected.
PARK_STATES = frozenset({"parked", "foreground_lost", "resumed"})

#: The derived state for a phone that stopped beating. Never reported BY a
#: phone — a phone that could report it would still be beating.
PARK_DROPPED_STATE = "dropped"


def _now() -> datetime:
    """Current UTC time, behind one indirection so tests can control it.

    Every time-dependent rule in this module (6h TTL, 24h retention, 30s
    dropped-detection, the 1/s beat floor) reads the clock through here, so a
    test can prove them by moving a fake clock instead of sleeping.
    """
    return datetime.now(UTC)


# Beat throttle: last accepted beat per (park_token, student_hint). In-memory
# and stdlib-only, matching the existing `_throttle_login` posture in
# _shared.py — single-process uvicorn, and this is a burst guard on an
# anonymous endpoint rather than a security boundary (the token already is
# one). It reads the injected clock rather than time.monotonic() so the
# throttle is deterministic under a patched `_now`.
_last_beat: dict[tuple[str, str], float] = {}


def _reset_beat_throttle() -> None:
    """Test hook — drop the throttle window so one test cannot throttle the next."""
    _last_beat.clear()


def _throttle_beat(park_token: str, student_hint: str, now: datetime) -> None:
    key = (park_token, student_hint)
    ts = now.timestamp()
    previous = _last_beat.get(key)
    if previous is not None and ts - previous < PARK_MIN_BEAT_INTERVAL_SECONDS:
        # Deliberately NOT recorded: only accepted beats move the window, so a
        # phone hammering the endpoint recovers 1s after its last good beat
        # instead of locking itself out indefinitely.
        raise HTTPException(status_code=429, detail="Slow down — one beat per second.")
    _last_beat[key] = ts
    if len(_last_beat) > 10_000:  # bound memory under token churn
        _last_beat.clear()


def _is_live(session: dict, now: datetime) -> bool:
    """True while a session is still inside its 6h TTL."""
    created = datetime.fromisoformat(session["created_at"])
    return now - created < timedelta(seconds=PARK_TTL_SECONDS)


def _owned_session_or_error(exam_session_id: str, tenant_id: str) -> dict:
    """Fetch a session, enforcing that it belongs to the caller's institution.

    Tenant isolation for a surface with no student ids in it: the opening
    principal's tenant is stamped on the session row and every later read or
    delete is filtered on it. ``exam_session_id`` is a professor-chosen string,
    so two institutions can plausibly pick the same one ("final-exam") — this
    is what stops one of them seeing the other's tiles.
    """
    session = _repo().park_get_session_by_exam(exam_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No such park session.")
    if session["tenant_id"] != tenant_id:
        raise HTTPException(status_code=403, detail="That park session belongs to another tenant.")
    return session


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/proctor/park/open")
def open_park_session(body: ParkOpenRequest, request: Request):
    """Open (or re-join) a phone-park for one exam sitting. Staff only.

    Returns the token to bake into a QR code and the URL that token points at.
    Re-opening a live session hands back the SAME token rather than minting a
    new one — a professor reloading the proctor view must not strand the phones
    already parked on the old QR. Once the 6h TTL has passed the token rotates
    and the previous one's beats are dropped.

    Also sweeps rows past the 24h retention window, which is why this feature
    needs no scheduler.
    """
    _require_staff(request)
    tenant_id = _bluebook_tenant(request)

    exam_session_id = body.exam_session_id.strip()
    if not exam_session_id:
        raise HTTPException(status_code=422, detail="exam_session_id is required")
    if len(exam_session_id) > EXAM_SESSION_ID_MAX_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"exam_session_id max {EXAM_SESSION_ID_MAX_LEN} chars",
        )

    now = _now()
    repo = _repo()
    repo.park_purge(now - timedelta(seconds=PARK_RETENTION_SECONDS))

    existing = repo.park_get_session_by_exam(exam_session_id)
    if existing is not None and existing["tenant_id"] != tenant_id:
        # Fail closed on a cross-tenant id collision rather than letting this
        # caller take the id over (which would hand them the other tenant's
        # tiles). Expired rows stay claimed until the 24h purge releases them.
        raise HTTPException(status_code=403, detail="That park session belongs to another tenant.")

    if existing is not None and _is_live(existing, now):
        park_token = existing["park_token"]
    else:
        park_token = secrets.token_urlsafe(16)
        repo.park_open(exam_session_id, tenant_id, park_token, now)

    base = str(request.base_url).rstrip("/")
    return {"park_token": park_token, "qr_url": f"{base}/bluebook/parked.html?t={park_token}"}


@router.post("/proctor/park/beat")
def beat(body: ParkBeatRequest):
    """One heartbeat from a parked phone. **Anonymous by design.**

    The phone has no login and never will — issuing student credentials to a
    parked device would create exactly the roster linkage this feature exists
    without. The scanned ``park_token`` is the capability, and it carries no
    authority beyond "append a heartbeat to this one exam session".

    Note the absent ``Request`` parameter: this handler cannot read an IP or a
    user-agent even by accident.
    """
    park_token = body.park_token.strip()
    student_hint = body.student_hint.strip()
    if not park_token:
        raise HTTPException(status_code=422, detail="park_token is required")
    if not student_hint:
        raise HTTPException(status_code=422, detail="student_hint is required")
    if len(student_hint) > STUDENT_HINT_MAX_LEN:
        raise HTTPException(
            status_code=422, detail=f"student_hint max {STUDENT_HINT_MAX_LEN} chars"
        )
    if body.state not in PARK_STATES:
        raise HTTPException(
            status_code=422,
            detail="state must be 'parked', 'foreground_lost', or 'resumed'",
        )

    now = _now()
    repo = _repo()
    session = repo.park_get_session(park_token)
    if session is None or not _is_live(session, now):
        # Unknown and expired are one answer on purpose: an anonymous caller
        # learns nothing about which tokens ever existed.
        raise HTTPException(status_code=404, detail="Unknown or expired park token.")

    _throttle_beat(park_token, student_hint, now)
    repo.park_beat(park_token, student_hint, body.state, now)
    return {"ok": True}


@router.get("/proctor/park/status")
def park_status(request: Request, exam_session_id: str):
    """Live tiles for one exam sitting. Staff only, own tenant only.

    ``state`` is *derived*, not merely reported: a phone whose last beat is
    more than 30s old reads ``"dropped"`` whatever it last claimed to be. That
    inversion is the point of the whole feature — the interesting event is a
    beacon going quiet, and a phone in someone's pocket cannot tell us it left.

    ``transitions`` is the record of real state changes only (a steady 10s
    heartbeat appends nothing), so it stays readable as an exam timeline.
    """
    _require_staff(request)
    tenant_id = _bluebook_tenant(request)
    _owned_session_or_error(exam_session_id, tenant_id)

    now = _now()
    tiles = []
    for row in _repo().park_tiles(exam_session_id):
        last_seen = datetime.fromisoformat(row["last_seen_at"])
        seconds_ago = max(int((now - last_seen).total_seconds()), 0)
        tiles.append(
            {
                "student_hint": row["student_hint"],
                "state": (
                    PARK_DROPPED_STATE if seconds_ago > PARK_DROPPED_AFTER_SECONDS else row["state"]
                ),
                "last_seen_seconds_ago": seconds_ago,
                "transitions": row["transitions"],
            }
        )
    return {"tiles": tiles}


@router.delete("/proctor/park/{exam_session_id}")
def delete_park_session(exam_session_id: str, request: Request):
    """Delete a park session and every beat on it. Staff only, own tenant only.

    Not guarded by ``_require_guard``: this destroys only the ephemeral park
    data described above — no student profile, no baseline, no submission — so
    deleting early is data minimisation, and a professor should never have to
    find an ops token to do it.
    """
    _require_staff(request)
    tenant_id = _bluebook_tenant(request)
    _owned_session_or_error(exam_session_id, tenant_id)
    return {"deleted": _repo().park_delete(exam_session_id)}
