"""Collection options (Collections merge, PR 2): untimed sittings,
in-class vs take-home trust, and the Smalls/Greats word-range preset.

Spec: /workspace/collections_merge_spec.md, decisions from Andrew 2026-10-20:
- Smalls < 1,000 words, Greats >= 1,000 words.
- Untimed: no time limit; the sitting stays open until the collection's
  close time (deadline = closes_at), or has no deadline when there is none.
  Never a huge fake duration.
- Take-home work joins a baseline only as an extension, one paper at a time,
  after the professor approves it and the drift gate finds it not
  substantially different; it is never stored as proctored.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from original import bluebook_rules as rules
from original import principal as principal_mod
from original.onboarding import set_original
from original.repository import get_repository

PW = "s3cret-passw0rd"
BASE = (
    "Augustine argues that the restless heart finds rest only in God, and he builds the "
    "argument slowly, from memory and desire, through the long middle books of the work, "
    "until the reader sees that the search was the subject all along. I find the argument "
    "persuasive in its account of desire but less so in its account of memory, which seems "
    "to me to carry more of the weight than he admits."
)


@pytest.fixture(autouse=True)
def _isolate(store_reset, live_app):
    import original.api as api

    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()
    yield
    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _prof(client, email="prof@school.edu", original=True):
    r = client.post(
        "/auth/signup",
        json={"email": email, "password": PW, "name": "Prof", "accept_terms": True},
    )
    assert r.status_code == 201, r.text
    prof = r.json()
    if original:
        set_original(email, True)
    course = client.post(
        "/bluebook/courses", json={"name": "Alpha", "code": "A 101"}, headers=_auth(prof["token"])
    ).json()["id"]
    return prof, course


def _exam(client, prof, course, **body):
    payload = {"title": "Essay", "status": "ACTIVE", "prompt": "Discuss.", "course_id": course}
    payload.update(body)
    r = client.post("/bluebook/exams", json=payload, headers=_auth(prof["token"]))
    return r


def _student(client, prof, course, email="stu@school.edu"):
    row = client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": email, "name": email.split("@")[0]}]},
        headers=_auth(prof["token"]),
    ).json()["students"][0]
    token = parse_qs(urlparse(row["invite_path"]).query)["invite"][0]
    r = client.post("/auth/invite/redeem", json={"token": token, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()


def _seal(client, student, exam_id, text=BASE, words=None):
    client.post(f"/bluebook/me/exams/{exam_id}/start", headers=_auth(student["token"]))
    body = {
        "exam_id": exam_id,
        "student_id": student["student_id"],
        "word_count": words if words is not None else len(text.split()),
        "text": text,
        "answers": [text],
        "submission_uuid": f"uuid-{student['student_id']}-{exam_id}",
    }
    r = client.post("/bluebook/submissions", json=body, headers=_auth(student["token"]))
    assert r.status_code == 201, r.text
    return r.json()


# ── rules ──────────────────────────────────────────────────────────────────────


def test_smalls_greats_cutoff_is_1000_words():
    assert rules.SMALLS_GREATS_CUTOFF == 1000
    assert rules.size_class({"minWords": 0, "maxWords": 999, "conditions": {}}) == "small"
    assert rules.size_class({"minWords": 1000, "maxWords": 0, "conditions": {}}) == "great"
    assert rules.size_class({"minWords": 0, "maxWords": 0, "conditions": {}}) is None
    assert rules.size_class({"minWords": 0, "maxWords": 0, "conditions": {"size": "great"}}) == "great"


def test_timing_and_setting_default_to_timed_in_class_for_old_rows():
    old = {"duration": 120, "minWords": 0, "conditions": {}}
    assert rules.is_timed(old) is True
    assert rules.setting(old) == "in_class"
    assert rules.setting({"conditions": None}) == "in_class"


def test_untimed_deadline_is_the_close_time_or_none():
    now = datetime(2026, 10, 20, 16, 0, tzinfo=UTC)
    untimed = {"duration": 25, "conditions": {"timed": False}}
    assert rules.session_seconds(untimed, now) is None
    closes = now + timedelta(days=3)
    with_close = {**untimed, "closes_at": closes.isoformat()}
    assert rules.session_seconds(with_close, now) == int((closes - now).total_seconds())
    # Timed sittings are unchanged: the duration, clipped to the close time.
    assert rules.session_seconds({"duration": 25, "conditions": {}}, now) == 25 * 60


@pytest.mark.parametrize(
    "conditions,min_w,max_w,expected",
    [
        ({"size": "small"}, 0, 0, (0, 999)),
        ({"size": "great"}, 0, 0, (1000, 0)),
        ({"size": "small"}, 200, 800, (200, 800)),
        ({"size": "great"}, 1200, 3000, (1200, 3000)),
        ({}, 0, 0, (0, 0)),
    ],
)
def test_size_preset_fills_the_word_range(conditions, min_w, max_w, expected):
    _, lo, hi = rules.collection_options(conditions, min_w, max_w)
    assert (lo, hi) == expected


@pytest.mark.parametrize(
    "conditions,min_w,max_w",
    [
        ({"size": "small"}, 0, 1500),
        ({"size": "great"}, 500, 0),
        ({"size": "medium"}, 0, 0),
        ({"setting": "online"}, 0, 0),
        ({"timed": "sometimes"}, 0, 0),
    ],
)
def test_inconsistent_options_are_refused(conditions, min_w, max_w):
    with pytest.raises(ValueError):
        rules.collection_options(conditions, min_w, max_w)


# ── API: create ────────────────────────────────────────────────────────────────


def test_create_applies_the_greats_preset(live_client):
    prof, course = _prof(live_client)
    r = _exam(live_client, prof, course, conditions={"size": "great", "setting": "take_home"})
    assert r.status_code == 201, r.text
    assert (r.json()["minWords"], r.json()["maxWords"]) == (1000, 0)
    assert r.json()["conditions"]["setting"] == "take_home"


def test_create_refuses_a_small_with_a_long_range(live_client):
    prof, course = _prof(live_client)
    r = _exam(live_client, prof, course, maxWords=2000, conditions={"size": "small"})
    assert r.status_code == 422


def test_patch_checks_the_options_too(live_client):
    prof, course = _prof(live_client)
    exam = _exam(live_client, prof, course).json()
    r = live_client.patch(
        f"/bluebook/exams/{exam['id']}",
        json={"conditions": {"setting": "nowhere"}},
        headers=_auth(prof["token"]),
    )
    assert r.status_code == 422


# ── API: untimed sittings ──────────────────────────────────────────────────────


def test_untimed_without_close_has_no_deadline_and_is_never_late(live_client):
    prof, course = _prof(live_client)
    exam = _exam(live_client, prof, course, duration=25, conditions={"timed": False}).json()
    stu = _student(live_client, prof, course)

    r = live_client.post(f"/bluebook/me/exams/{exam['id']}/start", headers=_auth(stu["token"]))

    assert r.status_code == 200, r.text
    assert r.json()["deadline_at"] is None
    assert r.json()["duration_seconds"] is None
    assert get_repository().get_bluebook_session(exam["id"], stu["student_id"]) is None
    assert _seal(live_client, stu, exam["id"])["late"] == 0


def test_untimed_with_close_runs_until_the_close_time(live_client):
    prof, course = _prof(live_client)
    closes = (datetime.now(UTC) + timedelta(days=2)).replace(microsecond=0)
    exam = _exam(
        live_client, prof, course, duration=25, conditions={"timed": False},
        closes_at=closes.isoformat(),
    ).json()
    stu = _student(live_client, prof, course)

    r = live_client.post(f"/bluebook/me/exams/{exam['id']}/start", headers=_auth(stu["token"]))

    deadline = datetime.fromisoformat(r.json()["deadline_at"])
    assert abs((deadline - closes).total_seconds()) <= 2


def test_staff_session_route_follows_the_same_untimed_rule(live_client):
    prof, course = _prof(live_client)
    exam = _exam(live_client, prof, course, conditions={"timed": False}).json()
    r = live_client.post(
        f"/bluebook/exams/{exam['id']}/session",
        json={"candidate": "walk-in@school.edu"},
        headers=_auth(prof["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["deadline_at"] is None
    assert r.json()["duration_seconds"] is None


# ── API: take-home trust ───────────────────────────────────────────────────────


def _proctored_baseline(client, prof, course, stu, n=3):
    for i in range(n):
        ex = _exam(client, prof, course, title=f"In class {i}").json()
        sub = _seal(client, stu, ex["id"], text=f"{BASE} Sitting {i} adds one more plain sentence.")
        r = client.post(f"/bluebook/submissions/{sub['id']}/baseline", headers=_auth(prof["token"]))
        assert r.json()["status"] == "added", r.text


def test_take_home_needs_an_existing_baseline(live_client):
    prof, course = _prof(live_client)
    stu = _student(live_client, prof, course)
    home = _exam(live_client, prof, course, conditions={"setting": "take_home"}).json()
    sub = _seal(live_client, stu, home["id"])

    r = live_client.post(f"/bluebook/submissions/{sub['id']}/baseline", headers=_auth(prof["token"]))

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "needs_baseline"
    state = get_repository().get(stu["student_id"])
    assert state is None or state.sample_count == 0


def test_take_home_extends_a_baseline_as_unverified_never_proctored(live_client):
    prof, course = _prof(live_client)
    stu = _student(live_client, prof, course)
    _proctored_baseline(live_client, prof, course, stu)
    home = _exam(live_client, prof, course, title="Take-home", conditions={"setting": "take_home"}).json()
    sub = _seal(live_client, stu, home["id"], text=f"{BASE} At home I added a closing thought.")

    r = live_client.post(f"/bluebook/submissions/{sub['id']}/baseline", headers=_auth(prof["token"]))

    # Close to the in-class papers, so the drift gate lets it through.
    assert r.json()["status"] == "added", r.text
    state = get_repository().get(stu["student_id"])
    take_home = [s for s in state.samples if s.assignment == "Take-home"]
    assert [s.provenance for s in take_home] == ["unverified"]
    assert all(s.provenance == "proctored" for s in state.samples if s.assignment != "Take-home")


def test_bulk_approval_sets_take_home_aside_for_one_at_a_time_review(live_client):
    prof, course = _prof(live_client)
    stu = _student(live_client, prof, course)
    _proctored_baseline(live_client, prof, course, stu)
    home = _exam(live_client, prof, course, conditions={"setting": "take_home"}).json()
    _seal(live_client, stu, home["id"])

    r = live_client.post(f"/bluebook/exams/{home['id']}/baseline", headers=_auth(prof["token"]))

    assert r.status_code == 200, r.text
    rows = r.json()["results"]
    assert [row["status"] for row in rows] == ["needs_review"]
    assert "take-home" in rows[0]["detail"]


# ── Alpha regression: the live alpha workspace's one exam and submission ──────


def test_the_existing_alpha_exam_and_submission_keep_working(live_client):
    """Shape of workspace t-2c28d5f65bd1: course "Alpha" (A 101), one exam of
    120 minutes with no word minimum and no collection options, and one
    223-word SUBMITTED submission."""
    prof, course = _prof(live_client)
    r = _exam(live_client, prof, course, title="Alpha test", duration=120, minWords=0, conditions={})
    assert r.status_code == 201, r.text
    exam = r.json()
    stu = _student(live_client, prof, course)
    text = " ".join((BASE.split() * 4)[:223])
    sub = _seal(live_client, stu, exam["id"], text=text, words=223)

    listed = live_client.get("/bluebook/exams", headers=_auth(prof["token"])).json()["exams"]
    row = next(e for e in listed if e["id"] == exam["id"])
    assert (row["duration"], row["minWords"], row["submissions"]) == (120, 0, 1)
    assert rules.is_timed(row) and rules.setting(row) == "in_class"
    session = get_repository().get_bluebook_session(exam["id"], stu["student_id"])
    span = datetime.fromisoformat(session["deadline_at"]) - datetime.fromisoformat(session["started_at"])
    assert abs(span.total_seconds() - 120 * 60) <= 2
    one = live_client.get(f"/bluebook/submissions/{sub['id']}", headers=_auth(prof["token"]))
    assert one.status_code == 200, one.text
    assert (one.json()["status"], one.json()["words"]) == ("SUBMITTED", 223)
    approved = live_client.post(f"/bluebook/submissions/{sub['id']}/baseline", headers=_auth(prof["token"]))
    assert approved.json()["status"] == "added"
    assert get_repository().get(stu["student_id"]).samples[0].provenance == "proctored"
