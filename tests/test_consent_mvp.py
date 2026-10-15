"""Student consent MVP (university beta): one policy module, every gate.

Spec: the consent spec §1-§5 MVP row. Covers the pilot-agreement invite gate,
the versioned consent screen, the age block, withdrawal-as-exclusion, the
three-way Original gate, the teacher roster, the request-log IP removal, and
a source-level guard that every Original entry point consults the one policy.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from original import principal as principal_mod
from original.consent import policy
from original.onboarding import set_original
from original.repository import get_repository

PW = "s3cret-passw0rd"
TEXT = (
    "Augustine argues that the restless heart finds rest only in God, and he builds the "
    "argument slowly, from memory and desire, through the long middle books of the work, "
    "until the reader sees that the search was the subject all along. I find the argument "
    "persuasive in its account of desire but less so in its account of memory."
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


def _operator() -> dict:
    return _auth(principal_mod.mint_principal_token("op-1", "operator", "ops"))


def _agreement_body(**kw) -> dict:
    return {
        "entity_name": "Dept. of Philosophy",
        "signer_name": "Dean Smith",
        "doc_version": "pilot-2026-10-draft",
        "doc_sha256": hashlib.sha256(b"signed pdf").hexdigest(),
        "signed_on": "2026-10-12",
        **kw,
    }


def _university(client, email="prof@uni.edu", *, original=True, agreement=True, course_on=True):
    r = client.post(
        "/auth/signup",
        json={"email": email, "password": PW, "name": "Prof", "accept_terms": True},
    )
    assert r.status_code == 201, r.text
    prof = r.json()
    tid = prof["tenant_id"]
    repo = get_repository()
    t = repo.get_tenant(tid)
    repo.put_tenant(tid, t["name"], t["environment"], {**t["meta"], "tenant_type": "university"})
    if original:
        set_original(email, True)
    principal_mod.invalidate_tenant_cache()
    if agreement:
        r = client.post(f"/tenants/{tid}/agreements", json=_agreement_body(), headers=_operator())
        assert r.status_code == 201, r.text
    course = client.post(
        "/bluebook/courses", json={"name": "Ethics", "code": "ETH"}, headers=_auth(prof["token"])
    ).json()["id"]
    if course_on:
        r = client.patch(
            f"/bluebook/courses/{course}",
            json={"original_enabled": True},
            headers=_auth(prof["token"]),
        )
        assert r.status_code == 200 and r.json()["original_enabled"] is True
    return prof, course


def _student(client, prof, course, email="stu@uni.edu", name="Jane Doe"):
    r = client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": email, "name": name}]},
        headers=_auth(prof["token"]),
    )
    assert r.status_code == 200, r.text
    row = r.json()["students"][0]
    token = parse_qs(urlparse(row["invite_path"]).query)["invite"][0]
    r = client.post("/auth/invite/redeem", json={"token": token, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()


def _consent(client, stu, *, name="Jane Doe", over_18=True, class_use=True, consistency=True):
    return client.post(
        "/bluebook/me/consent",
        json={
            "typed_name": name,
            "over_18": over_18,
            "class_use": class_use,
            "consistency": consistency,
        },
        headers=_auth(stu["token"]),
    )


def _baseline(client, prof, sid):
    return client.post(
        f"/students/{sid}/baseline",
        json={"text": TEXT, "provenance": "verified", "assignment": "Essay 1"},
        headers=_auth(prof["token"]),
    )


# ── §5 Pilot agreement gate ───────────────────────────────────────────────────


def test_invite_blocked_without_agreement(live_client):
    prof, course = _university(live_client, agreement=False)
    r = live_client.post(
        f"/bluebook/courses/{course}/students",
        json={"students": [{"email": "a@uni.edu", "name": "A"}]},
        headers=_auth(prof["token"]),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "agreement_required"


def test_agreement_record_supersedes_and_gates_invites(live_client):
    prof, course = _university(live_client)
    tid = prof["tenant_id"]
    r = live_client.post(
        f"/tenants/{tid}/agreements", json=_agreement_body(doc_version="v2"), headers=_operator()
    )
    assert r.status_code == 201
    out = live_client.get(f"/tenants/{tid}/agreements", headers=_operator()).json()
    assert len(out["agreements"]) == 2 and out["current"]["doc_version"] == "v2"
    assert out["agreements"][0]["superseded_at"] is not None
    _student(live_client, prof, course)  # invites work with an agreement on file


def test_agreement_routes_require_operator_and_admin(live_client):
    prof, _ = _university(live_client)
    tid = prof["tenant_id"]
    r = live_client.post(
        f"/tenants/{tid}/agreements", json=_agreement_body(), headers=_auth(prof["token"])
    )
    assert r.status_code == 403
    assert (
        live_client.get(f"/tenants/{tid}/agreements", headers=_auth(prof["token"])).status_code
        == 403
    )
    assert (
        live_client.post(
            "/tenants/nope/agreements", json=_agreement_body(), headers=_operator()
        ).status_code
        == 404
    )


def test_agreement_hash_must_be_sha256(live_client):
    prof, _ = _university(live_client)
    r = live_client.post(
        f"/tenants/{prof['tenant_id']}/agreements",
        json=_agreement_body(doc_sha256="not-a-hash"),
        headers=_operator(),
    )
    assert r.status_code == 422


def test_non_regime_tenant_is_unchanged(live_client):
    """An independent teacher's workspace: no agreement, no consent screen."""
    r = live_client.post(
        "/auth/signup",
        json={"email": "t@x.edu", "password": PW, "name": "T", "accept_terms": True},
    )
    prof = r.json()
    course = live_client.post(
        "/bluebook/courses", json={"name": "C"}, headers=_auth(prof["token"])
    ).json()["id"]
    stu = _student(live_client, prof, course, "s@x.edu", "S")
    assert live_client.get("/bluebook/me/exams", headers=_auth(stu["token"])).status_code == 200
    view = live_client.get("/bluebook/me/consent", headers=_auth(stu["token"])).json()
    assert view["required"] is False and view["blocked"] is None
    assert policy.original_allowed(stu["student_id"]) is True


# ── §1 Consent screen ─────────────────────────────────────────────────────────


def test_student_blocked_until_consent(live_client):
    prof, course = _university(live_client)
    stu = _student(live_client, prof, course)
    h = _auth(stu["token"])
    for path in ("/bluebook/me/exams", "/bluebook/me/submissions", "/me/voice"):
        r = live_client.get(path, headers=h)
        assert r.status_code == 403, path
        assert r.json()["detail"]["code"] == "consent_required"
    me = live_client.get("/bluebook/me", headers=h).json()
    assert me["consent_blocked"] == "consent_required"
    view = live_client.get("/bluebook/me/consent", headers=h).json()
    assert set(view["needs"]) == {"class_use", "consistency", "age"}
    assert all("DRAFT — pending counsel review" in d["body"] for d in view["documents"])
    assert _consent(live_client, stu, consistency=False).status_code == 200
    assert live_client.get("/bluebook/me/exams", headers=h).status_code == 200


def test_scopes_default_off(live_client):
    prof, course = _university(live_client)
    stu = _student(live_client, prof, course)
    r = live_client.post(
        "/bluebook/me/consent",
        json={"typed_name": "Jane Doe", "over_18": True, "class_use": True},
        headers=_auth(stu["token"]),
    )
    assert r.json()["scopes"]["consistency"]["decision"] == "declined"
    assert r.json()["original_consent"] is False


def test_typed_name_mismatch_rejected(live_client):
    prof, course = _university(live_client)
    stu = _student(live_client, prof, course)
    assert _consent(live_client, stu, name="Someone Else").status_code == 422
    assert _consent(live_client, stu, name="  jane   DOE ").status_code == 200


def test_under18_university_blocked(live_client):
    prof, course = _university(live_client)
    stu = _student(live_client, prof, course)
    out = _consent(live_client, stu, over_18=False).json()
    assert out["age_blocked"] is True and out["blocked"] == "age_blocked"
    r = live_client.get("/bluebook/me/exams", headers=_auth(stu["token"]))
    assert r.json()["detail"]["code"] == "age_blocked"
    # A later "yes" does not lift an age block.
    assert _consent(live_client, stu).json()["blocked"] == "age_blocked"
    roster = live_client.get(
        f"/bluebook/courses/{course}/consent", headers=_auth(prof["token"])
    ).json()
    assert roster["students"][0]["alternative_assignment"] is True


def test_class_use_decline_sets_alternative(live_client):
    prof, course = _university(live_client)
    stu = _student(live_client, prof, course)
    out = _consent(live_client, stu, class_use=False).json()
    assert out["alternative_assignment"] is True
    # Declining class use also leaves (b) off, whatever was ticked.
    assert out["scopes"]["consistency"]["decision"] == "declined"
    r = live_client.get("/bluebook/me/exams", headers=_auth(stu["token"]))
    assert r.json()["detail"]["code"] == "alternative_assignment"
    # The student may change their mind later.
    assert _consent(live_client, stu).json()["blocked"] is None


def test_reconsent_only_blocks_changed_scope(live_client, monkeypatch):
    prof, course = _university(live_client)
    stu = _student(live_client, prof, course)
    _consent(live_client, stu)
    assert policy.original_allowed(stu["student_id"]) is True
    docs = {k: dict(v) for k, v in policy.DOCUMENTS.items()}
    docs["consistency"]["version"] = "2099-01-01"
    monkeypatch.setattr(policy, "DOCUMENTS", docs)
    # Class use continues; Original pauses until the new (b) is answered.
    assert live_client.get("/bluebook/me/exams", headers=_auth(stu["token"])).status_code == 200
    assert policy.original_allowed(stu["student_id"]) is False
    out = _consent(live_client, stu).json()
    assert out["needs"] == [] and out["original_consent"] is True


def test_consent_record_append_only_and_no_ip(live_client):
    prof, course = _university(live_client)
    stu = _student(live_client, prof, course)
    _consent(live_client, stu)
    live_client.post(
        "/bluebook/me/consent/withdraw", json={"scope": "consistency"}, headers=_auth(stu["token"])
    )
    rows = get_repository().list_consent_records(prof["tenant_id"], stu["student_id"])
    assert [r["decision"] for r in rows if r["scope"] == "consistency"] == [
        "granted",
        "withdrawn",
    ]
    for r in rows:
        assert set(r) == {
            "record_id", "tenant_id", "student_id", "course_id", "scope", "decision",
            "doc_version", "body_sha256", "typed_name", "age_attested", "created_at",
        }  # fmt: skip
        assert r["body_sha256"] == policy.body_sha256(r["scope"])
    audit = get_repository().list_audit(tenant_id=prof["tenant_id"], limit=500)["items"]
    blob = json.dumps(audit).lower()
    assert "testclient" not in blob and "user-agent" not in blob and "127.0.0.1" not in blob
    consent_rows = [a for a in audit if a["action"].startswith("consent_")]
    assert consent_rows
    for a in consent_rows:
        assert set(a.get("details") or {}) <= {"scope", "version"}


# ── §2 / §4.6 Withdrawal and the Original gate ────────────────────────────────


def test_original_gate_truth_table(live_client):
    cases = []
    for product in (True, False):
        for course_on in (True, False):
            for consent in (True, False):
                cases.append((product, course_on, consent))
    for i, (product, course_on, consent) in enumerate(cases):
        prof, course = _university(
            live_client, f"p{i}@uni.edu", original=product, course_on=course_on
        )
        stu = _student(live_client, prof, course, f"s{i}@uni.edu")
        _consent(live_client, stu, consistency=consent)
        principal_mod.invalidate_tenant_cache()
        expected = product and course_on and consent
        assert policy.original_allowed(stu["student_id"]) is expected, (product, course_on, consent)


def test_original_blocked_without_consent_at_entry_points(live_client):
    prof, course = _university(live_client)
    stu = _student(live_client, prof, course)
    _consent(live_client, stu, consistency=False)
    sid = stu["student_id"]
    h = _auth(prof["token"])
    calls = [
        ("post", f"/students/{sid}/baseline", {"text": TEXT, "provenance": "verified"}),
        ("post", f"/students/{sid}/score", {"text": TEXT}),
        ("post", f"/students/{sid}/score/blend", {"text": TEXT}),
        ("post", f"/students/{sid}/request-baseline", {}),
        ("post", f"/canvas/baseline/{sid}/import-baseline", {}),
    ]
    for method, path, body in calls:
        r = getattr(live_client, method)(path, json=body, headers=h)
        assert r.status_code in (403, 422), (path, r.status_code, r.text)
        if r.status_code == 403:
            assert r.json()["detail"]["code"] == "original_not_available", path
    r = live_client.post(
        f"/students/{sid}/baseline/upload-batch",
        files=[("files", ("a.txt", TEXT.encode(), "text/plain"))],
        headers=h,
    )
    assert r.status_code == 403
    r = live_client.post("/me/work", json={"text": TEXT, "title": "x"}, headers=_auth(stu["token"]))
    assert r.status_code == 403
    assert get_repository().get(sid) is None or get_repository().get(sid).sample_count == 0


def test_consenting_student_can_build_baseline(live_client):
    prof, course = _university(live_client)
    stu = _student(live_client, prof, course)
    _consent(live_client, stu)
    r = _baseline(live_client, prof, stu["student_id"])
    assert r.status_code == 200, r.text
    assert get_repository().get(stu["student_id"]).authenticated_count == 1


def test_withdraw_excludes_baseline_and_blocks_scoring(live_client):
    prof, course = _university(live_client)
    stu = _student(live_client, prof, course)
    _consent(live_client, stu)
    assert _baseline(live_client, prof, stu["student_id"]).status_code == 200
    r = live_client.post(
        "/bluebook/me/consent/withdraw", json={"scope": "consistency"}, headers=_auth(stu["token"])
    )
    assert r.status_code == 200 and r.json()["original_consent"] is False
    state = get_repository().get(stu["student_id"])
    assert state.sample_count == 1 and state.authenticated_count == 0  # kept, excluded
    assert state.samples[0].context_manifest["consent_excluded_at"]
    r = live_client.post(
        f"/students/{stu['student_id']}/score", json={"text": TEXT}, headers=_auth(prof["token"])
    )
    assert r.status_code == 403
    # Re-consent: Original runs again, but excluded samples stay excluded, so
    # the thin baseline reads "no authenticated samples" (INCONCLUSIVE path).
    _consent(live_client, stu)
    r = live_client.post(
        f"/students/{stu['student_id']}/score", json={"text": TEXT}, headers=_auth(prof["token"])
    )
    assert r.status_code == 422


def test_withdraw_class_use_sets_flag_without_penalty(live_client):
    prof, course = _university(live_client)
    stu = _student(live_client, prof, course)
    _consent(live_client, stu)
    out = live_client.post(
        "/bluebook/me/consent/withdraw", json={"scope": "class_use"}, headers=_auth(stu["token"])
    ).json()
    assert out["alternative_assignment"] is True
    assert out["scopes"]["consistency"]["decision"] == "withdrawn"
    roster = live_client.get(
        f"/bluebook/courses/{course}/consent", headers=_auth(prof["token"])
    ).json()["students"][0]
    assert roster["alternative_assignment"] is True and roster["original"] == "off"
    assert "typed_name" not in roster


def test_bulk_approve_skips_unconsented(live_client):
    prof, course = _university(live_client)
    exam = live_client.post(
        "/bluebook/exams",
        json={"title": "Mid", "status": "ACTIVE", "prompt": "Discuss.", "course_id": course},
        headers=_auth(prof["token"]),
    ).json()
    yes = _student(live_client, prof, course, "yes@uni.edu", "Yes Person")
    no = _student(live_client, prof, course, "no@uni.edu", "No Person")
    _consent(live_client, yes, name="Yes Person")
    _consent(live_client, no, name="No Person", consistency=False)
    for stu in (yes, no):
        h = _auth(stu["token"])
        assert (
            live_client.post(f"/bluebook/me/exams/{exam['id']}/start", headers=h).status_code == 200
        )
        r = live_client.post(
            "/bluebook/submissions",
            json={
                "exam_id": exam["id"],
                "student_id": stu["student_id"],
                "word_count": 60,
                "text": TEXT,
                "answers": [TEXT],
                "stylometric": 40,
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
    subs = {
        s["student_id"]: s for s in get_repository().list_bluebook_submissions(prof["tenant_id"])
    }
    assert subs[no["student_id"]]["stylometric"] is None  # seal stores no reading
    r = live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=_auth(prof["token"]))
    assert r.status_code == 200, r.text
    statuses = {row["submission_id"]: row["status"] for row in r.json()["results"]}
    assert statuses[subs[no["student_id"]]["id"]] == "skipped_no_consent"
    assert statuses[subs[yes["student_id"]]["id"]] == "added"
    r = live_client.post(
        f"/bluebook/submissions/{subs[no['student_id']]['id']}/baseline",
        headers=_auth(prof["token"]),
    )
    assert r.status_code == 403


def test_pool_excludes_non_consenting_students(live_client):
    prof, course = _university(live_client)
    yes = _student(live_client, prof, course, "yes@uni.edu", "Yes Person")
    no = _student(live_client, prof, course, "no@uni.edu", "No Person")
    _consent(live_client, yes, name="Yes Person")
    _consent(live_client, no, name="No Person")
    _baseline(live_client, prof, yes["student_id"])
    _baseline(live_client, prof, no["student_id"])
    live_client.post(
        "/bluebook/me/consent/withdraw", json={"scope": "consistency"}, headers=_auth(no["token"])
    )
    states = get_repository().all_states(tenant_id=prof["tenant_id"])
    kept = {s.student_id for s in policy.filter_pool(states)}
    assert yes["student_id"] in kept and no["student_id"] not in kept


def test_roster_is_course_scoped(live_client):
    prof, course = _university(live_client)
    other, _ = _university(live_client, "other@uni.edu")
    r = live_client.get(f"/bluebook/courses/{course}/consent", headers=_auth(other["token"]))
    assert r.status_code == 404


# ── §1 IP-free request logs ───────────────────────────────────────────────────


def test_request_log_has_no_ip_or_ua(live_client, caplog):
    caplog.set_level(logging.INFO)
    live_client.get("/bluebook/courses", headers={"User-Agent": "UniqueAgent/9"})
    recs = [r for r in caplog.records if r.getMessage() == "request"]
    assert recs
    for r in recs:
        assert not hasattr(r, "client_ip") and not hasattr(r, "user_agent")
        assert "UniqueAgent" not in json.dumps(r.__dict__, default=str)


# ── Bypass guard: every Original entry point consults the one policy ──────────

# Calls that read or write a student's Original data. Any router function that
# makes one must also call consent_policy (or be listed here with a reason).
_SENSITIVE = {"add_sample", "quantum_score", "detect_blend", "score_submission"}
_ALLOWED = {
    # Playground: inline texts only, no student id, no DB writes.
    ("admin.py", "test_score"),
    # Calls add_baseline, which consults the policy; _add checks it too.
    ("bluebook_baselines.py", "_add"),
}


def _calls(fn: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            names.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return names


def test_every_original_entry_point_calls_the_policy():
    routers = Path(__file__).resolve().parents[1] / "original" / "routers"
    offenders = []
    checked = 0
    for path in sorted(routers.glob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            calls = _calls(fn)
            if not calls & _SENSITIVE or fn.name == "score_submission":
                continue
            checked += 1
            if (path.name, fn.name) in _ALLOWED:
                continue
            src = ast.get_source_segment(path.read_text(), fn) or ""
            if "consent_policy." not in src:
                offenders.append(f"{path.name}:{fn.name}")
    assert checked >= 6, "guard found too few entry points; is the scan broken?"
    assert offenders == [], f"Original entry points missing the consent policy: {offenders}"


def test_score_submission_itself_calls_the_policy():
    import inspect

    from original.routers.students_scoring import score_submission

    assert "consent_policy.require_original" in inspect.getsource(score_submission)
