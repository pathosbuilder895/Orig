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
        (_paper(1, TOPICS[0]), "unverified", "shared_paper"),
        # Shared but still pending: not teacher-approved.
        (_paper(1, TOPICS[1]), "unverified", "student_upload"),
        # Another student's approved paper does not count for this one.
        (_paper(1, TOPICS[2]), "unverified", "student_upload"),
        (_paper(1, TOPICS[3]), "unverified", "student_upload"),
    ]
    _submission("bbsub-th", SID, answers=take_home_parts)
    _submission("bbsub-legacy", SID, answers=[_paper(0, TOPICS[5])], text=headed)
    _past_paper("pp-ok", SID, _paper(1, TOPICS[0]), "approved")
    _past_paper("pp-wait", SID, _paper(1, TOPICS[1]), "pending")
    _past_paper("pp-bob", OTHER, _paper(1, TOPICS[2]), "approved")
    # Another student's sealed submission with this student's plain upload.
    _submission("bbsub-bob", OTHER, answers=[_paper(1, TOPICS[3])])
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
    calls = {"subs": 0, "papers": 0}
    subs = SqliteRepository.list_bluebook_submission_texts_for_student
    papers = SqliteRepository.list_past_papers

    def _subs(self, *a, **k):
        calls["subs"] += 1
        return subs(self, *a, **k)

    def _papers(self, *a, **k):
        calls["papers"] += 1
        return papers(self, *a, **k)

    monkeypatch.setattr(SqliteRepository, "list_bluebook_submission_texts_for_student", _subs)
    monkeypatch.setattr(SqliteRepository, "list_past_papers", _papers)
    return calls


def test_no_lookups_without_an_unverified_sample(live_client, monkeypatch):
    _add(live_client, _paper(0, TOPICS[0]), "verified")
    _add(live_client, _paper(0, TOPICS[1]), "proctored")
    calls = _counting(monkeypatch)
    assert _sources(live_client) == ["staff_or_supervised"] * 2
    assert calls == {"subs": 0, "papers": 0}


def test_one_lookup_each_however_many_unverified(live_client, monkeypatch):
    for k in range(4):
        _add(live_client, _paper(1, TOPICS[k]), "unverified")
    calls = _counting(monkeypatch)
    assert _sources(live_client) == ["student_upload"] * 4
    assert calls == {"subs": 1, "papers": 1}


def test_unknown_for_a_provenance_it_does_not_know(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("no lookup when nothing is unverified")

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
    assert calls == {"subs": 1, "papers": 0}


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
    assert calls == {"subs": 0, "papers": 0}
    assert live_client.get(f"/students/{sid}", headers=S2).status_code == 403
    assert live_client.get(f"/students/{sid}", headers=T2).status_code == 403
    assert live_client.get(f"/students/{sid}").status_code == 403  # anonymous demo: real tenant
