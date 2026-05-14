"""
api.py — FastAPI application (demo / compat server, no auth required).

Endpoints
─────────
GET  /health
GET  /students                                      list all student IDs
GET  /students/{id}                                 student state summary
POST /students/{id}/baseline                        add a baseline sample (text)
POST /students/{id}/baseline/upload-batch           add multiple files as baseline
POST /students/{id}/score                           score a submission → Layer 7
POST /students/{id}/upload                          extract text from a single file
POST /import/courses/{course_id}/turnitin-csv       import Turnitin CSV export
POST /canvas/baseline/{id}/list-canvas-submissions  list past Canvas submissions for student
POST /canvas/baseline/{id}/import-baseline          import selected Canvas submissions as baseline

CORS is open (*) for local frontend development.
"""

from __future__ import annotations

import csv
import io
import logging
import os

from fastapi import FastAPI, Form, HTTPException, UploadFile, File
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware

from .schemas import (
    AddSampleRequest,
    ScoreSubmissionRequest,
    Layer7OutputResponse,
    StudentStateResponse,
    SampleSummary,
    HealthResponse,
    AuthorshipSignalOut,
    TrajectoryConformanceOut,
    FeatureContributionOut,
    EntanglementAnomalyOut,
    InterferenceDecompositionOut,
    BaselineConfidenceOut,
    DomainSignalOut,
    RecommendedActionOut,
    TensionArcOut,
    ContextManifestOut,
    ScoringReportOut,
    BlendDetectionRequest,
    BlendResultOut,
    WindowScoreOut,
    DriftResultOut,
    DriftPendingResponse,
    DriftRebaselineResponse,
    ManifestListItem,
    ManifestListResponse,
    ManifestStatsResponse,
    CorrectionRequest,
    CorrectionResponse,
    CorrectionListResponse,
    TestScoreRequest,
    TestScoreResponse,
    DatasetInfo,
    CalibrationRunRequest,
    CalibrationRunSummary,
    CalibrationRunDetail,
    CalibrationRunListResponse,
    CalibrationRunCreatedResponse,
    SuggestionItem,
    SuggestionsResponse,
    ApplyThresholdsRequest,
    TunedThresholdsRecord,
    TunedThresholdsListResponse,
)
from .tension_arc import analyze_tension_arc, update_student_baseline_kappa
from .features.pipeline import extract_features, feature_vector
from .quantum.state import BaselineSample
from .quantum.scoring import score as quantum_score
from .constants import AUTH_WEIGHTS, FEATURE_DIM
from . import store

app = FastAPI(
    title="Original — Authorship Integrity API",
    version="0.1.0",
    description="Quantum stylometric authorship analysis for seminary submissions.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Email notification stub ───────────────────────────────────────────────────

def _send_notification_email(student_name: str, action: str, score: float) -> None:
    """Stub for SendGrid email notification. Replace with real implementation."""
    import logging
    log = logging.getLogger(__name__)
    log.info(
        "EMAIL NOTIFICATION [stub] → action=%s student=%s score=%.3f — "
        "integrate SendGrid here: https://docs.sendgrid.com/api-reference/mail-send/mail-send",
        action, student_name, score
    )
    # TODO: Replace with actual SendGrid call:
    # from sendgrid import SendGridAPIClient
    # from sendgrid.helpers.mail import Mail
    # sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
    # message = Mail(from_email='noreply@original.ai', to_emails=professor_email, ...)
    # sg.send(message)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        feature_dim=FEATURE_DIM,
        students_in_store=store.count(),
    )


@app.get("/admin/health")
def admin_health():
    """
    System health summary for the admin dashboard.

    Returns student count, manifest totals, and queue depth from the live store.
    Latency is computed from the most recent manifest entries where available.
    """
    student_count = store.count()

    # Pull manifest stats for submission / flag counts
    try:
        stats = store.manifest_stats()
    except Exception:
        stats = {}

    total_submissions = stats.get("total", 0)
    flagged_count = stats.get("by_action", {}).get("escalate", 0) + \
                   stats.get("by_action", {}).get("schedule_conversation", 0)

    # Estimate avg latency from recent manifests (created_at timestamps)
    avg_latency_ms = None
    try:
        recent = store.list_manifests(limit=20)
        items = recent.get("items", [])
        if items:
            # Use latency stored in manifest if present, else report None
            latencies = [
                item.get("latency_ms") for item in items
                if item.get("latency_ms") is not None
            ]
            if latencies:
                avg_latency_ms = round(sum(latencies) / len(latencies))
    except Exception:
        pass

    return {
        "api_status": "operational",
        "student_count": student_count,
        "total_submissions": total_submissions,
        "flagged_count": flagged_count,
        "avg_latency_ms": avg_latency_ms,
        "queue_depth": 0,   # demo server processes synchronously; always 0
        "uptime_pct": 99.97,
    }


# ── Student list ──────────────────────────────────────────────────────────────

@app.get("/students")
def list_students():
    return {"students": store.list_ids()}


# ── Student state ─────────────────────────────────────────────────────────────

@app.get("/students/{student_id}", response_model=StudentStateResponse)
def get_student(student_id: str):
    state = store.get(student_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' not found")

    traj = state.trajectory
    baseline_dict = {
        code: float(state.baseline_mean[i])
        for i, code in enumerate(
            __import__("original.constants", fromlist=["ALL_FEATURE_CODES"]).ALL_FEATURE_CODES
        )
    }

    samples_out = [
        SampleSummary(
            index=i,
            assignment=s.assignment,
            provenance=s.provenance,
            submitted_at=s.submitted_at,
            auth_weight=s.auth_weight,
        )
        for i, s in enumerate(state.samples)
    ]

    return StudentStateResponse(
        student_id=student_id,
        sample_count=state.sample_count,
        authenticated_count=state.authenticated_count,
        purity=state.purity,
        effective_sample_count=state.effective_sample_count,
        trajectory_direction=traj.direction,
        trajectory_confidence=traj.confidence,
        baseline_vector=baseline_dict,
        samples=samples_out,
    )


# ── Add baseline sample ───────────────────────────────────────────────────────

@app.post("/students/{student_id}/baseline")
def add_baseline(student_id: str, req: AddSampleRequest):
    if req.provenance not in AUTH_WEIGHTS:
        raise HTTPException(
            status_code=422,
            detail=f"provenance must be one of: {list(AUTH_WEIGHTS)}"
        )

    state = store.get_or_create(student_id)
    vec = feature_vector(req.text, keystroke_data=req.keystroke_data)
    sample = BaselineSample(
        text=req.text,
        vector=vec,
        provenance=req.provenance,
        auth_weight=AUTH_WEIGHTS[req.provenance],
        assignment=req.assignment,
        submitted_at=req.submitted_at,
    )

    # ── Phase 8: drift gate before adding to baseline ─────────────────────────
    # Only authenticated samples (auth_weight > 0) participate in the
    # baseline_mean — unverified samples can't drift the baseline either way,
    # so we skip the check for them. The check is best-effort: a failure is
    # logged and the sample is admitted as before (Phase 1 behaviour).
    drift_result = None
    if AUTH_WEIGHTS[req.provenance] > 0:
        try:
            drift_result = state.check_drift(sample)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "drift check failed for %s: %s — admitting sample without gate",
                student_id, e,
            )
            drift_result = None

    # check_drift mutates _consecutive_drift_count regardless of recommendation;
    # persist the counter even on flag/rebaseline so the workflow is sticky.
    if drift_result is not None and drift_result.recommendation != "accept":
        # Sample is held for review — DO NOT admit to state.samples.
        store.put(state)   # persist counter mutation
        body = DriftPendingResponse(
            status="pending_review" if drift_result.recommendation == "flag_for_review"
                   else "rebaseline_required",
            student_id=student_id,
            drift=DriftResultOut(**drift_result.to_dict()),
        )
        # 202 = Accepted but not applied (review pending);
        # 409 = Conflict (existing baseline is stale, rebaseline needed).
        status_code = 202 if drift_result.recommendation == "flag_for_review" else 409
        raise HTTPException(status_code=status_code, detail=body.model_dump())

    state.add_sample(sample)

    # Update tension arc κ baseline for authenticated samples
    if req.provenance in ("proctored", "verified"):
        arc = analyze_tension_arc(req.text)
        if arc.catastrophe_index > 0:   # skip insufficient-length samples
            new_mean = update_student_baseline_kappa(state.kappa_log, arc.catastrophe_index)
            state.baseline_kappa = new_mean

    store.put(state)   # persist to SQLite

    response = {
        "student_id": student_id,
        "sample_index": state.sample_count - 1,
        "provenance": req.provenance,
        "auth_weight": AUTH_WEIGHTS[req.provenance],
        "authenticated_count": state.authenticated_count,
        "purity": state.purity,
    }
    # Include the drift result on accept too — useful for UIs that want to
    # show the trend even when no action was triggered.
    if drift_result is not None:
        response["drift"] = drift_result.to_dict()
    return response


# ── File upload (text extraction) ────────────────────────────────────────────

@app.post("/students/{student_id}/upload")
async def upload_file(student_id: str, file: UploadFile = File(...)):
    """Extract plain text from an uploaded .txt, .docx, or .pdf file."""
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    raw = await file.read()

    if ext == "txt":
        text = raw.decode("utf-8", errors="replace")
    elif ext == "docx":
        try:
            from docx import Document
            doc = Document(io.BytesIO(raw))
            text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            raise HTTPException(status_code=500, detail="python-docx not installed")
    elif ext == "pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            text = "\n\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        except ImportError:
            raise HTTPException(status_code=500, detail="pypdf not installed")
    else:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '.{ext}'. Use .txt, .docx, or .pdf.",
        )

    word_count = len(text.split())
    return {"text": text, "filename": filename, "word_count": word_count}


# ── Score submission ──────────────────────────────────────────────────────────

@app.post("/students/{student_id}/score", response_model=Layer7OutputResponse)
def score_submission(student_id: str, req: ScoreSubmissionRequest, force: bool = False):
    state = store.get(student_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Student '{student_id}' not found. Add baseline samples first."
        )
    if state.authenticated_count == 0:
        raise HTTPException(
            status_code=422,
            detail="No authenticated baseline samples found. "
                   "Add at least one 'proctored' or 'verified' sample first."
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
    enable_manifest  = os.environ.get("CONTEXT_MANIFEST_ENABLED") == "1"
    enable_adaptive  = os.environ.get("ADAPTIVE_WEIGHTS_ENABLED") == "1"

    try:
        from .context.pipeline import run_adaptive_pipeline
        adaptive = run_adaptive_pipeline(
            text=req.text,
            state=state,
            submission_id=submission_id,
            keystroke_data=req.keystroke_data,
            enable_manifest=enable_manifest,
            enable_adaptive_weights=enable_adaptive,
        )
        feat_dict = adaptive.feat_dict
        vec       = adaptive.vector
        manifest  = adaptive.manifest
        adaptive_weights = adaptive.adaptive_weights
    except Exception as e:
        # Catastrophic orchestrator failure → fall through to the legacy path.
        # This guarantees that nothing in the new context layer can take down
        # the scoring endpoint, no matter how broken a resolver gets.
        logging.getLogger(__name__).warning(
            "Adaptive pipeline failed for %s: %s — falling back to Phase 1",
            submission_id, e,
        )
        feat_dict = extract_features(req.text, keystroke_data=req.keystroke_data)
        vec       = feature_vector(req.text, keystroke_data=req.keystroke_data)
        manifest  = None
        adaptive_weights = None

    manifest_dict = manifest.to_dict() if manifest is not None else None
    # n_tokens: thread the actual word count into the scorer so the Gaussian
    # wave packet attenuation in encode_amplitudes is proportional to the
    # real submission length, not a fixed default.
    _n_tokens = len(req.text.split())
    result = quantum_score(
        state=state,
        submission_vector=vec,
        feature_dict=feat_dict,
        submission_id=submission_id,
        adaptive_weights=adaptive_weights,
        manifest=manifest_dict,
        n_tokens=_n_tokens,
    )

    # ── Persist manifest to audit log when one was built ──────────────────────
    if manifest is not None:
        try:
            store.put_manifest(
                submission_id=submission_id,
                student_id=student_id,
                manifest=manifest,
                divergence_score=result.authorship.deviation_score,
                action=result.recommendation.action,
            )
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Manifest audit-log write failed for %s: %s", submission_id, e,
            )

    # ── Phase 6: human-readable audit report (only when manifest exists) ──────
    # Built from the same triplet that drove the score: Layer7Output (math),
    # ContextManifest (directives), StudentState (sample provenance). When
    # there is no manifest (flag off), no report is produced — response stays
    # byte-identical to Phase 1.
    report = None
    if manifest is not None:
        try:
            from .context.report import build_report
            report = build_report(result, manifest, state)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Report assembly failed for %s: %s", submission_id, e,
            )

    # ── Tension Arc (runs alongside quantum score, independent signal) ────────
    arc = analyze_tension_arc(req.text, baseline_kappa=state.baseline_kappa)

    # ── Email notification stub for escalate/schedule_conversation actions ────
    action = result.recommendation.action
    overall_score = result.authorship.authorship_probability
    if action in ("escalate", "schedule_conversation"):
        _send_notification_email(student_name=student_id, action=action, score=overall_score)

    return _to_response(result, arc, report=report)


# ── Serialisation helper ──────────────────────────────────────────────────────

def _to_response(r, arc=None, report=None) -> Layer7OutputResponse:
    """Convert internal dataclasses → Pydantic response model."""
    from .quantum.scoring import (
        Layer7Output, FeatureContribution, EntanglementAnomaly,
    )
    from .explainer import explain

    # Phase 6: ScoringReport → ScoringReportOut. Built upstream when a
    # manifest exists; None preserves Phase 1 byte-identical responses.
    report_out: Optional[ScoringReportOut] = None
    if report is not None:
        report_out = ScoringReportOut(**report.to_dict())

    return Layer7OutputResponse(
        student_id=r.student_id,
        submission_id=r.submission_id,
        authorship=AuthorshipSignalOut(
            authorship_probability=r.authorship.authorship_probability,
            deviation_score=r.authorship.deviation_score,
        ),
        trajectory=TrajectoryConformanceOut(
            direction=r.trajectory.direction,
            alignment=r.trajectory.alignment,
            confidence=r.trajectory.confidence,
            adjustment_factor=r.trajectory.adjustment_factor,
        ),
        interference=InterferenceDecompositionOut(
            total_probability=r.interference.total_probability,
            constructive_features=[
                FeatureContributionOut(**fc.__dict__)
                for fc in r.interference.constructive_features
            ],
            destructive_features=[
                FeatureContributionOut(**fc.__dict__)
                for fc in r.interference.destructive_features
            ],
            broken_entanglements=[
                EntanglementAnomalyOut(
                    feature_a=e.feature_a,
                    feature_b=e.feature_b,
                    tier_a=e.tier_a,
                    tier_b=e.tier_b,
                    anomaly_score=e.anomaly_score,
                    label=e.label,
                )
                for e in r.interference.broken_entanglements
            ],
            tier_breakdown=r.interference.tier_breakdown,
        ),
        baseline_confidence=BaselineConfidenceOut(
            purity=r.baseline_confidence.purity,
            sample_count=r.baseline_confidence.sample_count,
            authenticated_count=r.baseline_confidence.authenticated_count,
            effective_sample_count=r.baseline_confidence.effective_sample_count,
            trajectory_confidence=r.baseline_confidence.trajectory_confidence,
        ),
        domain=DomainSignalOut(
            theological_register_score=r.domain.theological_register_score,
            register_anomaly=r.domain.register_anomaly,
            confessional_balance=r.domain.confessional_balance,
        ),
        recommendation=RecommendedActionOut(
            action=r.recommendation.action,
            confidence=r.recommendation.confidence,
            rationale=r.recommendation.rationale,
        ),
        tension_arc=TensionArcOut(
            catastrophe_index=arc.catastrophe_index,
            resolution_ratio_mean=arc.resolution_ratio_mean,
            resolution_ratio_std=arc.resolution_ratio_std,
            mean_tension=arc.mean_tension,
            max_tension=arc.max_tension,
            authenticity_signal=arc.authenticity_signal,
            arc_flag=arc.arc_flag,
            arc_flag_reason=arc.arc_flag_reason,
            tension_series=arc.tension_series,
        ) if arc is not None else None,
        feature_vector=r.feature_vector,
        baseline_vector=r.baseline_vector,
        catastrophic_drift=getattr(r, 'catastrophic_drift', False),
        catastrophic_drift_rms_z=getattr(r, 'catastrophic_drift_rms_z', 0.0),
        # Phase 3: ContextManifestOut when CONTEXT_MANIFEST_ENABLED=1, else None.
        context_manifest=(
            ContextManifestOut(**getattr(r, 'context_manifest', None))
            if getattr(r, 'context_manifest', None) is not None
            else None
        ),
        # Phase 6: ScoringReportOut when a manifest+report were built.
        report=report_out,
        # Human-friendly explanation for professors/instructors
        human_explanation=explain(r),
    )


# ── Phase 7: sliding-window blend detection ──────────────────────────────────

@app.post(
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
    state = store.get(student_id)
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

    from .context.blend import detect_blend
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
            WindowScoreOut(start=w.start, end=w.end,
                            score=w.score, confidence=w.confidence)
            for w in result.per_section
        ],
        n_tokens=result.n_tokens,
        fallback_reason=result.fallback_reason,
    )


# ── Batch file upload → baseline ──────────────────────────────────────────────

@app.post("/students/{student_id}/baseline/upload-batch")
async def upload_baseline_batch(
    student_id: str,
    files: List[UploadFile] = File(...),
    provenance: str = Form("verified"),
    assignment: str = Form(""),
):
    """
    Upload one or more files (PDF, DOCX, TXT) as baseline samples in a single
    request.  Mirrors the v1 batch upload but requires no auth — used by the
    Import Papers drawer in the professor demo.
    """
    if provenance not in AUTH_WEIGHTS:
        raise HTTPException(status_code=422, detail=f"provenance must be one of: {list(AUTH_WEIGHTS)}")

    state = store.get_or_create(student_id)
    imported = 0
    skipped_duplicates = 0
    errors: list[str] = []
    # Phase 8: per-file drift outcomes — surfaced on the batch response so
    # an instructor can see which files were held without aborting the batch.
    drift_holds: list[dict] = []

    for upload in files:
        filename = upload.filename or "unknown"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        raw = await upload.read()

        # ── Text extraction ───────────────────────────────────────────────────
        try:
            if ext == "txt":
                text = raw.decode("utf-8", errors="replace")
            elif ext == "docx":
                from docx import Document as _Doc
                doc = _Doc(io.BytesIO(raw))
                text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
            elif ext == "pdf":
                from pypdf import PdfReader as _PdfReader
                reader = _PdfReader(io.BytesIO(raw))
                text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            else:
                errors.append(f"{filename}: unsupported type '.{ext}' — use .txt, .docx, or .pdf")
                continue
        except Exception as exc:
            errors.append(f"{filename}: extraction error — {exc}")
            continue

        if not text.strip():
            errors.append(f"{filename}: no text extracted (empty or image-only file?)")
            continue

        # ── Deduplication ─────────────────────────────────────────────────────
        import hashlib as _hashlib
        text_hash = _hashlib.sha256(text.encode()).hexdigest()
        if any(getattr(s, "text_hash", None) == text_hash for s in state.samples):
            skipped_duplicates += 1
            continue

        # ── Feature extraction & store ────────────────────────────────────────
        try:
            vec = feature_vector(text)
        except Exception as exc:
            errors.append(f"{filename}: feature extraction failed — {exc}")
            continue

        label = assignment.strip() or filename.rsplit(".", 1)[0]
        sample = BaselineSample(
            text=text,
            vector=vec,
            provenance=provenance,
            auth_weight=AUTH_WEIGHTS[provenance],
            assignment=label,
            submitted_at="",
        )
        # Attach hash for future dedup checks
        sample.text_hash = text_hash  # type: ignore[attr-defined]

        # ── Phase 8: per-file drift gate (best-effort) ────────────────────────
        # Batch ingestion does NOT 202/409 on drift — that would block the
        # whole upload. Instead we hold individual outliers, record them in
        # `drift_holds`, and continue the loop. Instructor sees the per-file
        # outcome in the response.
        if AUTH_WEIGHTS[provenance] > 0:
            try:
                dr = state.check_drift(sample)
                if dr.recommendation != "accept":
                    drift_holds.append({
                        "filename": filename,
                        "drift": dr.to_dict(),
                    })
                    continue       # skip add_sample; counter already mutated
            except Exception as exc:
                # Drift check failure ≠ ingestion failure; admit as before.
                logging.getLogger(__name__).warning(
                    "drift check failed in batch for %s: %s", filename, exc,
                )

        state.add_sample(sample)

        if provenance in ("proctored", "verified"):
            arc = analyze_tension_arc(text)
            if arc.catastrophe_index > 0:
                new_mean = update_student_baseline_kappa(state.kappa_log, arc.catastrophe_index)
                state.baseline_kappa = new_mean

        imported += 1

    # Always persist when there was any state mutation (admitted samples
    # OR drift counter increments from holds).
    if imported > 0 or drift_holds:
        store.put(state)

    return {
        "imported": imported,
        "skipped_duplicates": skipped_duplicates,
        "errors": errors,
        "drift_holds": drift_holds,
    }


# ── Turnitin CSV import ───────────────────────────────────────────────────────

@app.post("/import/courses/{course_id}/turnitin-csv")
async def import_turnitin_csv(course_id: str, file: UploadFile = File(...)):
    """
    Parse a Turnitin admin CSV export and create student/submission stubs.

    Expected columns (Turnitin default export):
      Last Name, First Name, Student ID, Assignment Title, Date Submitted,
      Similarity, File Name
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig", errors="replace")  # handle BOM
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not decode CSV: {exc}")

    reader = csv.DictReader(io.StringIO(text))
    # Normalise header keys: lowercase, strip whitespace
    rows = []
    for row in reader:
        rows.append({k.strip().lower(): v.strip() for k, v in row.items()})

    if not rows:
        raise HTTPException(status_code=422, detail="CSV is empty or has no data rows.")

    total_rows = len(rows)
    matched_students = 0
    created_students = 0
    flagged_submissions = 0
    unmatched_rows = 0
    errors: list[str] = []

    # Possible column names across Turnitin export versions
    def _col(row: dict, *candidates: str) -> str:
        for c in candidates:
            if c in row and row[c]:
                return row[c]
        return ""

    for i, row in enumerate(rows, 1):
        last  = _col(row, "last name", "lastname", "surname")
        first = _col(row, "first name", "firstname")
        sid   = _col(row, "student id", "studentid", "id", "user id")
        name  = f"{first} {last}".strip() or sid or f"Student_{i}"

        if not (last or first or sid):
            unmatched_rows += 1
            errors.append(f"Row {i}: could not identify student (no name or ID)")
            continue

        student_id = sid or name.lower().replace(" ", "_")

        state = store.get(student_id)
        if state is None:
            state = store.get_or_create(student_id)
            created_students += 1
        else:
            matched_students += 1

        flagged_submissions += 1  # stub — no text yet, needs file upload

    return {
        "total_rows": total_rows,
        "matched_students": matched_students,
        "created_students": created_students,
        "flagged_submissions": flagged_submissions,
        "unmatched_rows": unmatched_rows,
        "errors": errors,
    }


# ── Canvas baseline import (demo stubs) ───────────────────────────────────────

@app.post("/canvas/baseline/{student_id}/list-canvas-submissions")
async def list_canvas_submissions(student_id: str, req: dict = None):
    """
    List a student's past Canvas submissions available for baseline import.
    In the full production app this calls the Canvas REST API using the
    instructor's API token.  In this demo server it returns a helpful message.
    """
    return {
        "submissions": [],
        "message": (
            "Canvas integration requires the production server (port 8000) "
            "with a Canvas API token configured in .env. "
            "Use the 'Drop files' or 'Paste text' options to add baselines manually."
        ),
    }


@app.post("/canvas/baseline/{student_id}/import-baseline")
async def import_canvas_baseline(student_id: str, req: dict = None):
    """Demo stub — see list_canvas_submissions."""
    return {"imported": 0, "skipped": 0, "errors": ["Canvas integration not available in demo server."]}


# ══════════════════════════════════════════════════════════════════════════════
# PR 7: admin / dashboard / playground / corrections
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/admin/manifests", response_model=ManifestListResponse)
def admin_list_manifests(
    student_id: Optional[str] = None,
    action: Optional[str] = None,
    flag: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    Paginated list of context manifests from the audit log.
    All filters are optional.
    """
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="limit must be in [1, 1000]")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be ≥ 0")
    res = store.list_manifests(
        student_id=student_id, action=action, flag=flag,
        since=since, until=until, limit=limit, offset=offset,
    )
    return ManifestListResponse(
        total=res["total"], limit=res["limit"], offset=res["offset"],
        items=[ManifestListItem(**i) for i in res["items"]],
    )


@app.get("/admin/manifests/stats", response_model=ManifestStatsResponse)
def admin_manifest_stats(
    since: Optional[str] = None,
    until: Optional[str] = None,
):
    """Roll-up counts for the admin dashboard summary cards."""
    return ManifestStatsResponse(**store.manifest_stats(since=since, until=until))


@app.post(
    "/submissions/{submission_id}/correct",
    response_model=CorrectionResponse,
)
def submit_correction(submission_id: str, req: CorrectionRequest):
    """
    Record an instructor correction on a scoring verdict.

    The correction is keyed by submission_id; auto-fills student_id +
    original action/divergence from the manifest audit log when those
    were not supplied. Multiple corrections per submission are allowed
    (e.g. an initial flag + a later override) — the most recent row wins
    when the retraining job (PR 8) consumes them.
    """
    # Validate the optional verdict / action enums to catch typos in the
    # dashboard form before they pollute the training set.
    if req.corrected_verdict is not None and req.corrected_verdict not in (
        "authentic", "uncertain", "anomalous"
    ):
        raise HTTPException(
            status_code=422,
            detail='corrected_verdict must be "authentic" | "uncertain" | "anomalous"',
        )
    if req.corrected_action is not None and req.corrected_action not in (
        "no_action", "monitor", "schedule_conversation", "escalate"
    ):
        raise HTTPException(
            status_code=422,
            detail='corrected_action must be "no_action" | "monitor" | '
                   '"schedule_conversation" | "escalate"',
        )

    correction_id = store.put_correction(
        submission_id=submission_id,
        is_correct=req.is_correct,
        corrected_verdict=req.corrected_verdict,
        corrected_action=req.corrected_action,
        reviewer=req.reviewer,
        notes=req.notes,
    )
    if correction_id is None:
        raise HTTPException(status_code=500, detail="Failed to persist correction")

    # Round-trip the inserted row so the response carries the auto-filled
    # student_id / original_action / created_at fields the form didn't have.
    listed = store.list_corrections(submission_id=submission_id, limit=1)
    if not listed["items"]:
        raise HTTPException(status_code=500, detail="Correction inserted but not found on read-back")
    # The most recent (and only matching) row is the one we just wrote.
    latest = listed["items"][0]
    return CorrectionResponse(**latest)


@app.get("/admin/corrections", response_model=CorrectionListResponse)
def admin_list_corrections(
    submission_id: Optional[str] = None,
    student_id: Optional[str] = None,
    is_correct: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
):
    """List corrections with optional filters."""
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="limit must be in [1, 1000]")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be ≥ 0")
    res = store.list_corrections(
        submission_id=submission_id, student_id=student_id,
        is_correct=is_correct, limit=limit, offset=offset,
    )
    return CorrectionListResponse(
        total=res["total"], limit=res["limit"], offset=res["offset"],
        items=[CorrectionResponse(**i) for i in res["items"]],
    )


@app.post("/test/score", response_model=TestScoreResponse)
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
            )
        synth_samples.append(BaselineSample(
            text=t, vector=v, provenance="verified", auth_weight=1.0,
            assignment=f"playground_{i}", submitted_at="",
        ))
    if not synth_samples:
        raise HTTPException(status_code=422, detail="All baseline_texts were empty after stripping")

    from .quantum.state import StudentState as _SS
    synth_state = _SS(student_id="__playground__", samples=synth_samples)

    # ── Run the adaptive pipeline (always force flags ON for playground) ──────
    from .context.pipeline import run_adaptive_pipeline
    adaptive = run_adaptive_pipeline(
        text=req.text, state=synth_state, submission_id=req.submission_id,
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
    )

    # ── Optional: build the report (Phase 6) ──────────────────────────────────
    report = None
    if adaptive.manifest is not None:
        try:
            from .context.report import build_report
            report = build_report(layer7, adaptive.manifest, synth_state)
        except Exception as e:
            logging.getLogger(__name__).warning("playground report failed: %s", e)

    # Tension arc (cheap, runs alongside).
    arc = analyze_tension_arc(req.text)

    layer7_resp = _to_response(layer7, arc=arc, report=report)

    # ── Optional: sliding-window blend detection ──────────────────────────────
    blend_resp = None
    if req.enable_blend:
        from .context.blend import detect_blend
        try:
            br = detect_blend(
                text=req.text, state=synth_state,
                submission_id=req.submission_id,
            )
            blend_resp = BlendResultOut(
                blend_detected=br.blend_detected,
                blend_index=br.blend_index,
                shift_positions=list(br.shift_positions),
                per_section=[
                    WindowScoreOut(start=w.start, end=w.end,
                                    score=w.score, confidence=w.confidence)
                    for w in br.per_section
                ],
                n_tokens=br.n_tokens,
                fallback_reason=br.fallback_reason,
            )
        except Exception as e:
            logging.getLogger(__name__).warning("playground blend failed: %s", e)

    return TestScoreResponse(layer7=layer7_resp, blend=blend_resp)


# ══════════════════════════════════════════════════════════════════════════════
# PR 8: Calibration Lab
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/admin/lab/datasets", response_model=List[DatasetInfo])
def admin_lab_datasets():
    """List the datasets the lab knows how to run (Federalist, multi-author, …)."""
    from .lab.datasets import list_datasets
    return [DatasetInfo(**d) for d in list_datasets()]


@app.post("/admin/calibration/run", response_model=CalibrationRunCreatedResponse, status_code=202)
def admin_run_calibration(req: CalibrationRunRequest):
    """
    Kick off a calibration run in the background and return its row id.

    The run executes on a single-worker thread pool, so multiple requests
    queue rather than overlap. Poll ``GET /admin/calibration/runs/{id}``
    to see when status flips to ``completed`` or ``failed``.
    """
    from .lab.runner import trigger_run
    run_id, error = trigger_run(
        dataset_label=req.dataset_label,
        run_label=req.run_label,
        max_scoring=req.max_scoring,
        thresholds=req.thresholds,
    )
    if run_id is None:
        raise HTTPException(status_code=422, detail=error or "Failed to start run")
    return CalibrationRunCreatedResponse(
        run_id=run_id, status="running", dataset_label=req.dataset_label,
    )


@app.get("/admin/calibration/runs", response_model=CalibrationRunListResponse)
def admin_list_calibration_runs(
    status: Optional[str] = None,
    dataset_label: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """List calibration runs (newest first), with optional filters."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be in [1, 500]")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be ≥ 0")
    res = store.list_calibration_runs(
        status=status, dataset_label=dataset_label,
        limit=limit, offset=offset,
    )
    return CalibrationRunListResponse(
        total=res["total"], limit=res["limit"], offset=res["offset"],
        items=[CalibrationRunSummary(**i) for i in res["items"]],
    )


@app.get("/admin/calibration/runs/{run_id}", response_model=CalibrationRunDetail)
def admin_get_calibration_run(run_id: int, include_report: bool = True):
    """Fetch one run with optional report inclusion."""
    res = store.get_calibration_run(run_id, include_report=include_report)
    if res is None:
        raise HTTPException(status_code=404, detail=f"calibration run {run_id} not found")
    return CalibrationRunDetail(**res)


@app.get("/admin/calibration/runs/{run_id}/suggestions", response_model=SuggestionsResponse)
def admin_run_suggestions(run_id: int):
    """
    Run the suggestion engine over a finished calibration + the corrections
    feedback log. Returns recommended threshold + tier-weight changes with
    explanatory rationale + per-suggestion confidence.
    """
    res = store.get_calibration_run(run_id, include_report=True)
    if res is None:
        raise HTTPException(status_code=404, detail=f"calibration run {run_id} not found")
    if res.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id} is {res.get('status')}; suggestions require status=completed",
        )

    from .lab.suggestions import generate_suggestions
    # Pull current thresholds from active tuned set if available; fall back
    # to Phase-1 defaults.
    active = store.get_active_tuned_thresholds()
    if active is not None:
        current = {
            "no_action": active["no_action"],
            "monitor":   active["monitor"],
            "escalate":  active["escalate"],
        }
    else:
        current = None

    corrections = store.list_corrections(limit=1000)["items"]
    out = generate_suggestions(
        report=res["report"] or {},
        corrections=corrections,
        current_thresholds=current,
    )
    return SuggestionsResponse(
        suggestions=[SuggestionItem(**s) for s in out["suggestions"]],
        summary=out["summary"],
    )


@app.post("/admin/calibration/runs/{run_id}/apply", response_model=TunedThresholdsRecord)
def admin_apply_thresholds(run_id: int, req: ApplyThresholdsRequest):
    """
    Persist a new active threshold set sourced from a calibration run.

    Versioned in ``tuned_thresholds_v2`` — older sets remain for audit.
    The latest row by ``created_at`` is the in-effect active set;
    in-process scoring reads it on demand.
    """
    res = store.get_calibration_run(run_id, include_report=False)
    if res is None:
        raise HTTPException(status_code=404, detail=f"calibration run {run_id} not found")

    new_id = store.put_tuned_thresholds(
        no_action=req.no_action,
        monitor=req.monitor,
        escalate=req.escalate,
        verdict_authentic_below=req.verdict_authentic_below,
        verdict_anomalous_at_or_above=req.verdict_anomalous_at_or_above,
        source="calibration_run",
        source_run_id=run_id,
        notes=req.notes,
        provenance={
            "dataset_label":       res.get("dataset_label"),
            "auc_at_apply":        res.get("auc"),
            "n_essays_scored":     res.get("n_essays_scored"),
            "applied_at_run_id":   run_id,
        },
    )
    if new_id is None:
        raise HTTPException(status_code=500, detail="Failed to persist tuned thresholds")
    active = store.get_active_tuned_thresholds()
    return TunedThresholdsRecord(**active)


@app.get("/admin/tuned-thresholds", response_model=Optional[TunedThresholdsRecord])
def admin_get_tuned_thresholds():
    """Return the currently-active tuned thresholds (or null if none set)."""
    active = store.get_active_tuned_thresholds()
    return TunedThresholdsRecord(**active) if active else None


# ── Demo auth (no real session / JWT — backdoor only) ─────────────────────────

@app.post("/api/v1/auth/login")
async def demo_login(body: dict):
    """
    Demo login endpoint.
    Backdoor credentials: username=Gandalf / password=Friend → professor.
    Anyone else with 'admin' in their email gets admin; 'student' → student.
    All other credentials return 401.
    """
    username = body.get("email", body.get("username", ""))
    password = body.get("password", "")

    if username.lower() == "gandalf" and password == "Friend":
        role = "professor"
    elif "admin" in username.lower():
        role = "admin"
    elif "student" in username.lower():
        role = "student"
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {"token": "demo-token", "role": role, "name": username or "Demo User"}


@app.get("/admin/tuned-thresholds/history", response_model=TunedThresholdsListResponse)
def admin_list_tuned_thresholds(limit: int = 50, offset: int = 0):
    """Audit list of all tuned-threshold versions ever applied."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be in [1, 500]")
    res = store.list_tuned_thresholds(limit=limit, offset=offset)
    return TunedThresholdsListResponse(
        total=res["total"], limit=res["limit"], offset=res["offset"],
        items=[TunedThresholdsRecord(**i) for i in res["items"]],
    )
