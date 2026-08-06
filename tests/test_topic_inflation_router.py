"""
tests/test_topic_inflation_router.py — router-level wiring for topic-adaptive
variance inflation (TOPIC_VARIANCE_INFLATION), from the 2026-08-06
whole-branch review.

Finding 3: `_amplitude_score` computes `quantum_fidelity` under the INFLATED
sigma (`baseline_std_override=sigma` in `quantum/scoring.py`), but
`put_fidelity_score` (`original/routers/students_scoring.py`) persists that
fidelity into the SAME per-student calibration set `get_authentic_fidelities`
later compares un-inflated fidelities against. Persisting an inflated-regime
value contaminates that set irreversibly — turning the flag back off does not
undo a row already written. `students_scoring.py` must skip the write
whenever `result.topic_inflation_applied` is True.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

import original.store as store
import run

app = run.load_legacy_demo_app()
client = TestClient(app)

# Deliberately narrow, repetitive theological vocabulary so the TF-IDF
# centroid is tight and a genuinely different topic reads as far away.
_BASELINE_TEXTS = [
    "The doctrine of justification has been central to Reformation theology since Luther.",
    "Calvin developed a covenantal framework that distinguished forensic from transformative grace.",
    "Modern Pauline scholarship has revisited the theological vocabulary of the apostle.",
    "Theological method requires careful attention to both biblical text and historical context.",
]

# Verified via original.context.resolvers.resolve_topic(_SUBMISSION,
# _BASELINE_TEXTS) == baseline_distance 0.3292, novelty "medium", degraded
# False -- i.e. above the 0.25 novelty floor, so _topic_inflation_vector
# returns a real (not None) multiplier under "on". TF-IDF cosine similarity
# is deterministic (no RNG), so this is not a flaky threshold: the same
# baseline/submission text always produces the same distance.
_SUBMISSION = (
    "Coffee shops with reliable wifi multiply across suburban strip malls near the highway. "
    "Baristas pull delicate flat whites while soft jazz plays overhead every single afternoon. "
    "A new roastery promises single origin beans sourced directly from small mountain farms. "
    "Weekend lines stretch out the door long before the doors even open for business."
)


def _seed_student(sid: str) -> None:
    for text in _BASELINE_TEXTS:
        r = client.post(f"/students/{sid}/baseline", json={"text": text, "provenance": "proctored"})
        assert r.status_code == 200, r.text


def _score(sid: str, submission_id: str) -> dict:
    r = client.post(
        f"/students/{sid}/score",
        json={"text": _SUBMISSION, "submission_id": submission_id},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _fidelity_rows(submission_id: str):
    with store._get_conn() as conn:
        return conn.execute(
            "SELECT submission_id, fidelity, is_authentic FROM fidelity_scores "
            "WHERE submission_id = ?",
            (submission_id,),
        ).fetchall()


def test_fidelity_persistence_skipped_when_topic_inflation_applied(monkeypatch):
    monkeypatch.setenv("CONTEXT_MANIFEST_ENABLED", "1")
    monkeypatch.setenv("AMPLITUDE_SCORING_ENABLED", "1")
    monkeypatch.setenv("TOPIC_VARIANCE_INFLATION", "on")
    monkeypatch.delenv("ADAPTIVE_WEIGHTS_ENABLED", raising=False)

    sid = f"topic_infl_persist_{uuid.uuid4().hex[:8]}"
    _seed_student(sid)
    submission_id = f"{sid}_sub_1"

    resp = _score(sid, submission_id)
    # deviation_score IS copied by _to_response today, so it's a reliable
    # signal that scoring actually ran end to end (unlike topic_inflation_
    # applied/topic_distance/etc, which are not yet wired through -- see
    # Finding 4).
    assert resp["authorship"]["deviation_score"] > 0.0, resp

    assert _fidelity_rows(submission_id) == [], (
        "put_fidelity_score must be skipped when topic inflation was applied "
        "-- persisting an inflated-regime fidelity would contaminate this "
        "student's conformal calibration set irreversibly."
    )


def test_fidelity_persistence_still_happens_when_inflation_not_applied(monkeypatch):
    """
    Control for the test above: same baseline/submission pair, same
    AMPLITUDE_SCORING_ENABLED=1, only TOPIC_VARIANCE_INFLATION differs.
    Proves the skip is keyed on topic_inflation_applied specifically, not on
    some other property of this fixture (e.g. an unrelated exception that
    would make the row absent for the wrong reason in the test above).
    """
    monkeypatch.setenv("CONTEXT_MANIFEST_ENABLED", "1")
    monkeypatch.setenv("AMPLITUDE_SCORING_ENABLED", "1")
    monkeypatch.setenv("TOPIC_VARIANCE_INFLATION", "off")
    monkeypatch.delenv("ADAPTIVE_WEIGHTS_ENABLED", raising=False)

    sid = f"topic_infl_control_{uuid.uuid4().hex[:8]}"
    _seed_student(sid)
    submission_id = f"{sid}_sub_1"

    resp = _score(sid, submission_id)
    assert resp["authorship"]["deviation_score"] > 0.0, resp

    rows = _fidelity_rows(submission_id)
    assert len(rows) == 1
    assert rows[0][0] == submission_id
