"""Phone parking tied to the student's account (2026-10).

The older QR phone-park in ``proctor.py`` (T8) is anonymous: one shared code
per sitting, a name typed on the phone, nothing required. This module is the
per-collection version Andrew asked for:

* **Optional, off by default.** A teacher switches it on for one collection
  (``conditions.phonePark``). With it off, nothing here is reachable for that
  collection and starting a sitting is exactly as before.
* **Tied to the student.** The student's own briefing shows a QR code that
  carries a short-lived signed grant for *that student and that collection*
  (``student_auth.mint_phone_scan_token``). Scanning it needs no app and no
  sign-in on the phone; the grant is the whole capability and can park a phone
  for nobody else.
* **Required before beginning.** A new sitting of such a collection cannot
  start until the phone is parked, or the teacher has let that student begin
  without one (an override, recorded with who and when, and audit-logged).
* **Deterrence and a signal, never proof.** As in ``proctor.py``: the phone
  page reports only whether it is open. Nothing here flags work, changes a
  score, or touches a profile. A person decides.

Stored per (collection, student): the state the phone page last reported, when
it was parked and last seen, and any override. No device details, no IP, no
user-agent, no location. Deleted with the student's data on withdrawal
(``delete_student``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import bluebook_rules as rules
from .. import student_auth
from ._shared import _repo, _require_staff

router = APIRouter()

#: States a parked phone may report (the same three as proctor.py).
PHONE_STATES = frozenset({"parked", "foreground_lost", "resumed"})
#: A phone beats every ~10s; quiet for longer than this reads "dropped".
PHONE_DROPPED_AFTER_SECONDS = 30
#: Minimum spacing between accepted beats for one (collection, student).
PHONE_MIN_BEAT_INTERVAL_SECONDS = 1.0
OVERRIDE_NOTE_MAX_LEN = 200

NOT_PARKED_DETAIL = (
    "Park your phone first: scan the code on this page with your phone, or ask your teacher."
)


def _now() -> datetime:
    """Behind one indirection so tests can move the clock."""
    return datetime.now(UTC)


_last_beat: dict[tuple[str, str], float] = {}


def _reset_beat_throttle() -> None:
    _last_beat.clear()


def _throttle(exam_id: str, sid: str, now: datetime) -> None:
    key = (exam_id, sid)
    ts = now.timestamp()
    prev = _last_beat.get(key)
    if prev is not None and ts - prev < PHONE_MIN_BEAT_INTERVAL_SECONDS:
        raise HTTPException(status_code=429, detail="Slow down — one beat per second.")
    _last_beat[key] = ts
    if len(_last_beat) > 10_000:
        _last_beat.clear()


# ── Shared rule, also used by the two start routes ───────────────────────────


def require_cleared(exam: dict, exam_id: str, student_id: str) -> None:
    """Refuse a NEW sitting until the phone is parked (409). Callers skip this
    for a sitting already under way, so nobody is ever locked out mid-exam."""
    if not rules.phone_park_required(exam):
        return
    row = _repo().get_phone_park(exam_id, student_id)
    if not (row and (row.get("parked_at") or row.get("override_at"))):
        raise HTTPException(status_code=409, detail=NOT_PARKED_DETAIL)


def _status(exam_id: str, student_id: str, now: datetime) -> dict:
    row = _repo().get_phone_park(exam_id, student_id) or {}
    state = row.get("state") or ""
    last = row.get("last_seen_at")
    seconds_ago = None
    if last:
        seconds_ago = max(int((now - datetime.fromisoformat(last)).total_seconds()), 0)
        if state and seconds_ago > PHONE_DROPPED_AFTER_SECONDS:
            state = "dropped"
    return {
        "parked": bool(row.get("parked_at")),
        "overridden": bool(row.get("override_at")),
        "state": state or ("overridden" if row.get("override_at") else "waiting"),
        "parked_at": row.get("parked_at"),
        "last_seen_seconds_ago": seconds_ago,
        "override_at": row.get("override_at"),
        "override_note": row.get("override_note") or "",
    }


def _student(request: Request):
    p = getattr(request.state, "principal", None)
    if p is None or p.is_demo:
        raise HTTPException(status_code=401, detail="Not signed in.")
    if p.role != "student":
        raise HTTPException(status_code=403, detail="Student account required.")
    return p


def _student_exam(p, exam_id: str) -> dict:
    exam = _repo().get_bluebook_exam(exam_id)
    if exam is None or exam.get("tenant_id") != p.tenant_id:
        raise HTTPException(status_code=404, detail="exam not found")
    if rules.exam_state(exam, rules.now_utc()) == rules.DRAFT:
        raise HTTPException(status_code=404, detail="exam not found")
    return exam


# ── Student: the code on their own briefing ──────────────────────────────────


@router.get("/bluebook/me/exams/{exam_id}/phone-park")
def my_phone_park(exam_id: str, request: Request, code: int = 1):
    """Whether this collection asks the student to park their phone, whether
    they have, and (``code=1``) a fresh QR code that parks it for them alone.
    Polling with ``code=0`` reads the status without minting a code."""
    p = _student(request)
    exam = _student_exam(p, exam_id)
    if not rules.phone_park_required(exam):
        return {"required": False}
    out = {"required": True, **_status(exam_id, p.user_id, _now())}
    if code:
        token = student_auth.mint_phone_scan_token(p.user_id, exam_id)
        base = str(request.base_url).rstrip("/")
        out["qr_url"] = f"{base}/bluebook/parked.html?s={token}"
        out["expires_in"] = student_auth.PHONE_SCAN_TTL
    return out


# ── The phone: no app, no sign-in ────────────────────────────────────────────


class PhoneScanBody(BaseModel):
    token: str


class PhoneBeatBody(BaseModel):
    beat_token: str
    state: str = "parked"


def _live_exam_for(body: dict) -> dict:
    exam = _repo().get_bluebook_exam(body["exam"])
    if exam is None or not rules.phone_park_required(exam):
        raise HTTPException(
            status_code=404, detail="This code has expired. Scan the new one on your screen."
        )
    return exam


@router.post("/bluebook/phone-park/scan")
def phone_scan(body: PhoneScanBody):
    """A phone opened a student's QR code. The signed code names the student
    and the collection; nothing about the phone is read or kept. Returns the
    grant the page uses to say it is still open."""
    grant = student_auth.verify_phone_scan_token(body.token.strip())
    if grant is None:
        # Bad, forged and expired codes get one answer.
        raise HTTPException(
            status_code=404, detail="This code has expired. Scan the new one on your screen."
        )
    exam = _live_exam_for(grant)
    exam_id = grant["exam"]
    tenant = exam.get("tenant_id") or ""
    sid = grant["student"] if grant["student_is_full"] else f"{tenant}:{grant['student']}"
    if tenant and not sid.startswith(f"{tenant}:"):
        raise HTTPException(
            status_code=404, detail="This code has expired. Scan the new one on your screen."
        )
    now = _now().isoformat()
    existing = _repo().get_phone_park(exam_id, sid) or {}
    _repo().put_phone_park(
        exam_id,
        sid,
        exam.get("tenant_id") or "",
        {"state": "parked", "parked_at": existing.get("parked_at") or now, "last_seen_at": now},
    )
    _reset_key(exam_id, sid)
    _repo().log_audit(
        action="bluebook_phone_parked",
        tenant_id=exam.get("tenant_id"),
        student_id=sid,
        details={"exam_id": exam_id},
    )
    return {
        "ok": True,
        "beat_token": student_auth.mint_phone_beat_token(sid, exam_id),
        "exam_title": exam.get("title") or "",
    }


def _reset_key(exam_id: str, sid: str) -> None:
    _last_beat.pop((exam_id, sid), None)


@router.post("/bluebook/phone-park/beat")
def phone_beat(body: PhoneBeatBody):
    """ "This page is still open" from a parked phone."""
    grant = student_auth.verify_phone_beat_token(body.beat_token.strip())
    if grant is None:
        raise HTTPException(status_code=404, detail="Unknown or expired.")
    if body.state not in PHONE_STATES:
        raise HTTPException(
            status_code=422, detail="state must be 'parked', 'foreground_lost', or 'resumed'"
        )
    exam = _live_exam_for(grant)
    sid, exam_id = grant["sid"], grant["exam"]
    if _repo().get_phone_park(exam_id, sid) is None:
        # Withdrawn (deleted) since the scan: nothing to update, nothing re-created.
        raise HTTPException(status_code=404, detail="Unknown or expired.")
    now = _now()
    _throttle(exam_id, sid, now)
    _repo().put_phone_park(
        exam_id,
        sid,
        exam.get("tenant_id") or "",
        {"state": body.state, "last_seen_at": now.isoformat()},
    )
    return {"ok": True}


# ── Teacher: who has parked, and letting a student begin without a phone ─────


def _owned(exam_id: str, request: Request) -> dict:
    from .bluebook import _owned_exam

    return _owned_exam(exam_id, request)


@router.get("/bluebook/exams/{exam_id}/phone-park")
def exam_phone_parks(exam_id: str, request: Request):
    """One entry per student who may sit this collection (its course roster,
    or every rostered student for a collection with no course), plus anyone
    who has already parked, so the teacher can see who is still waiting and
    let a student without a phone begin."""
    _require_staff(request)
    exam = _owned(exam_id, request)
    from .bluebook_accounts import _tenant_rosters

    now = _now()
    rows = {r["student_key"]: r for r in _repo().list_phone_parks(exam_id)}
    if exam.get("course_id"):
        ids = [e["student_id"] for e in _repo().list_enrollments_for_course(exam["course_id"])]
    else:
        ids = list(_tenant_rosters(exam.get("tenant_id"))[1])
    ids = list(dict.fromkeys([*ids, *rows]))
    users = {u["user_id"]: u for u in _repo().list_users_by_ids(ids)}
    students = []
    for sid in ids:
        u = users.get(sid) or {}
        students.append(
            {
                "student_id": sid,
                "name": u.get("name") or u.get("display_name") or "",
                **_status(exam_id, sid, now),
                "override_by": (rows.get(sid) or {}).get("override_by") or "",
            }
        )
    students.sort(key=lambda r: (r["name"].lower(), r["student_id"]))
    return {"required": rules.phone_park_required(exam), "students": students}


class PhoneOverrideBody(BaseModel):
    note: str = ""


@router.post("/bluebook/exams/{exam_id}/phone-park/{student_id}/override")
def override_phone_park(exam_id: str, student_id: str, body: PhoneOverrideBody, request: Request):
    """Let one student begin without a parked phone (for example, they have
    none with them). Recorded on their row with who and when, and in the
    audit log. It says nothing about the student and changes no score."""
    _require_staff(request)
    exam = _owned(exam_id, request)
    tenant = exam.get("tenant_id") or ""
    if tenant and not student_id.startswith(f"{tenant}:"):
        raise HTTPException(status_code=404, detail="student not found")
    note = (body.note or "").strip()[:OVERRIDE_NOTE_MAX_LEN]
    p = request.state.principal
    row = _repo().put_phone_park(
        exam_id,
        student_id,
        tenant,
        {"override_by": p.user_id, "override_at": _now().isoformat(), "override_note": note},
    )
    _repo().log_audit(
        action="bluebook_phone_park_override",
        tenant_id=tenant,
        student_id=student_id,
        actor=p.user_id,
        details={"exam_id": exam_id, "note": note},
    )
    return {
        "ok": True,
        "override_at": row.get("override_at"),
        "override_by": row.get("override_by"),
    }
