"""Admin, dashboard and calibration-lab surfaces.

Audit log, context manifests, instructor corrections, the /test/score
playground, the calibration lab and tuned thresholds. Moved verbatim from
original/api.py.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from .. import principal as principal_mod
from ..features.pipeline import feature_vector
from ..quantum.scoring import ScoringConfig
from ..quantum.scoring import score as quantum_score
from ..quantum.state import BaselineSample
from ..schemas import (
    ApplyThresholdsRequest,
    BlendResultOut,
    CalibrationRunCreatedResponse,
    CalibrationRunDetail,
    CalibrationRunListResponse,
    CalibrationRunRequest,
    CalibrationRunSummary,
    CorrectionListResponse,
    CorrectionRequest,
    CorrectionResponse,
    DatasetInfo,
    ManifestListItem,
    ManifestListResponse,
    ManifestStatsResponse,
    SuggestionItem,
    SuggestionsResponse,
    TestScoreRequest,
    TestScoreResponse,
    TunedThresholdsListResponse,
    TunedThresholdsRecord,
    WindowScoreOut,
)
from ..tension_arc import analyze_tension_arc
from ._shared import _repo, _require_guard, _require_staff, _to_response

router = APIRouter()


@router.get("/admin/audit")
def list_audit_log(
    request: Request,
    student_id: str = "",
    action: str = "",
    limit: int = 100,
    offset: int = 0,
):
    """
    Query the system audit log. Staff-only: the tenant-isolation middleware
    already 401s anonymous callers on real deploys (tests/test_pilot_lockdown);
    the explicit guard here additionally rejects STUDENT tokens in the demo —
    audit rows carry other students' identifiers.

    Optional filters:
        student_id — restrict to a specific student
        action     — restrict to a specific action type
                     (baseline_add, score, student_delete, correction,
                      threshold_apply, tenant_register, bulk_delete)

    Results are ordered most-recent-first.
    """
    _require_staff(request)
    limit = min(limit, 500)
    return _repo().list_audit(
        student_id=student_id or None,
        action=action or None,
        limit=limit,
        offset=offset,
    )


# ══════════════════════════════════════════════════════════════════════════════
# PR 7: admin / dashboard / playground / corrections
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/admin/manifests", response_model=ManifestListResponse)
def admin_list_manifests(
    request: Request,
    student_id: str | None = None,
    action: str | None = None,
    flag: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    Paginated list of context manifests from the audit log.
    All filters are optional.

    Staff-only on the same grounds as /admin/audit: the tenant-isolation
    middleware already 401s anonymous callers on real deploys
    (tests/test_pilot_lockdown), and the explicit guard here additionally
    rejects STUDENT tokens in the demo — manifest rows carry other students'
    identifiers, and `student_id` above is a filter over exactly that.
    """
    _require_staff(request)
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="limit must be in [1, 1000]")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be ≥ 0")
    res = _repo().list_manifests(
        student_id=student_id,
        action=action,
        flag=flag,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return ManifestListResponse(
        total=res["total"],
        limit=res["limit"],
        offset=res["offset"],
        items=[ManifestListItem(**i) for i in res["items"]],
    )


@router.get("/admin/manifests/stats", response_model=ManifestStatsResponse)
def admin_manifest_stats(
    request: Request,
    since: str | None = None,
    until: str | None = None,
):
    """Roll-up counts for the admin dashboard summary cards.

    Staff-only for the same reason as /admin/manifests, which these cards
    summarise: the middleware covers real deploys, and the explicit guard
    additionally rejects STUDENT tokens in the demo.
    """
    _require_staff(request)
    return ManifestStatsResponse(**_repo().manifest_stats(since=since, until=until))


@router.post(
    "/submissions/{submission_id}/correct",
    response_model=CorrectionResponse,
)
def submit_correction(submission_id: str, req: CorrectionRequest, request: Request):
    """
    Record an instructor correction on a scoring verdict.

    The correction is keyed by submission_id; auto-fills student_id +
    original action/divergence from the manifest audit log when those
    were not supplied. Multiple corrections per submission are allowed
    (e.g. an initial flag + a later override) — the most recent row wins
    when the retraining job (PR 8) consumes them.

    Authorization: corrections flip the authenticity labels that feed
    conformal calibration and threshold tuning, so this is a staff-only
    write. A non-super staff principal may only correct submissions whose
    student is in its own tenant (operator/super are cross-tenant by design).
    """
    principal = _require_staff(request)
    # Tenant-scope the correction to the submission's student. Resolve the owner
    # the same way put_correction back-fills it (manifest, then the score audit
    # row); when the submission is unknown there is no cross-tenant target to
    # protect, so a staff principal is allowed through and the row is written
    # with a null student_id (unchanged behaviour).
    owner_id = _repo().submission_student_id(submission_id)
    if owner_id is not None:
        try:
            principal_mod.assert_student_access(principal, owner_id)
        except principal_mod.TenantAccessError:
            raise HTTPException(status_code=403, detail="Cross-tenant access denied.") from None

    # Validate the optional verdict / action enums to catch typos in the
    # dashboard form before they pollute the training set.
    if req.corrected_verdict is not None and req.corrected_verdict not in (
        "authentic",
        "uncertain",
        "anomalous",
    ):
        raise HTTPException(
            status_code=422,
            detail='corrected_verdict must be "authentic" | "uncertain" | "anomalous"',
        )
    if req.corrected_action is not None and req.corrected_action not in (
        "no_action",
        "monitor",
        "schedule_conversation",
        "escalate",
    ):
        raise HTTPException(
            status_code=422,
            detail='corrected_action must be "no_action" | "monitor" | '
            '"schedule_conversation" | "escalate"',
        )

    correction_id = _repo().put_correction(
        submission_id=submission_id,
        is_correct=req.is_correct,
        student_id=owner_id,
        corrected_verdict=req.corrected_verdict,
        corrected_action=req.corrected_action,
        reviewer=req.reviewer,
        notes=req.notes,
    )
    if correction_id is None:
        raise HTTPException(status_code=500, detail="Failed to persist correction")

    # Round-trip the inserted row so the response carries the auto-filled
    # student_id / original_action / created_at fields the form didn't have.
    listed = _repo().list_corrections(submission_id=submission_id, limit=1)
    if not listed["items"]:
        raise HTTPException(
            status_code=500, detail="Correction inserted but not found on read-back"
        )
    # The most recent (and only matching) row is the one we just wrote.
    latest = listed["items"][0]

    # /admin/audit's own docstring promises "correction" as a filterable
    # action type — log it so that contract is actually true (WS-9).
    _repo().log_audit(
        action="correction",
        student_id=latest.get("student_id"),
        actor=req.reviewer,
        result="ok",
        details={"submission_id": submission_id, "is_correct": req.is_correct},
    )

    # ── Close the conformal feedback loop ────────────────────────────────────
    # Determine whether this correction establishes the submission as authentic,
    # then update the fidelity_scores row so the conformal calibration set
    # reflects real instructor labels rather than the automated heuristic.
    #
    # Rules:
    #   is_correct=True  + original was "no_action"   → confirmed authentic
    #   is_correct=True  + original was not "no_action" → confirmed anomalous
    #   is_correct=False + corrected_verdict/action is authentic → now authentic
    #   is_correct=False + no clear corrected label → assume anomalous
    try:
        _orig_action = latest.get("original_action") or ""
        if req.is_correct:
            _is_now_authentic = _orig_action == "no_action"
        else:
            _is_now_authentic = (
                req.corrected_verdict == "authentic" or req.corrected_action == "no_action"
            )
        _repo().update_fidelity_authenticity(submission_id, _is_now_authentic)
    except Exception as _fid_exc:
        # Non-fatal: the correction row was saved; the fidelity update is
        # best-effort. Log at DEBUG so production noise stays low.
        logging.getLogger(__name__).debug(
            "fidelity authenticity update skipped for %s: %s",
            submission_id,
            _fid_exc,
        )

    return CorrectionResponse(**latest)


@router.get("/admin/corrections", response_model=CorrectionListResponse)
def admin_list_corrections(
    request: Request,
    submission_id: str | None = None,
    student_id: str | None = None,
    is_correct: bool | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """List corrections with optional filters.

    Staff-only on the same grounds as /admin/audit: the tenant-isolation
    middleware already 401s anonymous callers on real deploys
    (tests/test_pilot_lockdown), and the explicit guard here additionally
    rejects STUDENT tokens in the demo — correction rows carry other
    students' identifiers.
    """
    _require_staff(request)
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="limit must be in [1, 1000]")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be ≥ 0")
    res = _repo().list_corrections(
        submission_id=submission_id,
        student_id=student_id,
        is_correct=is_correct,
        limit=limit,
        offset=offset,
    )
    return CorrectionListResponse(
        total=res["total"],
        limit=res["limit"],
        offset=res["offset"],
        items=[CorrectionResponse(**i) for i in res["items"]],
    )


@router.post("/test/score", response_model=TestScoreResponse)
def test_score(req: TestScoreRequest):
    """
    Playground endpoint — runs the full adaptive pipeline on inline text
    + inline baselines, **with no DB writes**. The two adaptive feature
    flags default to True regardless of the server's env-var config so
    callers always see the full output. Optionally also runs blend
    detection on the same submission.

    Use cases:
        - Demo / "kick the tires" UI on `/playground.html`
        - Reproducing a bug report's manifest without persisting
        - Tuning resolver thresholds in a quick feedback loop
    """
    if not req.baseline_texts:
        raise HTTPException(
            status_code=422,
            detail="baseline_texts must be non-empty (need at least one sample to score against)",
        )
    if len(req.baseline_texts) > 10:
        raise HTTPException(
            status_code=422,
            detail="baseline_texts capped at 10 — playground only",
        )

    # Build a synthetic, in-memory StudentState. Verified provenance + 1.0
    # auth_weight so every supplied text contributes to the density matrix.
    synth_samples = []
    for i, t in enumerate(req.baseline_texts):
        if not (t or "").strip():
            continue
        try:
            v = feature_vector(t)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"baseline_texts[{i}] feature extraction failed: {exc}",
            ) from exc
        synth_samples.append(
            BaselineSample(
                text=t,
                vector=v,
                provenance="verified",
                auth_weight=1.0,
                assignment=f"playground_{i}",
                submitted_at="",
            )
        )
    if not synth_samples:
        raise HTTPException(status_code=422, detail="All baseline_texts were empty after stripping")

    from ..quantum.state import StudentState as _SS

    synth_state = _SS(student_id="__playground__", samples=synth_samples)

    # ── Run the adaptive pipeline (always force flags ON for playground) ──────
    from ..context.pipeline import run_adaptive_pipeline

    adaptive = run_adaptive_pipeline(
        text=req.text,
        state=synth_state,
        submission_id=req.submission_id,
        keystroke_data=req.keystroke_data,
        enable_manifest=req.enable_manifest,
        enable_adaptive_weights=req.enable_adaptive_weights,
    )
    manifest_dict = adaptive.manifest.to_dict() if adaptive.manifest is not None else None
    layer7 = quantum_score(
        state=synth_state,
        submission_vector=adaptive.vector,
        feature_dict=adaptive.feat_dict,
        submission_id=req.submission_id,
        adaptive_weights=adaptive.adaptive_weights,
        manifest=manifest_dict,
        n_tokens=len(req.text.split()),
        # Synthetic in-memory student has no store record — no authentic
        # fidelities or genre to fetch, but flags still come from env
        # for parity with the pre-WS-7 live os.environ reads.
        scoring_config=ScoringConfig.from_env(),
    )

    # ── Optional: build the report (Phase 6) ──────────────────────────────────
    report = None
    if adaptive.manifest is not None:
        try:
            from ..context.report import build_report

            report = build_report(layer7, adaptive.manifest, synth_state)
        except Exception as e:
            logging.getLogger(__name__).warning("playground report failed: %s", e)

    # Tension arc (cheap, runs alongside).
    arc = analyze_tension_arc(req.text)

    layer7_resp = _to_response(layer7, arc=arc, report=report)

    # ── Optional: sliding-window blend detection ──────────────────────────────
    blend_resp = None
    if req.enable_blend:
        from ..context.blend import detect_blend

        try:
            br = detect_blend(
                text=req.text,
                state=synth_state,
                submission_id=req.submission_id,
            )
            blend_resp = BlendResultOut(
                blend_detected=br.blend_detected,
                blend_index=br.blend_index,
                shift_positions=list(br.shift_positions),
                per_section=[
                    WindowScoreOut(
                        start=w.start,
                        end=w.end,
                        score=w.score,
                        confidence=w.confidence,
                        # Report-only shadow field; None unless AI_LIKELIHOOD_SHADOW=1.
                        ai_probability=w.ai_probability,
                    )
                    for w in br.per_section
                ],
                n_tokens=br.n_tokens,
                fallback_reason=br.fallback_reason,
                ai_window_max=br.ai_window_max,
                ai_window_mean=br.ai_window_mean,
            )
        except Exception as e:
            logging.getLogger(__name__).warning("playground blend failed: %s", e)

    return TestScoreResponse(layer7=layer7_resp, blend=blend_resp)


# ══════════════════════════════════════════════════════════════════════════════
# PR 8: Calibration Lab
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/admin/lab/datasets", response_model=list[DatasetInfo])
def admin_lab_datasets(request: Request):
    """List the datasets the lab knows how to run (Federalist, multi-author, …).

    Staff-only on the same grounds as /admin/audit: the middleware already 401s
    anonymous callers on real deploys, and the explicit guard here additionally
    rejects STUDENT tokens in the demo — the calibration lab is instructor
    tooling that steers scoring for everyone.
    """
    _require_staff(request)
    from ..lab.datasets import list_datasets

    return [DatasetInfo(**d) for d in list_datasets()]


@router.post(
    "/admin/calibration/run", response_model=CalibrationRunCreatedResponse, status_code=202
)
def admin_run_calibration(request: Request, req: CalibrationRunRequest):
    """
    Kick off a calibration run in the background and return its row id.

    The run executes on a single-worker thread pool, so multiple requests
    queue rather than overlap. Poll ``GET /admin/calibration/runs/{id}``
    to see when status flips to ``completed`` or ``failed``.

    Staff-only on the same grounds as /admin/audit: the middleware already 401s
    anonymous callers on real deploys, and the explicit guard here additionally
    rejects STUDENT tokens in the demo — this burns shared compute on the run
    queue and produces the report that threshold changes are argued from.
    """
    _require_staff(request)
    from ..lab.runner import trigger_run

    run_id, error = trigger_run(
        dataset_label=req.dataset_label,
        run_label=req.run_label,
        max_scoring=req.max_scoring,
        thresholds=req.thresholds,
    )
    if run_id is None:
        raise HTTPException(status_code=422, detail=error or "Failed to start run")
    return CalibrationRunCreatedResponse(
        run_id=run_id,
        status="running",
        dataset_label=req.dataset_label,
    )


@router.get("/admin/calibration/runs", response_model=CalibrationRunListResponse)
def admin_list_calibration_runs(
    request: Request,
    status: str | None = None,
    dataset_label: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List calibration runs (newest first), with optional filters.

    Staff-only for the same reason as the rest of the lab: the middleware
    covers real deploys, and the explicit guard additionally rejects STUDENT
    tokens in the demo.
    """
    _require_staff(request)
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be in [1, 500]")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be ≥ 0")
    res = _repo().list_calibration_runs(
        status=status,
        dataset_label=dataset_label,
        limit=limit,
        offset=offset,
    )
    return CalibrationRunListResponse(
        total=res["total"],
        limit=res["limit"],
        offset=res["offset"],
        items=[CalibrationRunSummary(**i) for i in res["items"]],
    )


@router.get("/admin/calibration/runs/{run_id}", response_model=CalibrationRunDetail)
def admin_get_calibration_run(request: Request, run_id: int, include_report: bool = True):
    """Fetch one run with optional report inclusion.

    Staff-only for the same reason as the runs list: the middleware covers real
    deploys, and the explicit guard additionally rejects STUDENT tokens in the
    demo — the attached report details how the scoring bar was drawn.
    """
    _require_staff(request)
    res = _repo().get_calibration_run(run_id, include_report=include_report)
    if res is None:
        raise HTTPException(status_code=404, detail=f"calibration run {run_id} not found")
    return CalibrationRunDetail(**res)


@router.get("/admin/calibration/runs/{run_id}/suggestions", response_model=SuggestionsResponse)
def admin_run_suggestions(request: Request, run_id: int):
    """
    Run the suggestion engine over a finished calibration + the corrections
    feedback log. Returns recommended threshold + tier-weight changes with
    explanatory rationale + per-suggestion confidence.

    Staff-only on the same grounds as /admin/corrections, which it reads: the
    middleware covers real deploys, and the explicit guard additionally rejects
    STUDENT tokens in the demo.
    """
    _require_staff(request)
    res = _repo().get_calibration_run(run_id, include_report=True)
    if res is None:
        raise HTTPException(status_code=404, detail=f"calibration run {run_id} not found")
    if res.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id} is {res.get('status')}; suggestions require status=completed",
        )

    from ..lab.suggestions import generate_suggestions

    # Pull current thresholds from active tuned set if available; fall back
    # to Phase-1 defaults.
    active = _repo().get_active_tuned_thresholds()
    if active is not None:
        current = {
            "no_action": active["no_action"],
            "monitor": active["monitor"],
            "escalate": active["escalate"],
        }
    else:
        current = None

    corrections = _repo().list_corrections(limit=1000)["items"]
    out = generate_suggestions(
        report=res["report"] or {},
        corrections=corrections,
        current_thresholds=current,
    )
    return SuggestionsResponse(
        suggestions=[SuggestionItem(**s) for s in out["suggestions"]],
        summary=out["summary"],
    )


@router.post("/admin/calibration/runs/{run_id}/apply", response_model=TunedThresholdsRecord)
def admin_apply_thresholds(run_id: int, req: ApplyThresholdsRequest, request: Request):
    """
    Persist a new active threshold set sourced from a calibration run.

    Versioned in ``tuned_thresholds_v2`` — older sets remain for audit.
    The latest row by ``created_at`` is the in-effect active set;
    in-process scoring reads it on demand.

    When GUARD_DESTRUCTIVE=1, requires X-Guard-Token header — applying new
    thresholds changes system behaviour globally and should only be allowed
    for admins in pilot/production mode.

    The guard token is a *deploy* secret, not an identity, so it is checked
    after the staff gate rather than instead of it: the middleware only 401s
    anonymous callers on real deploys, and this endpoint is the one that
    rewrites the live scoring thresholds. A STUDENT token is refused here in
    every environment, exactly as on /admin/audit.
    """
    _require_staff(request)
    _require_guard(request)
    res = _repo().get_calibration_run(run_id, include_report=False)
    if res is None:
        raise HTTPException(status_code=404, detail=f"calibration run {run_id} not found")

    new_id = _repo().put_tuned_thresholds(
        no_action=req.no_action,
        monitor=req.monitor,
        escalate=req.escalate,
        verdict_authentic_below=req.verdict_authentic_below,
        verdict_anomalous_at_or_above=req.verdict_anomalous_at_or_above,
        source="calibration_run",
        source_run_id=run_id,
        notes=req.notes,
        provenance={
            "dataset_label": res.get("dataset_label"),
            "auc_at_apply": res.get("auc"),
            "n_essays_scored": res.get("n_essays_scored"),
            "applied_at_run_id": run_id,
        },
    )
    if new_id is None:
        raise HTTPException(status_code=500, detail="Failed to persist tuned thresholds")
    active = _repo().get_active_tuned_thresholds()
    return TunedThresholdsRecord(**active)


@router.get("/admin/tuned-thresholds", response_model=Optional[TunedThresholdsRecord])
def admin_get_tuned_thresholds(request: Request):
    """Return the currently-active tuned thresholds (or null if none set).

    Staff-only on the same grounds as /admin/audit: the middleware covers real
    deploys, and the explicit guard additionally rejects STUDENT tokens in the
    demo — these are the live bars a submission is judged against, which a
    student should not be able to read off and write toward.
    """
    _require_staff(request)
    active = _repo().get_active_tuned_thresholds()
    return TunedThresholdsRecord(**active) if active else None


@router.get("/admin/tuned-thresholds/history", response_model=TunedThresholdsListResponse)
def admin_list_tuned_thresholds(request: Request, limit: int = 50, offset: int = 0):
    """Audit list of all tuned-threshold versions ever applied.

    Staff-only for the same reason as the active-set getter above: the
    middleware covers real deploys, and the explicit guard additionally rejects
    STUDENT tokens in the demo.
    """
    _require_staff(request)
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be in [1, 500]")
    res = _repo().list_tuned_thresholds(limit=limit, offset=offset)
    return TunedThresholdsListResponse(
        total=res["total"],
        limit=res["limit"],
        offset=res["offset"],
        items=[TunedThresholdsRecord(**i) for i in res["items"]],
    )
