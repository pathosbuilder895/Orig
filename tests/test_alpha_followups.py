"""Alpha follow-ups: server-side student terms record, /me/voice hidden from
students in the pilot, and the explainer's writing-consistency wording."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from original import principal as principal_mod
from original import student_auth
from original.onboarding import set_original
from original.repository import get_repository
from original.routers.auth import TERMS_VERSION

PW = "s3cret-passw0rd"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate(store_reset, live_app):
    import original.api as api

    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()
    yield
    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _invite(client, email):
    r = client.post(
        "/auth/signup",
        json={"email": "prof@school.edu", "password": PW, "name": "Prof", "accept_terms": True},
    )
    assert r.status_code == 201, r.text
    prof = r.json()
    set_original("prof@school.edu", True)
    course = client.post(
        "/bluebook/courses", json={"name": "Alpha", "code": "A"}, headers=_auth(prof["token"])
    ).json()["id"]
    row = client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": email, "name": "Stu"}]},
        headers=_auth(prof["token"]),
    ).json()["students"][0]
    return parse_qs(urlparse(row["invite_path"]).query)["invite"][0]


def _redeems(email):
    items = get_repository().list_audit(action="invite_redeem", limit=50)["items"]
    return [i for i in items if i.get("actor") == email]


def test_student_terms_acceptance_is_recorded(live_client):
    tok = _invite(live_client, "s1@school.edu")
    r = live_client.post(
        "/auth/invite/redeem", json={"token": tok, "password": PW, "accept_terms": True}
    )
    assert r.status_code == 200, r.text
    rows = _redeems("s1@school.edu")
    assert len(rows) == 1
    assert (rows[0].get("details") or {}).get("terms_version") == TERMS_VERSION


def test_student_without_terms_box_still_redeems_and_records_nothing(live_client):
    tok = _invite(live_client, "s2@school.edu")
    r = live_client.post("/auth/invite/redeem", json={"token": tok, "password": PW})
    assert r.status_code == 200, r.text
    rows = _redeems("s2@school.edu")
    assert len(rows) == 1
    assert not (rows[0].get("details") or {}).get("terms_version")


def test_me_voice_refused_for_students_by_default(live_client, monkeypatch):
    monkeypatch.delenv("STUDENT_ORIGINAL_PAGES", raising=False)
    token = student_auth.mint_session("t-x:stu-1", "Stu")
    r = live_client.get("/me/voice", headers=_auth(token))
    assert r.status_code == 403, r.text


def test_me_voice_refused_when_flag_off(live_client, monkeypatch):
    monkeypatch.setenv("STUDENT_ORIGINAL_PAGES", "0")
    token = student_auth.mint_session("t-x:stu-1", "Stu")
    assert live_client.get("/me/voice", headers=_auth(token)).status_code == 403
    assert live_client.get("/me/voice").status_code == 401


def test_me_voice_available_when_flag_on(live_client, monkeypatch):
    monkeypatch.setenv("STUDENT_ORIGINAL_PAGES", "1")
    token = student_auth.mint_session("t-x:stu-1", "Stu")
    assert live_client.get("/me/voice", headers=_auth(token)).status_code == 200


def test_explainer_uses_writing_consistency_framing():
    html = (ROOT / "demo/_components/explainer.html").read_text().lower()
    for banned in ("authenticity", "ai detection", "cheating", "authorship verification",
                   "fingerprint"):
        assert banned not in html, banned
    assert "writing-consistency reading" in html
    assert "in testing" in html
    assert "inconclusive" in html
