"""QR phone-park endpoint tests (T8) — original/routers/proctor.py.

Time is injected, never slept. Every deadline this feature has (the 6h token
TTL, the 24h purge, the 30s dropped threshold, the 1/s beat floor) is read
through ``proctor._now``, so these tests move a fake clock instead of blocking
the suite for half a minute to watch a tile go stale.

The privacy assertions here are deliberate: "stores no IP / user-agent /
roster id" is a requirement, and a requirement nobody tests is a comment.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from original.routers import proctor

PW = "s3cret-passw0rd"
T0 = datetime(2026, 7, 20, 9, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_park(monkeypatch):
    """Fresh throttle window + a frozen clock for every test."""
    proctor._reset_beat_throttle()
    import original.api as _api

    _api._login_attempts.clear()
    yield
    proctor._reset_beat_throttle()


@pytest.fixture
def clock(monkeypatch):
    """A movable clock. ``clock.set(t)`` / ``clock.advance(seconds=…)``."""

    class Clock:
        def __init__(self):
            self.now = T0

        def set(self, when: datetime):
            self.now = when

        def advance(self, **kwargs):
            self.now = self.now + timedelta(**kwargs)
            return self.now

    c = Clock()
    monkeypatch.setattr(proctor, "_now", lambda: c.now)
    return c


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def _professor(live_client, tenant: str, email: str) -> dict:
    """Register + log in a professor; returns their auth header."""
    live_client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PW,
            "role": "professor",
            "tenant_id": tenant,
            "name": "Dr Test",
        },
    )
    r = live_client.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return _auth(r.json()["token"])


def _student(live_client, email: str, institution: str) -> dict:
    """Sign a student in; returns their auth header (role='student')."""
    r = live_client.post(
        "/student-auth/login",
        json={"email": email, "institution": institution, "name": "Stu"},
    )
    assert r.status_code == 200, r.text
    return _auth(r.json()["token"])


@pytest.fixture
def real_deploy(live_app, monkeypatch):
    """Flip the loaded app into pilot behaviour without reloading it (same
    pattern as tests/test_bluebook_crud.py / test_pilot_lockdown.py)."""
    import original.api as api_mod

    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", True)
    yield


def _open(live_client, headers, exam_session_id="ST501-final") -> dict:
    r = live_client.post(
        "/proctor/park/open", json={"exam_session_id": exam_session_id}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


def _beat(live_client, token, hint, state="parked"):
    return live_client.post(
        "/proctor/park/beat",
        json={"park_token": token, "student_hint": hint, "state": state},
    )


def _status(live_client, headers, exam_session_id="ST501-final"):
    return live_client.get(
        "/proctor/park/status", params={"exam_session_id": exam_session_id}, headers=headers
    )


# ── Route inventory ───────────────────────────────────────────────────────────


def test_park_routes_are_mounted(live_app):
    """The router-split mount style is easy to forget — assert the splice took."""
    live = {(r.path, m) for r in live_app.routes for m in (r.methods or ())}
    for path, method in [
        ("/proctor/park/open", "POST"),
        ("/proctor/park/beat", "POST"),
        ("/proctor/park/status", "GET"),
        ("/proctor/park/{exam_session_id}", "DELETE"),
    ]:
        assert (path, method) in live, f"missing {method} {path}"


# ── open ──────────────────────────────────────────────────────────────────────


def test_open_returns_token_and_qr_url(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "open@sem.edu")
    body = _open(live_client, headers)

    assert body["park_token"]
    assert len(body["park_token"]) >= 20  # token_urlsafe(16)
    assert body["qr_url"].endswith(f"/bluebook/parked.html?t={body['park_token']}")
    assert body["qr_url"].startswith("http://")


def test_open_response_carries_nothing_but_the_contract(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "open2@sem.edu")
    assert set(_open(live_client, headers)) == {"park_token", "qr_url"}


def test_reopen_returns_the_same_live_token(store_reset, live_client, clock):
    """A professor reloading the proctor view must not strand parked phones."""
    headers = _professor(live_client, "sem-dallas", "reopen@sem.edu")
    first = _open(live_client, headers)
    clock.advance(minutes=45)
    second = _open(live_client, headers)
    assert second["park_token"] == first["park_token"]


def test_reopen_after_the_ttl_rotates_the_token(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "rotate@sem.edu")
    first = _open(live_client, headers)
    clock.advance(seconds=proctor.PARK_TTL_SECONDS + 1)
    second = _open(live_client, headers)
    assert second["park_token"] != first["park_token"]
    # …and the dead token is genuinely dead.
    assert _beat(live_client, first["park_token"], "AB").status_code == 404


def test_open_rejects_a_student_principal(store_reset, live_client, clock):
    """A signed-in student must not be able to open a park, in any environment."""
    headers = _student(live_client, "stu@sem.edu", "Seminary of Dallas")
    r = live_client.post(
        "/proctor/park/open", json={"exam_session_id": "ST501-final"}, headers=headers
    )
    assert r.status_code == 403, r.text


def test_open_requires_a_staff_login_on_a_real_deploy(real_deploy, store_reset, live_client, clock):
    """Off a real deploy the anonymous sandbox principal is fine; on one it is not."""
    r = live_client.post("/proctor/park/open", json={"exam_session_id": "ST501-final"})
    assert r.status_code == 401, r.text


def test_open_rejects_empty_exam_session_id(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "empty@sem.edu")
    r = live_client.post("/proctor/park/open", json={"exam_session_id": "   "}, headers=headers)
    assert r.status_code == 422, r.text


# ── beat ──────────────────────────────────────────────────────────────────────


def test_beat_is_anonymous(store_reset, live_client, clock):
    """The phone has no login — the token is the whole capability."""
    headers = _professor(live_client, "sem-dallas", "anon@sem.edu")
    token = _open(live_client, headers)["park_token"]

    r = _beat(live_client, token, "M.R.")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_beat_rejects_unknown_token(store_reset, live_client, clock):
    assert _beat(live_client, "no-such-token", "AB").status_code == 404


def test_beat_rejects_expired_token(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "expire@sem.edu")
    token = _open(live_client, headers)["park_token"]
    assert _beat(live_client, token, "AB").status_code == 200

    clock.advance(seconds=proctor.PARK_TTL_SECONDS + 1)
    assert _beat(live_client, token, "AB").status_code == 404


def test_beat_rejects_empty_hint(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "hint@sem.edu")
    token = _open(live_client, headers)["park_token"]
    assert _beat(live_client, token, "   ").status_code == 422


def test_beat_rejects_overlong_hint(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "long@sem.edu")
    token = _open(live_client, headers)["park_token"]
    over = "x" * (proctor.STUDENT_HINT_MAX_LEN + 1)
    assert _beat(live_client, token, over).status_code == 422
    assert _beat(live_client, token, "y" * proctor.STUDENT_HINT_MAX_LEN).status_code == 200


def test_beat_strips_whitespace_from_hint(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "strip@sem.edu")
    token = _open(live_client, headers)["park_token"]
    assert _beat(live_client, token, "  M.R.  ").status_code == 200

    (tile,) = _status(live_client, headers).json()["tiles"]
    assert tile["student_hint"] == "M.R."


def test_beat_rejects_unknown_state(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "state@sem.edu")
    token = _open(live_client, headers)["park_token"]
    assert _beat(live_client, token, "AB", state="cheating").status_code == 422


def test_beats_faster_than_one_per_second_are_throttled(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "throttle@sem.edu")
    token = _open(live_client, headers)["park_token"]

    assert _beat(live_client, token, "AB").status_code == 200
    clock.advance(milliseconds=200)
    assert _beat(live_client, token, "AB").status_code == 429

    clock.advance(seconds=1)
    assert _beat(live_client, token, "AB").status_code == 200


def test_throttle_is_per_hint_not_per_session(store_reset, live_client, clock):
    """Two phones on one exam are not each other's rate limit."""
    headers = _professor(live_client, "sem-dallas", "perhint@sem.edu")
    token = _open(live_client, headers)["park_token"]

    assert _beat(live_client, token, "AA").status_code == 200
    assert _beat(live_client, token, "BB").status_code == 200


def test_a_throttled_beat_is_not_recorded(store_reset, live_client, clock):
    """A rejected beat must not count as liveness or as a transition."""
    headers = _professor(live_client, "sem-dallas", "notrec@sem.edu")
    token = _open(live_client, headers)["park_token"]

    assert _beat(live_client, token, "AB", state="parked").status_code == 200
    clock.advance(milliseconds=100)
    assert _beat(live_client, token, "AB", state="foreground_lost").status_code == 429

    (tile,) = _status(live_client, headers).json()["tiles"]
    assert tile["state"] == "parked"
    assert len(tile["transitions"]) == 1


# ── status ────────────────────────────────────────────────────────────────────


def test_status_requires_staff(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "sgate@sem.edu")
    _open(live_client, headers)
    r = live_client.get(
        "/proctor/park/status",
        params={"exam_session_id": "ST501-final"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code in (401, 403), r.text


def test_status_tile_shape_matches_the_contract(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "shape@sem.edu")
    token = _open(live_client, headers)["park_token"]
    _beat(live_client, token, "M.R.")

    body = _status(live_client, headers).json()
    assert set(body) == {"tiles"}
    (tile,) = body["tiles"]
    assert set(tile) == {"student_hint", "state", "last_seen_seconds_ago", "transitions"}
    assert tile["student_hint"] == "M.R."
    assert tile["state"] == "parked"
    assert tile["last_seen_seconds_ago"] == 0
    assert [t["state"] for t in tile["transitions"]] == ["parked"]
    assert set(tile["transitions"][0]) == {"state", "at"}


def test_status_is_empty_before_any_phone_parks(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "empty2@sem.edu")
    _open(live_client, headers)
    assert _status(live_client, headers).json() == {"tiles": []}


def test_status_404s_for_an_unopened_session(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "unopened@sem.edu")
    assert _status(live_client, headers, "never-opened").status_code == 404


def test_a_phone_that_stops_beating_reads_dropped(store_reset, live_client, clock):
    """The derived-state rule — the whole point of the feature."""
    headers = _professor(live_client, "sem-dallas", "drop@sem.edu")
    token = _open(live_client, headers)["park_token"]
    _beat(live_client, token, "M.R.", state="parked")

    clock.advance(seconds=proctor.PARK_DROPPED_AFTER_SECONDS)
    (tile,) = _status(live_client, headers).json()["tiles"]
    assert tile["state"] == "parked"  # exactly at the threshold: still fine
    assert tile["last_seen_seconds_ago"] == 30

    clock.advance(seconds=1)
    (tile,) = _status(live_client, headers).json()["tiles"]
    assert tile["state"] == "dropped"
    assert tile["last_seen_seconds_ago"] == 31


def test_dropped_overrides_whatever_the_phone_last_claimed(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "drop2@sem.edu")
    token = _open(live_client, headers)["park_token"]
    _beat(live_client, token, "M.R.", state="parked")
    clock.advance(seconds=2)
    _beat(live_client, token, "M.R.", state="resumed")

    clock.advance(seconds=90)
    (tile,) = _status(live_client, headers).json()["tiles"]
    assert tile["state"] == "dropped"
    # The record of what it *did* report is preserved.
    assert [t["state"] for t in tile["transitions"]] == ["parked", "resumed"]


def test_a_resumed_phone_stops_reading_dropped(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "back@sem.edu")
    token = _open(live_client, headers)["park_token"]
    _beat(live_client, token, "M.R.", state="parked")

    clock.advance(seconds=60)
    assert _status(live_client, headers).json()["tiles"][0]["state"] == "dropped"

    _beat(live_client, token, "M.R.", state="resumed")
    (tile,) = _status(live_client, headers).json()["tiles"]
    assert tile["state"] == "resumed"
    assert tile["last_seen_seconds_ago"] == 0


def test_ten_identical_beats_make_one_transition(store_reset, live_client, clock):
    """A 10s heartbeat is liveness, not a log source."""
    headers = _professor(live_client, "sem-dallas", "dedupe@sem.edu")
    token = _open(live_client, headers)["park_token"]

    for _ in range(10):
        assert _beat(live_client, token, "J.T.", state="parked").status_code == 200
        clock.advance(seconds=10)

    (tile,) = _status(live_client, headers).json()["tiles"]
    assert len(tile["transitions"]) == 1
    assert tile["transitions"][0]["state"] == "parked"


def test_leaving_and_returning_is_recorded_as_transitions(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "trans@sem.edu")
    token = _open(live_client, headers)["park_token"]

    for state in ["parked", "parked", "foreground_lost", "foreground_lost", "resumed"]:
        _beat(live_client, token, "K.L.", state=state)
        clock.advance(seconds=10)

    (tile,) = _status(live_client, headers).json()["tiles"]
    assert [t["state"] for t in tile["transitions"]] == [
        "parked",
        "foreground_lost",
        "resumed",
    ]


def test_one_tile_per_parked_phone(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "many@sem.edu")
    token = _open(live_client, headers)["park_token"]
    for hint in ["A.A.", "B.B.", "C.C."]:
        _beat(live_client, token, hint)

    tiles = _status(live_client, headers).json()["tiles"]
    assert sorted(t["student_hint"] for t in tiles) == ["A.A.", "B.B.", "C.C."]


# ── Tenant isolation ──────────────────────────────────────────────────────────


def test_cross_tenant_status_read_is_403(store_reset, live_client, clock):
    dallas = _professor(live_client, "sem-dallas", "owner@dallas.edu")
    boston = _professor(live_client, "sem-boston", "intruder@boston.edu")
    _open(live_client, dallas, "shared-exam-id")

    r = _status(live_client, boston, "shared-exam-id")
    assert r.status_code == 403, r.text


def test_cross_tenant_open_of_the_same_id_is_403(store_reset, live_client, clock):
    """exam_session_id is professor-chosen, so collisions are plausible."""
    dallas = _professor(live_client, "sem-dallas", "owner2@dallas.edu")
    boston = _professor(live_client, "sem-boston", "intruder2@boston.edu")
    _open(live_client, dallas, "final-exam")

    r = live_client.post(
        "/proctor/park/open", json={"exam_session_id": "final-exam"}, headers=boston
    )
    assert r.status_code == 403, r.text


def test_cross_tenant_delete_is_403(store_reset, live_client, clock):
    dallas = _professor(live_client, "sem-dallas", "owner3@dallas.edu")
    boston = _professor(live_client, "sem-boston", "intruder3@boston.edu")
    _open(live_client, dallas, "shared-exam-3")

    r = live_client.delete("/proctor/park/shared-exam-3", headers=boston)
    assert r.status_code == 403, r.text
    # …and the owner's data survived the attempt.
    assert _status(live_client, dallas, "shared-exam-3").status_code == 200


# ── delete ────────────────────────────────────────────────────────────────────


def test_delete_removes_the_session_and_its_beats(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "del@sem.edu")
    token = _open(live_client, headers)["park_token"]
    _beat(live_client, token, "A.A.")
    _beat(live_client, token, "B.B.")

    r = live_client.delete("/proctor/park/ST501-final", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 3}  # 2 beats + 1 session row

    assert _status(live_client, headers).status_code == 404
    assert _beat(live_client, token, "A.A.").status_code == 404


def test_delete_requires_staff(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "delgate@sem.edu")
    _open(live_client, headers)
    r = live_client.delete("/proctor/park/ST501-final", headers={"Authorization": "Bearer nope"})
    assert r.status_code in (401, 403), r.text


def test_delete_unknown_session_is_404(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "del404@sem.edu")
    assert live_client.delete("/proctor/park/never-opened", headers=headers).status_code == 404


# ── Retention ─────────────────────────────────────────────────────────────────


def test_opening_a_park_purges_rows_older_than_24h(store_reset, live_client, clock):
    """No scheduler: the sweep rides along on the next open."""
    headers = _professor(live_client, "sem-dallas", "purge@sem.edu")
    token = _open(live_client, headers, "old-exam")["park_token"]
    _beat(live_client, token, "A.A.")

    clock.advance(hours=25)
    _open(live_client, headers, "new-exam")

    assert _status(live_client, headers, "old-exam").status_code == 404
    assert _status(live_client, headers, "new-exam").status_code == 200


def test_purge_spares_rows_inside_the_window(store_reset, live_client, clock):
    headers = _professor(live_client, "sem-dallas", "spare@sem.edu")
    _open(live_client, headers, "recent-exam")

    clock.advance(hours=23)
    _open(live_client, headers, "another-exam")

    assert _status(live_client, headers, "recent-exam").status_code == 200


# ── Privacy contract ──────────────────────────────────────────────────────────


def test_nothing_identifying_is_persisted(store_reset, live_client, clock):
    """The requirement, asserted against the real SQLite file.

    Reads the actual columns rather than the response shape, so a future
    'just add a column' change fails here rather than shipping.
    """
    headers = _professor(live_client, "sem-dallas", "priv@sem.edu")
    token = _open(live_client, headers)["park_token"]
    _beat(live_client, token, "M.R.")

    conn = store_reset._get_conn()
    try:
        columns = set()
        rows = []
        for table in ("park_sessions", "park_beats"):
            columns |= {r[1].lower() for r in conn.execute(f"PRAGMA table_info({table})")}
            rows += [str(r) for r in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()

    assert columns == {
        "exam_session_id",
        "tenant_id",
        "park_token",
        "created_at",
        "student_hint",
        "state",
        "first_seen_at",
        "last_seen_at",
        "transitions_json",
    }
    for forbidden in ("ip", "user_agent", "useragent", "location", "device", "fingerprint"):
        assert not any(forbidden in c for c in columns), forbidden

    # Nor did the professor's identity leak into the rows via the request.
    stored = " ".join(rows)
    assert "priv@sem.edu" not in stored
    assert "testclient" not in stored.lower()  # the TestClient user-agent


def test_the_beat_handler_cannot_see_a_request(store_reset, live_client, clock):
    """Structural guarantee, not a promise: no Request parameter to read from."""
    import inspect

    assert "request" not in inspect.signature(proctor.beat).parameters
