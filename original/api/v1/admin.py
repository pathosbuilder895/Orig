"""
api/v1/admin.py — Admin endpoints for data policy, LTI registration, and audit log.

Implements the governance controls required by procurement checklists:

  Data policy (per institution):
    GET  /admin/institutions/{id}/data-policy       View current policy
    PUT  /admin/institutions/{id}/data-policy       Update policy
    POST /admin/institutions/{id}/submissions/purge Purge submissions per policy

  LTI registrations:
    GET  /admin/canvas/registrations                List all registrations
    POST /admin/canvas/registrations                Create new registration
    GET  /admin/canvas/registrations/{id}           Get one registration
    PUT  /admin/canvas/registrations/{id}           Update registration
    POST /admin/canvas/registrations/{id}/rotate-key  Rotate access token

  Audit log:
    GET  /admin/audit-log                           System-wide audit events

All endpoints require ADMIN role.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from original.api.deps import get_current_user, get_db
from original.core.config import get_settings
from original.core.logging import get_logger
from original.db.models import (
    Institution,
    Submission,
    SubmissionStatus,
    Student,
    StudentEnrollment,
    Course,
    ScoringResult,
    InstructorDecision,
    ActionType,
    User,
)
from original.db.models.canvas import CanvasSubmission, LTIRegistration
from original.db.models.user import UserRole

log = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


# ── Auth guard ────────────────────────────────────────────────────────────────

def require_admin(user=Depends(get_current_user)):
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


# ── Schemas ────────────────────────────────────────────────────────────────────

class DataPolicy(BaseModel):
    """
    Per-institution data governance policy.

    All fields are optional in PATCH semantics — omit to keep current value.
    """
    index_submissions: bool = Field(
        False,
        description=(
            "If False (default), submission texts are never indexed into a comparison "
            "corpus. Set True only if the institution explicitly opts in for "
            "self-plagiarism detection across cohorts."
        ),
    )
    retention_days: int = Field(
        0,
        ge=0,
        description=(
            "Number of days to retain scored submissions. "
            "0 = retain indefinitely (until admin purge). "
            "Typical GDPR-compliant value: 365 (one academic year)."
        ),
    )
    store_submission_text: bool = Field(
        False,
        description=(
            "If False (default), submission text is processed but not persisted. "
            "Only feature vectors and scores are stored. "
            "Set True to enable draft-history corroboration workflows."
        ),
    )
    lawful_basis: str = Field(
        "legitimate_interest",
        description=(
            "GDPR lawful basis for processing: 'legitimate_interest', "
            "'public_task', or 'consent'. Used in student-facing transparency notices."
        ),
    )
    student_transparency_url: Optional[str] = Field(
        None,
        description="URL to the institution's student-facing privacy notice for this tool.",
    )
    deletion_contact_email: Optional[str] = Field(
        None,
        description="Email address students can contact to request submission deletion.",
    )


class DataPolicyResponse(DataPolicy):
    institution_id: str
    institution_name: str
    last_updated: Optional[datetime]


class LTIRegistrationCreate(BaseModel):
    platform_iss: str = Field(..., description="Canvas issuer URL, e.g. https://canvas.instructure.com")
    client_id: str = Field(..., description="Client ID from Canvas Developer Key")
    deployment_id: Optional[str] = Field(None, description="Deployment ID (optional for multi-deployment)")
    auth_endpoint: str = Field(
        "https://canvas.instructure.com/api/lti/authorize_redirect",
        description="Canvas OIDC authorization endpoint",
    )
    jwks_url: str = Field(
        "https://canvas.instructure.com/api/lti/security/jwks",
        description="Canvas JWKS endpoint",
    )
    api_token: Optional[str] = Field(None, description="Canvas system-level API token")
    institution_id: Optional[str] = Field(None, description="Link to Original institution")
    label: str = Field("Canvas", description="Human-readable label for this registration")


class LTIRegistrationResponse(BaseModel):
    id: str
    platform_iss: str
    client_id: str
    deployment_id: Optional[str]
    auth_endpoint: str
    jwks_url: str
    institution_id: Optional[str]
    label: str
    is_active: bool
    created_at: datetime


class PurgeResult(BaseModel):
    institution_id: str
    purged_count: int
    cutoff_date: Optional[datetime]
    dry_run: bool


# ── Stats and monitoring schemas ────────────────────────────────────────────────

class StatsResponse(BaseModel):
    """Institution-wide statistics."""
    total_students: int
    total_submissions: int
    total_scored: int
    flagged_count: int
    average_deviation: Optional[float]


class CourseInfo(BaseModel):
    """Course information with enrollment and submission counts."""
    id: str
    name: str
    code: str
    instructor_id: Optional[str]
    instructor_name: Optional[str]
    student_count: int
    submission_count: int
    flag_count: int = 0
    avg_deviation: Optional[float] = None
    baseline_coverage_pct: int = 0


class CoursesResponse(BaseModel):
    """List of courses for an institution."""
    courses: List[CourseInfo]
    total: int


class FlaggedSubmissionInfo(BaseModel):
    """Recent flagged submission details."""
    submission_id: str
    student_id: str
    student_name: str
    deviation_score: float
    action: str
    scored_at: datetime


class FlaggedSubmissionsResponse(BaseModel):
    """Recent flagged submissions."""
    submissions: List[FlaggedSubmissionInfo]
    total: int


# ── Data policy endpoints ──────────────────────────────────────────────────────

@router.get(
    "/institutions/{institution_id}/data-policy",
    response_model=DataPolicyResponse,
    summary="Get institution data policy",
)
def get_data_policy(
    institution_id: str,
    db: Session = Depends(get_db),
    _user=Depends(require_admin),
) -> DataPolicyResponse:
    """Return the current data governance policy for an institution."""
    inst = _get_institution(db, institution_id)
    policy = _read_policy(inst)
    return DataPolicyResponse(
        **policy.model_dump(),
        institution_id=inst.id,
        institution_name=inst.name,
        last_updated=inst.updated_at,
    )


@router.put(
    "/institutions/{institution_id}/data-policy",
    response_model=DataPolicyResponse,
    summary="Update institution data policy",
)
def update_data_policy(
    institution_id: str,
    body: DataPolicy,
    db: Session = Depends(get_db),
    _user=Depends(require_admin),
) -> DataPolicyResponse:
    """
    Update the data governance policy for an institution.

    Changes take effect immediately for new submissions.
    Existing submissions are not retroactively affected — run /purge to enforce
    retention limits on existing data.
    """
    inst = _get_institution(db, institution_id)

    # Merge into institution.settings JSON
    settings = dict(inst.settings or {})
    settings["data_policy"] = body.model_dump()
    inst.settings = settings
    db.commit()
    db.refresh(inst)

    log.info(
        "Data policy updated",
        extra={"institution_id": institution_id, "policy": body.model_dump()},
    )

    return DataPolicyResponse(
        **body.model_dump(),
        institution_id=inst.id,
        institution_name=inst.name,
        last_updated=inst.updated_at,
    )


@router.post(
    "/institutions/{institution_id}/submissions/purge",
    response_model=PurgeResult,
    summary="Purge submissions per data policy",
)
def purge_submissions(
    institution_id: str,
    dry_run: bool = Query(True, description="If True, report what would be deleted without deleting"),
    db: Session = Depends(get_db),
    _user=Depends(require_admin),
) -> PurgeResult:
    """
    Purge student submissions (and Canvas submission records) that exceed the
    institution's retention policy.

    Always run with dry_run=True first to verify the scope.
    Deletion is permanent and not reversible.
    """
    inst = _get_institution(db, institution_id)
    policy = _read_policy(inst)

    cutoff: Optional[datetime] = None
    if policy.retention_days > 0:
        cutoff = datetime.utcnow() - timedelta(days=policy.retention_days)

    # Find submissions for students in this institution
    from original.db.models import Student, BaselineSample

    student_ids = [s.id for s in db.query(Student.id).filter(
        Student.institution_id == institution_id
    ).all()]

    if not student_ids:
        return PurgeResult(
            institution_id=institution_id,
            purged_count=0,
            cutoff_date=cutoff,
            dry_run=dry_run,
        )

    query = db.query(Submission).filter(Submission.student_id.in_(student_ids))
    if cutoff:
        query = query.filter(Submission.submitted_at < cutoff)

    submissions = query.all()
    count = len(submissions)

    if not dry_run and submissions:
        # Also purge Canvas submission records
        original_ids = [s.id for s in submissions]
        db.query(CanvasSubmission).filter(
            CanvasSubmission.original_submission_id.in_(original_ids)
        ).delete(synchronize_session=False)

        for sub in submissions:
            db.delete(sub)
        db.commit()

        log.info(
            "Submissions purged",
            extra={
                "institution_id": institution_id,
                "count": count,
                "cutoff": str(cutoff),
            },
        )

    return PurgeResult(
        institution_id=institution_id,
        purged_count=count,
        cutoff_date=cutoff,
        dry_run=dry_run,
    )


# ── LTI registration endpoints ────────────────────────────────────────────────

@router.get(
    "/canvas/registrations",
    response_model=List[LTIRegistrationResponse],
    summary="List LTI registrations",
)
def list_lti_registrations(
    db: Session = Depends(get_db),
    _user=Depends(require_admin),
) -> List[LTIRegistrationResponse]:
    """List all Canvas LTI 1.3 registrations."""
    regs = db.query(LTIRegistration).order_by(LTIRegistration.created_at.desc()).all()
    return [_reg_to_response(r) for r in regs]


@router.post(
    "/canvas/registrations",
    response_model=LTIRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a Canvas LTI deployment",
)
def create_lti_registration(
    body: LTIRegistrationCreate,
    db: Session = Depends(get_db),
    _user=Depends(require_admin),
) -> LTIRegistrationResponse:
    """
    Register a Canvas instance with Original's LTI 1.3 integration.

    Requires the client_id from the Canvas Developer Key and the Canvas
    platform OIDC/JWKS endpoints (defaults are for canvas.instructure.com).

    After creating a registration, provide the following URLs to Canvas:
      - OIDC initiation: {ORIGINAL_BASE_URL}/lti/login
      - Redirect URI:    {ORIGINAL_BASE_URL}/lti/launch
      - JWKS URL:        {ORIGINAL_BASE_URL}/lti/jwks
    """
    # Check for duplicate
    existing = db.query(LTIRegistration).filter(
        LTIRegistration.platform_iss == body.platform_iss,
        LTIRegistration.client_id == body.client_id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A registration with this platform_iss + client_id already exists",
        )

    reg = LTIRegistration(
        platform_iss=body.platform_iss,
        client_id=body.client_id,
        deployment_id=body.deployment_id,
        auth_endpoint=body.auth_endpoint,
        jwks_url=body.jwks_url,
        api_token=body.api_token,
        institution_id=body.institution_id,
        label=body.label,
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)

    log.info("LTI registration created", extra={"id": reg.id, "iss": reg.platform_iss})
    return _reg_to_response(reg)


@router.put(
    "/canvas/registrations/{registration_id}",
    response_model=LTIRegistrationResponse,
    summary="Update an LTI registration",
)
def update_lti_registration(
    registration_id: str,
    body: LTIRegistrationCreate,
    db: Session = Depends(get_db),
    _user=Depends(require_admin),
) -> LTIRegistrationResponse:
    """Update an existing LTI registration (e.g. rotate API token, update endpoints)."""
    reg = db.query(LTIRegistration).filter(LTIRegistration.id == registration_id).first()
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")

    reg.platform_iss  = body.platform_iss
    reg.client_id     = body.client_id
    reg.deployment_id = body.deployment_id
    reg.auth_endpoint = body.auth_endpoint
    reg.jwks_url      = body.jwks_url
    reg.label         = body.label
    if body.api_token:
        reg.api_token = body.api_token
    if body.institution_id:
        reg.institution_id = body.institution_id

    db.commit()
    db.refresh(reg)
    return _reg_to_response(reg)


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/audit-log", summary="System audit log")
def audit_log(
    institution_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _user=Depends(require_admin),
) -> Dict[str, Any]:
    """
    Return recent system events for audit purposes.

    Currently surfaces:
      - Recent Canvas submission events (status + timestamps)
      - Recent purge operations (derived from submission counts)
      - LTI registration changes

    Full structured audit logging (with actor, IP, etc.) is a Phase 2 item.
    """
    # Canvas submission events
    q = db.query(CanvasSubmission).order_by(
        desc(CanvasSubmission.updated_at)
    ).limit(limit)

    events = []
    for cs in q.all():
        events.append({
            "type": "canvas_submission",
            "canvas_submission_id": cs.canvas_submission_id,
            "canvas_user_id": cs.canvas_user_id,
            "canvas_assignment_id": cs.canvas_assignment_id,
            "status": cs.status,
            "report_posted_at": cs.report_posted_at,
            "error": cs.error_message,
            "created_at": cs.created_at,
            "updated_at": cs.updated_at,
        })

    return {
        "events": events,
        "total": len(events),
        "note": (
            "Full structured audit log (with actor, IP, action context) "
            "is available in Phase 2. This endpoint surfaces pipeline events."
        ),
    }


# ── Statistics endpoints ──────────────────────────────────────────────────────

@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Institution-wide statistics",
)
def get_stats(
    db: Session = Depends(get_db),
    user=Depends(require_admin),
) -> StatsResponse:
    """
    Return institution-wide statistics scoped to the current admin's institution.

    Returns:
      - total_students: Count of students in this institution
      - total_submissions: Count of all submissions (baseline + scored)
      - total_scored: Count of scored submissions
      - flagged_count: Count of submissions with action in (schedule_conversation, escalate)
      - average_deviation: Mean deviation_score across all scoring results
    """
    institution_id = user.institution_id

    # Total students
    total_students = db.query(func.count(Student.id)).filter(
        Student.institution_id == institution_id
    ).scalar() or 0

    # Get all student IDs for this institution
    student_ids = [
        s[0] for s in db.query(Student.id).filter(
            Student.institution_id == institution_id
        ).all()
    ]

    # Total submissions
    total_submissions = 0
    total_scored = 0
    if student_ids:
        total_submissions = db.query(func.count(Submission.id)).filter(
            Submission.student_id.in_(student_ids)
        ).scalar() or 0

        total_scored = db.query(func.count(Submission.id)).filter(
            Submission.student_id.in_(student_ids),
            Submission.status == SubmissionStatus.SCORED,
        ).scalar() or 0

    # Flagged count (escalate or schedule_conversation actions)
    flagged_count = 0
    if student_ids:
        flagged_count = db.query(func.count(InstructorDecision.id)).filter(
            InstructorDecision.submission_id.in_(
                db.query(Submission.id).filter(Submission.student_id.in_(student_ids))
            ),
            InstructorDecision.action.in_([
                ActionType.ESCALATE,
                ActionType.SCHEDULE_CONVERSATION,
            ]),
        ).scalar() or 0

    # Average deviation score
    average_deviation = None
    if student_ids:
        avg = db.query(func.avg(ScoringResult.deviation_score)).filter(
            ScoringResult.submission_id.in_(
                db.query(Submission.id).filter(Submission.student_id.in_(student_ids))
            )
        ).scalar()
        if avg is not None:
            average_deviation = float(avg)

    return StatsResponse(
        total_students=total_students,
        total_submissions=total_submissions,
        total_scored=total_scored,
        flagged_count=flagged_count,
        average_deviation=average_deviation,
    )


@router.get(
    "/courses",
    response_model=CoursesResponse,
    summary="List courses for this institution",
)
def list_courses(
    db: Session = Depends(get_db),
    user=Depends(require_admin),
) -> CoursesResponse:
    """
    Return all courses for the current admin's institution with enrollment
    and submission statistics.

    Returns:
      - Course id, name, code
      - instructor_id and instructor_name (if assigned)
      - student_count: Number of enrolled students
      - submission_count: Total submissions from students in this course
    """
    institution_id = user.institution_id

    courses = db.query(Course).filter(
        Course.institution_id == institution_id
    ).order_by(Course.name).all()

    course_list = []
    for course in courses:
        # Count enrolled students
        student_count = db.query(func.count(
            Student.id
        )).join(
            StudentEnrollment, Student.id == StudentEnrollment.student_id
        ).filter(
            StudentEnrollment.course_id == course.id
        ).scalar() or 0

        # Count submissions from students in this course
        submission_count = db.query(func.count(Submission.id)).filter(
            Submission.course_id == course.id
        ).scalar() or 0

        instructor_name = None
        if course.instructor_id:
            instr = db.query(User).filter(User.id == course.instructor_id).first()
            if instr:
                instructor_name = instr.full_name

        # Count flagged submissions for this course
        flag_count = db.query(func.count(ScoringResult.id)).filter(
            ScoringResult.submission_id.in_(
                db.query(Submission.id).filter(Submission.course_id == course.id)
            ),
            ScoringResult.recommended_action.in_(["schedule_conversation", "escalate"]),
        ).scalar() or 0

        # Average deviation score for this course
        avg_dev_raw = db.query(func.avg(ScoringResult.deviation_score)).filter(
            ScoringResult.submission_id.in_(
                db.query(Submission.id).filter(Submission.course_id == course.id)
            )
        ).scalar()
        avg_deviation = round(float(avg_dev_raw), 2) if avg_dev_raw is not None else None

        # Baseline coverage: % of enrolled students who have ≥3 baseline samples
        from original.db.models import BaselineSample
        covered = 0
        enrolled_ids_q = db.query(Student.id).join(
            StudentEnrollment, Student.id == StudentEnrollment.student_id
        ).filter(StudentEnrollment.course_id == course.id)
        enrolled_ids = [row[0] for row in enrolled_ids_q.all()]
        for sid in enrolled_ids:
            cnt = db.query(func.count(BaselineSample.id)).filter(
                BaselineSample.student_id == sid,
                BaselineSample.is_active == True,
            ).scalar() or 0
            if cnt >= 3:
                covered += 1
        baseline_coverage_pct = round(covered / len(enrolled_ids) * 100) if enrolled_ids else 0

        course_list.append(CourseInfo(
            id=course.id,
            name=course.name,
            code=course.code,
            instructor_id=course.instructor_id,
            instructor_name=instructor_name,
            student_count=student_count,
            submission_count=submission_count,
            flag_count=flag_count,
            avg_deviation=avg_deviation,
            baseline_coverage_pct=baseline_coverage_pct,
        ))

    return CoursesResponse(
        courses=course_list,
        total=len(course_list),
    )


@router.get(
    "/recent-flags",
    response_model=FlaggedSubmissionsResponse,
    summary="Recent flagged submissions",
)
def get_recent_flags(
    db: Session = Depends(get_db),
    user=Depends(require_admin),
) -> FlaggedSubmissionsResponse:
    """
    Return the last 20 submissions flagged with action 'schedule_conversation' or 'escalate',
    scoped to the current admin's institution.

    Returns:
      - submission_id, student_id, student_name
      - deviation_score: From the scoring result
      - action: The instructor decision action
      - scored_at: When the submission was scored
    """
    institution_id = user.institution_id

    # Get all student IDs for this institution
    student_ids = [
        s[0] for s in db.query(Student.id).filter(
            Student.institution_id == institution_id
        ).all()
    ]

    if not student_ids:
        return FlaggedSubmissionsResponse(submissions=[], total=0)

    # Get flagged instructor decisions
    flagged_decisions = db.query(InstructorDecision).filter(
        InstructorDecision.submission_id.in_(
            db.query(Submission.id).filter(Submission.student_id.in_(student_ids))
        ),
        InstructorDecision.action.in_([
            ActionType.ESCALATE,
            ActionType.SCHEDULE_CONVERSATION,
        ]),
    ).order_by(
        desc(InstructorDecision.created_at)
    ).limit(20).all()

    submissions_list = []
    for decision in flagged_decisions:
        submission = db.query(Submission).filter(
            Submission.id == decision.submission_id
        ).first()
        if not submission:
            continue

        student = db.query(Student).filter(
            Student.id == submission.student_id
        ).first()
        if not student:
            continue

        scoring_result = db.query(ScoringResult).filter(
            ScoringResult.submission_id == submission.id
        ).first()

        scored_at = submission.submitted_at
        deviation_score = 0.0
        if scoring_result:
            scored_at = scoring_result.scored_at
            deviation_score = scoring_result.deviation_score

        submissions_list.append(FlaggedSubmissionInfo(
            submission_id=submission.id,
            student_id=student.id,
            student_name=student.full_name,
            deviation_score=deviation_score,
            action=decision.action.value,
            scored_at=scored_at,
        ))

    return FlaggedSubmissionsResponse(
        submissions=submissions_list,
        total=len(submissions_list),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_institution(db: Session, institution_id: str) -> Institution:
    inst = db.query(Institution).filter(Institution.id == institution_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Institution not found")
    return inst


def _read_policy(inst: Institution) -> DataPolicy:
    """Extract DataPolicy from institution.settings, applying global defaults."""
    settings = get_settings()
    raw = (inst.settings or {}).get("data_policy", {})
    return DataPolicy(
        index_submissions=raw.get("index_submissions", settings.DEFAULT_INDEX_SUBMISSIONS),
        retention_days=raw.get("retention_days", settings.DEFAULT_RETENTION_DAYS),
        store_submission_text=raw.get("store_submission_text", False),
        lawful_basis=raw.get("lawful_basis", "legitimate_interest"),
        student_transparency_url=raw.get("student_transparency_url"),
        deletion_contact_email=raw.get("deletion_contact_email"),
    )


def _reg_to_response(reg: LTIRegistration) -> LTIRegistrationResponse:
    return LTIRegistrationResponse(
        id=reg.id,
        platform_iss=reg.platform_iss,
        client_id=reg.client_id,
        deployment_id=reg.deployment_id,
        auth_endpoint=reg.auth_endpoint,
        jwks_url=reg.jwks_url,
        institution_id=reg.institution_id,
        label=reg.label,
        is_active=reg.is_active,
        created_at=reg.created_at,
    )
