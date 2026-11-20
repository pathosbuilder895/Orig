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
    Parts the rules set aside or listed as possible that are measured anyway.

One rule
--------
A choice changes only the splitter's measurement (``matter``, ``fs2+matter``),
never the default ``v1`` measurement, and does nothing at all unless both
``MATTER_SPLITTER_ENABLED`` and ``PAPER_PROFILE_ENABLED`` are on. With either
switch off a choice, stored or sent, has no effect anywhere: a past paper's
stored splitter measurement made with a choice is then replaced, in
``measurement.vector_for``, by the rules-only one stored beside the choice.

How it travels
--------------
A choice belongs to one paper, never to a string of text: the scored
submission's choice (from its request) and each past paper's stored choice
(``BaselineSample.part_overrides``) ride on that paper's own text object,
``ChosenText``, a ``str`` that carries ``part_choice``. A submission whose
words equal a past paper's is a different object and never picks up that
paper's choice. ``features.preprocess.body_segments`` reads the choice with
``for_text`` (the one hook); every other string measures by the rules alone,
so a score without a choice is byte-for-byte what it was.

Checks (``validate``)
---------------------
Ranges are snapped to whole lines, so a page marker or the PDF tag is never
split and line structure survives in the measured body; the PDF tag itself
is never inside a range. Every range must hold at least one word. The ranges
set aside may take at most ``MAX_EXCLUDED_SHARE`` of the words the rules
keep. An included range must be exactly a part the rules set aside or listed
as possible (or touching such parts merged), never anything else.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from . import matter as _matter

log = logging.getLogger(__name__)

#: The most of the words the rules keep that a teacher may set aside by hand.
MAX_EXCLUDED_SHARE = 0.60
#: The most ranges in either list (a paper has a handful of parts).
MAX_RANGES = 64

Range = tuple[int, int]
_ON_VALUES = frozenset({"1", "on", "true", "yes"})


class OverrideError(ValueError):
    """A choice of ranges that cannot be applied to this text."""


def switches_on() -> bool:
    """Both MATTER_SPLITTER_ENABLED and PAPER_PROFILE_ENABLED are on."""
    return all(
        os.environ.get(name, "0").strip().lower() in _ON_VALUES
        for name in ("MATTER_SPLITTER_ENABLED", "PAPER_PROFILE_ENABLED")
    )


def text_digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PartOverride:
    """Checked, sorted, non-overlapping, whole-line ranges (hashable)."""

    exclude: tuple[Range, ...] = ()
    include: tuple[Range, ...] = ()

    def to_doc(self) -> dict[str, list[list[int]]]:
        return {
            "exclude_ranges": [[a, b] for a, b in self.exclude],
            "include_ranges": [[a, b] for a, b in self.include],
        }


class ChosenText(str):
    """A paper's text carrying that paper's own choice of parts."""

    part_choice: PartOverride | None

    def __new__(cls, text: str, choice: PartOverride | None):
        obj = super().__new__(cls, text)
        obj.part_choice = choice
        return obj

    def __reduce__(self):  # pickles as the plain text: a choice never leaves the process
        return (str, (str(self),))


def chosen(text: str, choice: PartOverride | None) -> str:
    """``text`` carrying ``choice``; the plain text when there is none."""
    return ChosenText(text, choice) if choice is not None else text


def for_text(text: str) -> PartOverride | None:
    """The choice this paper carries, when it may apply: both switches on and
    the splitter's measurement in force. None otherwise."""
    choice = getattr(text, "part_choice", None)
    if choice is None or not switches_on():
        return None
    from . import feature_flags as _ff  # feature_flags imports this module

    return choice if _ff.matter_splitter_enabled() else None


# ── Checks ───────────────────────────────────────────────────────────────────


def _ranges(raw: Any, text_len: int, name: str) -> list[Range]:
    if raw is None:
        return []
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
    return out


def _words(text: str, ranges: Iterable[Range]) -> int:
    return sum(len(text[a:b].split()) for a, b in ranges)  # a page marker is whitespace


def _content_end(text: str) -> int:
    """Where the paper's lines end: before the PDF tag, if it carries one."""
    tag = _matter.PDF_TAG
    return len(text) - len(tag) if text.endswith(tag) else len(text)


def _snap(text: str, a: int, b: int) -> Range:
    """``[a, b)`` widened to whole lines (the last line's newline included),
    never into the PDF tag."""
    end = _content_end(text)
    a = text.rfind("\n", 0, min(a, end)) + 1
    nl = text.find("\n", max(b - 1, a), end)
    b = end if nl < 0 else nl + 1
    return a, min(b, end)


def intersect(a: Sequence[Range], b: Sequence[Range]) -> list[Range]:
    return [(max(x, y), min(p, q)) for x, p in a for y, q in b if max(x, y) < min(p, q)]


def validate(text: str, exclude: Any, include: Any) -> PartOverride | None:
    """The choice as a ``PartOverride``, or None when both lists are empty or
    absent. Raises ``OverrideError`` (see the module notes for the checks)."""
    text = str(text or "")
    ex_raw = _ranges(exclude, len(text), "exclude_ranges")
    inc = _ranges(include, len(text), "include_ranges")
    for a, b in [*ex_raw, *inc]:
        if not text[a:b].split():
            raise OverrideError(f"range [{a}, {b}] holds no words")
    ex = union_ranges(_snap(text, a, b) for a, b in ex_raw)
    if ex_raw and not ex:  # only the PDF tag
        raise OverrideError("exclude_ranges holds no words")
    if inc:
        found = _matter.find_parts(text)
        rule_ranges = {(r.start, r.end) for r in [*found.set_aside, *found.possible]}
        for a, b in inc:
            # Exactly one part, or touching parts merged into one range.
            inside = [r for r in rule_ranges if a <= r[0] and r[1] <= b]
            if union_ranges(inside) != [(a, b)]:
                raise OverrideError(
                    f"include_ranges [{a}, {b}] is not a part the rules set aside or listed"
                )
    if intersect(ex, inc):
        raise OverrideError("a range cannot be both set aside and measured")
    if ex:
        kept = _matter.kept_ranges(text)
        kept_words = _words(text, kept)
        if _words(text, intersect(ex, kept)) > MAX_EXCLUDED_SHARE * kept_words:
            raise OverrideError(
                f"the parts set aside hold more than {MAX_EXCLUDED_SHARE:.0%} of the words "
                "the rules measure"
            )
    if not ex and not inc:
        return None
    return PartOverride(tuple(ex), tuple(inc))


# ── Stored with a past paper ─────────────────────────────────────────────────


def to_stored(
    choice: PartOverride | None, text: str, rules_vectors: dict[str, Any] | None = None
) -> dict | None:
    """The document stored with a past paper: the ranges, the digest of the
    text they belong to, and that paper's splitter measurements made by the
    rules alone (``rules_vectors``), which stand in whenever a switch is off."""
    if choice is None:
        return None
    doc: dict[str, Any] = {**choice.to_doc(), "text_sha256": text_digest(text)}
    if rules_vectors:
        doc["rules_vectors"] = {k: [float(x) for x in v] for k, v in sorted(rules_vectors.items())}
    return doc


def rules_vector(sample: Any, measurement: str):
    """A past paper's ``measurement`` made by the rules alone, when it carries
    a stored choice and a switch is off (the stored ``extra_vectors`` entry
    then holds the choice's measurement); None otherwise."""
    doc = getattr(sample, "part_overrides", None)
    if not doc or switches_on():
        return None
    raw = (doc.get("rules_vectors") or {}).get(measurement)
    if raw is None:
        return None
    import numpy as np

    from ..constants import FEATURE_DIM

    vector = np.asarray(raw, dtype=np.float64)
    return vector if vector.shape == (FEATURE_DIM,) else None


def of_sample(sample: Any) -> PartOverride | None:
    """A past paper's stored choice, checked again against that paper's text.
    A choice whose digest is not this paper's, or that no longer passes the
    checks, is logged and ignored (the paper then measures by the rules)."""
    doc = getattr(sample, "part_overrides", None)
    if not doc:
        return None
    text = getattr(sample, "text", "") or ""
    try:
        if doc.get("text_sha256") != text_digest(text):
            raise OverrideError("the stored choice belongs to another text")
        return validate(text, doc.get("exclude_ranges"), doc.get("include_ranges"))
    except (OverrideError, AttributeError, TypeError, ValueError):
        log.warning("part_overrides: a stored choice does not fit its paper; ignored")
        return None


def text_of(sample: Any) -> str:
    """A past paper's text, carrying that paper's own stored choice."""
    return chosen(getattr(sample, "text", "") or "", of_sample(sample))


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
    """``segments`` with this paper's choice applied when it may apply
    (``for_text``); ``segments`` itself (the same list) otherwise."""
    override = for_text(text)
    if override is None:
        return segments
    return combine(segments, override)
