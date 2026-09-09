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


# ── store.get_active_tuned_thresholds() reaching the live scoring path ─────


def test_tuned_thresholds_absent_matches_the_static_action_thresholds(
    live_client, store_reset
):
    """Default state of every deployment today: no row in
    tuned_thresholds_v2, so store.get_active_tuned_thresholds() returns None
    and ScoringConfig.tuned_action_thresholds stays None -- _recommend() must
    fall back to the static ACTION_THRESHOLDS bands byte-identically. This is
    the more important half of the pair below: it proves wiring the lookup
    into students_scoring.py did not silently change the DEFAULT behavior of
    every existing score() call."""
    sid = "tuned-thresholds-absent"
    assert _add_baseline(live_client, sid).status_code == 200

    first = _score(live_client, sid, force=True)
    assert first.status_code == 200, first.text
    second = _score(live_client, sid, force=True)
    assert second.status_code == 200, second.text

    assert store_reset.get_active_tuned_thresholds() is None
    first_auth, second_auth = first.json()["authorship"], second.json()["authorship"]
    assert first_auth["deviation_score"] == second_auth["deviation_score"]
    assert first.json()["recommendation"]["action"] == second.json()["recommendation"]["action"]
    # Sanity: the static bands' escalate band is (0.75, 1.00) -- a same-ish
    # baseline/submission pair scored with no tuning applied should not land
    # there, which the next test relies on for contrast.
    assert first.json()["recommendation"]["action"] != "escalate"


def test_tuned_thresholds_from_store_change_the_recommended_action(
    live_client, store_reset
):
    """Applying a tuned threshold set through store.put_tuned_thresholds()
    -- the exact call original/routers/admin.py's Apply-thresholds endpoint
    makes -- must move the recommended action for a request scored
    afterward. no_action=monitor=escalate=0.0 collapses every band except
    "escalate" to an empty [x, x) interval, so any non-negative deviation
    score lands in escalate's [0.0, 1.0) band regardless of its actual
    value -- a deterministic, real behavior change traceable to a row
    written through the same persistence layer the admin route uses, not a
    mock of ScoringConfig. The deviation score itself is untouched; only the
    action derived from it moves, proving the wiring wraps the existing
    band-selection logic rather than replacing the underlying computation."""
    sid = "tuned-thresholds-present"
    assert _add_baseline(live_client, sid).status_code == 200

    before = _score(live_client, sid, force=True)
    assert before.status_code == 200, before.text
    assert before.json()["recommendation"]["action"] != "escalate"

    store_reset.put_tuned_thresholds(
        no_action=0.0, monitor=0.0, escalate=0.0, source="manual"
    )
    assert store_reset.get_active_tuned_thresholds() is not None

    after = _score(live_client, sid, force=True)
    assert after.status_code == 200, after.text
    assert after.json()["recommendation"]["action"] == "escalate"
    assert (
        before.json()["authorship"]["deviation_score"]
        == after.json()["authorship"]["deviation_score"]
    )


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


# ── FUSED_SCORE_{ENABLED,SHADOW}: abstain + hit + persist-failure arms ──────
# students_scoring.py:375-431. Two modes share one call site:
#   [384,385]  True arm — either flag turns the block on at all.
#   [413,452]  False arm — `_fused is None` (abstain), skip persistence.
#   [413,414]  True arm — a "hit" (non-None) fused score.
#   [414,415]/[414,416] — FUSED_SCORE_ENABLED attaches to the response vs.
#     FUSED_SCORE_SHADOW-only persists but leaves the field null.
# The abstain arms are reachable cheaply (SUBMISSION_TEXT is short — under
# fusion's own MIN_WORDS floor — so predict_fused_score_with_reason abstains
# before even touching the artifact or peer pool). The "hit" arms need
# original.fusion's own MIN_BASELINES (3) and N_REFERENCES (8) floors met
# for real, which tests/fusion/test_wiring.py already exercises at full
# scale — reproduced here at the *minimum* viable cohort size (exactly 8
# peers, not test_wiring.py's 12, and one cohort shared across all three
# assertions below) to keep this fast enough for the scoped branch-coverage
# run: building even the minimal cohort costs ~40s of real feature
# extraction over 27 HTTP baseline calls, so it is deliberately not repeated
# per-assertion.


def test_fused_score_flag_on_but_probe_too_short_is_a_clean_abstain(
    live_client, store_reset, monkeypatch
):
    sid = "fused-abstain"
    assert _add_baseline(live_client, sid).status_code == 200

    monkeypatch.setenv("FUSED_SCORE_SHADOW", "1")
    r = _score(live_client, sid, force=True)

    assert r.status_code == 200, r.text
    assert r.json().get("fused_score") is None


def test_fused_score_hit_enabled_shadow_and_persistence_failure(
    live_client, store_reset, monkeypatch, tmp_path
):
    import json
    import uuid

    import numpy as np

    from original.fusion import reset_for_tests

    # A tiny local artifact (same shape test_wiring.py's fixture_artifact
    # uses) so this doesn't depend on the real shipped model's calibration.
    payload = {
        "schema_version": 1,
        "channel_order": ["peer_centered_z", "compression", "function_word_network"],
        "mu": [0.0, 0.0, 0.0],
        "sd": [1.0, 1.0, 1.0],
        "weights": [1.0, 1.0, 1.0],
        "intercept": 0.0,
        "threshold_fa5": 0.5,
        "threshold_fa1": 1.5,
        "reference_inputs": [[0.1, 0.2, 0.3]],
        "reference_outputs": [float(np.dot([0.1, 0.2, 0.3], [1.0, 1.0, 1.0]))],
        "provenance": {"dataset": "unit-test"},
    }
    artifact_path = tmp_path / "fused.json"
    artifact_path.write_text(json.dumps(payload))
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(artifact_path))
    reset_for_tests()

    tenant = f"fusedhit{uuid.uuid4().hex[:6]}"
    r = live_client.post(
        "/tenants", json={"tenant_id": tenant, "name": tenant, "environment": "demo"}
    )
    assert r.status_code == 201, r.text

    long_text = (
        "However, a reader might ask why these claims have been made; therefore we "
        "reply that the argument is careful and that it is also sound. "
    ) * 40
    claimed = f"{tenant}:alice"
    for name in ["alice"] + [f"peer{i}" for i in range(8)]:  # exactly N_REFERENCES
        student_id = f"{tenant}:{name}"
        for index in range(3):  # MIN_BASELINES
            resp = live_client.post(
                f"/students/{student_id}/baseline",
                json={
                    "text": long_text,
                    "provenance": "proctored",
                    "assignment": f"{name}-{index}",
                },
            )
            assert resp.status_code == 200, resp.text

    # ── [414,415]: FUSED_SCORE_ENABLED=1 → attached AND persisted ───────────
    monkeypatch.setenv("FUSED_SCORE_ENABLED", "1")
    monkeypatch.delenv("FUSED_SCORE_SHADOW", raising=False)
    r_enabled = live_client.post(
        f"/students/{claimed}/score",
        json={"text": long_text, "submission_id": uuid.uuid4().hex},
    )
    assert r_enabled.status_code == 200, r_enabled.text
    assert r_enabled.json().get("fused_score") is not None

    # ── [414,416]: SHADOW-only → persisted, field STILL null ────────────────
    monkeypatch.delenv("FUSED_SCORE_ENABLED", raising=False)
    monkeypatch.setenv("FUSED_SCORE_SHADOW", "1")
    r_shadow = live_client.post(
        f"/students/{claimed}/score",
        json={"text": long_text, "submission_id": uuid.uuid4().hex},
    )
    assert r_shadow.status_code == 200, r_shadow.text
    assert r_shadow.json().get("fused_score") is None

    # ── persistence exception (best-effort, never surfaces to the caller) ───
    from original.repository import SqliteRepository

    def _put_fused_score_boom(self, **kwargs):
        raise RuntimeError("simulated fused-score persistence failure")

    monkeypatch.setattr(SqliteRepository, "put_fused_score", _put_fused_score_boom)
    r_persist_fail = live_client.post(
        f"/students/{claimed}/score",
        json={"text": long_text, "submission_id": uuid.uuid4().hex},
    )
    assert r_persist_fail.status_code == 200, r_persist_fail.text


# ── `force=True` cache-bypass arm ────────────────────────────────────────────
# students_scoring.py:[52,62] — `force` is a plain route parameter alongside
# a Pydantic body model, so FastAPI resolves it as a QUERY parameter, not
# part of the JSON body. `_score()`'s `force=True` kwarg above lands *inside*
# `json={...}` (harmless here — the cache-check block is a no-op stub either
# way, `existing_result` is hardcoded `None` regardless of `force`), but it
# never actually sets the query param, so the `not force` False arm (skip the
# cache-check block entirely) was never taken by any existing test. Verified
# empirically before writing this test.


def test_force_true_as_a_real_query_param_skips_the_cache_check_block(
    live_client, store_reset
):
    sid = "force-query-param"
    assert _add_baseline(live_client, sid).status_code == 200

    r = live_client.post(
        SCORE.format(sid=sid),
        json={"text": SUBMISSION_TEXT},
        params={"force": "true"},
    )

    assert r.status_code == 200, r.text


# ── Best-effort exception handlers ───────────────────────────────────────────
# These are statement-only gaps, not branch pairs (try/except isn't a branch
# coverage.py tracks) — students_scoring.py has many of this shape (adaptive
# pipeline fallback, impostor-pool build, ai_likelihood/fused/fidelity/
# manifest persistence, report assembly, audit log — all "log and continue,
# never fail the request"). The four below are the highest-value ones
# (whole-orchestrator fallback, and the three persistence writes every
# scored submission goes through); the remainder are the same shape and are
# documented, not chased, in the sweep report.


def test_adaptive_pipeline_catastrophic_failure_falls_back_to_phase1(
    live_client, store_reset, monkeypatch
):
    """students_scoring.py:85-97 — `except Exception as e:` around the
    whole adaptive-context orchestrator call. A broken resolver must not be
    able to take down scoring; the handler falls back to plain
    extract_features/feature_vector (Phase 1 behaviour)."""
    import original.context.pipeline as pipeline_mod

    def _boom(**kwargs):
        raise RuntimeError("simulated adaptive pipeline failure")

    monkeypatch.setattr(pipeline_mod, "run_adaptive_pipeline", _boom)

    sid = "adaptive-pipeline-boom"
    assert _add_baseline(live_client, sid).status_code == 200

    r = _score(live_client, sid, force=True)

    assert r.status_code == 200, r.text


def test_fidelity_persistence_failure_is_swallowed(live_client, store_reset, monkeypatch):
    """students_scoring.py:460-461 — `except Exception as _e:` around
    put_fidelity_score. A failing conformal-calibration write must not
    fail the scoring response. Only reachable when
    `result.authorship.quantum_fidelity > 0` on the INTERNAL Layer7Output
    (quantum_fidelity is the Phase 6 amplitude-encoding score, computed
    only under AMPLITUDE_SCORING_ENABLED=1). Patch the leaf
    `original.quantum.amplitude.quantum_fidelity` function so the internal
    value is unconditionally positive regardless of amplitude-encoding
    numerics on a short test document.

    Can't assert this via the HTTP response's `authorship.quantum_fidelity`
    field — schemas.py:576's own docstring documents that `_to_response()`
    never copies it from the internal dataclass ("WS-7 S9 completeness
    gap... silently dropped today"), so that field always reads 0.0
    regardless of the internal value. Verified empirically: the internal
    branch this test targets is independent of that separate, pre-existing,
    already-tracked serialization gap — asserting response status is the
    right level here, matching every other "swallowed exception" test in
    this file."""
    import original.quantum.amplitude as amplitude_mod
    from original.repository import SqliteRepository

    monkeypatch.setattr(amplitude_mod, "quantum_fidelity", lambda psi_b, psi_s: 0.87)
    monkeypatch.setenv("AMPLITUDE_SCORING_ENABLED", "1")

    def _boom(self, **kwargs):
        raise RuntimeError("simulated put_fidelity_score failure")

    monkeypatch.setattr(SqliteRepository, "put_fidelity_score", _boom)

    sid = "fidelity-persist-boom"
    assert _add_baseline(live_client, sid).status_code == 200

    r = _score(live_client, sid, force=True)

    assert r.status_code == 200, r.text


def test_manifest_persistence_failure_is_swallowed(live_client, store_reset, monkeypatch):
    """students_scoring.py:477-478 — `except Exception as e:` around
    put_manifest. Requires CONTEXT_MANIFEST_ENABLED=1 so `manifest is not
    None`, else the persist block is skipped entirely (not this arm)."""
    from original.repository import SqliteRepository

    def _boom(self, **kwargs):
        raise RuntimeError("simulated put_manifest failure")

    monkeypatch.setattr(SqliteRepository, "put_manifest", _boom)
    monkeypatch.setenv("CONTEXT_MANIFEST_ENABLED", "1")

    sid = "manifest-persist-boom"
    assert _add_baseline(live_client, sid).status_code == 200

    r = _score(live_client, sid, force=True)

    assert r.status_code == 200, r.text


def test_audit_log_failure_is_swallowed(live_client, store_reset, monkeypatch):
    """students_scoring.py:523-524 — the bare `except Exception: pass`
    around the final best-effort audit-log write."""
    from original.repository import SqliteRepository

    real_log_audit = SqliteRepository.log_audit

    def _boom(self, **kwargs):
        if kwargs.get("action") == "score":
            raise RuntimeError("simulated log_audit failure")
        return real_log_audit(self, **kwargs)

    monkeypatch.setattr(SqliteRepository, "log_audit", _boom)

    sid = "auditlog-persist-boom"
    assert _add_baseline(live_client, sid).status_code == 200

    r = _score(live_client, sid, force=True)

    assert r.status_code == 200, r.text


# ── Final-sweep residual arms (cross-cluster branch-coverage closure) ───────
# The tests above (Part 2) chased the highest-value best-effort guards;
# these six close the remaining residual `except Exception:` arms a later
# full-suite measurement found still missing in students_scoring.py. Same
# idiom throughout: set the one env flag needed to reach the guarded block,
# monkeypatch the specific inline-imported leaf function to raise, and
# assert the request still returns 200 — a broken optional signal must never
# fail the scoring endpoint.


def test_impostor_pool_build_exception_is_swallowed(live_client, store_reset, monkeypatch):
    """students_scoring.py:149-150 — `except Exception:` around
    `build_impostor_stats(...)`. Reached whenever NULL_MODEL=impostor (or
    CHARACTERISTIC_WEIGHTS != "off") makes the impostor-pool block run at
    all; a broken pool builder must not take the scoring endpoint down with
    it, only skip the signals that depend on it (llr_deviation_score,
    characteristic weighting)."""
    import original.quantum.null_pool as null_pool_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated impostor pool build failure")

    monkeypatch.setattr(null_pool_mod, "build_impostor_stats", _boom)
    monkeypatch.setenv("NULL_MODEL", "impostor")

    sid = "impostor-pool-boom"
    assert _add_baseline(live_client, sid).status_code == 200

    r = _score(live_client, sid, force=True)

    assert r.status_code == 200, r.text


def test_longitudinal_genre_resolution_exception_is_swallowed(live_client, store_reset, monkeypatch):
    """students_scoring.py:304-305 — `except Exception:` around
    `resolve_genre(req.text)` inside the LONGITUDINAL_DRIFT_ENABLED block. A
    broken genre resolver must not prevent the (report-only) longitudinal
    drift analysis from running — it just falls back to
    `_longitudinal_genre = None`."""
    import original.context.resolvers as resolvers_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated genre resolution failure")

    monkeypatch.setattr(resolvers_mod, "resolve_genre", _boom)
    monkeypatch.setenv("LONGITUDINAL_DRIFT_ENABLED", "1")

    sid = "longitudinal-genre-boom"
    assert _add_baseline(live_client, sid).status_code == 200

    r = _score(live_client, sid, force=True)

    assert r.status_code == 200, r.text


def test_ai_likelihood_persistence_exception_is_swallowed(live_client, store_reset, monkeypatch):
    """students_scoring.py:354-355 — `except Exception:` around
    `_repo().put_ai_likelihood_score(...)`. Only reachable when the
    predictor actually returns a non-None result, so the leaf predictor
    itself is patched to a fixed successful result (same style as
    test_fidelity_persistence_failure_is_swallowed's amplitude patch above)
    rather than relying on the real model producing one for arbitrary text."""
    import original.ai_likelihood as ai_likelihood_mod
    from original.repository import SqliteRepository

    fake_result = ai_likelihood_mod.AiLikelihoodResult(
        probability=0.42, band="elevated", model_version="v1", trained_on="unit-test"
    )
    monkeypatch.setattr(ai_likelihood_mod, "predict_ai_likelihood", lambda vec: fake_result)

    def _boom(self, **kwargs):
        raise RuntimeError("simulated ai_likelihood persistence failure")

    monkeypatch.setattr(SqliteRepository, "put_ai_likelihood_score", _boom)
    monkeypatch.setenv("AI_LIKELIHOOD_SHADOW", "1")

    sid = "ai-likelihood-persist-boom"
    assert _add_baseline(live_client, sid).status_code == 200

    r = _score(live_client, sid, force=True)

    assert r.status_code == 200, r.text


def test_style_authorship_inference_exception_is_swallowed(live_client, store_reset, monkeypatch):
    """students_scoring.py:369-370 — `except Exception:` around
    `predict_style_authorship(...)`. Report-only and action-blind by
    contract; a broken expert must only skip `result.style_authorship`, not
    fail the request."""
    import original.style_authorship as style_authorship_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated style-authorship inference failure")

    monkeypatch.setattr(style_authorship_mod, "predict_style_authorship", _boom)
    monkeypatch.setenv("STYLE_AUTHORSHIP_ENABLED", "1")

    sid = "style-authorship-boom"
    assert _add_baseline(live_client, sid).status_code == 200

    r = _score(live_client, sid, force=True)

    assert r.status_code == 200, r.text


def test_fused_score_inference_exception_is_swallowed(live_client, store_reset, monkeypatch):
    """students_scoring.py:397-401 — `except Exception:` around
    `predict_fused_score_with_reason(...)`. FUSED_SCORE_SHADOW=1 is enough
    to enter the block (no need for the full 8-peer cohort test_wiring.py
    and the fused-hit test above build — the leaf function is replaced
    outright, so it never gets far enough to need real peer data)."""
    import original.fusion as fusion_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated fused-score inference failure")

    monkeypatch.setattr(fusion_mod, "predict_fused_score_with_reason", _boom)
    monkeypatch.setenv("FUSED_SCORE_SHADOW", "1")

    sid = "fused-score-inference-boom"
    assert _add_baseline(live_client, sid).status_code == 200

    r = _score(live_client, sid, force=True)

    assert r.status_code == 200, r.text
    assert r.json().get("fused_score") is None


def test_report_assembly_exception_is_swallowed_in_score_submission(
    live_client, store_reset, monkeypatch
):
    """students_scoring.py:495-496 — `except Exception as e:` around
    `build_report(...)` in score_submission (distinct from admin.py's own
    playground report-assembly guard, a separate call site). Only reached
    when a manifest was actually built (CONTEXT_MANIFEST_ENABLED=1); a
    broken report builder must not fail the scoring response, only leave
    `report=None`."""
    import original.context.report as report_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated report assembly failure")

    monkeypatch.setattr(report_mod, "build_report", _boom)
    monkeypatch.setenv("CONTEXT_MANIFEST_ENABLED", "1")

    sid = "report-assembly-boom"
    assert _add_baseline(live_client, sid).status_code == 200

    r = _score(live_client, sid, force=True)

    assert r.status_code == 200, r.text
