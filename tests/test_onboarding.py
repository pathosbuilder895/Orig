"""Operator onboarding for an invitation-only pilot (SELF_SERVE_SIGNUP=0)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from original import mailer, users
from original import principal as principal_mod
from original.onboarding import invite_professor
from original.repository import get_repository
from original.routers.auth import TERMS_VERSION
from scripts import invite_professor as cli

PW = "chosen-passw0rd"
TERMS_MSG = "Please accept the terms of service and privacy policy."


def _token(link: str, param: str = "invite") -> str:
    return parse_qs(urlparse(link).query)[param][0]


def _redeem_audit(tenant_id: str) -> dict:
    items = get_repository().list_audit(action="invite_redeem", tenant_id=tenant_id)["items"]
    return items[0]["details"]


@pytest.fixture(autouse=True)
def _isolate(store_reset, live_app, monkeypatch):
    import original.api as api

    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setattr(mailer, "configured", lambda: False)
    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()
    yield
    api._login_attempts.clear()
    principal_mod.invalidate_tenant_cache()


def test_invite_creates_a_bluebook_only_workspace_and_an_inactive_professor():
    out = invite_professor("Prof@Seminary.edu", "Dr Prof", "https://bluebook.example.test")
    repo = get_repository()
    assert out["email"] == "prof@seminary.edu"
    assert out["emailed"] is False
    assert out["invite_link"].startswith("https://bluebook.example.test/bluebook/?invite=")
    assert repo.get_tenant(out["tenant_id"])["products"] == ["bluebook"]
    user = repo.get_user_by_email("prof@seminary.edu")
    assert user["role"] == "professor"
    assert user["tenant_id"] == out["tenant_id"]


def test_invited_professor_sets_a_password_and_signs_in(live_client):
    out = invite_professor("p2@seminary.edu", "P Two", "https://x.test")
    # The SPA shows the terms checkbox when the link says so.
    assert out["invite_link"].endswith("&terms=1")
    token = _token(out["invite_link"])
    assert (
        live_client.post(
            "/auth/login", json={"email": "p2@seminary.edu", "password": "chosen-passw0rd"}
        ).status_code
        == 401
    )
    r = live_client.post(
        "/auth/invite/redeem",
        json={"token": token, "password": "chosen-passw0rd", "accept_terms": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "professor"
    assert r.json()["products"] == ["bluebook"]
    login = live_client.post(
        "/auth/login", json={"email": "p2@seminary.edu", "password": "chosen-passw0rd"}
    )
    assert login.status_code == 200


def test_invited_professor_must_accept_the_terms_and_a_refusal_keeps_the_link(live_client):
    out = invite_professor("terms@seminary.edu", base_url="https://x.test")
    token = _token(out["invite_link"])
    # The server enforces this whatever the URL said (a link that lost its
    # terms=1, or a ?reset= link for a professor who never activated).
    refused = live_client.post("/auth/invite/redeem", json={"token": token, "password": PW})
    assert refused.status_code == 422
    assert refused.json()["detail"] == TERMS_MSG
    assert not users.is_activated(get_repository().get_user_by_email("terms@seminary.edu"))
    ok = live_client.post(
        "/auth/invite/redeem", json={"token": token, "password": PW, "accept_terms": True}
    )
    assert ok.status_code == 200, ok.text
    assert _redeem_audit(out["tenant_id"])["terms_version"] == TERMS_VERSION


def test_activated_professor_password_reset_needs_no_terms(live_client, monkeypatch):
    out = invite_professor("reset@seminary.edu", base_url="https://x.test")
    first = live_client.post(
        "/auth/invite/redeem",
        json={"token": _token(out["invite_link"]), "password": PW, "accept_terms": True},
    )
    assert first.status_code == 200, first.text
    links = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send_reset", lambda to, link: links.append(link) or True)
    live_client.post("/auth/password-reset/request", json={"email": "reset@seminary.edu"})
    r = live_client.post(
        "/auth/invite/redeem",
        json={"token": _token(links[0], "reset"), "password": "fresh-passw0rd"},
    )
    assert r.status_code == 200, r.text
    assert "terms_version" not in _redeem_audit(out["tenant_id"])


@pytest.mark.parametrize("email", ["", "not-an-email"])
def test_invite_rejects_an_invalid_email(email):
    with pytest.raises(ValueError):
        invite_professor(email)


def test_rerunning_the_invite_reissues_for_an_unactivated_professor(live_client):
    first = invite_professor("dup@seminary.edu", base_url="https://x.test")
    second = invite_professor("dup@seminary.edu", base_url="https://x.test")
    assert first["reissued"] is False
    assert second["reissued"] is True
    assert second["invite_link"] != first["invite_link"]
    assert second["invite_link"].endswith("&terms=1")
    assert (second["tenant_id"], second["user_id"]) == (first["tenant_id"], first["user_id"])
    reissues = get_repository().list_audit(
        action="professor_invite_reissue", tenant_id=first["tenant_id"]
    )
    assert reissues["total"] == 1
    old = live_client.post(
        "/auth/invite/redeem",
        json={"token": _token(first["invite_link"]), "password": PW, "accept_terms": True},
    )
    assert old.status_code == 400
    new = live_client.post(
        "/auth/invite/redeem",
        json={"token": _token(second["invite_link"]), "password": PW, "accept_terms": True},
    )
    assert new.status_code == 200, new.text
    assert new.json()["tenant_id"] == first["tenant_id"]


def test_invite_refuses_an_activated_professor(live_client):
    out = invite_professor("active@seminary.edu", base_url="https://x.test")
    r = live_client.post(
        "/auth/invite/redeem",
        json={"token": _token(out["invite_link"]), "password": PW, "accept_terms": True},
    )
    assert r.status_code == 200, r.text
    with pytest.raises(ValueError, match="already exists"):
        invite_professor("active@seminary.edu", base_url="https://x.test")


def test_invite_refuses_an_email_owned_by_a_student():
    users.create_student_account("t-course", "learner@seminary.edu", "Learner")
    with pytest.raises(ValueError, match="already exists"):
        invite_professor("learner@seminary.edu", base_url="https://x.test")
    assert get_repository().get_user_by_email("learner@seminary.edu")["role"] == "student"


def test_a_relative_link_is_never_emailed(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(
        mailer, "send_professor_invite", lambda to, link: sent.append((to, link)) or True
    )
    out = invite_professor("relative@seminary.edu")
    assert out["invite_link"].startswith("/bluebook/?invite=")
    assert out["emailed"] is False
    assert sent == []


def test_invite_emails_the_link_when_mail_is_configured(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(
        mailer, "send_professor_invite", lambda to, link: sent.append((to, link)) or True
    )
    out = invite_professor("mail@seminary.edu", base_url="https://x.test")
    assert out["emailed"] is True
    assert sent == [("mail@seminary.edu", out["invite_link"])]


def test_cli_prints_the_backend_and_the_link(capsys, monkeypatch):
    monkeypatch.delenv("REPO_BACKEND", raising=False)
    monkeypatch.delenv("REPO_SHADOW", raising=False)
    assert cli.main(["cli@seminary.edu", "--name", "C", "--base-url", "https://x.test"]) == 0
    out = capsys.readouterr().out
    assert "Database backend: sqlite" in out
    assert "https://x.test/bluebook/?invite=" in out
    assert "Existing unactivated professor" not in out


def test_cli_names_the_backend_it_wrote_to(capsys, monkeypatch):
    monkeypatch.setattr(cli, "backend_name", lambda: "postgres")
    assert cli.main(["pg@seminary.edu", "--base-url", "https://x.test"]) == 0
    assert "Database backend: postgres" in capsys.readouterr().out


def test_cli_reissues_and_warns_about_a_relative_link(capsys):
    assert cli.main(["again@seminary.edu", "--base-url", "https://x.test"]) == 0
    capsys.readouterr()
    assert cli.main(["again@seminary.edu"]) == 0
    captured = capsys.readouterr()
    assert (
        "Existing unactivated professor: issued a new link (earlier links no longer work)."
        in captured.out
    )
    assert "/bluebook/?invite=" in captured.out
    warning = captured.err
    assert "relative" in warning
    assert "PUBLIC_BASE_URL" in warning and "--base-url" in warning


def test_cli_fails_cleanly(capsys):
    assert cli.main(["not-an-email"]) == 1
    assert "valid email" in capsys.readouterr().err


def test_professor_invite_email_text(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        mailer,
        "send",
        lambda to, subject, text: captured.update(to=to, subject=subject, text=text) or True,
    )
    assert mailer.send_professor_invite("p@x.edu", "https://x.test/bluebook/?invite=abc") is True
    assert captured["subject"] == "Your Bluebook workspace is ready"
    assert "https://x.test/bluebook/?invite=abc" in captured["text"]
