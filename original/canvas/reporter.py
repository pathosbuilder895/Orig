"""
canvas/reporter.py — Post integrity reports back to Canvas SpeedGrader.

Implements two report types per the Document Processor / Plagiarism Framework spec:

  Report 1: Authorship Deviation
    - Score:    deviation_score (0–1, lower = more similar to baseline)
    - Colour:   green / amber / red based on ACTION_THRESHOLDS
    - Label:    e.g. "Authorship: 94% consistent" or "Authorship: FLAG"
    - Detail:   Link to Original's full feature-profile page

  Report 2: AI-Writing Signal
    - Score:    AI-marker tier average (from Tier 7 features)
    - Colour:   green / amber / red
    - Label:    e.g. "AI signal: low" / "AI signal: elevated"
    - Detail:   Link to Original's interference analysis page

Both reports are posted to the Canvas Plagiarism Platform originality report
endpoint:
  PUT /api/lti/assignments/{assignment_id}/submissions/{submission_id}/original_score_passback

Canvas reference:
  https://canvas.instructure.com/doc/api/originality_reports.html
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

import httpx

from original.core.config import get_settings
from original.core.logging import get_logger
from original.db.models.canvas import CanvasSubmission

log = get_logger(__name__)

# Colour thresholds (deviation score → SpeedGrader badge colour)
_GREEN_THRESHOLD = 0.40    # Below this → consistent (green)
_AMBER_THRESHOLD = 0.55    # Between green and amber → caution
# Above amber → flagged (red)


async def post_reports_to_canvas(
    record: CanvasSubmission,
    deviation_score: float,
    authorship_probability: float,
    recommended_action: str,
    feature_dict: Dict[str, float],
) -> None:
    """
    Post both integrity reports to Canvas SpeedGrader.

    Silently logs on failure — a failed report post should not crash the
    submission pipeline.
    """
    settings = get_settings()
    access_token = record.access_token or settings.CANVAS_API_TOKEN
    canvas_url = record.canvas_url or settings.CANVAS_BASE_URL

    if not access_token or not canvas_url:
        log.warning("Cannot post Canvas report — no access token or canvas URL configured")
        return

    base_report_url = (
        f"{settings.ORIGINAL_BASE_URL}/original-review.html"
        f"?submission={record.canvas_submission_id}"
    )

    # Build both report payloads
    authorship_report = _build_authorship_report(
        deviation_score=deviation_score,
        authorship_probability=authorship_probability,
        recommended_action=recommended_action,
        report_url=base_report_url + "&view=authorship",
    )

    ai_signal_report = _build_ai_signal_report(
        feature_dict=feature_dict,
        report_url=base_report_url + "&view=ai-signal",
    )

    # Post each report to Canvas
    for report_name, report_payload in [
        ("authorship_deviation", authorship_report),
        ("ai_writing_signal", ai_signal_report),
    ]:
        await _post_report(
            canvas_url=canvas_url,
            access_token=access_token,
            assignment_id=record.canvas_assignment_id,
            submission_id=record.canvas_user_id,
            payload=report_payload,
            report_name=report_name,
        )


def _build_authorship_report(
    deviation_score: float,
    authorship_probability: float,
    recommended_action: str,
    report_url: str,
) -> Dict[str, Any]:
    """Build the authorship deviation report payload for Canvas."""
    # Map action to colour indicator
    colour = _deviation_to_colour(deviation_score)
    consistency_pct = round(authorship_probability * 100)

    if deviation_score < _GREEN_THRESHOLD:
        label = f"Authorship: {consistency_pct}% consistent"
    elif deviation_score < _AMBER_THRESHOLD:
        label = f"Authorship: monitor ({consistency_pct}%)"
    else:
        label = f"Authorship: FLAG ({consistency_pct}%)"

    return {
        "originality_report": {
            "score": round(deviation_score * 100),   # Canvas expects 0–100
            "report_url": report_url,
            "tool_setting": {
                "tool_name": "Original — Authorship Deviation",
                "description": label,
                "resource_url": report_url,
            },
        }
    }


def _build_ai_signal_report(
    feature_dict: Dict[str, float],
    report_url: str,
) -> Dict[str, Any]:
    """
    Build the AI-writing signal report payload.

    Derives the AI signal from Tier 7 feature averages:
    - High burstiness → human-like (good)
    - High transition_predictability → AI-like (bad)
    - Low perplexity_proxy → AI-like (bad)
    """
    ai_features = {
        "burstiness": feature_dict.get("burstiness", 0.5),
        "perplexity_proxy": feature_dict.get("perplexity_proxy", 0.5),
        "transition_predictability": feature_dict.get("transition_predictability", 0.5),
        "vocabulary_introduction_rate": feature_dict.get("vocabulary_introduction_rate", 0.5),
        "repetition_gap_entropy": feature_dict.get("repetition_gap_entropy", 0.5),
        "filler_hedge_cluster_rate": feature_dict.get("filler_hedge_cluster_rate", 0.5),
    }

    # Invert features where higher = more human (not AI)
    # High burstiness and perplexity = human; high transition_predictability = AI
    human_signals = (
        ai_features["burstiness"]
        + ai_features["perplexity_proxy"]
        + ai_features["repetition_gap_entropy"]
        + (1 - ai_features["transition_predictability"])   # inverted
        + ai_features["vocabulary_introduction_rate"]
    ) / 5.0

    ai_score = 1.0 - human_signals  # higher = more AI-like

    if ai_score < 0.35:
        label = "AI signal: low"
    elif ai_score < 0.60:
        label = "AI signal: moderate"
    else:
        label = "AI signal: elevated — review recommended"

    return {
        "originality_report": {
            "score": round(ai_score * 100),
            "report_url": report_url,
            "tool_setting": {
                "tool_name": "Original — AI Writing Signal",
                "description": label,
                "resource_url": report_url,
            },
        }
    }


async def _post_report(
    canvas_url: str,
    access_token: str,
    assignment_id: str,
    submission_id: str,
    payload: Dict,
    report_name: str,
) -> None:
    """POST a single report to the Canvas originality report endpoint."""
    url = (
        f"{canvas_url}/api/lti/assignments/{assignment_id}"
        f"/submissions/{submission_id}/original_score_passback"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.put(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            log.info(
                "Canvas report posted",
                extra={
                    "report": report_name,
                    "assignment_id": assignment_id,
                    "status": resp.status_code,
                },
            )
    except httpx.HTTPStatusError as exc:
        log.error(
            "Canvas report post failed (HTTP error)",
            extra={"report": report_name, "status": exc.response.status_code, "url": url},
        )
    except Exception as exc:
        log.error(
            "Canvas report post failed",
            extra={"report": report_name, "error": str(exc), "url": url},
        )


async def post_speedgrader_comment(
    record: CanvasSubmission,
    deviation_score: float,
    authorship_probability: float,
    recommended_action: str,
    top_destructive: list[dict] | None = None,
) -> None:
    """
    Post a human-readable comment to Canvas SpeedGrader summarising the scoring result.

    This gives instructors a quick summary without leaving Canvas.
    """
    settings = get_settings()
    access_token = record.access_token or settings.CANVAS_API_TOKEN
    canvas_url = record.canvas_url or settings.CANVAS_BASE_URL

    if not access_token or not canvas_url:
        return

    # Build comment text
    consistency_pct = round(authorship_probability * 100)
    deviation_pct = round(deviation_score * 100)

    action_labels = {
        "no_action": "No concerns",
        "monitor": "Monitor — minor deviation",
        "schedule_conversation": "Recommend conversation with student",
        "escalate": "Significant deviation — review recommended",
    }
    action_label = action_labels.get(recommended_action, recommended_action)

    lines = [
        f"Original Authorship Report",
        f"Consistency: {consistency_pct}% | Deviation: {deviation_pct}%",
        f"Recommendation: {action_label}",
    ]

    if top_destructive:
        feature_names = [f["code"].replace("_", " ").title() for f in top_destructive[:3]]
        lines.append(f"Top deviating features: {', '.join(feature_names)}")

    lines.append(f"Full report: {settings.ORIGINAL_BASE_URL}/original-review.html?submission={record.canvas_submission_id}")
    comment_text = "\n".join(lines)

    # Post to Canvas
    url = (
        f"{canvas_url}/api/v1/courses/{record.canvas_course_id}"
        f"/assignments/{record.canvas_assignment_id}"
        f"/submissions/{record.canvas_user_id}"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.put(
                url,
                json={"comment": {"text_comment": comment_text}},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            log.info(
                "SpeedGrader comment posted",
                extra={
                    "assignment_id": record.canvas_assignment_id,
                    "user_id": record.canvas_user_id,
                },
            )
    except Exception as exc:
        log.error(
            "SpeedGrader comment failed",
            extra={"error": str(exc)},
        )


def _deviation_to_colour(deviation_score: float) -> str:
    if deviation_score < _GREEN_THRESHOLD:
        return "green"
    elif deviation_score < _AMBER_THRESHOLD:
        return "amber"
    return "red"
