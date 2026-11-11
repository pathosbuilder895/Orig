"""Phone parking tied to the student's account (2026-10,
original/routers/phone_park.py).

Off by default and per collection; when on, a student's new sitting waits for
their own phone (scanned from their own briefing code) or a teacher override;
codes are signed for one student and one collection and expire; the teacher's
override is recorded and audit-logged; the data goes with withdrawal."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import pytest

from original import student_auth
from original.repository import get_repository
from original.routers import phone_park
from tests.alpha.test_past_papers import _fresh, _ok, _workspace  # noqa: F401  (autouse fixture)


@pytest.fixture(autouse=True)
def _throttle_reset():
    phone_park._reset_beat_throttle()
    yield
    phone_park._reset_beat_throttle()


def _exam(client, T, phone_park_on, title="Phone exam"):
    cond = {"aiDetect": False}
    if phone_park_on is not None:
        cond["phonePark"] = phone_park_on
    return _ok(client.post("/bluebook/exams", json={
        "title": title, "status": "ACTIVE", "duration": 25,
        "questions": ["Say something."], "conditions": cond,
    }, headers=T), 201)


def _code(client, exam_id, S):
    got = _ok(client.get(f"/bluebook/me/exams/{exam_id}/phone-park", headers=S))
    return got, parse_qs(urlparse(got["qr_url"]).query)["s"][0]


def _start(client, exam_id, S):
    return client.post(f"/bluebook/me/exams/{exam_id}/start", headers=S)


@pytest.mark.slow
def test_off_by_default_changes_nothing(live_client):
    T, [(sid, S), _] = _workspace(live_client, "pp1@example.test")
    for flag in (None, False):
        exam = _exam(live_client, T, flag)
        assert _ok(live_client.get(f"/bluebook/me/exams/{exam['id']}/phone-park", headers=S)) == {"required": False}
        _ok(_start(live_client, exam["id"], S))
        assert get_repository().get_phone_park(exam["id"], sid) is None


@pytest.mark.slow
def test_option_must_be_boolean(live_client):
    T, _ = _workspace(live_client, "pp0@example.test", n_students=1)
    r = live_client.post("/bluebook/exams", json={
        "title": "x", "status": "ACTIVE", "duration": 25, "questions": ["q"],
        "conditions": {"phonePark": "yes"},
    }, headers=T)
    assert r.status_code == 422


@pytest.mark.slow
def test_on_blocks_until_parked_and_scan_links_the_right_student(live_client):
    T, [(sid, S), (sid2, S2)] = _workspace(live_client, "pp2@example.test")
    exam = _exam(live_client, T, True)
    r = _start(live_client, exam["id"], S)
    assert r.status_code == 409 and "Park your phone" in r.json()["detail"]
    got, token = _code(live_client, exam["id"], S)
    assert got["required"] is True and got["parked"] is False and got["state"] == "waiting"
    assert "/bluebook/parked.html?s=" in got["qr_url"] and got["expires_in"] == student_auth.PHONE_SCAN_TTL
    # Short enough for a small, easily scanned QR code (vendor/qr.js tops out at 213 bytes).
    assert len(got["qr_url"]) < 140
    # The phone needs no sign-in: the code alone parks it, for this student only.
    scanned = _ok(live_client.post("/bluebook/phone-park/scan", json={"token": token}))
    assert scanned["exam_title"] == "Phone exam" and scanned["beat_token"]
    row = get_repository().get_phone_park(exam["id"], sid)
    assert row["parked_at"] and row["state"] == "parked"
    assert get_repository().get_phone_park(exam["id"], sid2) is None
    # Student 1 may begin; student 2 still may not.
    _ok(_start(live_client, exam["id"], S))
    assert _start(live_client, exam["id"], S2).status_code == 409
    # The legacy session route is gated the same way for a student.
    r = live_client.post(f"/bluebook/exams/{exam['id']}/session", json={"student_id": sid2}, headers=S2)
    assert r.status_code == 409
    # Status polling without a new code.
    st = _ok(live_client.get(f"/bluebook/me/exams/{exam['id']}/phone-park?code=0", headers=S))
    assert st["parked"] is True and "qr_url" not in st
    # Beats move the state, and only for the scanning student.
    _ok(live_client.post("/bluebook/phone-park/beat", json={"beat_token": scanned["beat_token"], "state": "foreground_lost"}))
    assert get_repository().get_phone_park(exam["id"], sid)["state"] == "foreground_lost"
    bad = live_client.post("/bluebook/phone-park/beat", json={"beat_token": scanned["beat_token"], "state": "hacked"})
    assert bad.status_code == 422
    # Teacher sees it.
    tiles = _ok(live_client.get(f"/bluebook/exams/{exam['id']}/phone-park", headers=T))
    assert tiles["required"] is True
    by = {t["student_id"]: t for t in tiles["students"]}
    assert by[sid]["parked"] is True and by[sid2]["parked"] is False and by[sid2]["state"] == "waiting"


@pytest.mark.slow
def test_bad_forged_expired_and_wrong_kind_tokens_are_refused(live_client):
    T, [(sid, S), (sid2, S2)] = _workspace(live_client, "pp3@example.test")
    exam = _exam(live_client, T, True)
    _, token = _code(live_client, exam["id"], S)
    payload, sig = token.split(".", 1)
    for bad in ["", "nope", payload + ".AAAA", token[:-2] + "xx",
                student_auth.mint_phone_scan_token(sid, exam["id"], ttl_seconds=-5),
                student_auth.mint_phone_beat_token(sid, exam["id"]),  # a beat grant is not a scan code
                student_auth.mint_proctor_attestation(sid, exam["id"]),
                student_auth.mint_session(sid),
                # Signed, but for a student id outside this collection's workspace.
                student_auth.mint_phone_scan_token("other workspace:a b", exam["id"]),
                student_auth.mint_phone_scan_token(sid, "no-such-exam")]:
        r = live_client.post("/bluebook/phone-park/scan", json={"token": bad})
        assert r.status_code == 404, bad
    # A scan code is never a login session.
    assert student_auth.verify_session(token) is None
    assert live_client.get("/bluebook/me/exams", headers={"Authorization": f"Bearer {token}"}).status_code in (401, 403)
    # An expired beat grant is refused.
    old = student_auth.mint_phone_beat_token(sid, exam["id"], ttl_seconds=-1)
    assert live_client.post("/bluebook/phone-park/beat", json={"beat_token": old}).status_code == 404
    # Nothing was parked by any of that.
    assert get_repository().get_phone_park(exam["id"], sid) is None
    assert _start(live_client, exam["id"], S).status_code == 409


@pytest.mark.slow
def test_other_students_cannot_use_your_code(live_client):
    T, [(sid, S), (sid2, S2)] = _workspace(live_client, "pp4@example.test")
    exam = _exam(live_client, T, True)
    _, token = _code(live_client, exam["id"], S)
    # Student 2 scans student 1's code (e.g. a photo of their screen): it parks
    # student 1's phone, never student 2's, so student 2 still cannot begin.
    _ok(live_client.post("/bluebook/phone-park/scan", json={"token": token}, headers=S2))
    assert get_repository().get_phone_park(exam["id"], sid2) is None
    assert _start(live_client, exam["id"], S2).status_code == 409
    # A code for one collection does nothing for another.
    other = _exam(live_client, T, True, title="Other")
    assert get_repository().get_phone_park(other["id"], sid) is None
    assert _start(live_client, other["id"], S).status_code == 409
    # Another workspace's teacher cannot see or override.
    T2, _ = _workspace(live_client, "pp4b@example.test", n_students=1)
    assert live_client.get(f"/bluebook/exams/{exam['id']}/phone-park", headers=T2).status_code == 404
    r = live_client.post(f"/bluebook/exams/{exam['id']}/phone-park/{sid2}/override", json={}, headers=T2)
    assert r.status_code == 404
    # A student cannot override, nor read the teacher view.
    assert live_client.post(f"/bluebook/exams/{exam['id']}/phone-park/{sid2}/override", json={}, headers=S2).status_code in (401, 403)
    assert live_client.get(f"/bluebook/exams/{exam['id']}/phone-park", headers=S2).status_code in (401, 403)


@pytest.mark.slow
def test_proctor_override_lets_one_student_begin_and_is_logged(live_client):
    T, [(sid, S), (sid2, S2)] = _workspace(live_client, "pp5@example.test")
    exam = _exam(live_client, T, True)
    assert _start(live_client, exam["id"], S).status_code == 409
    out = _ok(live_client.post(f"/bluebook/exams/{exam['id']}/phone-park/{sid}/override",
                               json={"note": "No phone with them today"}, headers=T))
    assert out["override_at"] and out["override_by"]
    _ok(_start(live_client, exam["id"], S))
    assert _start(live_client, exam["id"], S2).status_code == 409
    st = _ok(live_client.get(f"/bluebook/me/exams/{exam['id']}/phone-park?code=0", headers=S))
    assert st["overridden"] is True and st["parked"] is False
    tiles = [t for t in _ok(live_client.get(f"/bluebook/exams/{exam['id']}/phone-park", headers=T))["students"]
             if t["student_id"] == sid]
    assert tiles[0]["override_note"] == "No phone with them today" and tiles[0]["override_by"]
    res = get_repository().list_audit(student_id=sid, action="bluebook_phone_park_override")
    rows = next(v for v in res.values() if isinstance(v, list))
    assert len(rows) == 1
    # A student id from another workspace is refused.
    assert live_client.post(f"/bluebook/exams/{exam['id']}/phone-park/other-tenant:abc/override",
                            json={}, headers=T).status_code == 404


@pytest.mark.slow
def test_a_sitting_already_under_way_is_never_held_up(live_client):
    T, [(sid, S), _] = _workspace(live_client, "pp6@example.test")
    exam = _exam(live_client, T, False)
    _ok(_start(live_client, exam["id"], S))
    # The teacher turns it on mid-sitting: the student can still resume.
    _ok(live_client.patch(f"/bluebook/exams/{exam['id']}", json={"conditions": {"aiDetect": False, "phonePark": True}}, headers=T))
    _ok(_start(live_client, exam["id"], S))


@pytest.mark.slow
def test_withdrawal_deletes_phone_data(live_client):
    T, [(sid, S), _] = _workspace(live_client, "pp7@example.test")
    exam = _exam(live_client, T, True)
    _, token = _code(live_client, exam["id"], S)
    scanned = _ok(live_client.post("/bluebook/phone-park/scan", json={"token": token}))
    assert get_repository().get_phone_park(exam["id"], sid) is not None
    assert get_repository().delete_student(sid) is True
    assert get_repository().get_phone_park(exam["id"], sid) is None
    # A phone still open after withdrawal re-creates nothing.
    time.sleep(0)
    r = live_client.post("/bluebook/phone-park/beat", json={"beat_token": scanned["beat_token"]})
    assert r.status_code == 404
    assert get_repository().get_phone_park(exam["id"], sid) is None
