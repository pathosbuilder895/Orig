"""One definition of an approved past paper (rule B, 2026-11).

A sample counts toward the minimum-baseline floor and the readiness report
when its provenance is trusted (proctored, verified, canvas), or it is a
shared past paper a teacher approved, or a take-home sitting a teacher
approved. Only a student's own self-upload that no teacher approved is left
out (``original/approved_papers.py``).

#271 counted trusted provenances only in ``baseline_integrity``, so an alpha
volunteer whose three baseline papers are approved shared papers (they enter
as ``unverified``) read ``thin`` and Bluebook sealed their sitting
INCONCLUSIVE. These tests hold every surface that decides "enough past
papers" to the one count, for staff and student callers.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from original import baseline_integrity, principal
from original.evidence import INCONCLUSIVE_WORDS
from original.repository import SqliteRepository, get_repository, reset_repository
from tests.alpha.test_alpha_ready_e2e import TOPICS, _paper
from tests.alpha.test_past_papers import _ok, _share, _workspace

SUBMISSION = _paper(1, "public parks")


@pytest.fixture(autouse=True)
def _fresh(store_reset, monkeypatch):
    monkeypatch.setenv("INVITE_NO_EXPIRY", "1")
    monkeypatch.delenv("MIN_BASELINE_SAMPLES", raising=False)
    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    monkeypatch.setenv("PRELIMINARY_SCORE_ENABLED", "1")
    reset_repository()
    principal.invalidate_tenant_cache()
    yield
    reset_repository()
    principal.invalidate_tenant_cache()


# ── helpers ──────────────────────────────────────────────────────────────────


def _share_and_approve(client, T, S, ks):
    """Student S shares papers TOPICS[k] for each k; teacher T approves them."""
    for k in ks:
        _ok(_share(client, S, text=_paper(0, TOPICS[k]), title=f"Paper {k}"), 201)
    rows = _ok(client.get("/bluebook/past-papers", headers=T))["papers"]
    ids = {p["title"]: p["paper_id"] for p in rows}
    for k in ks:
        out = _ok(client.post(f"/bluebook/past-papers/{ids[f'Paper {k}']}/approve", headers=T))
        assert out["status"] == "approved", out
    return ids


def _self_upload(client, sid, S, k):
    """The student's own upload: asks for 'verified', is kept as 'unverified'."""
    r = client.post(
        f"/students/{sid}/baseline",
        json={"text": _paper(0, TOPICS[k]), "provenance": "verified", "assignment": "mine"},
        headers=S,
    )
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == "unverified"


def _open_sitting(sid):
    """An exam with writing consistency on and this student's sitting, so a
    student principal may score (``_require_student_exam_scoring``), exactly
    as Bluebook's seal does."""
    repo = get_repository()
    tenant = principal.tenant_of(sid)
    repo.put_bluebook_exam(
        {
            "id": f"exam-seal-{sid[-6:]}",
            "tenant_id": tenant,
            "title": "Sitting",
            "conditions": {"aiDetect": True},
        }
    )
    repo.get_or_create_bluebook_session(f"exam-seal-{sid[-6:]}", sid, tenant, 3600)


def _score(client, sid, headers, sub="s1"):
    return client.post(
        f"/students/{sid}/score", json={"text": SUBMISSION, "submission_id": sub}, headers=headers
    )


def _readiness(client, sid, T):
    return _ok(client.get(f"/students/{sid}/readiness", headers=T))


def _seal_status(response) -> str:
    """Bluebook's seal decision (demo/bluebook/Exam.jsx: bbScoreWithOriginal
    then bbSealStatus) for a sitting with Original on: a 422
    insufficient_baseline, or a 200 whose baseline_integrity is not ready,
    is INCONCLUSIVE; any other reading is SUBMITTED or FLAGGED."""
    if response.status_code == 422:
        assert response.json()["detail"]["code"] == "insufficient_baseline"
        return "INCONCLUSIVE"
    assert response.status_code == 200, response.text
    bi = response.json().get("baseline_integrity")
    if not bi or bi["readiness"] != "ready":
        return "INCONCLUSIVE"
    return "READ"


# ── the pure count ───────────────────────────────────────────────────────────


def _s(provenance, weight=1.0):
    return SimpleNamespace(provenance=provenance, auth_weight=weight)


def test_rule_b_counts_trusted_and_teacher_approved_and_nothing_else():
    samples = [
        _s(p)
        for p in (
            "proctored",
            "verified",
            "canvas",
            "unverified",
            "unverified",
            "unverified",
            "instructor_verified",
        )
    ]
    sources = ["staff_or_supervised"] * 3 + [
        "shared_paper",
        "take_home",
        "student_upload",
        "unknown",
    ]
    assert baseline_integrity.APPROVED_SOURCES == {
        "staff_or_supervised",
        "shared_paper",
        "take_home",
    }
    assert baseline_integrity.count_approved(samples, sources) == 5
    # No records read: only what provenance alone shows to be approved.
    assert baseline_integrity.count_approved(samples, None) == 3
    # A sample that carries no weight does not count either way.
    assert (
        baseline_integrity.count_approved(
            [_s("verified", 0.0), _s("unverified", 0.0)], ["staff_or_supervised", "shared_paper"]
        )
        == 0
    )


def test_baseline_integrity_reads_the_sources_it_is_given():
    import numpy as np

    from original.constants import FEATURE_DIM
    from original.quantum.state import BaselineSample, StudentState

    st = StudentState(
        student_id="t:x",
        samples=[
            BaselineSample(
                text=f"paper {i}",
                vector=np.full(FEATURE_DIM, 0.5 + i / 100),
                provenance="unverified",
                auth_weight=0.5,
            )
            for i in range(3)
        ],
    )
    assert baseline_integrity.build_baseline_integrity(st).readiness == "thin"
    ready = baseline_integrity.build_baseline_integrity(
        st, sources=["shared_paper", "take_home", "shared_paper"]
    )
    assert (ready.readiness, ready.n_baselines) == ("ready", 3)
    thin = baseline_integrity.build_baseline_integrity(
        st, sources=["shared_paper", "shared_paper", "student_upload"]
    )
    assert (thin.readiness, thin.n_baselines) == ("thin", 2)


# ── 3 approved shared papers: ready, scored, preliminary shown ───────────────


@pytest.mark.slow
def test_three_approved_shared_papers_are_ready_for_staff_and_student(live_client):
    T, [(sid, S), _] = _workspace(live_client, "apc1@example.test")
    _share_and_approve(live_client, T, S, range(3))
    assert {s.provenance for s in get_repository().get(sid).samples} == {"unverified"}

    # #271's regression: these three read "thin" although a teacher approved each.
    staff = _ok(_score(live_client, sid, T))
    assert staff["baseline_integrity"]["readiness"] == "ready"
    assert staff["baseline_integrity"]["n_baselines"] == 3
    assert staff["preliminary"]["score"] is not None  # a reading, not "not enough writing"
    assert staff["preliminary"]["band_words"] != INCONCLUSIVE_WORDS
    assert [p["source"] for p in staff["evidence"]["baseline_papers"]] == ["shared_paper"] * 3

    ready = _readiness(live_client, sid, T)
    assert ready["verdict"] == "ready"
    assert ready["approved_count"] == 3 and ready["authenticated_count"] == 3
    assert not any("approved baseline papers" in r for r in ready["recommendations"])

    # The student's own sealed sitting (Bluebook) reads the same baseline as ready.
    _open_sitting(sid)
    mine = _score(live_client, sid, S, sub="s2")
    assert _seal_status(mine) == "READ"
    body = mine.json()
    assert body["baseline_integrity"]["n_baselines"] == 3
    assert body.get("preliminary") is None and body.get("evidence") is None


# ── 2 approved + 1 self-upload: thin, refused, inconclusive ──────────────────


@pytest.mark.slow
def test_two_approved_and_a_self_upload_is_thin_for_staff_and_student(live_client):
    T, [(sid, S), _] = _workspace(live_client, "apc2@example.test")
    _share_and_approve(live_client, T, S, range(2))
    _self_upload(live_client, sid, S, 2)
    state = get_repository().get(sid)
    assert state.authenticated_count == 3  # on file and weighted...

    ready = _readiness(live_client, sid, T)
    assert ready["verdict"] == "developing"  # ...but not three approved papers
    assert ready["approved_count"] == 2 and ready["authenticated_count"] == 3
    assert any(
        "at least 3 approved baseline papers; this student has 2." in r
        for r in ready["recommendations"]
    ), ready["recommendations"]

    refused = _score(live_client, sid, T)
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "insufficient_baseline"
    assert (detail["required"], detail["have"]) == (3, 2)
    assert "needs at least 3 approved baseline papers" in detail["message"]
    assert detail["message"].endswith("this student has 2.")
    assert "deviation_score" not in refused.text
    blend = live_client.post(f"/students/{sid}/score/blend", json={"text": SUBMISSION}, headers=T)
    assert blend.status_code == 422 and blend.json()["detail"]["have"] == 2

    _open_sitting(sid)
    assert _seal_status(_score(live_client, sid, S, sub="s2")) == "INCONCLUSIVE"


@pytest.mark.slow
def test_below_a_lowered_floor_the_report_still_reads_thin(live_client, monkeypatch):
    """With the floor lowered (research harnesses, conftest's legacy 1) the
    route scores, but the readiness report still counts approved papers only
    against its own 3, so Bluebook seals the sitting INCONCLUSIVE."""
    T, [(sid, S), _] = _workspace(live_client, "apc3@example.test")
    _share_and_approve(live_client, T, S, range(2))
    _self_upload(live_client, sid, S, 2)
    monkeypatch.setenv("MIN_BASELINE_SAMPLES", "1")
    staff = _ok(_score(live_client, sid, T))
    assert staff["baseline_integrity"]["readiness"] == "thin"
    assert staff["baseline_integrity"]["n_baselines"] == 2
    _open_sitting(sid)
    assert _seal_status(_score(live_client, sid, S, sub="s2")) == "INCONCLUSIVE"


def test_preliminary_chip_is_inconclusive_below_the_approved_floor(monkeypatch):
    """The chip reads the route's own approved count, not authenticated_count."""
    from original.routers import students_scoring as ss

    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "0")

    class _Resp:
        preliminary = None
        evidence = None

    result = SimpleNamespace(
        baseline_confidence=SimpleNamespace(authenticated_count=3),
        feature_vector=None,
        authorship=SimpleNamespace(deviation_score=0.4),
        recommendation=SimpleNamespace(action="monitor"),
    )
    state = SimpleNamespace(samples=[_s("unverified")] * 3)
    request = SimpleNamespace(state=SimpleNamespace(principal=None))
    for approved, reading in ((2, False), (3, True)):
        resp = _Resp()
        ss._attach_staff_explainability(resp, request, "t", state, result, "t:x", approved=approved)
        assert (resp.preliminary.score is not None) is reading, approved
        assert (resp.preliminary.band_words == INCONCLUSIVE_WORDS) is not reading, approved
    # Without the route's count only trusted provenances count: three
    # self-uploads are inconclusive even though authenticated_count is 3.
    resp = _Resp()
    ss._attach_staff_explainability(resp, request, "t", state, result, "t:x")
    assert resp.preliminary.score is None and resp.preliminary.band_words == INCONCLUSIVE_WORDS


# ── approved take-homes and proctored sittings count ─────────────────────────


@pytest.mark.slow
def test_an_approved_take_home_counts(live_client):
    T, [(sid, S), _] = _workspace(live_client, "apc4@example.test")
    ids = _share_and_approve(live_client, T, S, range(3))
    repo = get_repository()
    tenant = principal.tenant_of(sid)
    text = _paper(0, TOPICS[3])
    repo.put_bluebook_exam(
        {
            "id": "exam-th-apc",
            "tenant_id": tenant,
            "title": "Take-home",
            "conditions": {"setting": "take_home"},
        }
    )
    repo.put_bluebook_submission(
        {
            "id": "bbsub-apc",
            "tenant_id": tenant,
            "exam_id": "exam-th-apc",
            "student_id": sid,
            "candidate": "S0",
            "answers": [text],
            "text": text,
        }
    )
    out = _ok(live_client.post("/bluebook/submissions/bbsub-apc/baseline", headers=T))
    assert out["status"] == "added", out
    assert _readiness(live_client, sid, T)["approved_count"] == 4
    # Take one shared paper back out: two shared + the take-home is still three.
    _ok(live_client.post(f"/bluebook/past-papers/{ids['Paper 0']}/unapprove", headers=T))
    state = repo.get(sid)
    assert state.sample_count == 3 and {s.provenance for s in state.samples} == {"unverified"}
    ready = _readiness(live_client, sid, T)
    assert (ready["verdict"], ready["approved_count"]) == ("ready", 3)
    staff = _ok(_score(live_client, sid, T))
    assert staff["baseline_integrity"]["readiness"] == "ready"
    assert sorted(p["source"] for p in staff["evidence"]["baseline_papers"]) == [
        "shared_paper",
        "shared_paper",
        "take_home",
    ]


@pytest.mark.slow
def test_a_take_home_cannot_extend_a_baseline_of_self_uploads(live_client):
    T, [(sid, S), _] = _workspace(live_client, "apc5@example.test")
    for k in range(3):
        _self_upload(live_client, sid, S, k)
    repo = get_repository()
    tenant = principal.tenant_of(sid)
    text = _paper(0, TOPICS[3])
    repo.put_bluebook_exam(
        {
            "id": "exam-th-apc5",
            "tenant_id": tenant,
            "title": "Take-home",
            "conditions": {"setting": "take_home"},
        }
    )
    repo.put_bluebook_submission(
        {
            "id": "bbsub-apc5",
            "tenant_id": tenant,
            "exam_id": "exam-th-apc5",
            "student_id": sid,
            "candidate": "S0",
            "answers": [text],
            "text": text,
        }
    )
    out = _ok(live_client.post("/bluebook/submissions/bbsub-apc5/baseline", headers=T))
    assert out["status"] == "needs_baseline", out
    assert "Approve at least 3 papers" in out["detail"]
    assert repo.get(sid).sample_count == 3


@pytest.mark.slow
@pytest.mark.parametrize("provenance", ["proctored", "verified", "canvas"])
def test_trusted_provenances_count_with_no_lookup(live_client, monkeypatch, provenance):
    T, [(sid, S), _] = _workspace(live_client, f"apc6{provenance}@example.test")
    for k in range(3):
        _ok(
            live_client.post(
                f"/students/{sid}/baseline",
                json={"text": _paper(0, TOPICS[k]), "provenance": provenance},
                headers=T,
            )
        )
    calls = []
    for name in (
        "list_audit_actions_for_student",
        "list_past_papers",
        "list_bluebook_submission_texts_for_student",
    ):
        orig = getattr(SqliteRepository, name)
        monkeypatch.setattr(
            SqliteRepository,
            name,
            lambda self, *a, _o=orig, _n=name, **k: (calls.append(_n), _o(self, *a, **k))[1],
        )
    assert _readiness(live_client, sid, T)["verdict"] == "ready"
    staff = _ok(_score(live_client, sid, T))
    assert staff["baseline_integrity"]["readiness"] == "ready"
    assert staff["preliminary"]["score"] is not None
    assert calls == []  # nothing unverified: no record is read
    _open_sitting(sid)
    assert _seal_status(_score(live_client, sid, S, sub="s2")) == "READ"


# ── cost: one read of each record per score request ──────────────────────────


@pytest.mark.slow
def test_a_score_request_reads_each_record_once(live_client, monkeypatch):
    T, [(sid, S), _] = _workspace(live_client, "apc7@example.test")
    _share_and_approve(live_client, T, S, range(3))
    calls = {"audit": 0, "papers": 0}
    audit, papers = (
        SqliteRepository.list_audit_actions_for_student,
        SqliteRepository.list_past_papers,
    )

    def _audit(self, *a, **k):
        if list(a[1:2]) == [["baseline_approve", "baseline_remove"]]:
            calls["audit"] += 1
        return audit(self, *a, **k)

    def _papers(self, *a, **k):
        calls["papers"] += 1
        return papers(self, *a, **k)

    monkeypatch.setattr(SqliteRepository, "list_audit_actions_for_student", _audit)
    monkeypatch.setattr(SqliteRepository, "list_past_papers", _papers)
    staff = _ok(_score(live_client, sid, T))
    assert staff["evidence"]["baseline_papers"] and staff["preliminary"] is not None
    assert calls == {"audit": 1, "papers": 1}


def test_a_failed_lookup_counts_trusted_provenances_only(monkeypatch):
    from original import approved_papers

    def _boom(*a, **k):
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(approved_papers, "sample_sources", _boom)
    samples = [_s("verified"), _s("unverified"), _s("unverified")]
    assert approved_papers.gate_sources("t:x", samples) is None
    assert approved_papers.approved_paper_count("t:x", samples) == 1
