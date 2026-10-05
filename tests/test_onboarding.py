"""Operator onboarding for an invitation-only pilot (SELF_SERVE_SIGNUP=0)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from original import invites, mailer, users
from original import principal as principal_mod
from original.onboarding import invite_professor, set_original
from original.repository import get_repository
from original.routers.auth import TERMS_VERSION
from scripts import invite_professor as cli
from scripts import set_products as products_cli

ROOT = Path(__file__).resolve().parents[1]
PW = "chosen-passw0rd"
TERMS_MSG = "Please accept the terms of service and privacy policy."
INVALID_MSG = "This invite link is invalid, expired, or already used."
T01_MSG = (
    "Original's comparisons are not validated for real student work yet (gap T-01: "
    "frequent false alarms with few baseline samples). Use it only with the owner's "
    "agreement and the institution's consent."
)
APPLIES_MSG = (
    "The server applies this within 30 seconds. Open pages pick it up when the "
    "professor or student next loads their home page or signs in."
)
SHARED_MSG = (
    "WARNING: this is an institution workspace; the change applies to every "
    "professor and student in it."
)
PLAN_403 = "This workspace's plan does not include Original."


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


def _constant(path: str, pattern: str, expected: str) -> str:
    found = re.search(pattern, (ROOT / path).read_text(), re.M)
    assert found, f"{path}: expected a line of the form {expected}"
    return found.group(1)


def test_the_spa_matches_the_servers_terms_refusal_exactly():
    # The SPA reveals the terms checkbox by comparing the server's 422 detail
    # to this string; if either side is reworded the checkbox never appears
    # and an invited professor cannot get in.
    server = _constant(
        "original/routers/auth.py",
        r'^_TERMS_REQUIRED = "([^"]+)"',
        '_TERMS_REQUIRED = "<message>"',
    )
    client = _constant(
        "demo/bluebook/Account.jsx",
        r"^const TERMS_REFUSAL = '([^']+)';",
        "const TERMS_REFUSAL = '<message>';",
    )
    assert client == server


def test_a_reset_link_for_a_professor_who_never_set_a_password_needs_the_terms(
    live_client, monkeypatch
):
    out = invite_professor("never@seminary.edu", base_url="https://x.test")
    links = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send_reset", lambda to, link: links.append(link) or True)
    asked = live_client.post("/auth/password-reset/request", json={"email": "never@seminary.edu"})
    assert asked.status_code == 200, asked.text
    token = _token(links[0], "reset")
    assert "?reset=" in links[0]
    assert not users.is_activated(get_repository().get_user_by_email("never@seminary.edu"))
    refused = live_client.post("/auth/invite/redeem", json={"token": token, "password": PW})
    assert refused.status_code == 422
    assert refused.json()["detail"] == TERMS_MSG
    # The refusal consumed nothing: the same link still works once they accept.
    ok = live_client.post(
        "/auth/invite/redeem", json={"token": token, "password": PW, "accept_terms": True}
    )
    assert ok.status_code == 200, ok.text
    assert users.is_activated(get_repository().get_user_by_email("never@seminary.edu"))
    assert _redeem_audit(out["tenant_id"])["terms_version"] == TERMS_VERSION


def _put_invite(out: dict, token: str, expires_at: datetime) -> None:
    now = datetime.now(UTC)
    get_repository().put_invite(
        {
            "invite_id": f"ob-{token}",
            "tenant_id": out["tenant_id"],
            "user_id": out["user_id"],
            "course_id": None,
            "token_hash": invites.token_hash(token),
            "created_by": "operator",
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
    )


def _professor_token_that_is(kind: str, live_client) -> str:
    """A token for a never-activated professor that is no longer redeemable."""
    out = invite_professor(f"{kind}@seminary.edu", base_url="https://x.test")
    token = _token(out["invite_link"])
    if kind == "voided":
        invite_professor(f"{kind}@seminary.edu", base_url="https://x.test")  # reissue voids it
    elif kind == "used":
        ok = live_client.post(
            "/auth/invite/redeem", json={"token": token, "password": PW, "accept_terms": True}
        )
        assert ok.status_code == 200, ok.text
    elif kind == "expired":
        token = "expired-professor-token"
        _put_invite(out, token, datetime.now(UTC) - timedelta(days=1))
    else:  # pragma: no cover - guards a typo in the parametrization
        raise AssertionError(kind)
    return token


@pytest.mark.parametrize("kind", ["voided", "used", "expired"])
def test_an_unusable_professor_token_gets_the_uniform_400_not_the_terms_422(live_client, kind):
    token = _professor_token_that_is(kind, live_client)
    unknown = live_client.post(
        "/auth/invite/redeem", json={"token": "never-issued-token", "password": PW}
    )
    r = live_client.post("/auth/invite/redeem", json={"token": token, "password": PW})
    assert (unknown.status_code, unknown.json()["detail"]) == (400, INVALID_MSG)
    assert (r.status_code, r.json()["detail"]) == (400, INVALID_MSG)


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


# ── Original on/off per professor (operator) ───────────────────────────────


def _products_audits(tenant_id: str) -> list[dict]:
    return get_repository().list_audit(action="tenant_products_update", tenant_id=tenant_id)[
        "items"
    ]


def test_invite_is_bluebook_only_unless_original_is_asked_for():
    plain = invite_professor("plain@seminary.edu", base_url="https://x.test")
    both = invite_professor("both@seminary.edu", base_url="https://x.test", with_original=True)
    repo = get_repository()
    assert plain["products"] == ["bluebook"]
    assert repo.get_tenant(plain["tenant_id"])["products"] == ["bluebook"]
    assert both["products"] == ["bluebook", "original"]
    assert sorted(repo.get_tenant(both["tenant_id"])["products"]) == ["bluebook", "original"]


def test_reissue_with_original_leaves_the_workspace_products_alone():
    first = invite_professor("re@seminary.edu", base_url="https://x.test")
    again = invite_professor("re@seminary.edu", base_url="https://x.test", with_original=True)
    assert again["reissued"] is True
    assert again["products"] == ["bluebook"]
    assert get_repository().get_tenant(first["tenant_id"])["products"] == ["bluebook"]


def test_set_original_turns_it_on_and_off_and_audits_each_change():
    out = invite_professor("switch@seminary.edu", base_url="https://x.test")
    tid = out["tenant_id"]
    on = set_original("Switch@Seminary.edu", True)
    assert on == {
        "tenant_id": tid,
        "tenant_name": "switch's workspace",
        "email": "switch@seminary.edu",
        "before": ["bluebook"],
        "products": ["bluebook", "original"],
        "changed": True,
        "shared_workspace": False,
    }
    assert sorted(get_repository().get_tenant(tid)["products"]) == ["bluebook", "original"]
    audits = _products_audits(tid)
    assert len(audits) == 1
    assert audits[0]["actor"] == "operator"
    assert audits[0]["details"] == {"products": ["bluebook", "original"], "via": "set_products"}

    off = set_original("switch@seminary.edu", False)
    assert (off["before"], off["products"], off["changed"]) == (
        ["bluebook", "original"],
        ["bluebook"],
        True,
    )
    assert get_repository().get_tenant(tid)["products"] == ["bluebook"]
    assert len(_products_audits(tid)) == 2


def test_set_original_without_a_change_writes_nothing(monkeypatch):
    out = invite_professor("same@seminary.edu", base_url="https://x.test")
    writes = []
    repo = get_repository()
    real = repo.set_tenant_products
    monkeypatch.setattr(repo, "set_tenant_products", lambda *a: writes.append(a) or real(*a))
    res = set_original("same@seminary.edu", False)
    assert (res["before"], res["products"], res["changed"]) == (["bluebook"], ["bluebook"], False)
    assert writes == []
    assert _products_audits(out["tenant_id"]) == []


def test_set_original_refuses_a_student_account():
    users.create_student_account("t-course", "pupil@seminary.edu", "Pupil")
    with pytest.raises(ValueError) as err:
        set_original("pupil@seminary.edu", True)
    assert str(err.value) == (
        "pupil@seminary.edu is a student account. Original is switched per professor "
        "workspace; use the professor's email."
    )


def test_set_original_refuses_an_unknown_email():
    with pytest.raises(ValueError) as err:
        set_original("nobody@seminary.edu", True)
    assert str(err.value) == "No account with nobody@seminary.edu."


def test_set_original_never_leaves_a_workspace_with_no_products():
    out = invite_professor("only@seminary.edu", base_url="https://x.test")
    get_repository().set_tenant_products(out["tenant_id"], ["original"])
    with pytest.raises(ValueError) as err:
        set_original("only@seminary.edu", False)
    assert str(err.value) == "That would leave the workspace with no products."
    assert get_repository().get_tenant(out["tenant_id"])["products"] == ["original"]
    assert _products_audits(out["tenant_id"]) == []


def test_set_original_flags_an_institution_workspace(live_client):
    repo = get_repository()
    repo.put_tenant("inst-sem", "Institution Seminary", environment="pilot", meta={"plan": "x"})
    repo.set_tenant_products("inst-sem", ["bluebook"])
    email = "dean@inst-sem.edu"
    repo.put_user(users._user_id("inst-sem", email), email, "!x", "professor", "inst-sem", "Dean")
    assert set_original(email, True)["shared_workspace"] is True
    # A self-serve signup is a private workspace like an operator invite.
    r = live_client.post(
        "/auth/signup",
        json={"email": "solo@x.edu", "password": PW, "name": "Solo", "accept_terms": True},
    )
    assert r.status_code == 201, r.text
    assert set_original("solo@x.edu", True)["shared_workspace"] is False


def test_the_switch_reaches_the_server_gate(live_client):
    out = invite_professor("gate@seminary.edu", base_url="https://x.test")
    r = live_client.post(
        "/auth/invite/redeem",
        json={"token": _token(out["invite_link"]), "password": PW, "accept_terms": True},
    )
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    before = live_client.get("/students", headers=h)
    assert (before.status_code, before.json()["detail"]) == (403, PLAN_403)
    set_original("gate@seminary.edu", True)
    assert live_client.get("/students", headers=h).status_code == 200
    set_original("gate@seminary.edu", False)
    after = live_client.get("/students", headers=h)
    assert (after.status_code, after.json()["detail"]) == (403, PLAN_403)


def test_invite_cli_prints_the_products(capsys):
    assert cli.main(["p1@seminary.edu", "--base-url", "https://x.test"]) == 0
    out = capsys.readouterr().out
    assert "Products: bluebook\n" in out
    assert T01_MSG not in out
    assert cli.main(["p2@seminary.edu", "--base-url", "https://x.test", "--with-original"]) == 0
    out = capsys.readouterr().out
    assert "Products: bluebook, original\n" in out
    assert T01_MSG in out
    assert "were not changed" not in out


def test_invite_cli_reissue_does_not_change_products(capsys):
    assert cli.main(["p3@seminary.edu", "--base-url", "https://x.test"]) == 0
    capsys.readouterr()
    assert cli.main(["p3@seminary.edu", "--base-url", "https://x.test", "--with-original"]) == 0
    out = capsys.readouterr().out
    assert "Existing workspace products were not changed; use scripts/set_products.py.\n" in out
    assert "Products: bluebook\n" in out
    assert T01_MSG not in out


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line]


def test_set_products_cli_turns_original_on(capsys, monkeypatch):
    monkeypatch.setattr(products_cli, "backend_name", lambda: "postgres")
    out = invite_professor("cli-on@seminary.edu", base_url="https://x.test")
    assert products_cli.main(["cli-on@seminary.edu", "--original", "on"]) == 0
    assert _lines(capsys.readouterr().out) == [
        "Database backend: postgres",
        f"Workspace {out['tenant_id']} (cli-on's workspace)",
        "Products: bluebook -> bluebook, original",
        APPLIES_MSG,
        T01_MSG,
    ]


def test_set_products_cli_turns_original_off_without_the_caution(capsys, monkeypatch):
    monkeypatch.delenv("REPO_BACKEND", raising=False)
    monkeypatch.delenv("REPO_SHADOW", raising=False)
    out = invite_professor("cli-off@seminary.edu", base_url="https://x.test", with_original=True)
    assert products_cli.main(["cli-off@seminary.edu", "--original", "off"]) == 0
    assert _lines(capsys.readouterr().out) == [
        "Database backend: sqlite",
        f"Workspace {out['tenant_id']} (cli-off's workspace)",
        "Products: bluebook, original -> bluebook",
        APPLIES_MSG,
    ]


def test_set_products_cli_reports_no_change(capsys, monkeypatch):
    monkeypatch.delenv("REPO_BACKEND", raising=False)
    monkeypatch.delenv("REPO_SHADOW", raising=False)
    out = invite_professor("cli-same@seminary.edu", base_url="https://x.test")
    assert products_cli.main(["cli-same@seminary.edu", "--original", "off"]) == 0
    assert _lines(capsys.readouterr().out) == [
        "Database backend: sqlite",
        f"Workspace {out['tenant_id']} (cli-same's workspace)",
        "No change: products are already bluebook.",
    ]


def test_set_products_cli_warns_about_an_institution_workspace(capsys):
    repo = get_repository()
    repo.put_tenant("inst-cli", "Institution CLI", environment="pilot", meta={})
    repo.set_tenant_products("inst-cli", ["bluebook", "original"])
    email = "prof@inst-cli.edu"
    repo.put_user(users._user_id("inst-cli", email), email, "!x", "professor", "inst-cli", "P")
    assert products_cli.main([email, "--original", "off"]) == 0
    assert _lines(capsys.readouterr().out)[1:4] == [
        "Workspace inst-cli (Institution CLI)",
        SHARED_MSG,
        "Products: bluebook, original -> bluebook",
    ]


def test_set_products_cli_fails_cleanly(capsys):
    users.create_student_account("t-course", "kid@seminary.edu", "Kid")
    assert products_cli.main(["kid@seminary.edu", "--original", "on"]) == 1
    captured = capsys.readouterr()
    assert "kid@seminary.edu is a student account." in captured.err
    assert "Products:" not in captured.out
    assert products_cli.main(["ghost@seminary.edu", "--original", "off"]) == 1
    assert "No account with ghost@seminary.edu." in capsys.readouterr().err


def test_set_products_cli_requires_on_or_off(capsys):
    with pytest.raises(SystemExit) as missing:
        products_cli.main(["a@seminary.edu"])
    assert missing.value.code == 2
    with pytest.raises(SystemExit) as bad:
        products_cli.main(["a@seminary.edu", "--original", "maybe"])
    assert bad.value.code == 2
    capsys.readouterr()
