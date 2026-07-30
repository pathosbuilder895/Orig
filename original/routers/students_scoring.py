"""Submission scoring for a student.

The Born-rule score endpoint and the sliding-window blend detector. Moved
verbatim from original/api.py; part of the /students* route group split out of
students.py for file size.
"""

from __future__ import annotations

import dataclasses
import logging
import os

from fastapi import APIRouter, HTTPException

from ..features.pipeline import extract_features, feature_vector
from ..principal import tenant_of
from ..quantum.scoring import ScoringConfig
from ..quantum.scoring import score as quantum_score
from ..schemas import (
    BlendDetectionRequest,
    BlendResultOut,
    Layer7OutputResponse,
    ScoreSubmissionRequest,
    WindowScoreOut,
)
from ..tension_arc import analyze_tension_arc
from ._shared import _repo, _send_notification_email, _to_response

router = APIRouter()


# ── Score submission ──────────────────────────────────────────────────────────


@router.post("/students/{student_id}/score", response_model=Layer7OutputResponse)
def score_submission(student_id: str, req: ScoreSubmissionRequest, force: bool = False):
    state = _repo().get(student_id)
    if state is None:
        raise HTTPException(
            status_code=404, detail=f"Student '{student_id}' not found. Add baseline samples first."
        )
    if state.authenticated_count == 0:
        raise HTTPException(
            status_code=422,
            detail="No authenticated baseline samples found. "
            "Add at least one 'proctored' or 'verified' sample first.",
        )

    # Check cache only if force is False (allow cache bypass with force=True)
    submission_id = req.submission_id or f"{student_id}_submission_{state.sample_count}"
    if not force:
        # Check for cached result (stub for future caching implementation)
        existing_result = None  # TODO: retrieve from cache by submission_id
        if existing_result:
            return _to_response(existing_result)

    # ── Phase 5: adaptive-context orchestrator (env-flag gated) ───────────────
    # When both CONTEXT_MANIFEST_ENABLED and ADAPTIVE_WEIGHTS_ENABLED are
    # unset, the orchestrator short-circuits to plain extract_features +
    # feature_vector, preserving Phase 1 byte-identical behaviour.
    enable_manifest = os.environ.get("CONTEXT_MANIFEST_ENABLED") == "1"
    enable_adaptive = os.environ.get("ADAPTIVE_WEIGHTS_ENABLED") == "1"

    try:
        from ..context.pipeline import run_adaptive_pipeline

        adaptive = run_adaptive_pipeline(
            text=req.text,
            state=state,
            submission_id=submission_id,
            keystroke_data=req.keystroke_data,
            enable_manifest=enable_manifest,
            enable_adaptive_weights=enable_adaptive,
        )
        feat_dict = adaptive.feat_dict
        vec = adaptive.vector
        manifest = adaptive.manifest
        adaptive_weights = adaptive.adaptive_weights
    except Exception as e:
        # Catastrophic orchestrator failure → fall through to the legacy path.
        # This guarantees that nothing in the new context layer can take down
        # the scoring endpoint, no matter how broken a resolver gets.
        logging.getLogger(__name__).warning(
            "Adaptive pipeline failed for %s: %s — falling back to Phase 1",
            submission_id,
            e,
        )
        feat_dict = extract_features(req.text, keystroke_data=req.keystroke_data)
        vec = feature_vector(req.text, keystroke_data=req.keystroke_data)
        manifest = None
        adaptive_weights = None

    manifest_dict = manifest.to_dict() if manifest is not None else None
    # n_tokens: thread the actual word count into the scorer so the Gaussian
    # wave packet attenuation in encode_amplitudes is proportional to the
    # real submission length, not a fixed default.
    _n_tokens = len(req.text.split())

    # ── Explicit null model (rank-and-null work, production wiring) ───────────
    # NULL_MODEL=impostor: pool authenticated baseline vectors from the
    # claimed student's same-tenant peers into a diagonal-Gaussian impostor
    # cohort (original/quantum/null_pool.py); quantum_score() then attaches
    # llr_deviation_score — "fits this student vs fits a typical classmate".
    # None below the cold-start floors (3 peers / 5 vectors) and on any
    # failure; never changes deviation_score or the recommended action.
    _scoring_config_env = ScoringConfig.from_env()

    _impostor_stats = None
    if _scoring_config_env.null_model == "impostor":
        try:
            from ..quantum.null_pool import build_impostor_stats

            _impostor_stats = build_impostor_stats(student_id, _repo().all_states())
        except Exception:
            logging.getLogger(__name__).exception(
                "impostor pool build failed for %s — llr score skipped", student_id
            )

    # ── ScoringConfig persistence lookups (WS-7 step 1) ───────────────────────
    # scoring.py no longer reaches into store directly — resolve the same two
    # lookups here, gated behind the same flags scoring.py used to check
    # internally, and pass the results through.
    _authentic_fidelities = None
    if _scoring_config_env.amplitude_scoring_enabled:
        _authentic_fidelities = _repo().get_authentic_fidelities(student_id)
    _genre_stats = None
    if _scoring_config_env.bayesian_prior_enabled and state.sample_count < 10:
        _genre = (
            state.samples[-1].genre
            if state.samples and getattr(state.samples[-1], "genre", None)
            else None
        )
        if _genre:
            # Tenant-scoped: the cold-start prior pools only same-tenant
            # baselines, mirroring build_impostor_stats above. Returns None
            # more often than the old cross-tenant pool did — that's the
            # documented fallback to the student-only baseline, not an error.
            _prior_tenant = tenant_of(student_id)
            _genre_stats = _repo().get_genre_stats(_genre, _prior_tenant)
            # How often that fallback actually fires was never measured:
            # scripts/measure_genre_prior_scope.py found no reachable dataset
            # with genre-labelled authenticated samples (2026-07-29), so the
            # coverage cost of tenant-scoping is still unknown. This line lets
            # the first tenant to enable the flag measure it in situ — count
            # outcome=miss against outcome=hit for the per-(tenant, genre)
            # None rate. Tenant slug and genre label only: never a student id.
            logging.getLogger(__name__).info(
                "bayesian_prior outcome=%s genre=%s tenant=%s n_prior=%d",
                "hit" if _genre_stats is not None else "miss",
                _genre,
                _prior_tenant,
                _genre_stats["n_samples"] if _genre_stats is not None else 0,
            )
    _scoring_config = dataclasses.replace(
        _scoring_config_env,
        authentic_fidelities=_authentic_fidelities,
        genre_stats=_genre_stats,
    )

    result = quantum_score(
        state=state,
        submission_vector=vec,
        feature_dict=feat_dict,
        submission_id=submission_id,
        adaptive_weights=adaptive_weights,
        manifest=manifest_dict,
        n_tokens=_n_tokens,
        impostor_stats=_impostor_stats,
        scoring_config=_scoring_config,
    )

    # ── AI-likelihood (corpus-level second scoring mode, report-only) ─────────
    # Two modes, one persistence call site:
    #   AI_LIKELIHOOD_SHADOW=1  → compute + persist ONLY. result.ai_likelihood
    #     stays None, so narrative/explainer/response can never see it —
    #     silent real-world FPR measurement (scripts/shadow_report.py).
    #   AI_LIKELIHOOD_ENABLED=1 → attach to the result AND persist (strict
    #     superset: enablement is one env flip with unbroken data continuity).
    # Attached before report/narrative assembly so downstream explanation
    # layers can see it when enabled. Scores the same `vec` — no second
    # extraction. predict_ai_likelihood never raises; None when unavailable.
    _ai_enabled = os.environ.get("AI_LIKELIHOOD_ENABLED") == "1"
    _ai_shadow = os.environ.get("AI_LIKELIHOOD_SHADOW") == "1"
    if _ai_enabled or _ai_shadow:
        from ..ai_likelihood import predict_ai_likelihood

        _ai_res = predict_ai_likelihood(vec)
        if _ai_enabled:
            result.ai_likelihood = _ai_res
        if _ai_res is not None:
            # Deliberately outside the quantum_fidelity > 0 gate below —
            # shadow rows must persist for every scored submission.
            try:
                _repo().put_ai_likelihood_score(
                    submission_id=submission_id,
                    student_id=student_id,
                    probability=_ai_res.probability,
                    band=_ai_res.band,
                    model_version=_ai_res.model_version,
                )
            except Exception:
                logging.getLogger(__name__).exception(
                    "ai_likelihood persistence failed for %s", submission_id
                )

    # ── Persist quantum fidelity for conformal calibration ───────────────────
    # Stores every scored fidelity so get_authentic_fidelities() can build
    # a calibration set for the conformal p-value on future submissions.
    # "Authentic" is approximated as action == no_action here; the instructor
    # corrections flow (put_correction + is_correct=True) should override
    # this for any verdict the professor marks as wrong.
    if result.authorship.quantum_fidelity > 0:
        try:
            _repo().put_fidelity_score(
                submission_id=submission_id,
                student_id=student_id,
                fidelity=result.authorship.quantum_fidelity,
                is_authentic=(result.recommendation.action == "no_action"),
            )
        except Exception as _e:
            logging.getLogger(__name__).debug(
                "put_fidelity_score skipped for %s: %s",
                submission_id,
                _e,
            )

    # ── Persist manifest to audit log when one was built ──────────────────────
    if manifest is not None:
        try:
            _repo().put_manifest(
                submission_id=submission_id,
                student_id=student_id,
                manifest=manifest,
                divergence_score=result.authorship.deviation_score,
                action=result.recommendation.action,
            )
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Manifest audit-log write failed for %s: %s",
                submission_id,
                e,
            )

    # ── Phase 6: human-readable audit report (only when manifest exists) ──────
    # Built from the same triplet that drove the score: Layer7Output (math),
    # ContextManifest (directives), StudentState (sample provenance). When
    # there is no manifest (flag off), no report is produced — response stays
    # byte-identical to Phase 1.
    report = None
    if manifest is not None:
        try:
            from ..context.report import build_report

            report = build_report(result, manifest, state, n_tokens=_n_tokens)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Report assembly failed for %s: %s",
                submission_id,
                e,
            )

    # ── Tension Arc (runs alongside quantum score, independent signal) ────────
    arc = analyze_tension_arc(req.text, baseline_kappa=state.baseline_kappa)

    # ── Email notification stub for escalate/schedule_conversation actions ────
    action = result.recommendation.action
    overall_score = result.authorship.authorship_probability
    if action in ("escalate", "schedule_conversation"):
        _send_notification_email(student_name=student_id, action=action, score=overall_score)

    # ── Audit log — best-effort, never raises ─────────────────────────────────
    try:
        _repo().log_audit(
            action="score",
            student_id=student_id,
            details={
                "submission_id": submission_id,
                "deviation_score": round(result.authorship.deviation_score, 4),
                "recommendation": action,
                "sample_count": state.sample_count,
            },
        )
    except Exception:
        pass

    return _to_response(result, arc, report=report)


# ── Score audit log (best-effort, never raises) ───────────────────────────────
# Wire audit logging after the return object is built so any exception here
# cannot corrupt the response. The try/except is intentional insurance.


# ── Phase 7: sliding-window blend detection ──────────────────────────────────


@router.post(
    "/students/{student_id}/score/blend",
    response_model=BlendResultOut,
)
def score_blend(student_id: str, req: BlendDetectionRequest):
    """
    Detect mid-document fingerprint shifts (collaboration / AI insertion /
    advisor edits) by scoring overlapping token windows separately.

    Cost is N× the regular `/score` endpoint (one full feature extraction
    per window) — kept on a separate route so callers opt in explicitly.
    """
    state = _repo().get(student_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Student '{student_id}' not found. Add baseline samples first.",
        )
    if state.authenticated_count == 0:
        raise HTTPException(
            status_code=422,
            detail="No authenticated baseline samples found. "
            "Add at least one 'proctored' or 'verified' sample first.",
        )

    from ..context.blend import detect_blend

    submission_id = req.submission_id or f"{student_id}_blend_{state.sample_count}"
    result = detect_blend(
        text=req.text,
        state=state,
        window_tokens=req.window_tokens,
        overlap=req.overlap,
        submission_id=submission_id,
    )
    return BlendResultOut(
        blend_detected=result.blend_detected,
        blend_index=result.blend_index,
        shift_positions=list(result.shift_positions),
        per_section=[
            WindowScoreOut(start=w.start, end=w.end, score=w.score, confidence=w.confidence)
            for w in result.per_section
        ],
        n_tokens=result.n_tokens,
        fallback_reason=result.fallback_reason,
    )
