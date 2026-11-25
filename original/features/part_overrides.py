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
switch off a choice, stored or sent, has no effect anywhere. A past paper
keeps the rules' own splitter measurements in ``extra_vectors`` as always;
those made with its stored choice sit beside them in the choice's document
(``choice_vectors``, each with the splitter's rules version in
``choice_rules``; one made under other rules is served as missing) and are
served (``measurement.vector_for``) only while both switches are on. Both are
stored whenever a splitter measurement is made for a paper with a choice,
whatever the switches say then.

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
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
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


#: Set by ``measuring_stored_choice``: a stored choice is measured whatever the
#: switches say (to store its measurement beside the rules' one), never served.
_MEASURING_STORED: ContextVar[bool] = ContextVar("measuring_stored_choice", default=False)


@contextmanager
def measuring_stored_choice() -> Iterator[None]:
    token = _MEASURING_STORED.set(True)
    try:
        yield
    finally:
        _MEASURING_STORED.reset(token)


def for_text(text: str) -> PartOverride | None:
    """The choice this paper carries, when it may apply: both switches on (or
    a stored choice being measured, ``measuring_stored_choice``) and the
    splitter's measurement in force. None otherwise."""
    choice = getattr(text, "part_choice", None)
    if choice is None or not (switches_on() or _MEASURING_STORED.get()):
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
    # A range holding a word keeps it when snapped (the word sits before the
    # PDF tag), so a range with only the tag was refused just above.
    ex = union_ranges(_snap(text, a, b) for a, b in ex_raw)
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
    choice: PartOverride | None, text: str, choice_vectors: dict[str, Any] | None = None
) -> dict | None:
    """The document stored with a past paper: the ranges, the digest of the
    text they belong to, and the paper's splitter measurements made with the
    choice (``choice_vectors``). The rules' own measurements stay where they
    always are, in ``extra_vectors``; a choice's are served only with both
    switches on (``choice_vector``)."""
    if choice is None:
        return None
    doc: dict[str, Any] = {**choice.to_doc(), "text_sha256": text_digest(text)}
    if choice_vectors:
        doc["choice_vectors"] = {
            k: [float(x) for x in v] for k, v in sorted(choice_vectors.items())
        }
        doc["choice_rules"] = {k: _matter.RULES_VERSION for k in sorted(choice_vectors)}
    return doc


def is_splitter(measurement: str) -> bool:
    from . import feature_flags as _ff

    return bool(_ff.MEASUREMENTS.get(measurement, (1, False))[1])


def choice_vector(sample: Any, measurement: str):
    """A past paper's ``measurement`` made with its stored choice, or None
    (no choice, a choice that no longer fits its paper, not measured yet, or
    measured under other splitter rules than today's: ``choice_rules`` holds
    each one's ``matter.RULES_VERSION``, unstamped taken as
    ``matter.UNSTAMPED_RULES_VERSION``)."""
    doc = getattr(sample, "part_overrides", None)
    if not doc or of_sample(sample) is None:
        return None
    raw = (doc.get("choice_vectors") or {}).get(measurement)
    if raw is None:
        return None
    if not _matter.rules_current((doc.get("choice_rules") or {}).get(measurement)):
        return None
    import numpy as np

    from ..constants import FEATURE_DIM

    vector = np.asarray(raw, dtype=np.float64)
    return vector if vector.shape == (FEATURE_DIM,) else None


def served_vector(sample: Any, measurement: str, rules_vector):
    """What a score reads for this paper: the choice's measurement only while
    both switches are on and one is stored; the rules' own otherwise."""
    if rules_vector is None or not is_splitter(measurement) or not switches_on():
        return rules_vector
    chosen_vector = choice_vector(sample, measurement)
    return rules_vector if chosen_vector is None else chosen_vector


def measure_stored_choice(sample: Any, measurement: str, extract: Callable[[str], Any]):
    """``measurement`` of a past paper made with its stored choice, whatever
    the switches say, or None (no valid choice, or not a splitter measurement)."""
    choice = of_sample(sample)
    if choice is None or not is_splitter(measurement):
        return None
    import numpy as np

    from . import feature_flags as _ff

    with _ff.measuring(measurement), measuring_stored_choice():
        return np.asarray(extract(chosen(sample.text, choice)), dtype=np.float64)


def with_choice_vectors(doc: dict, vectors: dict[str, Any]) -> dict:
    """``doc`` (a stored choice) with these choice measurements added, each
    stamped with the current ``matter.RULES_VERSION``."""
    merged = dict(doc.get("choice_vectors") or {})
    merged.update({k: [float(x) for x in v] for k, v in vectors.items()})
    rules = dict(doc.get("choice_rules") or {})
    rules.update({k: _matter.RULES_VERSION for k in vectors})
    return {
        **doc,
        "choice_vectors": dict(sorted(merged.items())),
        "choice_rules": dict(sorted(rules.items())),
    }


def with_choice_rules(doc: dict, measurement: str) -> dict:
    """``doc`` with its ``measurement`` choice measurement stamped as made
    under today's rules (one stored before stamps existed, still current)."""
    rules = {**(doc.get("choice_rules") or {}), measurement: _matter.RULES_VERSION}
    return {**doc, "choice_rules": dict(sorted(rules.items()))}


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
