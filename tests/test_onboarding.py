"""Operator onboarding for an invitation-only pilot (SELF_SERVE_SIGNUP=0)."""

from __future__ import annotations

import pytest

from original import mailer
from original import principal as principal_mod
from original.onboarding import invite_professor
from original.repository import get_repository
from scripts import invite_professor as cli


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
    token = out["invite_link"].split("invite=", 1)[1]
    assert (
        live_client.post(
            "/auth/login", json={"email": "p2@seminary.edu", "password": "chosen-passw0rd"}
        ).status_code
        == 401
    )
    r = live_client.post(
        "/auth/invite/redeem", json={"token": token, "password": "chosen-passw0rd"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "professor"
    assert r.json()["products"] == ["bluebook"]
    login = live_client.post(
        "/auth/login", json={"email": "p2@seminary.edu", "password": "chosen-passw0rd"}
    )
    assert login.status_code == 200


@pytest.mark.parametrize("email", ["", "not-an-email"])
def test_invite_rejects_an_invalid_email(email):
    with pytest.raises(ValueError):
        invite_professor(email)


def test_invite_refuses_an_existing_account():
    invite_professor("dup@seminary.edu")
    with pytest.raises(ValueError, match="already exists"):
        invite_professor("dup@seminary.edu")


def test_invite_emails_the_link_when_mail_is_configured(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(
        mailer, "send_professor_invite", lambda to, link: sent.append((to, link)) or True
    )
    out = invite_professor("mail@seminary.edu", base_url="https://x.test")
    assert out["emailed"] is True
    assert sent == [("mail@seminary.edu", out["invite_link"])]


def test_cli_prints_the_link_and_fails_cleanly(capsys):
    assert cli.main(["cli@seminary.edu", "--name", "C", "--base-url", "https://x.test"]) == 0
    assert "https://x.test/bluebook/?invite=" in capsys.readouterr().out
    assert cli.main(["cli@seminary.edu"]) == 1
    assert "already exists" in capsys.readouterr().err


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
