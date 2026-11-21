"""A past paper's parts, and the teacher's own choice of them (staff only).

``GET /students/{id}/samples/{index}/parts``: the parts of one past paper the
rules found (``paper_profile.paper_parts``): title page, abstract, list of
sources, notes, an appendix, and the "possible" parts the rules were unsure
of and measured, each with what happens to it. It also says whether this
student's scores use the splitter's measurement yet (every past paper must
carry it), and why not when they do not.

``PUT /students/{id}/samples/{index}/parts``: the teacher's choice for that
paper (``exclude_ranges`` set aside, ``include_ranges`` measured, whatever the
rules say). It is stored with the paper (``BaselineSample.part_overrides``,
with the digest of the paper's text). For each splitter measurement the paper
already carries, its measurement made with the choice is stored beside the
rules' own (served only with both switches on). No measurement is created,
and neither the default ``vector`` nor ``extra_vectors`` is ever changed.

``DELETE`` (or a PUT with empty lists) goes back to the rules, restoring
exactly the state before the choice. Setting a
choice needs ``MATTER_SPLITTER_ENABLED`` and ``PAPER_PROFILE_ENABLED`` both on
(409 otherwise); going back to the rules is allowed whatever the switches
say. With either switch off a stored choice has no effect anywhere.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .. import measurement as _measurement
from ..features import feature_flags as _ff
from ..features import part_overrides as _po
from ..features.pipeline import feature_vector
from ..schemas import PartChoiceRequest
from ._shared import _persist_or_503, _repo, _require_staff

router = APIRouter()
log = logging.getLogger(__name__)

#: The splitter measurement a choice is stored under (ADR-014 ids).
SPLITTER_MEASUREMENT = "matter"


def _sample_or_404(student_id: str, index: int):
    state = _repo().get(student_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' not found")
    if index < 0 or index >= len(state.samples):
        raise HTTPException(
            status_code=404,
            detail=f"Sample index {index} out of range (student has {len(state.samples)} samples)",
        )
    return state, state.samples[index]


def _in_use(state) -> dict[str, Any]:
    """Whether this student's scores use the splitter's measurement now."""
    plan = _measurement.plan_for(state)
    if _ff.MEASUREMENTS[plan.used][1]:
        return {"measurement_in_use": True}
    missing = plan.papers - plan.papers_measured
    return {
        "measurement_in_use": False,
        "measurement_note": (
            f"Scores for this student do not use these parts yet: {missing} of {plan.papers} "
            "past papers are not measured with the splitter, so scores use the default "
            "measurement for every paper."
        ),
    }


def _parts_body(state, index: int, sample) -> dict[str, Any]:
    from ..paper_profile import paper_parts

    choice = _po.of_sample(sample)
    with _ff.measuring(SPLITTER_MEASUREMENT):  # the measurement the parts belong to
        parts = paper_parts(_po.text_of(sample))
    doc = choice.to_doc() if choice is not None else {"exclude_ranges": [], "include_ranges": []}
    measured = bool(_splitter_keys(sample))
    body = {
        "enabled": True,
        "index": index,
        "words": len((sample.text or "").split()),
        "parts": parts,
        **doc,
        "paper_measured": measured,
        **_in_use(state),
    }
    if not measured:
        body["paper_note"] = (
            "This paper is not measured with the splitter yet; a choice made here is kept "
            "and applies once it is."
        )
    return body


@router.get("/students/{student_id}/samples/{index}/parts")
def get_sample_parts(student_id: str, index: int, request: Request):
    """The parts of one past paper and what happens to each (staff only)."""
    _require_staff(request)
    state, sample = _sample_or_404(student_id, index)
    if not _po.switches_on():
        return {"enabled": False, "index": index, "parts": []}
    return _parts_body(state, index, sample)


def _splitter_keys(sample) -> list[str]:
    """The splitter measurements this paper already carries, made under
    today's rules (a stale one counts as missing, ``measurement.stored_vector``).
    A choice never creates one: that would change which measurement scores use."""
    return sorted(
        k
        for k in (sample.extra_vectors or {})
        if _po.is_splitter(k) and _measurement.stored_vector(sample, k) is not None
    )


def _store(student_id: str, index: int, choice) -> dict[str, Any]:
    state, sample = _sample_or_404(student_id, index)
    if choice is None and not sample.part_overrides:  # already the rules: nothing to do
        if not _po.switches_on():
            return {"enabled": False, "index": index, "parts": []}
        return _parts_body(state, index, sample)
    text = sample.text or ""

    def extract(data: str):
        if sample.keystroke_data is None:
            return feature_vector(data)
        return feature_vector(data, keystroke_data=sample.keystroke_data)

    # The choice is stored with the paper; for each splitter measurement the
    # paper already carries, the measurement made with the choice is stored
    # beside it (served only with both switches on). The rules' own
    # measurements in extra_vectors and the default vector are never touched,
    # so going back to the rules restores exactly the state before the choice.
    stored = _po.to_stored(choice, text)
    if stored is not None:
        pending = dataclasses.replace(sample, part_overrides=stored)
        vectors = {
            k: _po.measure_stored_choice(pending, k, extract) for k in _splitter_keys(sample)
        }
        stored = _po.to_stored(choice, text, {k: v for k, v in vectors.items() if v is not None})
    state.samples[index] = dataclasses.replace(sample, part_overrides=stored)
    _persist_or_503(state)
    try:
        _repo().log_audit(
            action="baseline_parts",
            student_id=student_id,
            details={
                "index": index,
                "set_aside_ranges": len(choice.exclude) if choice else 0,
                "measured_ranges": len(choice.include) if choice else 0,
            },
        )
    except Exception:
        pass
    if not _po.switches_on():
        return {"enabled": False, "index": index, "parts": []}
    return _parts_body(state, index, state.samples[index])


@router.put("/students/{student_id}/samples/{index}/parts")
def put_sample_parts(student_id: str, index: int, body: PartChoiceRequest, request: Request):
    """Store the teacher's choice of parts for one past paper and measure its
    splitter measurement again (staff only). Empty lists go back to the rules."""
    _require_staff(request)
    state, sample = _sample_or_404(student_id, index)
    if not body.exclude_ranges and not body.include_ranges:
        return _store(student_id, index, None)
    if not _po.switches_on():
        raise HTTPException(
            status_code=409,
            detail="Choosing the parts of a paper is turned off on this deployment.",
        )
    try:
        choice = _po.validate(sample.text or "", body.exclude_ranges, body.include_ranges)
    except _po.OverrideError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _store(student_id, index, choice)


@router.delete("/students/{student_id}/samples/{index}/parts")
def delete_sample_parts(student_id: str, index: int, request: Request):
    """Go back to the rules for one past paper (staff only), whatever the switches say."""
    _require_staff(request)
    _sample_or_404(student_id, index)
    return _store(student_id, index, None)
