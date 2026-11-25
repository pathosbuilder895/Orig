"""Measurement-version switches for the writing-habit features.

Two switches, both OFF by default. With both off every measurement, vector and
score is byte-for-byte what it was before they existed
(``tests/config/test_flag_byte_identity.py``).

``FEATURE_SET`` (default ``1``)
    ``2`` turns on the reworked word-list habits (``features/lexicon_v2.py``):
    hedging (Hyland 2005 list, word-class aware), modal verbs (tagged modals
    only, so "May 2026" is not a modal), confident-statement words (whole-word
    phrases, no double counts) and linking words (position rules for "so",
    "then", "first", "that is"). Any other value means ``1``.

``MATTER_SPLITTER_ENABLED`` (default off)
    On: ``features/matter.py`` sets aside the title page, the heading block,
    an abstract, section headings, running heads and page numbers, verified
    notes and footnotes and a verified list of sources (up to an appendix)
    before anything is measured, in place of the older back-matter rule; a
    PDF upload's measured body is also reflowed into paragraphs
    (``features/pdf_reflow.py``; stored text never changes). Cover letters and
    notes without years outside a verified notes block are not detected.

``UPLOAD_ALSO_MEASURE`` (default empty)
    A measurement id (e.g. ``fs2+matter``): each newly added past paper also
    stores that measurement beside its default one. Off: nothing extra runs.

Past papers' ``vector`` is always the default ``v1`` measurement; other
measurements are stored beside it and filled in by
``scripts/backfill_measurements.py``. A score uses the requested measurement
only when every past paper has it, otherwise the default, and says which it
used (``original/measurement.py``, ADR-014). Do not switch either on for live
scoring before the backfill and a recalibration.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeVar

T = TypeVar("T")

_ON_VALUES = frozenset({"1", "on", "true", "yes"})


#: Named measurements: (feature set, splitter on). "v1" is the default and
#: the measurement every stored ``BaselineSample.vector`` was made with.
MEASUREMENTS: dict[str, tuple[int, bool]] = {
    "v1": (1, False),
    "fs2": (2, False),
    "matter": (1, True),
    "fs2+matter": (2, True),
}
_ID_OF = {key: mid for mid, key in MEASUREMENTS.items()}

#: Set by ``measuring()``: the measurement in force for this context,
#: overriding the environment. A ContextVar, so one request's choice never
#: leaks into another thread's.
_OVERRIDE: ContextVar[tuple[int, bool] | None] = ContextVar("measurement_override", default=None)


def _env_feature_set() -> int:
    return 2 if os.environ.get("FEATURE_SET", "1").strip() == "2" else 1


def _env_matter() -> bool:
    return os.environ.get("MATTER_SPLITTER_ENABLED", "0").strip().lower() in _ON_VALUES


def feature_set() -> int:
    """2 only when FEATURE_SET is exactly "2" (spaces ignored); otherwise 1.
    Inside ``measuring()``, the measurement named there."""
    override = _OVERRIDE.get()
    return override[0] if override is not None else _env_feature_set()


def lexicon_v2() -> bool:
    return feature_set() >= 2


def matter_splitter_enabled() -> bool:
    override = _OVERRIDE.get()
    return override[1] if override is not None else _env_matter()


def cache_key() -> tuple[int, bool]:
    """The switch state, for any cache keyed on a paper's text."""
    return (feature_set(), matter_splitter_enabled())


def requested_measurement() -> str:
    """The measurement the environment asks for ("v1" with both switches off)."""
    return _ID_OF[(_env_feature_set(), _env_matter())]


def current_measurement() -> str:
    """The measurement in force right now (``measuring()`` or the environment)."""
    return _ID_OF[cache_key()]


@contextmanager
def measuring(measurement: str) -> Iterator[None]:
    """Measure as ``measurement`` inside this block, whatever the environment says."""
    token = _OVERRIDE.set(MEASUREMENTS[measurement])
    try:
        yield
    finally:
        _OVERRIDE.reset(token)


def set_measurement(measurement: str) -> None:
    """Measure as ``measurement`` for the rest of the current context. For a
    caller that already runs in its own copied context (the score routes run
    in ``contextvars.copy_context().run``); elsewhere use ``measuring()``."""
    _OVERRIDE.set(MEASUREMENTS[measurement])


def upload_also_measure() -> str | None:
    """UPLOAD_ALSO_MEASURE: a measurement to store next to the default one on
    every new past paper (e.g. "fs2+matter"). Unset, empty, "v1" or unknown:
    None (off), so a new upload costs exactly one extraction."""
    value = os.environ.get("UPLOAD_ALSO_MEASURE", "").strip()
    return value if value in MEASUREMENTS and value != "v1" else None


def text_cache(maxsize: int) -> Callable[[Callable[[str], T]], Callable[[str], T]]:
    """``functools.lru_cache`` for a function of one paper's text, keyed on the
    text *and* the switch state, so a value computed under one setting is never
    served under another. Keeps ``cache_clear``/``cache_info``/``__wrapped__``.
    With both switches off it caches exactly as ``lru_cache(maxsize)`` did."""

    def deco(fn: Callable[[str], T]) -> Callable[[str], T]:
        @functools.lru_cache(maxsize=maxsize)
        def keyed(text: str, _key: tuple[int, bool]) -> T:
            return fn(text)

        @functools.wraps(fn)
        def wrapper(text: str) -> T:
            return keyed(text, cache_key())

        wrapper.cache_clear = keyed.cache_clear  # type: ignore[attr-defined]
        wrapper.cache_info = keyed.cache_info  # type: ignore[attr-defined]
        return wrapper

    return deco
