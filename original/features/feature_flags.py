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
    On: ``features/matter.py`` sets aside the heading block, section headings,
    running heads and page numbers, footnote text and a verified list of
    sources before anything is measured, in place of the older back-matter rule.

Do not switch either on for live scoring yet. Past papers keep the vector made
when they were added, so a paper scored under a new setting would be compared
with past papers measured the old way. The plan's next step (PR 3) stores both
versions side by side and only compares like with like.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

_ON_VALUES = frozenset({"1", "on", "true", "yes"})


def feature_set() -> int:
    """2 only when FEATURE_SET is exactly "2" (spaces ignored); otherwise 1."""
    return 2 if os.environ.get("FEATURE_SET", "1").strip() == "2" else 1


def lexicon_v2() -> bool:
    return feature_set() >= 2


def matter_splitter_enabled() -> bool:
    return os.environ.get("MATTER_SPLITTER_ENABLED", "0").strip().lower() in _ON_VALUES


def cache_key() -> tuple[int, bool]:
    """The switch state, for any cache keyed on a paper's text."""
    return (feature_set(), matter_splitter_enabled())


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
