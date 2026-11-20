"""A teacher's own choice of which parts of a paper are measured (staff only).

What it is
----------
``features.matter`` decides which parts of a paper are set aside (title page,
abstract, list of sources, ...) and which are measured as prose. When the
rules are unsure they measure the part and list it as "possible" for the
teacher (``paper_profile``). This module lets the teacher overrule them:

``exclude_ranges``
    Stored-text character ranges that are set aside, whatever the rules say.
``include_ranges``
    Ranges that are measured, whatever the rules say.

The hook
--------
``features.preprocess.body_segments`` passes the rules' ranges through
``apply(text, segments)``. With no choice in force for that exact text it
returns ``segments`` itself, so a score without a choice is byte-for-byte what
it was. A choice is put in force for the length of one score or one
re-measurement with ``applying()`` / ``set_in_force()``, keyed on the paper's
text, so the paper being scored and each past paper carry their own choice.
It is a ContextVar, like ``feature_flags.measuring``: it never leaks into
another request.

Where choices come from
-----------------------
* ``POST /students/{id}/score`` takes ``exclude_ranges`` / ``include_ranges``
  for the paper being scored (staff only; a student session gets 403).
* A past paper keeps its choice in ``BaselineSample.part_overrides`` (set with
  ``PUT /students/{id}/samples/{index}/parts``), applied whenever that paper is
  measured again: its re-measurement, a backfill, and the evidence pages'
  re-reading of it.

Nothing here reads the text's content; it only checks and combines ranges.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

#: The most of a paper's words a teacher may set aside by hand. Above it the
#: choice is refused: what is left would not be the paper.
MAX_EXCLUDED_SHARE = 0.60
#: The most ranges in either list (a paper has a handful of parts).
MAX_RANGES = 64

Range = tuple[int, int]


class OverrideError(ValueError):
    """A choice of ranges that cannot be applied to this text."""


@dataclass(frozen=True)
class PartOverride:
    """Checked, sorted, non-overlapping ranges (hashable, so caches can key on it)."""

    exclude: tuple[Range, ...] = ()
    include: tuple[Range, ...] = ()

    def to_doc(self) -> dict[str, list[list[int]]]:
        return {
            "exclude_ranges": [[a, b] for a, b in self.exclude],
            "include_ranges": [[a, b] for a, b in self.include],
        }

    @classmethod
    def from_doc(cls, doc: Any, text: str) -> PartOverride | None:
        """A stored choice, checked again against ``text``. Anything that does
        not check out is logged and ignored (the paper is then measured by the
        rules alone), so a bad stored value can never fail a score."""
        if not doc:
            return None
        try:
            return validate(text, doc.get("exclude_ranges"), doc.get("include_ranges"))
        except (OverrideError, AttributeError, TypeError, ValueError):
            log.warning("part_overrides: a stored choice does not fit its paper; ignored")
            return None


def _ranges(raw: Any, text_len: int, name: str) -> tuple[Range, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise OverrideError(f"{name} must be a list of [start, end] pairs")
    if len(raw) > MAX_RANGES:
        raise OverrideError(f"{name} holds more than {MAX_RANGES} ranges")
    out: list[Range] = []
    for item in raw:
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) != 2:
            raise OverrideError(f"{name} must be a list of [start, end] pairs")
        a, b = item
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (a, b)):
            raise OverrideError(f"{name} must hold whole-number offsets")
        if not 0 <= a < b <= text_len:
            raise OverrideError(f"{name} range [{a}, {b}] is not within the text")
        if out and a < out[-1][1]:
            raise OverrideError(f"{name} must be sorted and must not overlap")
        out.append((a, b))
    return tuple(out)


def _words(text: str, ranges: Iterable[Range]) -> int:
    return sum(len(text[a:b].split()) for a, b in ranges)


def validate(text: str, exclude: Any, include: Any) -> PartOverride | None:
    """The choice as a ``PartOverride``, or None when both lists are empty or
    absent. Raises ``OverrideError`` when a range is outside the text, the
    ranges are unsorted or overlap, a range is in both lists, or the ranges set
    aside hold more than ``MAX_EXCLUDED_SHARE`` of the paper's words."""
    text = text or ""
    ex = _ranges(exclude, len(text), "exclude_ranges")
    inc = _ranges(include, len(text), "include_ranges")
    for a, b in ex:
        if any(a < d and c < b for c, d in inc):
            raise OverrideError("a range cannot be both set aside and measured")
    if ex:
        total = len(text.split())
        if _words(text, ex) > MAX_EXCLUDED_SHARE * total:
            raise OverrideError(
                f"the parts set aside hold more than {MAX_EXCLUDED_SHARE:.0%} of the paper's words"
            )
    if not ex and not inc:
        return None
    return PartOverride(ex, inc)


# ── In force for one score or re-measurement ─────────────────────────────────

_IN_FORCE: ContextVar[Mapping[str, PartOverride] | None] = ContextVar(
    "part_overrides_in_force", default=None
)


def for_text(text: str) -> PartOverride | None:
    """The choice in force for this exact text, or None."""
    in_force = _IN_FORCE.get()
    if not in_force:
        return None
    return in_force.get(text)


def _merged(overrides: Mapping[str, PartOverride | None]) -> dict[str, PartOverride] | None:
    out = dict(_IN_FORCE.get() or {})
    for text, o in overrides.items():
        if o is None:
            out.pop(text, None)
        else:
            out[text] = o
    return out or None


@contextmanager
def applying(overrides: Mapping[str, PartOverride | None]) -> Iterator[None]:
    """Measure each text in ``overrides`` with its choice inside this block
    (None removes a choice already in force for that text)."""
    token = _IN_FORCE.set(_merged(overrides))
    try:
        yield
    finally:
        _IN_FORCE.reset(token)


def set_in_force(overrides: Mapping[str, PartOverride | None]) -> None:
    """``applying()`` for the rest of the current context; for a caller that
    already runs in its own copied context (the score route)."""
    _IN_FORCE.set(_merged(overrides))


def of_sample(sample: Any) -> PartOverride | None:
    """A past paper's stored choice, checked against its text."""
    doc = getattr(sample, "part_overrides", None)
    return PartOverride.from_doc(doc, getattr(sample, "text", "") or "") if doc else None


def of_samples(samples: Iterable[Any]) -> dict[str, PartOverride]:
    """Stored choices of past papers, keyed on their text."""
    out: dict[str, PartOverride] = {}
    for s in samples:
        o = of_sample(s)
        if o is not None:
            out[s.text] = o
    return out


# ── The hook ─────────────────────────────────────────────────────────────────


def union_ranges(ranges: Iterable[Range]) -> list[Range]:
    """Sorted, merged ranges."""
    out: list[Range] = []
    for a, b in sorted(r for r in ranges if r[0] < r[1]):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def minus_ranges(kept: Sequence[Range], cut: Sequence[Range]) -> list[Range]:
    """``kept`` (sorted, merged) without anything in ``cut`` (sorted, merged)."""
    out: list[Range] = []
    for a, b in kept:
        pos = a
        for c, d in cut:
            if d <= pos or c >= b:
                continue
            if c > pos:
                out.append((pos, c))
            pos = max(pos, d)
        if pos < b:
            out.append((pos, b))
    return out


def combine(segments: Sequence[Range], override: PartOverride) -> list[Range]:
    """The measured ranges: the rules' ``segments`` plus ``include``, minus ``exclude``."""
    return minus_ranges(union_ranges([*segments, *override.include]), override.exclude)


def apply(text: str, segments: list[Range]) -> list[Range]:
    """``segments`` with the choice in force for ``text`` applied; ``segments``
    itself (the same list) when there is none."""
    override = for_text(text)
    if override is None:
        return segments
    return combine(segments, override)
