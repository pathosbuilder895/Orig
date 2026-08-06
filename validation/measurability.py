"""
validation/measurability.py — single source of truth for which feature
columns can, in principle, carry evidence in a corpus sweep.

The 2026-07-30 Instrument Report's root failure mode: structurally-blank
columns (comparison-shaped features hardwired to 0.5 outside scoring,
disabled groups, fallback constants) were read as "measured zero" by the
first weight derivation and would have driven wrong re-weighting. This
module makes that class of error structural to prevent: aggregation code
calls assert_aggregatable() and REFUSES non-measurable columns instead of
silently averaging them.

Statuses:
  MEASURABLE          varies in a corpus sweep; eligible for aggregation
  SCORING_ONLY        comparison-shaped; computed only against a baseline at
                      scoring time; extract_features() hardwires 0.5
                      (COMPARISON_CODES + MUSICAL_COMPARISON_CODES —
                      original/features/pipeline.py)
  STRUCTURALLY_BLANK  constant via a fallback path regardless of corpus
                      (tier 12's catastrophe_index)
  DISABLED            group is in DISABLED_FEATURE_GROUPS (live view — if a
                      group is enabled later this module tracks it with no
                      code change)
  CORPUS_LIMITED      measurable in principle but known-blank on named
                      corpora (tier 16 citation fingerprint on Plato /
                      Gutenberg literary prose, which has no academic
                      citation behavior)

Precedence (highest first): DISABLED > SCORING_ONLY > STRUCTURALLY_BLANK
> CORPUS_LIMITED > MEASURABLE. A disabled group is blank no matter what
else is true of its codes.
"""
from __future__ import annotations

from enum import Enum
from typing import Sequence

from original.constants import (
    ALL_FEATURE_CODES,
    COMPARISON_CODES,
    DISABLED_FEATURE_GROUPS,
    FEATURE_GROUPS,
    MUSICAL_COMPARISON_CODES,
    TIER16_CODES,
)


class MeasurabilityStatus(str, Enum):
    MEASURABLE = "measurable"
    SCORING_ONLY = "scoring_only"
    STRUCTURALLY_BLANK = "structurally_blank"
    DISABLED = "disabled"
    CORPUS_LIMITED = "corpus_limited"


class MeasurabilityError(ValueError):
    """Raised when aggregation is attempted over non-measurable columns."""


_ALL_CODES = set(ALL_FEATURE_CODES)
_SCORING_ONLY = set(COMPARISON_CODES) | set(MUSICAL_COMPARISON_CODES)
_STRUCTURALLY_BLANK = {"catastrophe_index"}
# Corpora with essentially no academic citation behavior — tier 16 measured
# "near zero" there is a corpus artifact, not a finding (Instrument Report,
# Ledger A, T16 row).
_CORPUS_LIMITED: dict[str, frozenset[str]] = {
    code: frozenset({"plato", "public_authors"}) for code in TIER16_CODES
}


def _disabled_codes() -> set[str]:
    # Read live so behavior tracks runtime state (same convention as
    # scripts/derive_measured_weights.structurally_excluded_codes).
    out: set[str] = set()
    for group in DISABLED_FEATURE_GROUPS:
        out.update(FEATURE_GROUPS.get(group, []))
    return out


def status(code: str, corpus: str | None = None) -> MeasurabilityStatus:
    if code not in _ALL_CODES:
        raise KeyError(f"unknown feature code: {code!r}")
    if code in _disabled_codes():
        return MeasurabilityStatus.DISABLED
    if code in _SCORING_ONLY:
        return MeasurabilityStatus.SCORING_ONLY
    if code in _STRUCTURALLY_BLANK:
        return MeasurabilityStatus.STRUCTURALLY_BLANK
    if corpus is not None and corpus in _CORPUS_LIMITED.get(code, frozenset()):
        return MeasurabilityStatus.CORPUS_LIMITED
    return MeasurabilityStatus.MEASURABLE


def measurable_codes(corpus: str | None = None) -> list[str]:
    return [
        c for c in ALL_FEATURE_CODES if status(c, corpus) is MeasurabilityStatus.MEASURABLE
    ]


def measurable_indices(corpus: str | None = None) -> list[int]:
    return [
        i
        for i, c in enumerate(ALL_FEATURE_CODES)
        if status(c, corpus) is MeasurabilityStatus.MEASURABLE
    ]


def disabled_feature_indices() -> list[int]:
    disabled = _disabled_codes()
    return [i for i, c in enumerate(ALL_FEATURE_CODES) if c in disabled]


def structurally_excluded_codes() -> set[str]:
    """
    Codes that can never carry corpus-sweep signal regardless of corpus:
    disabled + scoring-only + structurally blank. (CORPUS_LIMITED codes are
    NOT here — they are measurable on the right corpus.)
    """
    return _disabled_codes() | _SCORING_ONLY | set(_STRUCTURALLY_BLANK)


def assert_aggregatable(codes: Sequence[str], corpus: str | None = None) -> None:
    offending = [
        (c, status(c, corpus).value)
        for c in codes
        if status(c, corpus) is not MeasurabilityStatus.MEASURABLE
    ]
    if offending:
        raise MeasurabilityError(
            "refusing to aggregate over non-measurable columns "
            f"(corpus={corpus!r}): {offending}"
        )
