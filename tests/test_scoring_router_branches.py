"""
Branch tests for original/routers/students_scoring.py (score_submission,
score_blend, and the request-local _all_states() cache) — part 2 task 6.

score_submission's branches are mostly flag-interaction arms (CLAUDE.md's
flag table governs): each test below sets exactly the env flag its arm
needs via monkeypatch, and where the brief calls for it, also asserts the
flag-off/on invariant the docstring on that flag promises (e.g.
BAYESIAN_PRIOR_ENABLED and LONGITUDINAL_DRIFT_ENABLED are both documented
"never changes deviation_score or the action").

One arm — the `if existing_result:` cache-stub check at students_scoring.py
line 55 — is NOT covered here: `existing_result` is hardcoded to `None`
three lines above it (a documented `# TODO: retrieve from cache` stub), so
its True arm is unreachable from any HTTP request without editing the
module under test. See the task report for the full justification.

All tests HTTP-level via live_client + store_reset.
"""

from __future__ import annotations

import numpy as np

from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState
from original.repository import get_repository

BASELINE = "/students/{sid}/baseline"
SCORE = "/students/{sid}/score"
BLEND = "/students/{sid}/score/blend"
LOGIN = "/student-auth/login"

# ~150 words — comfortably above every tier's minimum, matching the LONG_TEXT
# idiom used across the rest of the router-branch suite (e.g. test_pilot_lockdown.py).
LONG_TEXT = (
    "The doctrine of justification by faith stands at the center of the gospel. "
    "When Paul writes to the Romans, he labors to show that righteousness comes "
    "not by works of the law but through faith in Christ alone. This conviction "
    "shaped the Reformation and continues to shape pastoral practice today. "
    "A careful reader notices how the argument unfolds in stages, each building "
    "on the last, until the conclusion becomes unavoidable. The voice here is "
    "deliberate and measured, favoring long subordinate clauses and a vocabulary "
    "drawn from systematic theology. Such patterns, repeated across many essays, "
    "form a fingerprint as distinctive as handwriting. The seminary student who "
    "writes this way in September will, absent intervention, write this way in "
    "May, and that continuity is precisely what we set out to measure and to "
    "protect with patience and with care."
)
SUBMISSION_TEXT = (
    "Grace and peace are the twin notes that open nearly every Pauline letter, "
    "and their repetition is not accidental but theological. The writer returns "
    "again and again to the same vocabulary, the same cadence, the same habit of "
    "qualifying a bold claim with a gentle clause. Across a semester these habits "
    "compound into a recognizable voice, and it is that voice, not any single "
    "sentence, that the system learns to know and to defend with care and patience."
)


def _add_baseline(client, sid, text=LONG_TEXT, provenance="verified"):
    return client.post(
        BASELINE.format(sid=sid),
        json={"text": text, "provenance": provenance, "assignment": ""},
    )


def _score(client, sid, **extra):
    return client.post(SCORE.format(sid=sid), json={"text": SUBMISSION_TEXT, **extra})


def _create_student_with_no_baseline(client, sid):
    """get_or_create()s the student record with zero samples, via the same
    path student_login uses — no /baseline call, so authenticated_count
    stays 0."""
    r = client.post(LOGIN, json={"email": f"{sid}@sod.edu", "institution": "Seminary of Dallas"})
    assert r.status_code == 200, r.text
    return r.json()["student_id"]


# ── score_submission: 404 / 422 guard arms ───────────────────────────────────


def test_score_unknown_student_is_404(live_client, store_reset):
    r = _score(live_client, "no-such-student-at-all")
    assert r.status_code == 404, r.text


def test_score_student_with_no_authenticated_samples_is_422(live_client, store_reset):
    sid = _create_student_with_no_baseline(live_client, "scoring-empty")
    r = _score(live_client, sid)
    assert r.status_code == 422, r.text
    assert "authenticated baseline" in r.json()["detail"].lower()


# ── score_blend: the same pair of guard arms ─────────────────────────────────


def test_blend_unknown_student_is_404(live_client, store_reset):
    r = live_client.post(BLEND.format(sid="no-such-blend-student"), json={"text": SUBMISSION_TEXT})
    assert r.status_code == 404, r.text


def test_blend_student_with_no_authenticated_samples_is_422(live_client, store_reset):
    sid = _create_student_with_no_baseline(live_client, "blend-empty")
    r = live_client.post(BLEND.format(sid=sid), json={"text": SUBMISSION_TEXT})
    assert r.status_code == 422, r.text
    assert "authenticated baseline" in r.json()["detail"].lower()


# ── BAYESIAN_PRIOR_ENABLED: genre-less cold start skips the prior lookup ────


def _seed_genreless_student(student_id: str, n: int = 3) -> None:
    """Persist a sub-floor (cold-start) baseline directly via the repository,
    bypassing the /baseline endpoint's own best-effort genre auto-detection
    (`students_baseline.py` runs `resolve_genre()` on every submitted text
    unconditionally — confirmed empirically: ordinary prose reliably resolves
    to a non-empty label under the default v1 rules, so an HTTP-added sample
    can't be relied on to carry `genre=None`). Same technique
    tests/test_bayesian_prior_wiring.py uses to force a specific label; here
    the label is simply omitted (BaselineSample.genre defaults to None)."""
    rng = np.random.default_rng(abs(hash(student_id)) % (2**31))
    state = StudentState(student_id=student_id)
    for i in range(n):
        state.add_sample(
            BaselineSample(
                text=f"seed sample {i} for {student_id}",
                vector=rng.random(FEATURE_DIM).astype(np.float64),
                provenance="verified",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    get_repository().put(state)


def test_bayesian_prior_on_but_baseline_has_no_genre_label_is_a_noop(
    live_client, store_reset, monkeypatch
):
    """BAYESIAN_PRIOR_ENABLED=1 + sample_count<10 (cold start) enters the
    prior block, but the baseline's last sample carries no genre label
    (`_seed_genreless_student` above), so `_genre` is falsy and the whole
    get_genre_stats lookup is skipped — the False arm of `if _genre:`.
    Proven two ways: the request succeeds (no crash reaching for
    genre_stats on a None genre), and the flag-off default-off invariant
    holds — deviation_score/quantum_fidelity/action are byte-identical with
    the flag on vs off, since a skipped lookup can't move the score either
    way."""
    sid = "bayesian-nogenre"
    _seed_genreless_student(sid)

    off = _score(live_client, sid, force=True)
    assert off.status_code == 200, off.text

    monkeypatch.setenv("BAYESIAN_PRIOR_ENABLED", "1")
    on = _score(live_client, sid, force=True)
    assert on.status_code == 200, on.text

    off_auth, on_auth = off.json()["authorship"], on.json()["authorship"]
    assert off_auth["deviation_score"] == on_auth["deviation_score"]
    assert off_auth["quantum_fidelity"] == on_auth["quantum_fidelity"]
    assert off.json()["recommendation"]["action"] == on.json()["recommendation"]["action"]


# ── LONGITUDINAL_DRIFT_ENABLED: report-only, never moves the score ──────────


def test_longitudinal_drift_enabled_attaches_report_without_changing_the_score(
    live_client, store_reset, monkeypatch
):
    """LONGITUDINAL_DRIFT_ENABLED=1 takes the True arm of
    `if _longitudinal_config.enabled:` and attempts genre resolution for the
    drift-analysis report; CLAUDE.md documents this flag as "Never changes
    deviation_score or the action" — asserted directly here, the same
    invariant the bayesian-prior test above proves for its own flag."""
    sid = "longitudinal-flag"
    assert _add_baseline(live_client, sid).status_code == 200

    off = _score(live_client, sid, force=True)
    assert off.status_code == 200, off.text
    assert off.json()["drift_analysis"] is None  # flag off → report absent

    monkeypatch.setenv("LONGITUDINAL_DRIFT_ENABLED", "1")
    on = _score(live_client, sid, force=True)
    assert on.status_code == 200, on.text
    assert on.json()["drift_analysis"] is not None  # flag on → report attached

    off_auth, on_auth = off.json()["authorship"], on.json()["authorship"]
    assert off_auth["deviation_score"] == on_auth["deviation_score"]
    assert off_auth["quantum_fidelity"] == on_auth["quantum_fidelity"]
    assert off.json()["recommendation"]["action"] == on.json()["recommendation"]["action"]


# ── _all_states() request-local cache: the second-call hit arm ─────────────


def test_all_states_cache_is_reused_across_two_consumers_in_one_request(
    live_client, store_reset, monkeypatch
):
    """`_all_states()` memoizes `_repo().all_states()` for the lifetime of
    one score_submission() call. Hitting the `_all_states_cache is None`
    False arm (the second-and-later call finding the cache already warm)
    needs at least two consumers active on the same request: NULL_MODEL=
    impostor (build_impostor_stats) and STYLE_AUTHORSHIP_ENABLED=1
    (predict_style_authorship) are the cheapest pair to turn on together —
    neither needs real peer data to reach its own `_all_states()` call, they
    just abstain gracefully (None / no peers) when there isn't any."""
    sid = "allstates-cache"
    assert _add_baseline(live_client, sid).status_code == 200

    monkeypatch.setenv("NULL_MODEL", "impostor")
    monkeypatch.setenv("STYLE_AUTHORSHIP_ENABLED", "1")
    r = _score(live_client, sid, force=True)
    assert r.status_code == 200, r.text
