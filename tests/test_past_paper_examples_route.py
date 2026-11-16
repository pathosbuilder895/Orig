"""GET /students/{id}/past-paper-examples: staff only, flag gated (ADR-013).

Real sentences from a student's past papers, grouped by family of habit. The
route is read-only and never changes a score. Students never receive it, and
one workspace never sees another's text.
"""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace

import pytest

from original import principal
from original.repository import reset_repository
from tests.alpha.test_alpha_ready_e2e import TOPICS, _paper
from tests.alpha.test_past_papers import _ok, _workspace


@pytest.fixture(autouse=True)
def _fresh(store_reset):
    reset_repository()
    yield
    reset_repository()


@pytest.fixture
def seeded(live_client, monkeypatch):
    """A workspace whose first student has three verified past papers."""
    monkeypatch.setenv("INVITE_NO_EXPIRY", "1")
    monkeypatch.delenv("MIN_BASELINE_SAMPLES", raising=False)
    principal.invalidate_tenant_cache()
    email = f"ppx-{uuid.uuid4().hex[:8]}@example.test"
    T, [(sid, S), (_classmate, S2)] = _workspace(live_client, email)
    for k in range(3):
        _ok(
            live_client.post(
                f"/students/{sid}/baseline",
                json={
                    "text": _paper(0, TOPICS[k]),
                    "provenance": "verified",
                    "assignment": f"Paper {k}",
                    "submitted_at": f"2026-0{k + 1}-10",
                },
                headers=T,
            )
        )
    return SimpleNamespace(client=live_client, T=T, sid=sid, S=S, S2=S2)


def _url(sid, habit=None):
    return f"/students/{sid}/past-paper-examples" + (f"?habit={habit}" if habit else "")


@pytest.mark.slow
def test_flag_off_is_404(seeded, monkeypatch):
    monkeypatch.delenv("EVIDENCE_PASSAGES_ENABLED", raising=False)
    r = seeded.client.get(_url(seeded.sid), headers=seeded.T)
    assert r.status_code == 404
    assert r.json()["detail"] == "Not found"
    # The flag is checked before the staff check: a student session sees the same 404, not a 403.
    r = seeded.client.get(_url(seeded.sid), headers=seeded.S)
    assert r.status_code == 404
    assert r.json()["detail"] == "Not found"


@pytest.mark.slow
def test_staff_get_the_whole_family_with_the_scores_labels(seeded, monkeypatch):
    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    c = seeded.client
    body = _ok(c.get(_url(seeded.sid), headers=seeded.T))
    assert body["family"] == "Sentence shape"
    assert body["habit"] == "mean_sentence_length"
    assert len(body["features"]) == 7
    mean = next(f for f in body["features"] if f["code"] == "mean_sentence_length")
    assert [p["paper"] for p in mean["per_paper"]] == [
        "past paper 1",
        "past paper 2",
        "past paper 3",
    ]
    assert any(p["examples"] for p in mean["per_paper"])
    assert all(ex["role"] == "typical" for p in mean["per_paper"] for ex in p["examples"])
    assert all("source" in p for p in body["baseline_papers"])
    assert [p["assignment"] for p in body["baseline_papers"]] == ["Paper 0", "Paper 1", "Paper 2"]
    voice = _ok(c.get(_url(seeded.sid, "contraction_rate"), headers=seeded.T))
    assert voice["family"] == "Voice"

    score = _ok(
        c.post(
            f"/students/{seeded.sid}/score",
            json={"text": _paper(0, "river cleanups")},
            headers=seeded.T,
        )
    )
    assert score["evidence"]["baseline_papers"] == body["baseline_papers"]


@pytest.mark.slow
def test_students_are_refused_even_for_their_own_record(seeded, monkeypatch):
    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    assert seeded.client.get(_url(seeded.sid), headers=seeded.S).status_code == 403
    assert seeded.client.get(_url(seeded.sid), headers=seeded.S2).status_code == 403


@pytest.mark.slow
def test_another_workspace_is_refused(seeded, monkeypatch):
    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    T2, _others = _workspace(seeded.client, f"ppy-{uuid.uuid4().hex[:8]}@example.test")
    assert seeded.client.get(_url(seeded.sid), headers=T2).status_code == 403


@pytest.mark.slow
def test_unknown_student_is_404_and_unknown_habit_is_422(seeded, monkeypatch):
    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    nobody = f"{principal.tenant_of(seeded.sid)}:nobody"
    assert seeded.client.get(_url(nobody), headers=seeded.T).status_code == 404
    r = seeded.client.get(_url(seeded.sid, "typing_speed_cv"), headers=seeded.T)
    assert r.status_code == 422


def test_a_student_without_stored_text_gets_empty_lists(live_client, monkeypatch):
    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    state = SimpleNamespace(samples=[SimpleNamespace(text="", auth_weight=1.0)])
    repo = SimpleNamespace(get=lambda _sid: state)
    monkeypatch.setattr("original.routers.students_scoring._repo", lambda: repo)
    # No paper to show, so no source lookup (and none of its repository reads).
    looked_up = []
    monkeypatch.setattr(
        "original.routers.students._sample_sources", lambda *a: looked_up.append(a) or []
    )
    body = _ok(live_client.get("/students/demo:nobody-text/past-paper-examples"))
    assert body["baseline_papers"] == []
    assert all(f["per_paper"] == [] for f in body["features"])
    assert looked_up == []


def test_a_build_failure_is_503(live_client, monkeypatch):
    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    state = SimpleNamespace(samples=[])
    repo = SimpleNamespace(get=lambda _sid: state)
    monkeypatch.setattr("original.routers.students_scoring._repo", lambda: repo)

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr("original.evidence.build_past_paper_examples", boom)
    r = live_client.get("/students/demo:nobody-text/past-paper-examples")
    assert r.status_code == 503
    assert r.json()["detail"] == "Examples could not be shown just now."


def test_a_response_that_cannot_be_built_is_the_same_logged_503(live_client, monkeypatch, caplog):
    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    state = SimpleNamespace(samples=[])
    repo = SimpleNamespace(get=lambda _sid: state)
    monkeypatch.setattr("original.routers.students_scoring._repo", lambda: repo)
    # A body the response model refuses (no "features"): a 503, never an unlogged 500.
    monkeypatch.setattr(
        "original.evidence.build_past_paper_examples",
        lambda *_a, **_k: {"family": "Sentence shape", "habit": "comma_rate", "families": []},
    )
    with caplog.at_level(logging.ERROR, logger="original.routers.students_scoring"):
        r = live_client.get("/students/demo:nobody-text/past-paper-examples")
    assert r.status_code == 503
    assert r.json()["detail"] == "Examples could not be shown just now."
    assert any(rec.getMessage() == "past paper examples failed" for rec in caplog.records)
