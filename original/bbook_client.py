"""
bbook_client.py — outbound HTTP client to a Bbook deployment.

Bbook is a separate Next.js app that runs a lockdown proctored exam
environment. Original calls Bbook to provision one-off proctored baseline
sittings ("Original-first" flow): the professor clicks a button on
professor.html → Original POSTs here → Bbook creates a magic-link exam →
the student takes it → Bbook pushes the result back to Original via the
existing /students/{id}/baseline endpoint.

This module is OPTIONAL. If BBOOK_API_URL is unset the integration is
disabled — callers should check is_enabled() before invoking.

Configuration (env vars):
    BBOOK_API_URL            base URL of the Bbook deployment, e.g. http://localhost:3000
    BBOOK_EXTERNAL_SECRET    long random string — must match Bbook's EXTERNAL_BASELINE_SECRET

See architecture doc: ~/.claude/plans/refactored-napping-bee.md
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

import httpx
from pydantic import BaseModel

log = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 10.0


class BaselineRequestResult(BaseModel):
    """Response shape returned by Bbook's POST /api/external/baseline-request."""

    externalRequestId: str
    examId: str
    status: str  # "pending" | "completed" | "expired"
    expiresAt: Optional[str] = None
    emailDelivered: bool = False
    magicLink: Optional[str] = None  # only included when email delivery failed/disabled
    idempotent: bool = False


class BaselineRequestStatus(BaseModel):
    """Response shape returned by GET /api/external/baseline-request/{id}."""

    externalRequestId: str
    examId: str
    status: str
    intendedForEmail: str
    examTitle: str
    expiresAt: Optional[str] = None
    consumedAt: Optional[str] = None
    submission: Optional[dict] = None


def is_enabled() -> bool:
    """True iff the Bbook integration is configured."""
    return bool(os.getenv("BBOOK_API_URL"))


def _headers() -> dict:
    secret = os.getenv("BBOOK_EXTERNAL_SECRET", "")
    if not secret:
        raise RuntimeError(
            "BBOOK_EXTERNAL_SECRET is unset — cannot authenticate to Bbook"
        )
    return {
        "Content-Type": "application/json",
        "x-external-secret": secret,
    }


def request_baseline(
    *,
    student_email: str,
    student_name: str,
    exam_title: str = "Proctored Baseline Sitting",
    institution_name: Optional[str] = None,
    requested_by: Optional[str] = None,
    duration_mins: int = 45,
    min_word_count: Optional[int] = None,
    max_word_count: Optional[int] = None,
    prompt_text: Optional[str] = None,
    external_request_id: Optional[str] = None,
) -> BaselineRequestResult:
    """
    Provision a magic-link proctored baseline exam in Bbook.

    Args:
        student_email:        the student who should take the exam (canonical email).
        student_name:         display name (used in the email + welcome card).
        exam_title:           shown to the student.
        institution_name:     groups exams within a single Bbook institution.
        requested_by:         free-form identifier of the requester for audit (e.g. professor email).
        duration_mins:        exam window in minutes (Bbook clamps to [5, 480]).
        min_word_count/max:   optional bounds enforced by Bbook's exam page.
        prompt_text:          essay prompt; Bbook substitutes a sensible default if omitted.
        external_request_id:  idempotency key. Defaults to a fresh UUID. Reuse the same value
                              to make a retry deterministic instead of creating duplicates.

    Returns:
        BaselineRequestResult with the exam id, status, expiry, and (when email
        delivery failed or SMTP is unconfigured) the raw magic link so the
        caller can present it to the professor for manual delivery.

    Raises:
        RuntimeError if BBOOK_API_URL or BBOOK_EXTERNAL_SECRET is unset.
        httpx.HTTPError on network or 4xx/5xx.
    """
    base = os.getenv("BBOOK_API_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("BBOOK_API_URL is unset — Bbook integration is disabled")

    payload = {
        "externalRequestId": external_request_id or str(uuid.uuid4()),
        "studentEmail":      student_email,
        "studentName":       student_name,
        "examTitle":         exam_title,
        "durationMins":      duration_mins,
    }
    if institution_name is not None:
        payload["institutionName"] = institution_name
    if requested_by is not None:
        payload["requestedBy"] = requested_by
    if min_word_count is not None:
        payload["minWordCount"] = min_word_count
    if max_word_count is not None:
        payload["maxWordCount"] = max_word_count
    if prompt_text is not None:
        payload["promptText"] = prompt_text

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        resp = client.post(
            f"{base}/api/external/baseline-request",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        return BaselineRequestResult.model_validate(resp.json())


def fetch_status(external_request_id: str) -> Optional[BaselineRequestStatus]:
    """
    Poll Bbook for the current state of a previously-issued request.

    Returns:
        BaselineRequestStatus on success.
        None if Bbook returned 404 (no such request).

    Raises:
        RuntimeError if config is missing.
        httpx.HTTPError on 5xx or network failure.
    """
    base = os.getenv("BBOOK_API_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("BBOOK_API_URL is unset")
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        resp = client.get(
            f"{base}/api/external/baseline-request/{external_request_id}",
            headers=_headers(),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return BaselineRequestStatus.model_validate(resp.json())
