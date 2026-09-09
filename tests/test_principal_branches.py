"""
tests/test_principal_branches.py — original/principal.py, remaining branch
arms not exercised by the many API-level tests that use `mint_principal_token`
across the suite (tenant isolation, LTI, staff auth, ...).

Those integration-style tests cover the "everything working" happy paths of
`resolve_principal`/`assert_student_access` extensively. What they don't
happen to hit: `verify_principal_token`'s malformed/unparseable/expired-token
arms (only "wrong signature" and "valid token" are exercised elsewhere),
`tenant_environment`'s unregistered-tenant and repository-error arms, and
`extract_scoped_id`'s `/canvas/baseline/{id}/...` branch.
"""

from __future__ import annotations

import original.principal as pr

# ── verify_principal_token: malformed / unparseable / expired ────────────────


def test_verify_principal_token_rejects_empty_and_dotless_tokens():
    """The 'bad principal token' arm — no signature separator at all."""
    assert pr.verify_principal_token("") is None
    assert pr.verify_principal_token("no-dot-in-this-string") is None


def test_verify_principal_token_rejects_payload_that_is_not_json():
    """Signature checks out (properly signed), but the base64 payload
    decodes to bytes that aren't valid JSON — the inner try/except must
    catch json.loads' error and degrade to None, not raise."""
    payload = pr._b64(b"not valid json{{{")
    sig = pr._sign(payload)
    token = f"{payload}.{sig}"
    assert pr.verify_principal_token(token) is None


def test_verify_principal_token_rejects_expired_token():
    token = pr.mint_principal_token("prof_expired", "professor", "acme", ttl_seconds=-10)
    assert pr.verify_principal_token(token) is None


# ── tenant_environment: unregistered tenant + repository error ──────────────


def test_tenant_environment_unregistered_tenant_returns_none():
    """`get_tenant()` returning a falsy value (tenant never registered) must
    resolve to None, not raise or KeyError, and the result gets cached."""
    slug = "principal-branch-test-unregistered-tenant"
    pr.invalidate_tenant_cache()
    try:
        assert pr.tenant_environment(slug) is None
        # Cached: a second call must not re-hit the repository (same result).
        assert pr.tenant_environment(slug) is None
    finally:
        pr.invalidate_tenant_cache()


def test_tenant_environment_repository_error_is_caught(monkeypatch):
    """A repository failure (DB down, etc.) inside the try block must
    degrade to None via the except clause, never propagate."""
    import original.repository as repo_mod

    def _boom():
        raise RuntimeError("db unreachable")

    slug = "principal-branch-test-repo-error"
    pr.invalidate_tenant_cache()
    monkeypatch.setattr(repo_mod, "get_repository", _boom)
    try:
        assert pr.tenant_environment(slug) is None
    finally:
        pr.invalidate_tenant_cache()


# ── extract_scoped_id: the canvas/baseline branch ────────────────────────────


def test_extract_scoped_id_canvas_baseline_path():
    assert pr.extract_scoped_id("/canvas/baseline/abc123/upload") == "abc123"


def test_extract_scoped_id_students_path_still_works():
    assert pr.extract_scoped_id("/students/sem:alice") == "sem:alice"


def test_extract_scoped_id_unrecognized_path_returns_none():
    assert pr.extract_scoped_id("/health") is None


# ── assert_student_access: anonymous/demo access on a real deploy (T-66) ────


def _demo_principal() -> pr.Principal:
    return pr.Principal(
        user_id="demo",
        role="operator",
        tenant_id=pr.DEMO_TENANT,
        auth_method="demo",
        is_demo=True,
    )


def test_demo_principal_flat_id_denied_on_real_deploy(monkeypatch):
    """The flat-id/demo-tenant carve-out assumes flat ids only ever exist in
    the demo sandbox — an invariant of legitimate write paths, not something
    assert_student_access can verify from the id alone. On a real deploy that
    assumption has no legitimate reason to matter: anonymous access must be
    denied outright, regardless of whether the id happens to look like a demo
    id."""
    import original.api as api_mod

    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", True)
    demo = _demo_principal()
    for student_id in ("some_flat_id", "demo:seeded_student"):
        try:
            pr.assert_student_access(demo, student_id)
            assert False, f"expected TenantAccessError for {student_id!r}"
        except pr.TenantAccessError:
            pass


def test_demo_principal_flat_id_still_allowed_off_real_deploy(monkeypatch):
    """Same principal/id shapes, but with _IS_REAL_DEPLOY False (the public
    demo default) — must keep working exactly as before (no regression)."""
    import original.api as api_mod

    monkeypatch.setattr(api_mod, "_IS_REAL_DEPLOY", False)
    demo = _demo_principal()
    pr.assert_student_access(demo, "some_flat_id")
    pr.assert_student_access(demo, "demo:seeded_student")
