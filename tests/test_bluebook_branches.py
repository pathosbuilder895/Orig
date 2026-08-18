"""
Branch-coverage tests for GET /bluebook/launch (original/routers/bluebook.py:
bluebook_magic_launch) — the magic-link no-Canvas fallback launch endpoint.

Not exercised anywhere else in the suite: tests/test_bluebook_api.py and
tests/test_bluebook_crud.py drive session/submission/exam/course CRUD but
never redeem a launch token (see the "does not attempt to restore ...
SECRET_KEY-lifespan coverage" note at the top of test_bluebook_api.py).

Tokens are minted with original/student_auth.py's own helpers — the same
functions roster_links.py (production) and lti.py (the LTI launch sibling)
use — so "invalid token" here means a structurally well-formed token that
fails verify_launch_token's own checks (expired / bad signature / wrong
typ), not a hand-rolled fake.

Uses the live_app/live_client/store_reset fixtures from tests/conftest.py,
same as the sibling Bluebook test files.
"""

from __future__ import annotations

from original import student_auth

_TENANT = "bbrx"


# ── Invalid / unusable tokens → 400, body-is-None arm ──────────────────────


def test_launch_missing_token_400(live_client, store_reset):
    """No `t` query param at all (defaults to "") — verify_launch_token
    rejects it immediately (`"." not in token`)."""
    r = live_client.get("/bluebook/launch")
    assert r.status_code == 400, r.text
    assert "invalid or has expired" in r.json()["detail"]


def test_launch_expired_token_400(live_client, store_reset):
    """A structurally valid, correctly signed token whose exp is already in
    the past."""
    token = student_auth.mint_launch_token(
        "bbrx:expiredstudent", _TENANT, exam="exam-1", name="", ttl_seconds=-10
    )
    r = live_client.get("/bluebook/launch", params={"t": token})
    assert r.status_code == 400, r.text


def test_launch_bad_signature_token_400(live_client, store_reset):
    """Same payload as a valid token, but the trailing HMAC signature is
    corrupted — hmac.compare_digest must reject it."""
    token = student_auth.mint_launch_token("bbrx:sigstudent", _TENANT, exam="exam-1")
    payload, sig = token.split(".", 1)
    flipped = ("A" if sig[-1] != "A" else "B")
    bad_token = f"{payload}.{sig[:-1]}{flipped}"
    r = live_client.get("/bluebook/launch", params={"t": bad_token})
    assert r.status_code == 400, r.text


def test_launch_malformed_token_400(live_client, store_reset):
    """Not `payload.signature`-shaped at all (no '.') — rejected before any
    decoding is attempted."""
    r = live_client.get("/bluebook/launch", params={"t": "not-a-launch-token"})
    assert r.status_code == 400, r.text


def test_launch_missing_sid_400(live_client, store_reset):
    """A validly signed, unexpired launch token whose bound student id is
    empty: verify_launch_token accepts it (the "sid" key is present), but
    the handler's own `if not sid` guard rejects it — the one arm where
    `body` is truthy but the request still 400s."""
    token = student_auth.mint_launch_token("", _TENANT, exam="exam-1", name="")
    r = live_client.get("/bluebook/launch", params={"t": token})
    assert r.status_code == 400, r.text
    assert "missing its student binding" in r.json()["detail"]


# ── Valid tokens → 200, localStorage-seed + redirect ───────────────────────


def test_launch_success_with_name_and_exam(live_client, store_reset):
    """A full launch token (student, tenant, exam, and an opted-in display
    name) — covers the `if name:` True arm (best-effort set_display_name)
    and the `if params:` True arm (redirect carries ?exam=&candidate=)."""
    import original.api as api_mod

    sid = "bbrx:launchstudent1"
    token = student_auth.mint_launch_token(sid, _TENANT, exam="exam-9", name="Jane Doe")
    r = live_client.get("/bluebook/launch", params={"t": token})
    assert r.status_code == 200, r.text
    body = r.text
    assert f'localStorage.setItem("bluebook_student_id","{sid}")' in body
    assert f'localStorage.setItem("original_tenant","{_TENANT}")' in body
    assert "original_session_token" in body
    assert "bluebook_proctor_token" in body
    assert 'var u="/bluebook/?exam=exam-9&candidate=Jane+Doe";' in body

    # The name-set try-branch actually ran and persisted (best-effort, not
    # just line-covered).
    assert api_mod._repo().get_display_name(sid) == "Jane Doe"


def test_launch_success_without_name_or_exam(live_client, store_reset):
    """A launch token with no exam and no display name (the default,
    FERPA-preferred, name-free link) — covers the `if name:` False arm
    (skip set_display_name) and the `if params:` False arm (bare
    redirect, no query string)."""
    sid = "bbrx:launchstudent2"
    token = student_auth.mint_launch_token(sid, _TENANT, exam="", name="")
    r = live_client.get("/bluebook/launch", params={"t": token})
    assert r.status_code == 200, r.text
    body = r.text
    assert f'localStorage.setItem("bluebook_student_id","{sid}")' in body
    assert 'var u="/bluebook/";' in body
    assert "candidate=" not in body
