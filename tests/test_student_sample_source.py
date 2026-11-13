"""GET /students/{id}: each sample says how it got into the baseline.

``source`` is derived at read time from data already stored (no schema
change, no score change): supervised provenances, a sealed Collections
submission a teacher approved as take-home work, a past paper a teacher
approved, any other self-upload, and ``unknown`` for anything else.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from original.repository import SqliteRepository, get_repository, reset_repository
from original.routers import students as students_router
from tests.alpha.test_alpha_ready_e2e import TOPICS, _paper

SID = "demo:src-alice"
OTHER = "demo:src-bob"


@pytest.fixture(autouse=True)
def _fresh(store_reset):
    reset_repository()
    yield
    reset_repository()


def _add(client, text, provenance):
    r = client.post(f"/students/{SID}/baseline", json={"text": text, "provenance": provenance})
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == provenance


def _submission(sub_id, student_id, *, answers=None, text=None):
    get_repository().put_bluebook_submission(
        {
            "id": sub_id,
            "tenant_id": "demo",
            "exam_id": "exam-src",
            "student_id": student_id,
            "candidate": "Alice",
            "answers": answers or [],
            "text": text,
        }
    )


def _approve(sub_id, student_id, result="added"):
    """The audit row POST /bluebook/submissions/{id}/baseline writes."""
    get_repository().log_audit(
        action="baseline_approve",
        student_id=student_id,
        tenant_id="demo",
        actor="prof",
        result=result,
        details={"submission_id": sub_id},
    )


def _undo(sub_id, student_id):
    """The audit row DELETE /bluebook/submissions/{id}/baseline writes."""
    get_repository().log_audit(
        action="baseline_remove",
        student_id=student_id,
        tenant_id="demo",
        actor="prof",
        result="removed",
        details={"submission_id": sub_id, "samples_removed": 1, "sample_count_after": 0},
    )


def _past_paper(paper_id, student_id, text, status):
    get_repository().put_past_paper(
        {
            "paper_id": paper_id,
            "tenant_id": "demo",
            "student_id": student_id,
            "title": paper_id,
            "text": text,
            "word_count": len(text.split()),
            "status": status,
        }
    )


def _sources(client):
    r = client.get(f"/students/{SID}")
    assert r.status_code == 200, r.text
    return [s["source"] for s in r.json()["samples"]]


def test_each_source_value(live_client):
    take_home_parts = [_paper(0, TOPICS[3]), _paper(0, TOPICS[4])]
    headed = "Question 1.\n\n" + _paper(0, TOPICS[5])
    cases = [
        (_paper(0, TOPICS[0]), "verified", "staff_or_supervised"),
        (_paper(0, TOPICS[1]), "proctored", "staff_or_supervised"),
        (_paper(0, TOPICS[2]), "canvas", "staff_or_supervised"),
        # The approved form of a sealed take-home: answers joined, no headings.
        ("\n\n".join(take_home_parts), "unverified", "take_home"),
        # A sample the old seal-time write stored with "Question N." headings.
        (headed, "unverified", "take_home"),
        # Sealed but never approved: the student uploading it is not approval.
        (_paper(0, TOPICS[6]), "unverified", "student_upload"),
        # Approved, then taken back out, then uploaded again by the student.
        (_paper(0, TOPICS[7]), "unverified", "student_upload"),
        # Approved a second time after being undone.
        (_paper(1, TOPICS[5]), "unverified", "take_home"),
        # An approval that did not add anything is no approval.
        (_paper(1, TOPICS[6]), "unverified", "student_upload"),
        (_paper(1, TOPICS[0]), "unverified", "shared_paper"),
        # Shared but still pending: not teacher-approved.
        (_paper(1, TOPICS[1]), "unverified", "student_upload"),
        # Another student's approved paper does not count for this one.
        (_paper(1, TOPICS[2]), "unverified", "student_upload"),
        (_paper(1, TOPICS[3]), "unverified", "student_upload"),
    ]
    _submission("bbsub-th", SID, answers=take_home_parts)
    _submission("bbsub-legacy", SID, answers=[_paper(0, TOPICS[5])], text=headed)
    _approve("bbsub-th", SID)
    _approve("bbsub-legacy", SID, result="already_in_baseline")
    _submission("bbsub-never", SID, answers=[_paper(0, TOPICS[6])])
    _submission("bbsub-undone", SID, answers=[_paper(0, TOPICS[7])])
    _approve("bbsub-undone", SID)
    _undo("bbsub-undone", SID)
    _submission("bbsub-again", SID, answers=[_paper(1, TOPICS[5])])
    _approve("bbsub-again", SID)
    _undo("bbsub-again", SID)
    _approve("bbsub-again", SID)
    _submission("bbsub-held", SID, answers=[_paper(1, TOPICS[6])])
    _approve("bbsub-held", SID, result="held")
    _past_paper("pp-ok", SID, _paper(1, TOPICS[0]), "approved")
    _past_paper("pp-wait", SID, _paper(1, TOPICS[1]), "pending")
    _past_paper("pp-bob", OTHER, _paper(1, TOPICS[2]), "approved")
    # Another student's approved submission with this student's plain upload.
    _submission("bbsub-bob", OTHER, answers=[_paper(1, TOPICS[3])])
    _approve("bbsub-bob", OTHER)
    # This student's approval row naming a submission that is not theirs.
    _approve("bbsub-bob", SID)
    for text, provenance, _ in cases:
        _add(live_client, text, provenance)
    assert _sources(live_client) == [want for _, _, want in cases]


def test_source_does_not_change_the_rest_of_the_response(live_client):
    _add(live_client, _paper(0, TOPICS[0]), "verified")
    _add(live_client, _paper(1, TOPICS[1]), "unverified")
    body = live_client.get(f"/students/{SID}").json()
    for s in body["samples"]:
        assert set(s) == {
            "index",
            "assignment",
            "provenance",
            "submitted_at",
            "auth_weight",
            "source",
        }
    assert [s["provenance"] for s in body["samples"]] == ["verified", "unverified"]
    assert [s["auth_weight"] for s in body["samples"]] == [1.0, 0.5]


def _counting(monkeypatch):
    calls = {"audit": 0, "subs": 0, "papers": 0}
    audit = SqliteRepository.list_audit_actions_for_student
    subs = SqliteRepository.list_bluebook_submission_texts_for_student
    papers = SqliteRepository.list_past_papers

    def _audit(self, *a, **k):
        calls["audit"] += 1
        return audit(self, *a, **k)

    def _subs(self, *a, **k):
        calls["subs"] += 1
        return subs(self, *a, **k)

    def _papers(self, *a, **k):
        calls["papers"] += 1
        return papers(self, *a, **k)

    monkeypatch.setattr(SqliteRepository, "list_audit_actions_for_student", _audit)
    monkeypatch.setattr(SqliteRepository, "list_bluebook_submission_texts_for_student", _subs)
    monkeypatch.setattr(SqliteRepository, "list_past_papers", _papers)
    return calls


def test_no_lookups_without_an_unverified_sample(live_client, monkeypatch):
    _add(live_client, _paper(0, TOPICS[0]), "verified")
    _add(live_client, _paper(0, TOPICS[1]), "proctored")
    calls = _counting(monkeypatch)
    assert _sources(live_client) == ["staff_or_supervised"] * 2
    assert calls == {"audit": 0, "subs": 0, "papers": 0}


def test_one_lookup_each_however_many_unverified(live_client, monkeypatch):
    for k in range(4):
        _submission(f"bbsub-{k}", SID, answers=[_paper(1, TOPICS[k])])
        _approve(f"bbsub-{k}", SID)
        _add(live_client, _paper(1, TOPICS[k]), "unverified")
    calls = _counting(monkeypatch)
    assert _sources(live_client) == ["take_home"] * 4
    assert calls == {"audit": 1, "subs": 1, "papers": 1}


def test_no_submission_read_without_an_approval(live_client, monkeypatch):
    _submission("bbsub-never", SID, answers=[_paper(1, TOPICS[0])])
    _add(live_client, _paper(1, TOPICS[0]), "unverified")
    calls = _counting(monkeypatch)
    assert _sources(live_client) == ["student_upload"]
    assert calls == {"audit": 1, "subs": 0, "papers": 1}


def test_unknown_for_a_provenance_it_does_not_know(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("no lookup when nothing is unverified")

    monkeypatch.setattr(SqliteRepository, "list_audit_actions_for_student", _boom)
    monkeypatch.setattr(SqliteRepository, "list_bluebook_submission_texts_for_student", _boom)
    monkeypatch.setattr(SqliteRepository, "list_past_papers", _boom)
    samples = [
        SimpleNamespace(provenance="instructor_verified", text="x"),
        SimpleNamespace(provenance="verified", text="y"),
    ]
    assert students_router._sample_sources(SID, samples) == ["unknown", "staff_or_supervised"]


def test_legacy_flat_id_skips_past_papers(monkeypatch):
    """A legacy flat id has no workspace, so no past paper can be its own."""
    calls = _counting(monkeypatch)
    samples = [SimpleNamespace(provenance="unverified", text="plain words")]
    assert students_router._sample_sources("flatid", samples) == ["student_upload"]
    assert calls == {"audit": 1, "subs": 0, "papers": 0}


@pytest.mark.slow
def test_real_flow_and_who_may_read_it(live_client, monkeypatch):
    """A paper a student shares and the teacher approves reads as
    ``shared_paper`` to that teacher. The route's existing rules hold: the
    student may read their own record (and is never given the source), a
    classmate and another workspace's teacher are refused."""
    from original import principal
    from tests.alpha.test_past_papers import _ok, _share, _workspace

    monkeypatch.setenv("INVITE_NO_EXPIRY", "1")
    monkeypatch.delenv("MIN_BASELINE_SAMPLES", raising=False)
    principal.invalidate_tenant_cache()
    T, [(sid, S), (_classmate, S2)] = _workspace(live_client, "src1@example.test")
    T2, _others = _workspace(live_client, "src2@example.test")
    _ok(_share(live_client, S, text=_paper(0, TOPICS[0]), title="Shared"), 201)
    [row] = _ok(live_client.get("/bluebook/past-papers", headers=T))["papers"]
    assert (
        _ok(live_client.post(f"/bluebook/past-papers/{row['paper_id']}/approve", headers=T))[
            "status"
        ]
        == "approved"
    )
    body = _ok(live_client.get(f"/students/{sid}", headers=T))
    assert [(s["provenance"], s["source"]) for s in body["samples"]] == [
        ("unverified", "shared_paper")
    ]
    calls = _counting(monkeypatch)
    own = _ok(live_client.get(f"/students/{sid}", headers=S))
    assert [s["source"] for s in own["samples"]] == ["unknown"]
    assert calls == {"audit": 0, "subs": 0, "papers": 0}
    assert live_client.get(f"/students/{sid}", headers=S2).status_code == 403
    assert live_client.get(f"/students/{sid}", headers=T2).status_code == 403
    assert live_client.get(f"/students/{sid}").status_code == 403  # anonymous demo: real tenant


@pytest.mark.slow
def test_take_home_through_the_real_approve_and_undo_routes(live_client, monkeypatch):
    """(1) sealed, never approved, same text uploaded: student_upload.
    (2) approved take-home: take_home. (3) approved, undone, the same text
    uploaded again: student_upload."""
    from original import principal
    from tests.alpha.test_past_papers import _ok, _workspace

    monkeypatch.setenv("INVITE_NO_EXPIRY", "1")
    monkeypatch.delenv("MIN_BASELINE_SAMPLES", raising=False)
    principal.invalidate_tenant_cache()
    T, [(sid, _S), _] = _workspace(live_client, "src3@example.test")
    tenant = principal.tenant_of(sid)
    repo = get_repository()
    repo.put_bluebook_exam(
        {
            "id": "exam-th",
            "tenant_id": tenant,
            "title": "Take-home",
            "conditions": {"setting": "take_home"},
        }
    )
    texts = {name: _paper(0, TOPICS[k]) for k, name in enumerate(("never", "kept", "undone"))}
    for name, text in texts.items():
        repo.put_bluebook_submission(
            {
                "id": f"bbsub-{name}",
                "tenant_id": tenant,
                "exam_id": "exam-th",
                "student_id": sid,
                "candidate": "S0",
                "answers": [text],
                "text": text,
            }
        )

    def _upload(text, provenance):
        _ok(
            live_client.post(
                f"/students/{sid}/baseline",
                json={"text": text, "provenance": provenance},
                headers=T,
            )
        )

    # Take-home work only extends an existing baseline.
    for k in range(3, 6):
        _upload(_paper(0, TOPICS[k]), "verified")
    for name in ("kept", "undone"):
        out = _ok(live_client.post(f"/bluebook/submissions/bbsub-{name}/baseline", headers=T))
        assert out["status"] == "added", out
    out = _ok(live_client.delete("/bluebook/submissions/bbsub-undone/baseline", headers=T))
    assert out["status"] == "removed", out
    _upload(texts["never"], "unverified")
    _upload(texts["undone"], "unverified")
    body = _ok(live_client.get(f"/students/{sid}", headers=T))
    got = [(s["provenance"], s["source"]) for s in body["samples"]]
    assert got == [("verified", "staff_or_supervised")] * 3 + [
        ("unverified", "take_home"),
        ("unverified", "student_upload"),
        ("unverified", "student_upload"),
    ]


@pytest.mark.slow
def test_score_evidence_carries_each_past_papers_source_for_staff_only(live_client, monkeypatch):
    """The staff score response records how each past paper got in as of the
    analysis (take_home and student_upload here). A student scoring their own
    work never gets evidence, and with the flag off no lookup runs."""
    from original import principal
    from tests.alpha.test_past_papers import _ok, _workspace

    monkeypatch.setenv("INVITE_NO_EXPIRY", "1")
    monkeypatch.delenv("MIN_BASELINE_SAMPLES", raising=False)
    principal.invalidate_tenant_cache()
    T, [(sid, S), _] = _workspace(live_client, "src4@example.test")
    tenant = principal.tenant_of(sid)
    repo = get_repository()
    repo.put_bluebook_exam(
        {
            "id": "exam-ev",
            "tenant_id": tenant,
            "title": "Take-home",
            "conditions": {"setting": "take_home"},
        }
    )
    kept, own = _paper(0, TOPICS[1]), _paper(0, TOPICS[2])
    repo.put_bluebook_submission(
        {
            "id": "bbsub-ev",
            "tenant_id": tenant,
            "exam_id": "exam-ev",
            "student_id": sid,
            "candidate": "S0",
            "answers": [kept],
            "text": kept,
        }
    )
    for k in range(3, 6):
        _ok(
            live_client.post(
                f"/students/{sid}/baseline",
                json={"text": _paper(0, TOPICS[k]), "provenance": "verified"},
                headers=T,
            )
        )
    assert (
        _ok(live_client.post("/bluebook/submissions/bbsub-ev/baseline", headers=T))["status"]
        == "added"
    )
    _ok(
        live_client.post(
            f"/students/{sid}/baseline", json={"text": own, "provenance": "unverified"}, headers=T
        )
    )
    paper = _paper(1, TOPICS[0])

    monkeypatch.delenv("EVIDENCE_PASSAGES_ENABLED", raising=False)
    calls = _counting(monkeypatch)
    off = _ok(
        live_client.post(
            f"/students/{sid}/score", json={"text": paper, "submission_id": "ev0"}, headers=T
        )
    )
    assert off["evidence"] is None
    assert calls == {"audit": 0, "subs": 0, "papers": 0}

    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    on = _ok(
        live_client.post(
            f"/students/{sid}/score", json={"text": paper, "submission_id": "ev1"}, headers=T
        )
    )
    got = [(p["provenance"], p["source"]) for p in on["evidence"]["baseline_papers"]]
    assert got == [("verified", "staff_or_supervised")] * 3 + [
        ("unverified", "take_home"),
        ("unverified", "student_upload"),
    ]

    # A student principal never receives evidence: refused outright on a take-home
    # workspace, and an answer without the field wherever it is allowed.
    mine = live_client.post(
        f"/students/{sid}/score", json={"text": paper, "submission_id": "ev2"}, headers=S
    )
    assert mine.status_code == 403 or mine.json().get("evidence") is None
    assert "baseline_papers" not in mine.text
