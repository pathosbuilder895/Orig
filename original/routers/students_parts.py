"""A past paper's parts, and the teacher's own choice of them (staff only).

``GET  /students/{id}/samples/{index}/parts``: the parts of one past paper the
rules found (``paper_profile.paper_parts``): title page, abstract, list of
sources, notes, an appendix, and the "possible" parts the rules were unsure
of and measured, each with what happened to it.

``PUT  /students/{id}/samples/{index}/parts``: the teacher's choice for that
paper (``exclude_ranges`` set aside, ``include_ranges`` measured, whatever the
rules say; empty lists go back to the rules). It is stored with the paper
(``BaselineSample.part_overrides``) and the paper is measured again at once,
its default ``vector`` and every other measurement it carries
(``extra_vectors``), so the baseline changes only when a teacher acts here.

Both answer only while the splitter and the paper profile are on
(``MATTER_SPLITTER_ENABLED`` and ``PAPER_PROFILE_ENABLED``); off, GET says so
and PUT is refused, so nothing about a baseline can change.
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


def parts_control_enabled() -> bool:
    """The parts list and the teacher's control: splitter and profile both on."""
    from ..paper_profile import paper_profile_enabled

    return paper_profile_enabled() and _ff.matter_splitter_enabled()


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


def _parts_body(index: int, sample) -> dict[str, Any]:
    from ..paper_profile import paper_parts

    choice = _po.of_sample(sample)
    text = sample.text or ""
    with _po.applying({text: choice}):
        parts = paper_parts(text)
    doc = choice.to_doc() if choice is not None else {"exclude_ranges": [], "include_ranges": []}
    return {"enabled": True, "index": index, "words": len(text.split()), "parts": parts, **doc}


@router.get("/students/{student_id}/samples/{index}/parts")
def get_sample_parts(student_id: str, index: int, request: Request):
    """The parts of one past paper and what happens to each (staff only)."""
    _require_staff(request)
    state, sample = _sample_or_404(student_id, index)
    if not parts_control_enabled():
        return {"enabled": False, "index": index, "parts": []}
    return _parts_body(index, sample)


def _measure(text: str, measurement: str, keystroke_data) -> np.ndarray:
    with _ff.measuring(measurement):
        if keystroke_data is None:
            return np.asarray(feature_vector(text), dtype=np.float64)
        return np.asarray(feature_vector(text, keystroke_data=keystroke_data), dtype=np.float64)


@router.put("/students/{student_id}/samples/{index}/parts")
def put_sample_parts(student_id: str, index: int, body: PartChoiceRequest, request: Request):
    """Store the teacher's choice of parts for one past paper and measure it
    again (staff only). Empty lists go back to the rules."""
    _require_staff(request)
    state, sample = _sample_or_404(student_id, index)
    if not parts_control_enabled():
        raise HTTPException(
            status_code=409,
            detail="Choosing the parts of a paper is turned off on this deployment.",
        )
    text = sample.text or ""
    try:
        choice = _po.validate(text, body.exclude_ranges, body.include_ranges)
    except _po.OverrideError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with _po.applying({text: choice}):
        vector = _measure(text, _measurement.DEFAULT, sample.keystroke_data)
        extra = {
            key: _measure(text, key, sample.keystroke_data)
            for key in sorted(sample.extra_vectors or {})
        }
    state.samples[index] = dataclasses.replace(
        sample,
        vector=vector,
        extra_vectors=extra or None,
        part_overrides=choice.to_doc() if choice is not None else None,
    )
    # Everything derived from the samples is computed again on next use.
    state._rho = None
    state._purity = None
    state._trajectory = None
    state._loo_distances = None
    _persist_or_503(state)

    from ..rule_d import mode as _rule_d_mode

    if _rule_d_mode() != "off":
        try:
            from ..rule_d.service import sync_profiles

            sync_profiles(_repo(), state, feature_vector)
        except Exception:  # a report-only mechanism never fails the change
            log.exception("rule_d profile rebuild failed after a parts choice")
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
    return _parts_body(index, state.samples[index])
