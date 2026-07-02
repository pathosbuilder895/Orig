"""
tests/test_readiness.py — baseline-readiness endpoint + short-submission note.

Phase D of the pilot-readiness work:
  - GET /students/{id}/readiness verdicts + recommendations
  - the < 300-word provisional-confidence note in the recommendation
    rationale and professor confidence note (prose-only: the action and
    confidence values never change)
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import run
from tests.test_ai_likelihood import _ESSAY   # ~214 words — under the 300 floor

app = run.load_legacy_demo_app()
client = TestClient(app)

_SHORT_TEXT = " ".join(_ESSAY.split()[:150])       # 150 words — well under
_LONG_TEXT = _ESSAY + " " + _ESSAY                 # ~428 words — over the floor


def _add_baseline(sid: str, text: str = _LONG_TEXT, provenance: str = "proctored",
                  assignment: str = "") -> None:
    r = client.post(f"/students/{sid}/baseline",
                    json={"text": text, "provenance": provenance,
                          "assignment": assignment})
    assert r.status_code == 200, r.text


def _readiness(sid: str):
    r = client.get(f"/students/{sid}/readiness")
    assert r.status_code == 200, r.text
    return r.json()


# ── Endpoint verdicts ─────────────────────────────────────────────────────────

def test_readiness_404_unknown_student():
    assert client.get(f"/students/nope_{uuid.uuid4().hex[:8]}/readiness").status_code == 404


def test_insufficient_then_developing_then_ready():
    sid = f"ready_ladder_{uuid.uuid4().hex[:8]}"
    _add_baseline(sid, assignment="a1")
    r = _readiness(sid)
    assert r["verdict"] == "insufficient"
    assert any("more authenticated" in rec for rec in r["recommendations"])

    _add_baseline(sid, assignment="a2")
    r = _readiness(sid)
    assert r["verdict"] == "developing"

    for i in range(3, 6):
        _add_baseline(sid, assignment=f"a{i}")
    r = _readiness(sid)
    assert r["authenticated_count"] == 5
    assert r["verdict"] == "ready"


def test_provenance_mix_and_word_stats():
    sid = f"ready_stats_{uuid.uuid4().hex[:8]}"
    _add_baseline(sid, provenance="proctored", assignment="a1")
    _add_baseline(sid, text=_SHORT_TEXT, provenance="verified", assignment="a2")
    r = _readiness(sid)

    assert r["provenance_mix"] == {"proctored": 1, "verified": 1}
    ws = r["word_stats"]
    assert ws["n_below_300"] == 1
    assert ws["min"] <= 150 <= ws["max"]
    assert any("under 300" in rec for rec in r["recommendations"])


def test_single_assignment_diversity_recommendation():
    sid = f"ready_div_{uuid.uuid4().hex[:8]}"
    for _ in range(3):
        _add_baseline(sid, assignment="same_one")
    r = _readiness(sid)
    assert any("one assignment" in rec for rec in r["recommendations"])


# ── Short-submission note (scoring rationale) ─────────────────────────────────

def _score(sid: str, text: str):
    r = client.post(f"/students/{sid}/score", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_short_submission_note_in_rationale_action_unchanged(monkeypatch):
    # Phase 1 path keeps the comparison deterministic.
    monkeypatch.setenv("CONTEXT_MANIFEST_ENABLED", "0")
    monkeypatch.setenv("ADAPTIVE_WEIGHTS_ENABLED", "0")

    sid = f"short_note_{uuid.uuid4().hex[:8]}"
    for _ in range(3):
        _add_baseline(sid)

    long_resp = _score(sid, _LONG_TEXT)
    short_resp = _score(sid, _SHORT_TEXT)

    assert "short submissions reduce stylometric confidence" \
        in short_resp["recommendation"]["rationale"]
    assert "short submissions reduce stylometric confidence" \
        not in long_resp["recommendation"]["rationale"]


def test_short_note_is_prose_only():
    """The note must never change the action — strip it and the action logic
    is untouched (it is appended after the action is already decided)."""
    from original.quantum.scoring import _recommend, SHORT_SUBMISSION_TOKENS
    from original.quantum.scoring import (
        InterferenceDecomposition, DomainSignal, BaselineConfidence,
    )

    interference = InterferenceDecomposition(
        total_probability=0.9, constructive_features=[],
        destructive_features=[], broken_entanglements=[], tier_breakdown={})
    domain = DomainSignal(theological_register_score=0.5,
                          register_anomaly=False, confessional_balance="balanced")
    bc = BaselineConfidence(purity=0.8, sample_count=6, authenticated_count=6,
                            effective_sample_count=5.0, trajectory_confidence=0.7)

    with_note = _recommend(0.9, 0.2, interference, domain, bc, n_tokens=120)
    without = _recommend(0.9, 0.2, interference, domain, bc, n_tokens=None)
    long_enough = _recommend(0.9, 0.2, interference, domain, bc,
                             n_tokens=SHORT_SUBMISSION_TOKENS)

    assert with_note.action == without.action == long_enough.action
    assert with_note.confidence == without.confidence
    assert "provisional" in with_note.rationale
    assert "provisional" not in without.rationale
    assert "provisional" not in long_enough.rationale  # 300 is NOT < 300


# ── Professor confidence note ─────────────────────────────────────────────────

def test_confidence_note_short_text_caveat():
    from original.quantum.professor_narrative import _build_confidence_note

    base = _build_confidence_note(8)
    assert "quite short" not in base

    with_caveat = _build_confidence_note(8, n_tokens=120)
    assert with_caveat.startswith(base)
    assert "quite short" in with_caveat

    # Default None keeps every existing caller byte-identical.
    assert _build_confidence_note(8, n_tokens=None) == base
    assert _build_confidence_note(8, n_tokens=300) == base
