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
with the digest of the paper's text) and that paper's splitter measurement
(``extra_vectors["matter"]``, and any other splitter measurement it carries)
is measured again. The default ``vector`` is never touched.

``DELETE`` (or a PUT with empty lists) goes back to the rules. Setting a
choice needs ``MATTER_SPLITTER_ENABLED`` and ``PAPER_PROFILE_ENABLED`` both on
(409 otherwise); going back to the rules is allowed whatever the switches
say. With either switch off a stored choice has no effect anywhere.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

import numpy as np
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
    return {
        "enabled": True,
        "index": index,
        "words": len((sample.text or "").split()),
        "parts": parts,
        **doc,
        **_in_use(state),
    }


@router.get("/students/{student_id}/samples/{index}/parts")
def get_sample_parts(student_id: str, index: int, request: Request):
    """The parts of one past paper and what happens to each (staff only)."""
    _require_staff(request)
    state, sample = _sample_or_404(student_id, index)
    if not _po.switches_on():
        return {"enabled": False, "index": index, "parts": []}
    return _parts_body(state, index, sample)


def _splitter_keys(sample, setting: bool) -> list[str]:
    """The splitter measurements to measure again: those the paper carries,
    and ``matter`` itself when a choice is being set."""
    keys = {k for k in (sample.extra_vectors or {}) if _ff.MEASUREMENTS.get(k, (1, False))[1]}
    if setting:
        keys.add(SPLITTER_MEASUREMENT)
    return sorted(keys)


def _store(student_id: str, index: int, choice) -> dict[str, Any]:
    state, sample = _sample_or_404(student_id, index)
    if choice is None and not sample.part_overrides:  # already the rules: nothing to do
        if not _po.switches_on():
            return {"enabled": False, "index": index, "parts": []}
        return _parts_body(state, index, sample)
    text = sample.text or ""

    def measure(key: str, data: str) -> np.ndarray:
        with _ff.measuring(key):
            if sample.keystroke_data is None:
                return np.asarray(feature_vector(data), dtype=np.float64)
            return np.asarray(
                feature_vector(data, keystroke_data=sample.keystroke_data), dtype=np.float64
            )

    keys = _splitter_keys(sample, choice is not None)
    # The rules-only splitter measurement, kept beside the choice: it stands
    # in whenever a switch is off (measurement.vector_for).
    rules = {key: measure(key, text) for key in keys} if choice is not None else {}
    updated = dataclasses.replace(sample, part_overrides=_po.to_stored(choice, text, rules))
    extra = dict(sample.extra_vectors or {})
    for key in keys:
        extra[key] = (
            measure(key, _po.text_of(updated)) if choice is not None else measure(key, text)
        )
    # The default vector is never measured again here: a choice changes only
    # the splitter's measurement.
    state.samples[index] = dataclasses.replace(updated, extra_vectors=extra or None)
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
