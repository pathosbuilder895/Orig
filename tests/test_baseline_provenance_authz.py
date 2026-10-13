"""
Provenance-authorization tests for POST /students/{id}/baseline.

A baseline sample's ``provenance`` sets its trust weight in the voice profile
(proctored 2.0 / verified 1.0 / canvas 0.8 / unverified 0.5). If a *student*
could self-assert a high-trust provenance, they could inject ghostwritten or
AI-written text as "proctored" ground truth and drag their own baseline toward
the very thing the system exists to flag. This gate proves:

  1. A student token cannot self-assert a trusted provenance — proctored /
     verified / canvas are all downgraded to 'unverified'.
  2. Staff principals (professor/admin/operator) keep the requested provenance.
  3. The anonymous demo principal keeps it too, but ONLY off a real deploy (the
     demo/e2e Bluebook flow posts proctored without a token). On a pilot it is
     an unauthenticated caller and is downgraded like any other — otherwise
     dropping the Authorization header would buy more trust than sending a real
     student session, since the anonymous principal carries a synthetic
     "operator" role.
  4. The legitimate proctored path still lands proctored samples: a student
     token accompanied by a valid server-minted proctor attestation (the
     ``X-Proctor-Attestation`` the LTI exam launch issues) is honored.
  5. An attestation minted for a *different* student does not authorize.
  6. The proctor attestation and the login session token are not interchangeable.
  7. A proctor attestation is single-use (T-69): the first proctored write it
     authorizes lands at full weight; a second write presenting the SAME
     attestation is downgraded to 'unverified' rather than honored again —
     closing the replay window a captured token would otherwise leave open
     for its whole 6h validity.
"""

import pytest
from fastapi.testclient import TestClient

import run  # repo-root launcher
from original import principal as pr
from original import student_auth

# ~130 words — comfortably above any per-sample minimum.
LONG_TEXT = (
    "The doctrine of justification by faith stands at the center of the gospel. "
    "When Paul writes to the Romans, he labors to show that righteousness comes "
    "not by works of the law but through faith alone. A careful reader notices "
    "how the argument unfolds in stages, each building on the last, until the "
    "conclusion becomes unavoidable. The voice here is deliberate and measured, "
    "favoring long subordinate clauses and a vocabulary drawn from systematic "
    "study. Such patterns, repeated across many essays, form a fingerprint as "
    "distinctive as handwriting. The student who writes this way in September "
    "will, absent intervention, write this way in May, and that continuity is "
    "precisely what we set out to measure and to protect with patience and care."
)


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def app():
    return run.load_legacy_demo_app()


@pytest.fixture
def client(app, store_reset):
    return TestClient(app)


@pytest.fixture
def real_deploy(monkeypatch):
    """Flip the loaded app into pilot behaviour without reloading it."""
    import original.api

    monkeypatch.setattr(original.api, "_IS_REAL_DEPLOY", True)
    yield


def _post_baseline(client, sid, provenance, *, headers=None):
    return client.post(
        f"/students/{sid}/baseline",
        json={"text": LONG_TEXT, "provenance": provenance, "assignment": "a1"},
        headers=headers or {},
    )


# ── 1. Students cannot self-assert trusted provenance ─────────────────────────


@pytest.mark.parametrize("provenance", ["proctored", "verified", "canvas"])
def test_student_trusted_provenance_downgraded(client, provenance):
    sid = "acme:selfauthor"
    stu = pr.mint_principal_token(sid, "student", "acme")
    r = _post_baseline(client, sid, provenance, headers=_auth(stu))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provenance"] == "unverified", body
    assert body["auth_weight"] == 0.5, body
    assert body["provenance_downgraded"] is True
    assert body["requested_provenance"] == provenance


def test_student_unverified_stays_unverified(client):
    """The self-assertable provenance is untouched — no spurious downgrade flag."""
    sid = "acme:honest"
    stu = pr.mint_principal_token(sid, "student", "acme")
    r = _post_baseline(client, sid, "unverified", headers=_auth(stu))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provenance"] == "unverified"
    assert "provenance_downgraded" not in body


# ── 2. Staff keep the requested provenance ────────────────────────────────────


def test_staff_verified_preserved(client):
    prof = pr.mint_principal_token("prof_acme", "professor", "acme")
    r = _post_baseline(client, "acme:bob", "verified", headers=_auth(prof))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provenance"] == "verified"
    assert body["auth_weight"] == 1.0


def test_staff_proctored_preserved(client):
    op = pr.mint_principal_token("op1", "operator", "platform")
    r = _post_baseline(client, "acme:carol", "proctored", headers=_auth(op))
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == "proctored"


# ── 3. Anonymous demo principal keeps proctored (demo/e2e flow) ───────────────


def test_demo_anonymous_proctored_preserved(client):
    """No token → demo principal (operator); the demo Bluebook flow posts
    proctored this way and must keep landing proctored samples."""
    r = _post_baseline(client, "demo_flat_student", "proctored")
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == "proctored"


def test_anonymous_proctored_downgraded_on_real_deploy(real_deploy):
    """On a pilot, dropping the Authorization header must NOT out-privilege an
    authenticated student.

    Regression: the anonymous principal defaults to role "operator", which is in
    _STAFF_ROLES, so an unauthenticated POST used to sail through the staff rule
    and land AI text at proctored/2.0 — while the same student's real session
    token was correctly downgraded to unverified/0.5.

    The tenant-isolation middleware now refuses the anonymous principal on every
    Original route on a real deploy (see the next test), so this handler clamp is
    defence in depth that no HTTP request can reach. It is pinned directly: if
    the middleware gate is ever loosened, the clamp must still hold.
    """
    from types import SimpleNamespace

    from original.routers._shared import _authorize_provenance

    anonymous = pr.Principal(
        user_id="demo", role="operator", tenant_id=pr.DEMO_TENANT, auth_method="demo", is_demo=True
    )
    request = SimpleNamespace(state=SimpleNamespace(principal=anonymous), headers={})
    assert _authorize_provenance(request, "seminary-of-dallas:jane", "proctored") == (
        "unverified",
        True,
    )


def test_anonymous_baseline_post_refused_on_real_deploy_even_for_a_demo_tenant(
    client, real_deploy
):
    """The tenant is registered with environment="demo", which used to be what
    let the anonymous principal past the isolation middleware. The middleware
    now answers 401 for it, and nothing is stored. (The tenant is registered
    directly: the only way a demo tenant exists on a pilot is an operator's
    guarded POST /tenants.)"""
    from original import student_auth
    from original.repository import get_repository

    get_repository().put_tenant("seminary-of-dallas", "Seminary of Dallas", environment="demo")
    sid = student_auth.derive_student_id("Seminary of Dallas", "jane@sod.edu")

    r = _post_baseline(client, sid, "proctored")
    assert r.status_code == 401, r.text
    assert get_repository().get(sid) is None


def test_authenticated_staff_still_preserved_on_real_deploy(client, real_deploy):
    """The real-deploy clamp must bite only the anonymous principal — a genuine
    professor token still keeps the requested provenance."""
    prof = pr.mint_principal_token("prof_x", "professor", "acme")
    r = _post_baseline(client, "acme:kid", "proctored", headers=_auth(prof))
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == "proctored"


# ── 4. The attested proctored path is honored ─────────────────────────────────


def test_student_with_attestation_lands_proctored(client):
    """A bound student in a real exam carries a student session token PLUS the
    server-minted proctor attestation — the legitimate proctored ingestion."""
    sid = "acme:examtaker"
    stu = pr.mint_principal_token(sid, "student", "acme")
    attest = student_auth.mint_proctor_attestation(sid, "Week 1 Writing Sample")
    headers = {**_auth(stu), "X-Proctor-Attestation": attest}
    r = _post_baseline(client, sid, "proctored", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provenance"] == "proctored", body
    assert body["auth_weight"] == 2.0
    assert "provenance_downgraded" not in body


def test_attestation_for_other_student_does_not_authorize(client):
    """An attestation minted for a different sid must not unlock this student."""
    sid = "acme:victim"
    stu = pr.mint_principal_token(sid, "student", "acme")
    wrong = student_auth.mint_proctor_attestation("acme:someone_else", "exam")
    headers = {**_auth(stu), "X-Proctor-Attestation": wrong}
    r = _post_baseline(client, sid, "proctored", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == "unverified"


# ── 5. Token types are not interchangeable ────────────────────────────────────


def test_proctor_attestation_is_not_a_session():
    sid = "acme:x"
    attest = student_auth.mint_proctor_attestation(sid)
    # A proctor attestation must never authenticate a request as a session.
    assert student_auth.verify_session(attest) is None
    assert student_auth.verify_proctor_attestation(attest, sid) is True


def test_session_token_is_not_an_attestation():
    sid = "acme:x"
    session = student_auth.mint_session(sid, "Ex Ample")
    assert student_auth.verify_proctor_attestation(session, sid) is False
    assert student_auth.verify_session(session) is not None


def test_attestation_signature_is_verified():
    sid = "acme:x"
    forged = student_auth.mint_proctor_attestation(sid)[:-3] + "xxx"
    assert student_auth.verify_proctor_attestation(forged, sid) is False


# ── 7. Proctor attestations are single-use (T-69) ─────────────────────────────

SECOND_TEXT = (
    "Systematic theology proceeds by careful attention to the whole counsel of "
    "Scripture. Each doctrine must be weighed against the entire canon rather "
    "than isolated proof texts, and the task requires patience, humility, and "
    "a willingness to be corrected by the text itself rather than by habit. "
    "This second sample must differ from the first so the seal-replay dedup "
    "guard (matched on text hash) never triggers — this test exercises the "
    "attestation single-use ledger, not the unrelated duplicate-text guard."
)


def test_attestation_reused_on_a_second_write_is_downgraded(client, store_reset):
    """The FIRST proctored write with a given attestation lands at full
    weight; a SECOND write presenting the identical token — a captured or
    accidentally-resent attestation — is downgraded, not honored again."""
    sid = "acme:examtaker-replay"
    stu = pr.mint_principal_token(sid, "student", "acme")
    attest = student_auth.mint_proctor_attestation(sid, "Week 1 Writing Sample")
    headers = {**_auth(stu), "X-Proctor-Attestation": attest}

    first = _post_baseline(client, sid, "proctored", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["provenance"] == "proctored"
    assert first.json()["auth_weight"] == 2.0

    second = client.post(
        f"/students/{sid}/baseline",
        json={"text": SECOND_TEXT, "provenance": "proctored", "assignment": "a1"},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["provenance"] == "unverified"
    assert body["auth_weight"] == 0.5
    assert body["provenance_downgraded"] is True
    assert body["requested_provenance"] == "proctored"


def test_attestation_held_for_drift_review_is_not_consumed(client, store_reset, monkeypatch):
    """A write that gets HELD for drift review (202/409) never reaches
    state.add_sample, so it must not burn the attestation — a legitimate
    retry of the same sitting can still redeem it."""
    from original.quantum.state import DriftResult, StudentState

    sid = "acme:examtaker-drifthold"
    stu = pr.mint_principal_token(sid, "student", "acme")
    attest = student_auth.mint_proctor_attestation(sid, "Week 1 Writing Sample")
    headers = {**_auth(stu), "X-Proctor-Attestation": attest}

    held = DriftResult(
        drift_detected=True,
        drift_magnitude=0.9,
        anchor_tier_deviations={4: 0.9},
        recommendation="flag_for_review",
        consecutive_drift_count=1,
    )
    monkeypatch.setattr(StudentState, "check_drift", lambda self, sample: held)

    first = _post_baseline(client, sid, "proctored", headers=headers)
    assert first.status_code == 202, first.text

    monkeypatch.undo()  # let the retry through the real (accepting) drift gate
    retry = _post_baseline(client, sid, "proctored", headers=headers)
    assert retry.status_code == 200, retry.text
    assert (
        retry.json()["provenance"] == "proctored"
    ), "the held attempt must not have consumed the attestation"


def test_attestation_reused_in_a_batch_upload_downgrades_remaining_files(client, store_reset):
    """T-69 extended to the batch route (a batch is one HTTP call that can
    admit many files at once — exactly the 'reuse a proctor attestation'
    shape T-69 describes if left unguarded). The first file consumes the
    attestation; every remaining file in the SAME batch is downgraded too."""
    import io

    sid = "acme:examtaker-batch"
    stu = pr.mint_principal_token(sid, "student", "acme")
    attest = student_auth.mint_proctor_attestation(sid, "Week 1 Writing Sample")
    headers = {**_auth(stu), "X-Proctor-Attestation": attest}

    r = client.post(
        f"/students/{sid}/baseline/upload-batch",
        files=[
            ("files", ("a.txt", io.BytesIO(LONG_TEXT.encode()), "text/plain")),
            ("files", ("b.txt", io.BytesIO(SECOND_TEXT.encode()), "text/plain")),
        ],
        data={"provenance": "proctored", "assignment": ""},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 2
    assert body["provenance"] == "unverified"
    assert body["provenance_downgraded"] is True
    assert body["provenance_counts"] == {"proctored": 1, "unverified": 1}

    from original.repository import get_repository

    samples = get_repository().get(sid).samples
    assert [s.provenance for s in samples] == ["proctored", "unverified"]
    assert [s.auth_weight for s in samples] == [2.0, 0.5]


# ── 8. An attestation authorizes ONE proctored sitting, nothing else ──────────

THIRD_TEXT = (
    "Church history rewards the reader who keeps several centuries in view at "
    "once. Councils answered questions their predecessors had not thought to "
    "ask, and each answer narrowed the next debate. A student tracing that "
    "movement learns to read slowly, to weigh a creed against the controversy "
    "that produced it, and to resist the temptation to read modern categories "
    "back into ancient arguments. This third sample exists only to differ in "
    "text from the other two, so no duplicate guard can mask a replay."
)


@pytest.mark.parametrize("provenance", ["verified", "canvas"])
def test_attestation_does_not_authorize_non_proctored_provenance(client, provenance):
    """A proctor attestation attests a proctored sitting. It must not buy
    instructor-verified or LMS trust, which the single-use ledger never
    consumes, so a student could otherwise replay one token as 'verified'
    without limit for its whole validity window."""
    sid = "acme:examtaker-verified"
    stu = pr.mint_principal_token(sid, "student", "acme")
    attest = student_auth.mint_proctor_attestation(sid, "Week 1 Writing Sample")
    headers = {**_auth(stu), "X-Proctor-Attestation": attest}
    for text in (LONG_TEXT, SECOND_TEXT):
        r = client.post(
            f"/students/{sid}/baseline",
            json={"text": text, "provenance": provenance, "assignment": "a1"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["provenance"] == "unverified", r.json()
        assert r.json()["provenance_downgraded"] is True


def test_reissued_attestation_for_the_same_sitting_is_single_use(client, store_reset):
    """Two attestations minted for the same sitting (a reloaded launch link,
    a restarted exam) differ byte-for-byte because their expiry differs, but
    they authorize ONE proctored sample between them."""
    sid = "acme:examtaker-reissue"
    stu = pr.mint_principal_token(sid, "student", "acme")
    first = student_auth.mint_proctor_attestation(sid, "Exam", sitting="link-1")
    second = student_auth.mint_proctor_attestation(
        sid, "Exam", ttl_seconds=3600, sitting="link-1"
    )
    assert first != second
    r1 = _post_baseline(
        client, sid, "proctored", headers={**_auth(stu), "X-Proctor-Attestation": first}
    )
    assert r1.json()["provenance"] == "proctored", r1.text
    r2 = client.post(
        f"/students/{sid}/baseline",
        json={"text": SECOND_TEXT, "provenance": "proctored", "assignment": "a1"},
        headers={**_auth(stu), "X-Proctor-Attestation": second},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["provenance"] == "unverified", r2.json()


def test_attestations_for_different_sittings_are_independent(client, store_reset):
    sid = "acme:examtaker-two-sittings"
    stu = pr.mint_principal_token(sid, "student", "acme")
    for sitting, text in (("exam-a", LONG_TEXT), ("exam-b", SECOND_TEXT)):
        attest = student_auth.mint_proctor_attestation(sid, "Exam", sitting=sitting)
        r = client.post(
            f"/students/{sid}/baseline",
            json={"text": text, "provenance": "proctored", "assignment": "a1"},
            headers={**_auth(stu), "X-Proctor-Attestation": attest},
        )
        assert r.json()["provenance"] == "proctored", r.text


def test_staff_write_does_not_consume_an_attestation_header(client, store_reset):
    """Staff trust comes from the staff role, not from any attestation the
    request happens to carry, so a staff write must neither consume the
    student's sitting nor be downgraded by an already-used token."""
    sid = "acme:examtaker-staff"
    attest = student_auth.mint_proctor_attestation(sid, "Exam", sitting="s-1")
    prof = pr.mint_principal_token("prof-1", "professor", "acme")
    staff = client.post(
        f"/students/{sid}/baseline",
        json={"text": LONG_TEXT, "provenance": "proctored", "assignment": "a1"},
        headers={**_auth(prof), "X-Proctor-Attestation": attest},
    )
    assert staff.json()["provenance"] == "proctored", staff.text
    stu = pr.mint_principal_token(sid, "student", "acme")
    own = client.post(
        f"/students/{sid}/baseline",
        json={"text": SECOND_TEXT, "provenance": "proctored", "assignment": "a1"},
        headers={**_auth(stu), "X-Proctor-Attestation": attest},
    )
    assert own.json()["provenance"] == "proctored", own.text


def test_failed_persist_releases_the_attestation(client, store_reset, monkeypatch):
    """The attestation is redeemed only once the sample is stored: a storage
    failure (503) must leave it redeemable for the retry of the same sitting."""
    from fastapi import HTTPException

    from original.routers import students_baseline

    sid = "acme:examtaker-503"
    stu = pr.mint_principal_token(sid, "student", "acme")
    attest = student_auth.mint_proctor_attestation(sid, "Exam", sitting="s-503")
    headers = {**_auth(stu), "X-Proctor-Attestation": attest}

    def _fail(state):
        raise HTTPException(status_code=503, detail="Not persisted; retry.")

    monkeypatch.setattr(students_baseline, "_persist_or_503", _fail)
    assert _post_baseline(client, sid, "proctored", headers=headers).status_code == 503
    monkeypatch.undo()

    retry = client.post(
        f"/students/{sid}/baseline",
        json={"text": THIRD_TEXT, "provenance": "proctored", "assignment": "a1"},
        headers=headers,
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["provenance"] == "proctored", retry.json()


def test_downgraded_write_does_not_complete_a_baseline_request(client, store_reset, monkeypatch):
    """Every AUTH_WEIGHTS value is above zero, so 'auth_weight > 0' let an
    unverified self-upload mark a professor's proctored-sitting request done."""
    from original import baseline_requests

    calls = []
    monkeypatch.setattr(
        baseline_requests, "mark_completed_for_student", lambda sid: calls.append(sid) or []
    )
    sid = "acme:selfupload-request"
    stu = pr.mint_principal_token(sid, "student", "acme")
    r = _post_baseline(client, sid, "proctored", headers=_auth(stu))
    assert r.json()["provenance"] == "unverified"
    assert calls == []

    prof = pr.mint_principal_token("prof-1", "professor", "acme")
    r = client.post(
        f"/students/{sid}/baseline",
        json={"text": SECOND_TEXT, "provenance": "proctored", "assignment": "a1"},
        headers=_auth(prof),
    )
    assert r.json()["provenance"] == "proctored"
    assert calls == [sid]


def test_magic_link_reredemption_keeps_one_sitting(client, monkeypatch):
    """Reopening the same launch link mints a fresh attestation (new expiry)
    but for the SAME sitting, so it cannot buy a second proctored sample."""
    sid = "acme:linktaker"
    link = student_auth.mint_launch_token(sid, "acme", exam="Week 2")
    first = client.get("/bluebook/launch", params={"t": link})
    assert first.status_code == 200, first.text
    clock = student_auth.time.time()
    monkeypatch.setattr(student_auth.time, "time", lambda: clock + 120)
    second = client.get("/bluebook/launch", params={"t": link})
    assert second.status_code == 200, second.text

    def _attestation(resp):
        import re

        m = re.search(r'localStorage\.setItem\("bluebook_proctor_token","([^"]+)"\)', resp.text)
        assert m, resp.text[:500]
        return m.group(1)

    a1, a2 = _attestation(first), _attestation(second)
    assert a1 != a2
    assert student_auth.attestation_jti(a1) == student_auth.attestation_jti(a2)
    other = student_auth.mint_launch_token(sid, "acme", exam="Week 3")
    a3 = _attestation(client.get("/bluebook/launch", params={"t": other}))
    assert student_auth.attestation_jti(a3) != student_auth.attestation_jti(a1)
