# Bluebook Professor Release — Finish Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take branch `claude/professor-release-continuation` from "local, verified candidate" to "a small group of invited professors can use Bluebook at a stable HTTPS address", with the remaining engineering gaps closed and every non-code gate assigned to a named owner.

**Architecture:** Part A is code on the existing live stack (`original/api.py` + `original/routers/` + `demo/bluebook/`). It covers invitation-only onboarding, a seal confirmation, the resume-button label, discarding keystroke-derived data at the API boundary, closing the anonymous route to Original on real deploys, encrypted off-box backups, a separate static origin for the fictional demo, and a legal-page release guard. Part B is deployment and operations on the existing `render.yaml` blueprint, following `docs/BLUEBOOK_LAUNCH_CHECKLIST.md` with the additions below. Part B tasks are owner/operator steps with exact commands and done-criteria, not code.

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / SQLite + Postgres 16 (Alembic) / React 19 bundled with esbuild / Playwright / Render blueprint / SendGrid / S3-compatible storage / `cryptography` (Fernet, already in `requirements-pilot.lock.txt`).

## Global Constraints

- No typing rhythm or keystroke biometrics: text and coarse session information only.
- No student text leaves the deployment (no external inference, analytics, fonts or telemetry carrying prose).
- Report-only, consistency-not-accusation UX; research flags stay default-off; Original stays off for Bluebook workspaces.
- Canvas/LTI deferred: no LTI configuration in the pilot blueprint.
- Python: always `/Users/andrew/Desktop/Original/.venv/bin/python` (a worktree has no `.venv` of its own).
- After any `demo/bluebook/*.jsx` or `*.css` edit: `cd demo/bluebook && npm run build` and commit the rebuilt `*.bundle.*` files in the same commit (CI byte-identity check).
- Never kill or restart a dev server you did not start. Never point tests at a production database.
- Commit style: `Fix …` / `Add …` / `Refactor …`, one logical change per commit, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Do not push to `main`. Publish the branch and update draft PR pathosbuilder895/Orig#226 (or open a new PR to `main`).
- Full suite budget is ~11–15 minutes. Run it in the background and never on a short timeout.
- Diffs touching `original/quantum/`, `original/features/`, `original/context/`, `original/store.py`, `original/routers/students_scoring.py` or `original/constants.py` get a `score-integrity-reviewer` pass before commit. Task 6 touches the inputs to Tier 17 extraction, so it gets one too.

## Decisions taken by this plan (owner may veto before execution)

The owner was asked these on 4 October and has not answered. The plan proceeds on these defaults; each is isolated in one task, so a veto drops or reverses that task alone.

| # | Question | Default taken | Task |
|---|---|---|---|
| D1 | Open public signup or invitation-only pilot? | **Invitation-only** on the pilot (`SELF_SERVE_SIGNUP=0` in `render.yaml`). Code default stays open, so demo and CI are unchanged. Professors are onboarded by an operator script. | 1, 2, 3 |
| D2 | Confirm before sealing? | **Yes**, a native confirm on manual seal only. Time-expiry auto-seal stays unconfirmed. | 4 |
| D3 | Backup encryption? | **Client-side Fernet encryption** before upload, key held only in Render (`BACKUP_ENCRYPTION_KEY`) and in the owner's password manager. The scheduled job refuses to run without it. | 8 |

## File map

| File | Responsibility | Tasks |
|---|---|---|
| `original/routers/_shared.py` | `_signup_open()` deploy-setting reader | 1 |
| `original/routers/auth.py` | refuse `/auth/signup` when closed | 1 |
| `original/routers/health.py`, `original/schemas.py` (`HealthResponse`) | expose `signup_open` | 1 |
| `render.yaml`, `tests/test_render_blueprint.py` | pin `SELF_SERVE_SIGNUP=0`, backup key, demo static site | 1, 8, 9 |
| `demo/bluebook/components.jsx` | `BB_API._health()`, `signupOpen()` | 2 |
| `demo/bluebook/Landing.jsx` | hide signup affordances when closed | 2 |
| `demo/bluebook/unit/*.test.mjs`, `.github/workflows/test.yml` | node unit tests, run in CI | 2, 5 |
| `original/onboarding.py` (new), `original/mailer.py`, `scripts/invite_professor.py` (new) | operator invites a professor | 3 |
| `demo/bluebook/Exam.jsx` | seal confirm, resume label, no deletion-key counting | 4, 5, 6 |
| `demo/bluebook/e2e/{exam-flow,exam-robustness,self-serve,professor-journey}.spec.mjs` | accept the seal dialog | 4 |
| `original/schemas.py` (`AddSampleRequest`, `ScoreSubmissionRequest`, `TestScoreRequest`) | discard keystroke-derived input | 6 |
| `original/api.py` (`tenant_isolation`) | anonymous never reaches Original on a real deploy | 7 |
| `scripts/pg_backup_offbox.py`, `tests/test_pg_backup_offbox.py` | encrypt/decrypt dumps | 8 |
| `scripts/build_teacher_demo_site.sh` (new), `tests/test_teacher_demo_site.py` (new), `.gitignore` | allowlisted static demo build | 9 |
| `tests/test_legal_release_guard.py` (new) | legal pages cannot ship half-final | 10 |
| `CLAUDE.md` (flag table), `docs/BLUEBOOK_LAUNCH_CHECKLIST.md`, `docs/release/*` | docs for the above | 1, 3, 8, 9, 11, B-tasks |

---

# Part A — Engineering

### Task 1: Server switch to close self-serve signup

**Files:**
- Modify: `original/routers/_shared.py` (add helper next to `_launch_products`)
- Modify: `original/routers/auth.py:122-131` (`auth_signup`)
- Modify: `original/schemas.py:1213` (`HealthResponse`)
- Modify: `original/routers/health.py:20-31`
- Modify: `render.yaml` (`original-pilot` envVars)
- Modify: `CLAUDE.md` (Environment Flags table)
- Test: `tests/test_bluebook_self_serve.py`, `tests/test_render_blueprint.py`

**Interfaces:**
- Produces: `original.routers._shared._signup_open() -> bool` (True unless env `SELF_SERVE_SIGNUP` is `"0"`); `GET /health` JSON gains `"signup_open": bool`; `POST /auth/signup` returns **403** with detail `"Bluebook is invitation-only here. Ask the person who runs Bluebook for your institution to invite you."` when closed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bluebook_self_serve.py` (the file's autouse `_isolate` fixture already isolates the store):

```python
def test_signup_closed_refuses_and_creates_nothing(live_client, monkeypatch):
    monkeypatch.setenv("SELF_SERVE_SIGNUP", "0")
    r = live_client.post(
        "/auth/signup",
        json={"email": "closed@school.edu", "password": PW, "name": "C", "accept_terms": True},
    )
    assert r.status_code == 403
    assert "invitation-only" in r.json()["detail"]
    assert get_repository().get_user_by_email("closed@school.edu") is None


def test_health_reports_whether_signup_is_open(live_client, monkeypatch):
    monkeypatch.delenv("SELF_SERVE_SIGNUP", raising=False)
    assert live_client.get("/health").json()["signup_open"] is True
    monkeypatch.setenv("SELF_SERVE_SIGNUP", "0")
    assert live_client.get("/health").json()["signup_open"] is False
```

Append to `tests/test_render_blueprint.py`:

```python
def test_pilot_is_invitation_only():
    assert _env("original-pilot")["SELF_SERVE_SIGNUP"]["value"] == "0"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_bluebook_self_serve.py tests/test_render_blueprint.py -k "signup_closed or signup_is_open or invitation_only" -q --no-cov`
Expected: 3 failed (signup returns 201; `signup_open` KeyError; `SELF_SERVE_SIGNUP` KeyError).

- [ ] **Step 3: Implement**

In `original/routers/_shared.py`, directly above `def _launch_products`:

```python
def _signup_open() -> bool:
    """Whether the public teacher signup is enabled on this deploy.

    ``SELF_SERVE_SIGNUP=0`` makes the pilot invitation-only: professors are
    then onboarded with ``scripts/invite_professor.py``. Read per request so an
    operator can flip it with a restart and tests can monkeypatch the env."""
    return os.environ.get("SELF_SERVE_SIGNUP", "1").strip() != "0"
```

In `original/routers/auth.py`, add `_signup_open` to the existing `from ._shared import (...)` list, then make it the first statement in `auth_signup` (before `_throttle_login`):

```python
    if not _signup_open():
        raise HTTPException(
            status_code=403,
            detail=(
                "Bluebook is invitation-only here. Ask the person who runs "
                "Bluebook for your institution to invite you."
            ),
        )
```

In `original/schemas.py`, inside `class HealthResponse`, after the `environment` field:

```python
    # False on an invitation-only deploy (SELF_SERVE_SIGNUP=0). The SPA hides
    # its "create a workspace" affordances when this is False.
    signup_open: bool = True
```

In `original/routers/health.py`, import `_signup_open` from `._shared` and pass `signup_open=_signup_open(),` into `HealthResponse(...)`.

In `render.yaml`, in `original-pilot` `envVars`, directly after the `ORIGINAL_ENV` entry:

```yaml
      # Invitation-only pilot: no public workspace signup. Onboard professors
      # with `python scripts/invite_professor.py EMAIL --name NAME` (Render Shell).
      - key: SELF_SERVE_SIGNUP
        value: "0"
```

In `CLAUDE.md`, add a row to the Environment Flags table after `LOGIN_THROTTLE_WINDOW_SEC`:

```markdown
| `SELF_SERVE_SIGNUP` | `1` | `0` closes `POST /auth/signup` (403) and hides the SPA's "create a workspace" links via `/health.signup_open`. The pilot blueprint pins `0` (invitation-only); onboard professors with `scripts/invite_professor.py`. |
```

- [ ] **Step 4: Run the tests to verify they pass, plus the neighbours**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_bluebook_self_serve.py tests/test_render_blueprint.py tests/test_openapi_stability.py tests/test_launch_hardening.py -q --no-cov`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add original/routers/_shared.py original/routers/auth.py original/schemas.py original/routers/health.py render.yaml CLAUDE.md tests/test_bluebook_self_serve.py tests/test_render_blueprint.py
git commit -m "Add SELF_SERVE_SIGNUP switch and make the pilot invitation-only

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Hide signup links when signup is closed; run node unit tests in CI

**Files:**
- Modify: `demo/bluebook/components.jsx:544-553` (`environment()`)
- Modify: `demo/bluebook/Landing.jsx` (hook + three call sites: nav "Start free →" ~line 45, hero "Create a free workspace" ~line 98, login "Teacher without an account?" paragraph ~line 278)
- Modify: `.github/workflows/test.yml` (after the `npm ci` step, ~line 231)
- Test: `demo/bluebook/unit/api-client.test.mjs`

**Interfaces:**
- Consumes: `/health` field `signup_open` (Task 1).
- Produces: `BB_API.signupOpen(): Promise<boolean>` (true when the field is true or absent; false when the field is false or the probe fails); `BB_API.environment()` keeps its contract.

- [ ] **Step 1: Write the failing test**

Append to `demo/bluebook/unit/api-client.test.mjs`:

```js
test('signupOpen follows /health and fails closed', async () => {
  const health = (body, status = 200) => async () => new Response(JSON.stringify(body), { status });
  delete BB_API._healthP;
  globalThis.fetch = health({ environment: 'pilot', signup_open: false });
  assert.equal(await BB_API.signupOpen(), false);
  assert.equal(await BB_API.environment(), 'pilot');

  delete BB_API._healthP;
  globalThis.fetch = health({ environment: 'pilot' });
  assert.equal(await BB_API.signupOpen(), true);

  delete BB_API._healthP;
  globalThis.fetch = async () => { throw new TypeError('offline'); };
  assert.equal(await BB_API.signupOpen(), false);
  assert.equal(await BB_API.environment(), null);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd demo/bluebook && node --test unit/`
Expected: FAIL — `BB_API.signupOpen is not a function`.

- [ ] **Step 3: Implement**

Replace the `environment()` method in `demo/bluebook/components.jsx` with:

```js
  // The public health probe, fetched once per page. A failure resolves to
  // null; every reader below treats null as "not a demo, signup closed".
  _health() {
    if (this._healthP === undefined) {
      this._healthP = fetch(this.base + '/health')
        .then(r => (r.ok ? r.json() : null))
        .catch(() => null);
    }
    return this._healthP;
  },
  // The deploy's environment label. Demo-only affordances ("Explore the
  // demo") show only when this is 'demo'.
  async environment() {
    const h = await this._health();
    return (h && h.environment) || null;
  },
  // Whether teachers may create their own workspace (SELF_SERVE_SIGNUP).
  // Fails closed so an invitation-only pilot never advertises signup
  // because of a network blip; an older server without the field is open.
  async signupOpen() {
    const h = await this._health();
    return !!h && h.signup_open !== false;
  },
```

In `demo/bluebook/Landing.jsx`, under `useIsDemoDeploy`, add:

```js
// Signup links show only once the deploy confirms signup is open.
function useSignupOpen() {
  const [open, setOpen] = React.useState(false);
  React.useEffect(() => {
    let live = true;
    BB_API.signupOpen().then(v => { if (live) setOpen(v); });
    return () => { live = false; };
  }, []);
  return open;
}
```

In `LandingScreen`, add `const signupOpen = useSignupOpen();` as the first line of the function body. Wrap the nav `Start free →` button as `{signupOpen && (<button …>Start free →</button>)}`. Wrap the hero `<BtnPrimary … onClick={() => onNavigate('signup')} …>Create a free workspace</BtnPrimary>` the same way. In the login screen component (the one containing `Teacher without an account?`), add `const signupOpen = useSignupOpen();` at the top and replace that whole `<p>…Create a free workspace</button></p>` block with:

```jsx
          {signupOpen ? (
            <p style={{
              textAlign: 'center', fontFamily: fontBody, fontSize: 16,
              color: BB.fade, letterSpacing: '0.02em', margin: '0 0 14px',
            }}>
              Teacher without an account?{' '}
              <button type="button" onClick={() => onNavigate('signup')} style={{
                fontFamily: fontBody, fontSize: 16, color: BB.gold,
                textDecoration: 'underline', letterSpacing: '0.02em',
                background: 'none', border: 'none', padding: 0, cursor: 'pointer',
              }}>Create a free workspace</button>
            </p>
          ) : (
            <p style={{
              textAlign: 'center', fontFamily: fontBody, fontSize: 16,
              color: BB.fade, letterSpacing: '0.02em', margin: '0 0 14px',
            }}>
              Teachers join Bluebook by invitation during the pilot.
            </p>
          )}
```

In `.github/workflows/test.yml`, directly after the step `Install Bluebook build/test dependencies`, add:

```yaml
      - name: Bluebook unit tests
        run: cd demo/bluebook && node --test unit/
```

- [ ] **Step 4: Build and run the unit tests**

Run: `cd demo/bluebook && npm run build && node --test unit/`
Expected: build prints three ✓ lines; `pass 4`, `fail 0`.

- [ ] **Step 5: Verify in the browser at phone width**

Start a disposable preview from this worktree on a free port with `SELF_SERVE_SIGNUP=0` (`.claude/launch.json` entry running `/bin/sh -c "SELF_SERVE_SIGNUP=0 ORIGINAL_DB=<scratchpad>/p.db exec /Users/andrew/Desktop/Original/.venv/bin/python run.py --demo --frontend-dir demo --skip-seed --port 8764"`). At 375×812, open `/bluebook/`. Expected: no "Start free" and no "Create a free workspace" on the landing page; the sign-in screen shows "Teachers join Bluebook by invitation during the pilot."; `document.documentElement.scrollWidth === 375`. Restart the preview without the variable: both links are back.

- [ ] **Step 6: Commit**

```bash
git add demo/bluebook/components.jsx demo/bluebook/Landing.jsx demo/bluebook/unit/api-client.test.mjs demo/bluebook/*.bundle.* .github/workflows/test.yml
git commit -m "Hide signup links on invitation-only deploys and run unit tests in CI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Operator invites a professor

**Files:**
- Create: `original/onboarding.py`
- Modify: `original/mailer.py` (add `send_professor_invite` after `send_invite`)
- Create: `scripts/invite_professor.py`
- Test: `tests/test_onboarding.py` (new)
- Modify: `docs/BLUEBOOK_LAUNCH_CHECKLIST.md` (new subsection under "Operating it")

**Interfaces:**
- Consumes: `original.users._user_id(tenant_id, email) -> str`, `original.users.INVITED_PASSWORD_HASH`, `original.invites.issue(tenant_id, user_id, created_by) -> {"invite_path","expires_at","invite_id"}`, `original.mailer.absolute_url(path, request_base="") -> str`, `original.mailer.configured() -> bool`, repository `put_tenant / set_tenant_products / put_user / get_user_by_email / log_audit`, `original.bluebook_rules.SELF_SERVE_PLAN`.
- Produces: `original.onboarding.invite_professor(email: str, name: str = "", base_url: str = "") -> dict` returning `{"tenant_id", "user_id", "email", "invite_link", "expires_at", "emailed"}`; raises `ValueError` for an invalid or already-registered email. `original.mailer.send_professor_invite(to: str, link: str) -> bool`. CLI `python scripts/invite_professor.py EMAIL [--name NAME] [--base-url URL]` exits 0/1.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_onboarding.py`:

```python
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
    assert live_client.post(
        "/auth/login", json={"email": "p2@seminary.edu", "password": "chosen-passw0rd"}
    ).status_code == 401
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
    monkeypatch.setattr(mailer, "send_professor_invite", lambda to, link: sent.append((to, link)) or True)
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
    monkeypatch.setattr(mailer, "send", lambda to, subject, text: captured.update(to=to, subject=subject, text=text) or True)
    assert mailer.send_professor_invite("p@x.edu", "https://x.test/bluebook/?invite=abc") is True
    assert captured["subject"] == "Your Bluebook workspace is ready"
    assert "https://x.test/bluebook/?invite=abc" in captured["text"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_onboarding.py -q --no-cov`
Expected: collection error — `No module named 'original.onboarding'`.

- [ ] **Step 3: Implement**

In `original/mailer.py`, after `send_invite`:

```python
def send_professor_invite(to: str, link: str) -> bool:
    text = (
        "You have been invited to Bluebook, the online written-examination "
        "service, with a private workspace of your own.\n\n"
        f"Set your password here (this link works once and expires in 14 days):\n{link}\n\n"
        "Then sign in with this email address to create a course, invite your "
        "students and set an examination.\n\n"
        "If you were not expecting this, you can ignore this email."
    )
    return send(to, "Your Bluebook workspace is ready", text)
```

Create `original/onboarding.py`:

```python
"""Operator-side professor onboarding for an invitation-only deploy.

With SELF_SERVE_SIGNUP=0 nobody can create a workspace from the website, so
the operator provisions each invited professor: a private Bluebook-only
workspace, an account that cannot sign in yet, and a one-time invite link the
professor redeems to choose their own password (the same /bluebook/?invite=
flow students use). The operator never sees or sets the password."""

from __future__ import annotations

import secrets

from . import invites, mailer, users
from .bluebook_rules import SELF_SERVE_PLAN
from .repository import get_repository


def invite_professor(email: str, name: str = "", base_url: str = "") -> dict:
    normalized = (email or "").strip().lower()
    if not normalized or "@" not in normalized or len(normalized) > 254:
        raise ValueError("A valid email is required.")
    repo = get_repository()
    if repo.get_user_by_email(normalized):
        raise ValueError(f"An account with {normalized} already exists.")
    display = (name or "").strip()[:200] or normalized.split("@")[0]
    tenant_id = f"t-{secrets.token_hex(6)}"
    repo.put_tenant(
        tenant_id,
        f"{display}'s workspace"[:200],
        environment="production",
        meta={"plan": SELF_SERVE_PLAN, "created_via": "operator_invite"},
    )
    repo.set_tenant_products(tenant_id, ["bluebook"])
    user_id = users._user_id(tenant_id, normalized)
    repo.put_user(user_id, normalized, users.INVITED_PASSWORD_HASH, "professor", tenant_id, display)
    inv = invites.issue(tenant_id, user_id, "operator")
    link = mailer.absolute_url(inv["invite_path"], base_url)
    emailed = bool(mailer.configured() and mailer.send_professor_invite(normalized, link))
    repo.log_audit(
        action="professor_invite",
        tenant_id=tenant_id,
        actor="operator",
        result="ok",
        details={"emailed": emailed},
    )
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "email": normalized,
        "invite_link": link,
        "expires_at": inv["expires_at"],
        "emailed": emailed,
    }
```

Create `scripts/invite_professor.py`:

```python
#!/usr/bin/env python3
"""Invite a professor to an invitation-only Bluebook deploy.

Run where the service's environment is available (Render → original-pilot →
Shell), so it writes to the live database:

    python scripts/invite_professor.py prof@school.edu --name "Dr Name"

Creates a private Bluebook-only workspace and emails a one-time set-password
link when SendGrid is configured. The link is always printed so the operator
can send it by hand if the email does not arrive. It is a credential: send it
only to the professor.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):  # run as a file: make `original` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from original.onboarding import invite_professor  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Invite a professor to Bluebook.")
    parser.add_argument("email")
    parser.add_argument("--name", default="")
    parser.add_argument(
        "--base-url", default="", help="public site URL, used only if PUBLIC_BASE_URL is unset"
    )
    args = parser.parse_args(argv)
    try:
        out = invite_professor(args.email, args.name, args.base_url)
    except ValueError as exc:
        print(f"invite_professor: {exc}", file=sys.stderr)
        return 1
    print(f"Workspace {out['tenant_id']} created for {out['email']}.")
    if out["emailed"]:
        print("Invitation emailed.")
    else:
        print("Email NOT sent (mail not configured or rejected): send this link yourself.")
    print(f"Set-password link (single use, expires {out['expires_at']}):")
    print(out["invite_link"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

In `docs/BLUEBOOK_LAUNCH_CHECKLIST.md`, under `## Operating it`, add:

```markdown
- **Inviting a professor** (the pilot is invitation-only, `SELF_SERVE_SIGNUP=0`):
  Render → `original-pilot` → Shell →
  `python scripts/invite_professor.py prof@school.edu --name "Dr Name"`.
  It prints whether the email was sent and always prints the single-use link
  (14 days). If the link expires, run it again: an existing account is
  refused, so use "Forgot your password?" on the sign-in page instead.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_onboarding.py tests/test_bluebook_self_serve.py -q --no-cov`
Expected: all pass.

- [ ] **Step 5: Confirm the repository methods it uses are covered on Postgres**

`invite_professor` uses only `put_tenant`, `set_tenant_products`, `put_user`, `get_user_by_email`, `put_invite` (via `invites.issue`) and `log_audit`, which the repository contract tests already run on both backends.
Run: `DATABASE_URL=postgresql://original:original@localhost:55432/original_test /Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_repository_contract.py -m postgres -q --no-cov`
Expected: all pass, none skipped. If the container is gone, `bash scripts/local_postgres.sh up` and use `DATABASE_URL=$(bash scripts/local_postgres.sh url)`.

- [ ] **Step 6: Commit**

```bash
git add original/onboarding.py original/mailer.py scripts/invite_professor.py tests/test_onboarding.py docs/BLUEBOOK_LAUNCH_CHECKLIST.md
git commit -m "Add operator invitation for professors on an invitation-only pilot

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Confirm before a manual seal

**Files:**
- Modify: `demo/bluebook/Exam.jsx:1165-1169` (Seal & Submit `BtnPrimary`)
- Modify: `demo/bluebook/e2e/exam-flow.spec.mjs:243`, `demo/bluebook/e2e/exam-robustness.spec.mjs:129` and `:147`, `demo/bluebook/e2e/self-serve.spec.mjs:126-129`, `demo/bluebook/e2e/professor-journey.spec.mjs:261`

**Interfaces:**
- Consumes: existing `handleSubmit(opts = {})` (`opts.force` is the timer-expiry path and stays unconfirmed).
- Produces: a manual seal requires `window.confirm(...)` to return true.

- [ ] **Step 1: Change the e2e specs first, so they describe the new behaviour**

Insert the dialog acceptor on the line immediately before each manual seal click:
- `exam-flow.spec.mjs`, before `await sealBtn.click()` (line 243): `page.once('dialog', d => d.accept())`
- `exam-robustness.spec.mjs`, before each of the two `await studentPage.locator('button', { hasText: /Seal & Submit|Sealing/ }).click()` (lines 129, 147): `studentPage.once('dialog', d => d.accept())`
- `self-serve.spec.mjs`, before `const [sealRes] = await Promise.all([` (line 126): `student.once('dialog', d => d.accept())`
- `professor-journey.spec.mjs`, before `await sealBtn.click()` (line 261): `studentPage.once('dialog', d => d.accept())`

- [ ] **Step 2: Implement**

In `demo/bluebook/Exam.jsx`, change the seal button's `onClick={handleSubmit}` to:

```jsx
                onClick={() => {
                  // A stray tap must not end the exam. Time expiry seals via
                  // handleSubmit({ force: true }) and never reaches this.
                  if (window.confirm('Seal and submit now? You cannot change your answers after sealing.')) handleSubmit();
                }}
```

- [ ] **Step 3: Build**

Run: `cd demo/bluebook && npm run build && node --test unit/`
Expected: three ✓ lines, unit tests pass.

- [ ] **Step 4: Run the affected Playwright specs against a pilot-mode server**

Start a server you own, exactly as CI does, on a free port, via a `.claude/launch.json` entry:
`/bin/sh -c "ORIGINAL_ENV=pilot SECRET_KEY=ci-test-only-secret-do-not-deploy MAINTENANCE_TOKEN=ci-test-only LOGIN_THROTTLE_MAX_ATTEMPTS=500 ORIGINAL_DB=<scratchpad>/e2e.db exec /Users/andrew/Desktop/Original/.venv/bin/python run.py --demo --frontend-dir demo --port 8771 --skip-seed"`
Then run: `cd demo/bluebook && npx playwright install chromium && PLAYWRIGHT_BASE_URL=http://localhost:8771 SECRET_KEY=ci-test-only-secret-do-not-deploy npx playwright test e2e/exam-flow.spec.mjs e2e/exam-robustness.spec.mjs e2e/self-serve.spec.mjs e2e/professor-journey.spec.mjs`
Expected: all pass. If a spec fails, read its trace before changing anything. A failure unrelated to sealing that also fails on the parent commit is pre-existing: record it and do not fix it here.

- [ ] **Step 5: Browser check**

In the same server at 375×812, sit an exam as a fictional student. Tap Seal & Submit and **Cancel**: the exam stays open with text intact. Tap again and **OK**: "Examination Sealed".

- [ ] **Step 6: Commit**

```bash
git add demo/bluebook/Exam.jsx demo/bluebook/*.bundle.* demo/bluebook/e2e/exam-flow.spec.mjs demo/bluebook/e2e/exam-robustness.spec.mjs demo/bluebook/e2e/self-serve.spec.mjs demo/bluebook/e2e/professor-journey.spec.mjs
git commit -m "Add a confirmation before a manual seal

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Say "Resume" when a sitting is already running

**Files:**
- Modify: `demo/bluebook/Exam.jsx:46-60` (`examToConfig`) and `:440-442` (briefing CTA text)
- Test: `demo/bluebook/unit/exam-config.test.mjs` (new)

**Interfaces:**
- Consumes: `GET /bluebook/me/exams/{id}` field `session` (`{started_at, deadline_at}` or `null`; see `_exam_summary` in `original/routers/bluebook_accounts.py:456`).
- Produces: `examToConfig(detail).inProgress: boolean`.

- [ ] **Step 1: Write the failing test**

Create `demo/bluebook/unit/exam-config.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const built = await build({
  entryPoints: [new URL('../Exam.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
});
globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
const { examToConfig } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

test('a running sitting is marked in progress', () => {
  assert.equal(examToConfig({ id: 'e1', session: { started_at: 't', deadline_at: 'd' } }).inProgress, true);
});
test('an unstarted exam is not in progress', () => {
  assert.equal(examToConfig({ id: 'e1', session: null }).inProgress, false);
  assert.equal(examToConfig({ id: 'e1' }).inProgress, false);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd demo/bluebook && node --test unit/`
Expected: 2 failures (`undefined !== true`, `undefined !== false`).

- [ ] **Step 3: Implement**

In `examToConfig`'s returned object, after `closesAt: d.closes_at || null,` add `inProgress: !!d.session,`. Replace the CTA text `Begin Examination — Timer Commences` with:

```jsx
                {cfg.inProgress ? 'Resume Examination — Timer Is Running' : 'Begin Examination — Timer Commences'}
```

- [ ] **Step 4: Build and test**

Run: `cd demo/bluebook && npm run build && node --test unit/`
Expected: all unit tests pass. `grep -rn "Begin Examination" e2e/` shows the specs match by regex or by the "Begin" text. Any spec that resumes a sitting and clicks an exact `Begin Examination — Timer Commences` string must be changed to `/Begin Examination|Resume Examination/`.

- [ ] **Step 5: Commit**

```bash
git add demo/bluebook/Exam.jsx demo/bluebook/unit/exam-config.test.mjs demo/bluebook/*.bundle.* demo/bluebook/e2e
git commit -m "Fix the briefing button to say Resume when a sitting is running

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Discard keystroke-derived data at the API boundary

The classroom release collects text and coarse session information only. Today `AddSampleRequest` / `ScoreSubmissionRequest` / `TestScoreRequest` accept `keystroke_data` (including `avgWpm`, `deletionRate`), and the baseline route persists the macro fields (`original/routers/students_baseline.py:177`). Bluebook's own page counts Backspace/Delete presses into `composition_summary.revision_count` (`Exam.jsx:536-575`). Tier 17 (`behavioral`) is disabled by default, so none of this moves a score. It is still keystroke data being collected and stored.

**Files:**
- Modify: `original/schemas.py` (`AddSampleRequest` line 17, `ScoreSubmissionRequest` line 47, `TestScoreRequest` line 539; import `model_validator`)
- Modify: `demo/bluebook/Exam.jsx:540-575` (drop `delsRef` and `revision_count`)
- Test: `tests/test_keystroke_boundary.py` (new); update any existing tests that post `keystroke_data` through the API and assert it is extracted or stored

**Interfaces:**
- Produces: when `"behavioral" in original.constants.DISABLED_FEATURE_GROUPS`, the three request models arrive in handlers with `keystroke_data is None` and with no `revision_count` key in `composition_summary`. When the group is enabled, behaviour is unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_keystroke_boundary.py`:

```python
"""No keystroke-derived data enters the classroom release (text + coarse session only)."""

from __future__ import annotations

from original import constants
from original.schemas import AddSampleRequest, ScoreSubmissionRequest, TestScoreRequest

KEYS = {"keystrokes": [1, 2], "pauses": [3], "deletionRate": 0.2, "avgWpm": 41}
SUMMARY = {"session_seconds": 600, "paste_attempts": 0, "focus_losses": 1, "revision_count": 37}


def test_keystroke_data_is_discarded_while_behavioral_features_are_disabled():
    assert "behavioral" in constants.DISABLED_FEATURE_GROUPS
    for model in (
        AddSampleRequest(text="t", keystroke_data=KEYS, composition_summary=SUMMARY),
        ScoreSubmissionRequest(text="t", keystroke_data=KEYS, composition_summary=SUMMARY),
    ):
        assert model.keystroke_data is None
        assert "revision_count" not in model.composition_summary
        assert model.composition_summary["session_seconds"] == 600
    assert TestScoreRequest(text="t", keystroke_data=KEYS).keystroke_data is None


def test_keystroke_data_passes_when_behavioral_features_are_enabled(monkeypatch):
    monkeypatch.setattr(
        constants, "DISABLED_FEATURE_GROUPS", constants.DISABLED_FEATURE_GROUPS - {"behavioral"}
    )
    model = AddSampleRequest(text="t", keystroke_data=KEYS, composition_summary=SUMMARY)
    assert model.keystroke_data == KEYS
    assert model.composition_summary["revision_count"] == 37


def test_baseline_route_persists_no_keystroke_data(live_client, store_reset):
    from original.repository import get_repository

    text = " ".join(["Augustine writes of memory and the restless heart."] * 30)
    r = live_client.post(
        "/students/demo:ks-student/baseline",
        json={"text": text, "keystroke_data": KEYS, "composition_summary": SUMMARY},
    )
    assert r.status_code == 200, r.text
    sample = get_repository().get("demo:ks-student").samples[-1]
    assert sample.keystroke_data is None
    assert "revision_count" not in (sample.composition_summary or {})
    assert sample.composition_summary["session_seconds"] == 600
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_keystroke_boundary.py -q --no-cov`
Expected: the first and third tests fail (data still present); the second passes.

- [ ] **Step 3: Implement**

In `original/schemas.py`, change the pydantic import to `from pydantic import BaseModel, Field, model_validator` and add above `class AddSampleRequest`:

```python
def _discard_keystroke_derived(model):
    """No typing rhythm or keystroke biometrics while the ``behavioral``
    feature group is disabled (the classroom default): drop ``keystroke_data``
    and the deletion-key ``revision_count`` before any handler can extract or
    store them. Read from the module at call time so enabling the group (and
    tests that do) takes effect without re-importing this module."""
    from . import constants

    if "behavioral" in constants.DISABLED_FEATURE_GROUPS:
        model.keystroke_data = None
        summary = getattr(model, "composition_summary", None)
        if isinstance(summary, dict) and "revision_count" in summary:
            model.composition_summary = {k: v for k, v in summary.items() if k != "revision_count"}
    return model
```

Add this method at the end of each of `AddSampleRequest`, `ScoreSubmissionRequest` and `TestScoreRequest`:

```python
    @model_validator(mode="after")
    def _no_keystroke_data(self):
        return _discard_keystroke_derived(self)
```

In `demo/bluebook/Exam.jsx`: delete `const delsRef = useExRef(0);` and the line `if (e.key === 'Backspace' || e.key === 'Delete') delsRef.current += 1;`. Delete `revision_count:  delsRef.current,` from `buildCompositionSummary`. Update the comment above `revsRef` to say `no per-key counts are kept`. Then `cd demo/bluebook && npm run build`.

- [ ] **Step 4: Run the new tests and every test that sends keystroke data**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_keystroke_boundary.py tests/test_keystroke_data_persistence.py tests/test_purge_keystroke_blobs.py tests/test_tier17_report.py tests/test_tier17_rehearsal.py tests/test_vector_cache.py tests/test_calibration_gate.py tests/context/test_composition_summary.py tests/validation/test_termsim.py -q --no-cov`
Expected: the new file passes. For each other failure, apply one rule. A test that deliberately exercises Tier 17 ingestion or `keystroke_data` persistence through a request model gets `monkeypatch.setattr(constants, "DISABLED_FEATURE_GROUPS", constants.DISABLED_FEATURE_GROUPS - {"behavioral"})` (with `from original import constants`). It is testing the enabled path, which still works. Never weaken an assertion. A test that is not about keystrokes but merely included them must instead assert the new behaviour (data absent).

- [ ] **Step 5: Score-integrity review**

Dispatch the `score-integrity-reviewer` agent on the diff. It must confirm that, with `behavioral` disabled, `deviation_score` and `recommendation` are byte-identical before and after for a request carrying `keystroke_data` (Tier 17 is masked by `active_feature_mask`). Resolve any finding before committing.

- [ ] **Step 6: Commit**

```bash
git add original/schemas.py demo/bluebook/Exam.jsx demo/bluebook/*.bundle.* tests/
git commit -m "Fix keystroke-derived data being accepted while behavioral features are off

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Anonymous callers never reach Original routes on a real deploy

`tenant_isolation` exempts `SUPER_ROLES` from the product gate (`original/api.py:481-488`), and the anonymous demo principal has role `operator` and `products=ALL_PRODUCTS`. On a real deploy the only remaining anonymous route into `/students/...` is a tenant registered with `environment="demo"` (`principal.py:328-333`). Close it at the gate. Keep `/bluebook/launch` and `/proctor/park/beat`, which are anonymous by design.

**Files:**
- Modify: `original/api.py` (`tenant_isolation`, immediately after `needed = _required_product(request.url.path)`)
- Test: `tests/security/test_unauthenticated_writes.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/security/test_unauthenticated_writes.py`:

```python
def test_anonymous_cannot_reach_original_even_for_a_demo_tenant_on_a_real_deploy(
    pilot_env, store_reset, live_client
):
    from original import principal as principal_mod
    from original.repository import get_repository

    get_repository().put_tenant("leftover-demo", "Leftover", environment="demo")
    principal_mod.invalidate_tenant_cache()
    assert live_client.get("/students/leftover-demo:alice").status_code == 401
    assert (
        live_client.post(
            "/students/leftover-demo:alice/baseline", json={"text": "x " * 200}
        ).status_code
        == 401
    )
    # Anonymous-by-design Bluebook entry points are untouched.
    assert live_client.get("/bluebook/launch?t=bogus").status_code == 400
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/security/test_unauthenticated_writes.py -k demo_tenant_on_a_real_deploy -q --no-cov`
Expected: FAIL. The first GET returns 404 (student not found), not 401.

- [ ] **Step 3: Implement**

In `original/api.py`, directly after `needed = _required_product(request.url.path)`:

```python
    if _IS_REAL_DEPLOY and principal.is_demo and needed == "original":
        # The anonymous principal carries an operator role and every product,
        # which the gate below exempts. On a real deploy it must never reach
        # Original data, even for a tenant left registered as "demo".
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required — sign in with a staff account."},
        )
```

- [ ] **Step 4: Run the security and lockdown suites**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/security/ tests/test_pilot_lockdown.py tests/test_bluebook_self_serve.py tests/test_tenant_isolation.py -m "not blocker and not certification" -q --no-cov`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add original/api.py tests/security/test_unauthenticated_writes.py
git commit -m "Fix anonymous access to Original routes via demo tenants on real deploys

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Encrypt off-box backups

**Files:**
- Modify: `scripts/pg_backup_offbox.py` (`main`, new helpers `encrypt_file` / `decrypt_file`, docstring)
- Modify: `tests/test_pg_backup_offbox.py` (`_OFFBOX`, new tests)
- Modify: `render.yaml` (`original-pg-backup` envVars), `tests/test_render_blueprint.py` (`SECRETS`, new test)
- Modify: `docs/BLUEBOOK_LAUNCH_CHECKLIST.md` (§3 backup table, §6 restore drill), `CLAUDE.md` (flag row)

**Interfaces:**
- Produces: `encrypt_file(src: Path, key: str) -> Path` writes `src.name + ".fernet"` beside `src`; `decrypt_file(src: Path, key: str, dst: Path) -> Path`; env `BACKUP_ENCRYPTION_KEY` (a Fernet key). Behaviour: with a key, the dump is encrypted and only the `.fernet` file is uploaded. `--require-upload` fails without a key. `--restore X.fernet` decrypts with the key first.

- [ ] **Step 1: Write the failing tests**

In `tests/test_pg_backup_offbox.py`, add `from cryptography.fernet import Fernet` to the imports, add `"BACKUP_ENCRYPTION_KEY": Fernet.generate_key().decode(),` to the `_OFFBOX` dict, and append:

```python
def test_encrypt_then_decrypt_round_trips(tmp_path):
    key = Fernet.generate_key().decode()
    plain = tmp_path / "dump.jsonl.gz"
    pgb.write_dump(_empty_rows(), plain, NOW)
    enc = pgb.encrypt_file(plain, key)
    assert enc.name == "dump.jsonl.gz.fernet"
    assert enc.read_bytes()[:2] != plain.read_bytes()[:2]
    out = pgb.decrypt_file(enc, key, tmp_path / "back.jsonl.gz")
    assert out.read_bytes() == plain.read_bytes()


def test_require_upload_fails_without_an_encryption_key(cli_env):
    for k, v in _OFFBOX.items():
        cli_env.setenv(k, v)
    cli_env.delenv("BACKUP_ENCRYPTION_KEY")
    cli_env.setattr(pgb, "upload", lambda cfg, path: None)
    assert pgb.main(["--require-upload"]) == 1


def test_main_uploads_only_the_encrypted_file(cli_env):
    for k, v in _OFFBOX.items():
        cli_env.setenv(k, v)
    uploaded = []

    def fake_upload(cfg, path):
        assert path.name.endswith(".jsonl.gz.fernet")
        uploaded.append((path, path.read_bytes()))

    cli_env.setattr(pgb, "upload", fake_upload)
    assert pgb.main(["--require-upload"]) == 0
    assert len(uploaded) == 1
    path, data = uploaded[0]
    assert not path.exists()
    assert not path.with_name(path.name[: -len(".fernet")]).exists()
    assert Fernet(_OFFBOX["BACKUP_ENCRYPTION_KEY"].encode()).decrypt(data)[:2] == b"\x1f\x8b"


def test_restore_decrypts_a_fernet_file(cli_env, tmp_path):
    cli_env.setenv("BACKUP_ENCRYPTION_KEY", _OFFBOX["BACKUP_ENCRYPTION_KEY"])
    plain = tmp_path / "dump.jsonl.gz"
    pgb.write_dump(_empty_rows(), plain, NOW)
    enc = pgb.encrypt_file(plain, _OFFBOX["BACKUP_ENCRYPTION_KEY"])
    seen = []
    cli_env.setattr(
        pgb, "restore",
        lambda scope, p: seen.append(pgb.read_dump(p)[0]["format"]) or {"parity": True, "tables": []},
    )
    assert pgb.main(["--restore", str(enc)]) == 0
    assert seen == [pgb.FORMAT]


def test_restore_of_a_fernet_file_without_the_key_fails_cleanly(cli_env, tmp_path):
    plain = tmp_path / "dump.jsonl.gz"
    pgb.write_dump(_empty_rows(), plain, NOW)
    enc = pgb.encrypt_file(plain, Fernet.generate_key().decode())
    cli_env.delenv("BACKUP_ENCRYPTION_KEY", raising=False)
    assert pgb.main(["--restore", str(enc)]) == 1
```

(The `cli_env` fixture already deletes every `_OFFBOX` key, so `BACKUP_ENCRYPTION_KEY` is unset at the start of each test.)

In `tests/test_render_blueprint.py`, add `"BACKUP_ENCRYPTION_KEY",` to `SECRETS` and append:

```python
def test_backup_job_requires_an_encryption_key():
    assert _env("original-pg-backup")["BACKUP_ENCRYPTION_KEY"].get("sync") is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_pg_backup_offbox.py tests/test_render_blueprint.py -q --no-cov`
Expected: failures for `encrypt_file` missing, upload of plain file, restore of `.fernet`, blueprint key missing.

- [ ] **Step 3: Implement**

In `scripts/pg_backup_offbox.py`, add after `dump_filename`:

```python
# ── Encryption ────────────────────────────────────────────────────────────────
# The dump holds every student answer. It is encrypted before it leaves
# Render, with a key that lives only in Render's env and the owner's password
# manager, so the bucket provider never holds readable student text.

ENC_SUFFIX = ".fernet"


def encrypt_file(src: Path, key: str) -> Path:
    from cryptography.fernet import Fernet

    dst = src.with_name(src.name + ENC_SUFFIX)
    dst.write_bytes(Fernet(key.encode()).encrypt(src.read_bytes()))
    return dst


def decrypt_file(src: Path, key: str, dst: Path) -> Path:
    from cryptography.fernet import Fernet, InvalidToken

    try:
        dst.write_bytes(Fernet(key.encode()).decrypt(src.read_bytes()))
    except InvalidToken as exc:
        raise ValueError(f"{src} could not be decrypted with BACKUP_ENCRYPTION_KEY") from exc
    return dst
```

In `main`, read the key once after the `DATABASE_URL` check: `key = os.environ.get("BACKUP_ENCRYPTION_KEY", "").strip()`.

Replace the restore branch's `report = restore(session_scope, Path(args.restore))` with:

```python
            src = Path(args.restore)
            if src.name.endswith(ENC_SUFFIX):
                if not key:
                    raise ValueError(f"{src} is encrypted and BACKUP_ENCRYPTION_KEY is not set")
                src = decrypt_file(
                    src, key, Path(tempfile.gettempdir()) / src.name[: -len(ENC_SUFFIX)]
                )
            report = restore(session_scope, src)
```

After the existing `--require-upload` / `cfg.ready()` check, add:

```python
    if args.require_upload and not key:
        log.error("pg backup: upload required but BACKUP_ENCRYPTION_KEY is not set.")
        return 1
```

Replace `upload(cfg, path)  # stored under its own file name` with:

```python
            if key:
                enc = encrypt_file(path, key)
                try:
                    upload(cfg, enc)  # stored under its own file name
                finally:
                    enc.unlink(missing_ok=True)
            else:
                upload(cfg, path)
```

Add `ValueError` to the `except (urllib.error.URLError, OSError, RuntimeError)` tuple of the dump branch. Add one paragraph to the module docstring under "Upload": `With BACKUP_ENCRYPTION_KEY set (required by --require-upload) the dump is Fernet-encrypted first and only the .fernet file is uploaded; --restore decrypts a .fernet file with the same key.`

In `render.yaml`, in `original-pg-backup` envVars, after `BACKUP_OFFBOX_SECRET_ACCESS_KEY`:

```yaml
      # Fernet key; generate once with
      #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
      # and keep a copy in the owner's password manager: without it no backup
      # can ever be restored.
      - key: BACKUP_ENCRYPTION_KEY
        sync: false
```

In `docs/BLUEBOOK_LAUNCH_CHECKLIST.md` §3, add a row to the `original-pg-backup` table: `| BACKUP_ENCRYPTION_KEY | generate with the command in render.yaml; store a copy in your password manager — losing it makes every backup unrecoverable |`. In §6, change the expected object name to `original-pg-….jsonl.gz.fernet` and prefix the restore command with `BACKUP_ENCRYPTION_KEY=<the key>`. In `CLAUDE.md`'s flag table add: `| BACKUP_ENCRYPTION_KEY | — | Fernet key for scripts/pg_backup_offbox.py. Required by --require-upload; the uploaded object is .jsonl.gz.fernet. |`.

- [ ] **Step 4: Run the tests**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_pg_backup_offbox.py tests/test_render_blueprint.py tests/test_backup_offbox.py -q --no-cov`
Expected: all pass.

- [ ] **Step 5: Real restore drill against local Postgres**

```bash
export DB=postgresql://original:original@localhost:55432
export BACKUP_ENCRYPTION_KEY=$(/Users/andrew/Desktop/Original/.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
DATABASE_URL=$DB/bluebook_release_preview /Users/andrew/Desktop/Original/.venv/bin/python scripts/pg_backup_offbox.py --out /tmp/drill.jsonl.gz
/Users/andrew/Desktop/Original/.venv/bin/python -c "import os;from pathlib import Path;from scripts.pg_backup_offbox import encrypt_file;print(encrypt_file(Path('/tmp/drill.jsonl.gz'), os.environ['BACKUP_ENCRYPTION_KEY']))"
docker exec codex-bluebook-release-postgres psql -U original -d postgres -c "DROP DATABASE IF EXISTS drill_enc" -c "CREATE DATABASE drill_enc"
DATABASE_URL=$DB/drill_enc /Users/andrew/Desktop/Original/.venv/bin/alembic upgrade head
DATABASE_URL=$DB/drill_enc /Users/andrew/Desktop/Original/.venv/bin/python scripts/pg_backup_offbox.py --restore /tmp/drill.jsonl.gz.fernet
```
Expected last line: `restore parity: OK`. (Use the scratchpad instead of `/tmp` if your session has one. If that container is gone, `bash scripts/local_postgres.sh up` and adjust host/port.)

- [ ] **Step 6: Commit**

```bash
git add scripts/pg_backup_offbox.py tests/test_pg_backup_offbox.py render.yaml tests/test_render_blueprint.py docs/BLUEBOOK_LAUNCH_CHECKLIST.md CLAUDE.md
git commit -m "Add client-side encryption to off-box Postgres backups

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Fictional professor demo on its own static origin

The demo (`demo/bluebook/teacher-demo.html`) makes no API calls and stores nothing. The plan requires it on a separate origin from classroom data. Publish only an allowlist of files: `demo/` also contains `seed.db` and old Original pages that must not be published.

**Files:**
- Create: `scripts/build_teacher_demo_site.sh`
- Create: `tests/test_teacher_demo_site.py`
- Modify: `render.yaml` (new static service), `tests/test_render_blueprint.py`, `.gitignore`

**Interfaces:**
- Produces: `bash scripts/build_teacher_demo_site.sh OUT_DIR` writes exactly `OUT_DIR/index.html` (redirect), `OUT_DIR/bluebook/{teacher-demo.html,teacher-demo.bundle.js,teacher-demo.bundle.css,fonts.css}`, `OUT_DIR/assets/codrington-library.jpeg`, `OUT_DIR/assets/fonts/*`; Render static service `bluebook-teacher-demo` publishing `./dist-teacher-demo`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_teacher_demo_site.py`:

```python
"""The fictional demo is published from an allowlist, never the whole demo/ tree."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_build_publishes_only_the_demo_allowlist(tmp_path):
    out = tmp_path / "site"
    subprocess.run(
        ["bash", str(ROOT / "scripts/build_teacher_demo_site.sh"), str(out)], check=True, cwd=ROOT
    )
    files = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    top = {f for f in files if not f.startswith("assets/fonts/")}
    assert top == {
        "index.html",
        "bluebook/teacher-demo.html",
        "bluebook/teacher-demo.bundle.js",
        "bluebook/teacher-demo.bundle.css",
        "bluebook/fonts.css",
        "assets/codrington-library.jpeg",
    }
    assert any(f.endswith(".woff2") for f in files)
    assert any(f.endswith("LICENSE.txt") for f in files)
    assert not any(f.endswith((".db", ".py", ".map")) for f in files)
    assert "bluebook/teacher-demo.html" in (out / "index.html").read_text()


def test_demo_page_references_no_third_party_hosts():
    for name in ("teacher-demo.html", "teacher-demo.bundle.css", "fonts.css"):
        text = (ROOT / "demo/bluebook" / name).read_text()
        assert "googleapis" not in text and "gstatic" not in text, name
```

Append to `tests/test_render_blueprint.py`:

```python
def test_teacher_demo_is_a_separate_static_site():
    demo = SERVICES["bluebook-teacher-demo"]
    assert demo["runtime"] == "static"
    assert demo["buildCommand"] == "bash scripts/build_teacher_demo_site.sh dist-teacher-demo"
    assert demo["staticPublishPath"] == "./dist-teacher-demo"
    assert _env("bluebook-teacher-demo") == {
        "SKIP_INSTALL_DEPS": {"key": "SKIP_INSTALL_DEPS", "value": "true"}
    }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_teacher_demo_site.py tests/test_render_blueprint.py -q --no-cov`
Expected: the build test fails (script missing); the blueprint test fails (KeyError). The third-party test passes already. Keep it as a guard.

- [ ] **Step 3: Implement**

Create `scripts/build_teacher_demo_site.sh`:

```bash
#!/usr/bin/env bash
# Build the static site for the fictional professor demo (no API, no data).
# Publishes an explicit allowlist: demo/ also holds seed.db and the old
# Original pages, none of which belong on a public static origin.
set -euo pipefail
out="${1:?usage: build_teacher_demo_site.sh OUT_DIR}"
root="$(cd "$(dirname "$0")/.." && pwd)"
rm -rf "$out"
mkdir -p "$out/bluebook" "$out/assets/fonts"
for f in teacher-demo.html teacher-demo.bundle.js teacher-demo.bundle.css fonts.css; do
  cp "$root/demo/bluebook/$f" "$out/bluebook/$f"
done
cp "$root/demo/assets/codrington-library.jpeg" "$out/assets/"
cp "$root"/demo/assets/fonts/* "$out/assets/fonts/"
cat > "$out/index.html" <<'HTML'
<!doctype html><meta charset="utf-8"><title>Bluebook demonstration</title>
<meta http-equiv="refresh" content="0; url=bluebook/teacher-demo.html">
<a href="bluebook/teacher-demo.html">Open the Bluebook demonstration</a>
HTML
```

In `render.yaml`, add this service at the end of `services:`:

```yaml
  # Fictional professor walkthrough on its own origin: no API, no accounts,
  # no student data. Separate from original-pilot so demo fiction and
  # classroom records never share an address.
  - type: web
    name: bluebook-teacher-demo
    runtime: static
    buildCommand: bash scripts/build_teacher_demo_site.sh dist-teacher-demo
    staticPublishPath: ./dist-teacher-demo
    envVars:
      - key: SKIP_INSTALL_DEPS
        value: "true"
    headers:
      - path: /*
        name: X-Frame-Options
        value: DENY
```

Append `dist-teacher-demo/` to `.gitignore`.

- [ ] **Step 4: Run the tests and open the built site**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_teacher_demo_site.py tests/test_render_blueprint.py -q --no-cov`
Expected: all pass. Then `bash scripts/build_teacher_demo_site.sh <scratchpad>/demo-site` and serve it with a static preview (`.claude/launch.json` entry: `/Users/andrew/Desktop/Original/.venv/bin/python -m http.server 8772 --directory <scratchpad>/demo-site`). At 375×812 and at desktop width: the page renders with the library image and local fonts; the network log shows only `localhost:8772` requests; there is no horizontal overflow.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_teacher_demo_site.sh tests/test_teacher_demo_site.py render.yaml tests/test_render_blueprint.py .gitignore
git commit -m "Add a separate static origin for the fictional professor demo

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Guard against shipping half-finished legal pages

**Files:**
- Create: `tests/test_legal_release_guard.py`

**Interfaces:**
- Consumes: `TERMS_VERSION` in `original/routers/auth.py:38` and `demo/bluebook/Account.jsx:18`; `class="fill"` spans and the `class="draft"` banner in `demo/legal/*.html`.

- [ ] **Step 1: Write the test**

```python
"""Legal pages ship either clearly DRAFT or fully complete, never in between."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = sorted((ROOT / "demo/legal").glob("*.html"))


def _server_version() -> str:
    text = (ROOT / "original/routers/auth.py").read_text()
    return re.search(r'^TERMS_VERSION = "([^"]+)"', text, re.M).group(1)


def _client_version() -> str:
    text = (ROOT / "demo/bluebook/Account.jsx").read_text()
    return re.search(r"export const TERMS_VERSION = '([^']+)'", text).group(1)


def test_server_and_client_record_the_same_terms_version():
    assert _server_version() == _client_version()


def test_a_final_version_has_no_draft_banner_or_blanks():
    version = _server_version()
    for page in PAGES:
        html = page.read_text()
        has_blanks = 'class="fill"' in html
        has_banner = 'class="draft"' in html
        if version.endswith("-draft"):
            assert has_banner, f"{page.name}: draft version but no DRAFT banner"
        else:
            assert not has_blanks, f"{page.name}: final version {version} still has [blanks]"
            assert not has_banner, f"{page.name}: final version {version} still shows DRAFT"
            assert version in html, f"{page.name}: version line does not say {version}"
```

- [ ] **Step 2: Run it**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_legal_release_guard.py -q --no-cov`
Expected: 2 passed today (version `2026-10-01-draft`, banners present). Then prove it bites: temporarily set the server `TERMS_VERSION` to `"2026-11-01"` and run it (expect FAIL on version mismatch and on blanks), then revert with `git checkout -- original/routers/auth.py`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_legal_release_guard.py
git commit -m "Add a guard so legal pages cannot ship half-final

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Verify the branch and publish the PR

**Files:**
- Modify: `docs/release/VERIFICATION_AND_BLOCKERS.md` (new dated section with results)

- [ ] **Step 1: Full CI command with Postgres, on a quiet machine**

Check `uptime` first: if the 1-minute load average is above 2× the CPU count, wait. The 4 October rerun stalled at load 74. Run in the background with a ≥40-minute limit:

```bash
DATABASE_URL=postgresql://original:original@localhost:55432/original_test /Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -m "not blocker and not certification" -q --cov=original --cov-branch --cov-report=term:skip-covered --cov-fail-under=98
```
Expected: 0 failed, 0 errors, coverage ≥ 98%. Treat any failure as real.

- [ ] **Step 2: Known-red lane**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python scripts/known_red.py`
Expected: exit 0; only T-01 (`tests/certification/test_cold_start_fpr.py`) listed.

- [ ] **Step 3: Full Playwright suite against a pilot-mode server**

Use the Task 4 server command, with `SELF_SERVE_SIGNUP` **unset** (the self-serve spec needs signup). Run `cd demo/bluebook && PLAYWRIGHT_BASE_URL=http://localhost:8771 SECRET_KEY=ci-test-only-secret-do-not-deploy npx playwright test`.
Expected: all pass, or every failure shown to also fail on `origin/codex/professor-release-handoff`.

- [ ] **Step 4: Record results**

Append a `## Finish pass, <date>` section to `docs/release/VERIFICATION_AND_BLOCKERS.md`. List the commits, the exact counts from steps 1–3, coverage, and which "Open decisions" from the continuation pass are now closed (D1–D3, anonymous gate, keystroke boundary). Commit: `Add finish-pass verification evidence`.

- [ ] **Step 5: Publish (needs the owner's GitHub sign-in)**

The owner runs `gh auth login -h github.com` once. Then:

```bash
git push -u origin claude/professor-release-continuation
gh pr create --repo pathosbuilder895/Orig --base main --head claude/professor-release-continuation --draft --title "Bluebook professor release: invitation-only pilot" --body-file docs/release/VERIFICATION_AND_BLOCKERS.md
```
If PR pathosbuilder895/Orig#226 should carry the work instead, say so in its description and link the new PR. Done when CI on the PR is green (including `coverage-combine` and `bundle-e2e`) and the owner has approved the merge. Merge is the owner's action.

---

# Part B — Hosting, operations and the professor pilot

These tasks need accounts, money, legal review or people. Each names its owner. None is complete until its "Done when" is true. Record evidence (dates, URLs, screenshots without secrets) in `docs/release/VERIFICATION_AND_BLOCKERS.md`.

### Task B1: Owner decisions and accounts (owner)

- [ ] Approve D1–D3 above (or veto before Part A runs).
- [ ] Choose the hosting budget and region. The blueprint creates `original-pilot` (Render **starter**), `original-db` (**basic-256mb** Postgres 16), `original-pg-backup` (cron, starter) and `bluebook-teacher-demo` (static, free), all in `oregon`. The existing services are in Ohio. If the institution needs a specific region, change every `region:` in `render.yaml` before creating anything. Check current Render prices on the pricing page at decision time.
- [ ] Decide what to do with the old services: the failed free Docker service `Originall` (`srv-d826vjmk1jcs73e4rk70`) and `original-demo` (`srv-d8madcernols73ccbsn0`). Suspend or delete them in the Render dashboard so nobody mistakes them for the release.
- [ ] Domain (optional): e.g. `bluebook.<your-domain>`.
- [ ] SendGrid account, authenticated sending domain, Mail-Send-only API key (checklist §2). Sign SendGrid's DPA: student email addresses pass through it.
- [ ] Backup bucket outside Render, with a lifecycle rule (≤ 35 days). Generate `BACKUP_ENCRYPTION_KEY` (command in `render.yaml`) and store it in a password manager.
- [ ] Name the **support contact** (an email address that someone reads) and the **operator** (hosting, invitations, restores, incidents). Replace `hello@originalvoice.io` in `demo/bluebook/Landing.jsx` and `demo/legal/*.html` if that is not the real address, then rebuild the bundle and commit.
- **Done when:** all of the above are written into `docs/release/VERIFICATION_AND_BLOCKERS.md` (names and choices only, no secrets).

### Task B2: Legal pages and institutional terms (owner + counsel, then engineer)

- [ ] Counsel fills every blank: `privacy.html` lines 17 (legal entity and address), 36 (region; must match B1), 39 (object-storage provider; must match B1), 44 (retention days); `terms.html` lines 14 (legal entity), 41 (warranty/liability/indemnity), 44 (governing law and venue). Counsel also reviews `student-notice.html`.
- [ ] With the first institution's privacy/legal staff: agree the allowed use, retention and deletion procedure, who may see submissions, and the incident contact. Record it as a short operating note in `docs/release/`.
- [ ] Engineer applies the final text: removes the `class="draft"` banner from all three pages, sets one final version string (e.g. `2026-11-01`) in each page's version line, in `TERMS_VERSION` in `original/routers/auth.py`, and in `demo/bluebook/Account.jsx`. Then `cd demo/bluebook && npm run build`, `pytest tests/test_legal_release_guard.py` passes, commit `Add final legal text for the pilot`.
- **Done when:** the guard test passes with a non-draft version, and the institution's operating note exists.

### Task B3: Create the hosted pilot from the merged commit (operator)

Follow `docs/BLUEBOOK_LAUNCH_CHECKLIST.md` §3–§4 with these differences:
- [ ] Blueprint from branch `main` **after** Task 11's PR is merged. Note the exact commit SHA.
- [ ] `original-pilot` secrets: `SECRET_KEY` and `MAINTENANCE_TOKEN` independently generated by Render (`generateValue: true`, 256-bit each). Existing values survive Blueprint syncs and deploys; do not regenerate them during routine setup. Securely retain the deployed values in the operator password manager. Previously exposed values require deliberate rotation, `SENDGRID_API_KEY`, `MAIL_FROM`, `PUBLIC_BASE_URL`, optional `SENTRY_DSN`. Confirm `SELF_SERVE_SIGNUP=0` and that no `LTI_*` variable exists.
- [ ] `original-pg-backup` secrets: the five `BACKUP_OFFBOX_*` values and `BACKUP_ENCRYPTION_KEY`.
- [ ] Custom domain and `ALLOWED_ORIGINS` if a domain was chosen.
- **Done when:** `original-pilot` is Live, the deploy log shows the Alembic upgrade, and `GET https://<host>/health` returns `"environment":"pilot"`, `"backend":"postgres"`, `"signup_open":false` and `"commit":"<the merged SHA>"`.

### Task B4: Deployed acceptance with fictional accounts (operator, then Claude)

- [ ] `python -m scripts.pilot_smoke_test --base-url https://<host> --bluebook` ends `smoke test: PASS`.
- [ ] Render Shell: `python scripts/invite_professor.py <operator's own address> --name "Rehearsal Professor"`. The email arrives; the link sets a password.
- [ ] As that professor, on a phone and on a laptop: create a course, add a second address you own as a student with "Email each student their invitation" ticked, and create a two-question exam. As the student, on a different device: set a password from the email, sit the exam, reload mid-way (draft and timer intact), seal (confirm dialog), and see "Delivered to your teacher". As the professor: read both answers, mark, give feedback, release. As the student: see the mark. Export CSV.
- [ ] "Forgot your password?" sends a reset email that works.
- [ ] Persistence: Render → `original-pilot` → **Manual Deploy → Restart service**. After it is Live again, both accounts sign in and the submission, mark and feedback are intact.
- [ ] Backups: `original-pg-backup` → **Trigger Run** succeeds, and an `original-pg-backups/original-pg-….jsonl.gz.fernet` object exists. Download it, then run the checklist §6 restore drill with `BACKUP_ENCRYPTION_KEY=<key>` against a scratch database (never the live one). It must end `restore parity: OK`.
- [ ] Rollback rehearsal: Render → `original-pilot` → Events → roll back to the previous deploy, confirm `/health.commit` changed, then roll forward again.
- [ ] Uptime monitor on `/health` (5 min) is green; Sentry (if set) shows `Sentry error reporting is on` in the log.
- [ ] Tell Claude the URL. Claude re-runs the smoke test and walks the journey above against the live site with the fictional accounts, then records results.
- [ ] Delete the rehearsal workspace's data (Students → delete; Courses → delete) or keep it clearly labelled "Rehearsal". Never mix it with a real class.
- **Done when:** every box above is ticked with a date in `docs/release/VERIFICATION_AND_BLOCKERS.md`.

### Task B5: Publish the fictional demo (operator)

- [ ] Confirm `bluebook-teacher-demo` deployed from the blueprint. Open `https://bluebook-teacher-demo.onrender.com/` on a phone and a laptop: the walkthrough works, Reset clears it, and the browser network panel shows only that origin.
- **Done when:** the demo link works from a device that has never visited the pilot, and it is recorded as the only link to share with prospective professors before they are invited.

### Task B6: Admit the first invited professors (owner + operator)

- [ ] Write `docs/release/PROFESSOR_QUICKSTART.md`, one page in plain language. Cover: the address; set your password from the invitation email; Courses → New course → add students by email (tick "Email each student their invitation"); Examinations → New examination (questions, duration, open/close times); what students see; Submissions → Read & mark → Release results; Export CSV. Then four points: lockdown warnings are context, not evidence; Original comparisons are not enabled in this pilot; support address and response expectations; how to ask for deletion. Send it with each invitation.
- [ ] Invite 1–3 professors with `scripts/invite_professor.py` (one run per professor). Start with a synthetic rehearsal session in their own workspace before any real class.
- [ ] Before any real classroom use, the institution's operating note (B2) is in place, and the professor knows the support contact.
- [ ] Watch the first real sessions: the operator checks `/health`, Render logs for 5xx, and that every student's submission appears for the professor.
- **Stop rule:** pause intake (set `MAINTENANCE_MODE`, or stop inviting) if acknowledged work is lost, a student sees another student's data, or a privacy boundary fails. Fix, re-run B4, then resume.
- **Done when:** each pilot professor has completed one session without developer help, and every acknowledged submission is visible to them and to no one else.

### Out of scope for this release (separately gated; do not enable)

Original comparisons and reports (needs its own evidence: baseline policy, held-out student-population validity, licensed-model/IP review, human-review procedure); Canvas/LTI; any research flag in `CLAUDE.md`'s table; outreach beyond the invited professors.
