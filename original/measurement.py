"""Versioned measurements: which way a paper was measured, and comparing like
with like.

The problem
-----------
``FEATURE_SET=2`` and ``MATTER_SPLITTER_ENABLED=1`` (features/feature_flags.py)
change what is measured. A past paper's ``vector`` was measured once, when it
was added, the default way ("v1"). Scoring a new paper measured another way
against those vectors would compare two different rulers.

What this module does
---------------------
* Past papers keep ``vector`` (always "v1") and may also carry
  ``extra_vectors[measurement]`` (written by ``scripts/backfill_measurements.py``
  or, if ``UPLOAD_ALSO_MEASURE`` names a measurement, at upload).
* ``plan_for(state)``: the environment asks for a measurement
  (``feature_flags.requested_measurement()``). It is *used* only when every
  past paper of that student has it; otherwise the score falls back to "v1"
  for the paper and the past papers alike. Never a mix.
* Scoring runs inside ``feature_flags.measuring(plan.used)``, so the new paper,
  the evidence pages' re-reading of the past papers, and any peer texts are
  all measured the same way as the stored vectors being compared.
* ``plan.stamp()`` is attached to the score response (``measurement``) and to
  the staff evidence (``evidence["measurement"]``) whenever anything other
  than the default was asked for. No stamp means "v1": with both switches off
  the response is byte-identical to before.

Seam for other engines (for example a future ``original/consistency`` engine)
------------------------------------------------------------------------------
Read the version from a stored or returned score with ``measurement_of(obj)``
(dict or response model; ``"v1"`` when unstamped), and read a past paper's
vector for a measurement with ``vector_for(sample, measurement)`` (``None``
when that paper was not measured that way). Compare two results only when
``measurement_of`` agrees. See docs/adr/ADR-014-measurement-versions.md.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from .features import feature_flags as ff

log = logging.getLogger(__name__)

DEFAULT = "v1"


@dataclass(frozen=True)
class MeasurementPlan:
    requested: str
    used: str
    state: Any  # StudentState to score against (a swapped view when used != v1)
    papers: int
    papers_measured: int

    def stamp(self) -> dict[str, Any] | None:
        """The version stamp for responses; None when only the default was asked for."""
        if self.requested == DEFAULT:
            return None
        stamp: dict[str, Any] = {
            "requested": self.requested,
            "used": self.used,
            "past_papers": self.papers,
            "past_papers_measured": self.papers_measured,
        }
        if self.used != self.requested:
            stamp["fallback"] = (
                f"{self.papers - self.papers_measured} of {self.papers} past papers are not "
                f"yet measured as {self.requested}, so this was measured the default way"
            )
        return stamp


def vector_for(sample: Any, measurement: str) -> np.ndarray | None:
    """A past paper's vector for ``measurement``, or None if it has none.

    A splitter measurement made with a teacher's choice of parts
    (``features/part_overrides.py``) is read only while both switches are on;
    otherwise the rules-only measurement stored beside the choice stands in,
    so a stored choice changes nothing with a switch off."""
    if measurement == DEFAULT:
        return sample.vector
    extra = getattr(sample, "extra_vectors", None) or {}
    vector = extra.get(measurement)
    if vector is not None:
        from .features import part_overrides

        rules = part_overrides.rules_vector(sample, measurement)
        if rules is not None:
            return rules
    return vector


def _view(state: Any, measurement: str) -> Any:
    """A copy of ``state`` whose samples carry the ``measurement`` vectors.
    Marked so the store refuses to persist it (store._refuse_measurement_view)."""
    from .quantum.state import StudentState

    view = StudentState(
        student_id=state.student_id,
        samples=[replace(s, vector=vector_for(s, measurement)) for s in state.samples],
        baseline_kappa=state.baseline_kappa,
        kappa_log=list(state.kappa_log),
    )
    view._consecutive_drift_count = state._consecutive_drift_count
    view._measurement_view = measurement
    return view


def plan_for(state: Any) -> MeasurementPlan:
    requested = ff.requested_measurement()
    papers = len(state.samples)
    if requested == DEFAULT:
        return MeasurementPlan(DEFAULT, DEFAULT, state, papers, papers)
    measured = sum(1 for s in state.samples if vector_for(s, requested) is not None)
    if papers and measured == papers:
        return MeasurementPlan(requested, requested, _view(state, requested), papers, measured)
    log.info(
        "measurement: %s requested but %d of %d past papers have it; using %s",
        requested,
        measured,
        papers,
        DEFAULT,
    )
    return MeasurementPlan(requested, DEFAULT, state, papers, measured)


def states_measured_as(states: Iterable[Any], measurement: str) -> list[Any]:
    """Peer states for the pool-based signals, measured as ``measurement``:
    as they are for "v1"; otherwise only students whose every past paper has
    it, swapped to it (a peer that cannot be compared like with like is left
    out rather than mixed in)."""
    if measurement == DEFAULT:
        return list(states)
    return [
        _view(st, measurement)
        for st in states
        if st.samples and all(vector_for(s, measurement) is not None for s in st.samples)
    ]


def extra_vectors_at_upload(
    text: str, keystroke_data: dict | None = None, extract: Callable | None = None
) -> dict[str, np.ndarray] | None:
    """The other measurement stored with a new past paper, or None (default).

    A new paper's ``vector`` is measured inside ``measuring("v1")`` by the
    upload route, whatever FEATURE_SET or the splitter say, so stored vectors
    never mix versions. This adds one more extraction only when
    UPLOAD_ALSO_MEASURE names a measurement, run after the first (one at a
    time, so the peak memory of a 512 MB instance stays where it was). A failed
    extra extraction is logged and skipped; the paper is still added and the
    backfill can fill it later. ``extract`` is the route's own
    ``feature_vector`` (so tests that replace it are honoured).
    """
    also = ff.upload_also_measure()
    if also is None:
        return None
    if extract is None:
        from .features.pipeline import feature_vector as extract
    try:
        with ff.measuring(also):
            if keystroke_data is None:
                vector = extract(text)
            else:
                vector = extract(text, keystroke_data=keystroke_data)
    except Exception:
        log.exception("measurement: %s extraction at upload failed; skipped", also)
        return None
    return {also: np.asarray(vector, dtype=np.float64)}


def measurement_of(obj: Any) -> str:
    """The measurement a stored or returned score used ("v1" when unstamped)."""
    stamp = obj.get("measurement") if isinstance(obj, dict) else getattr(obj, "measurement", None)
    if stamp is None:
        return DEFAULT
    used = stamp.get("used") if isinstance(stamp, dict) else getattr(stamp, "used", None)
    return used if used in ff.MEASUREMENTS else DEFAULT
