"""
validation/corpus_policy.py — enforced corpus floors, per task.

Policy (design spec C4): short texts are verification-only, never
attribution candidates. Floors are arguments with defaults — runners
record the values they used in their ExperimentSpec, so a floor change is
visible in every report diff.
"""
from __future__ import annotations

from dataclasses import dataclass

VERIFICATION_MIN_WORDS = 300  # matches the public_authors chunker floor
# Equal to the verification floor today, by measured decision (2026-07-31,
# design-spec open decision #2). The draft proposed 500, but against the real
# manifest that drops kempis entirely — all three of its baseline chunks are
# 393-499 words, i.e. exactly the author the TOC-bug fix repaired. The two
# constants stay separate so attribution can be raised independently once the
# corpus carries longer chunks.
ATTRIBUTION_MIN_WORDS = 300
ATTRIBUTION_MIN_BASELINE_DOCS = 3


@dataclass(frozen=True)
class PolicyViolation:
    kind: str     # "short_document" | "thin_baseline" | "genre_dominance"
    subject: str  # document id, author id, or genre name
    detail: str


def check_verification_pool(
    word_counts: dict[str, int],
    min_words: int = VERIFICATION_MIN_WORDS,
) -> list[PolicyViolation]:
    return [
        PolicyViolation(
            kind="short_document",
            subject=doc_id,
            detail=f"{count} words < verification floor {min_words}",
        )
        for doc_id, count in sorted(word_counts.items())
        if count < min_words
    ]


def check_attribution_pool(
    word_counts: dict[str, int],
    baseline_counts: dict[str, int],
    min_words: int = ATTRIBUTION_MIN_WORDS,
    min_baseline_docs: int = ATTRIBUTION_MIN_BASELINE_DOCS,
) -> list[PolicyViolation]:
    violations = [
        PolicyViolation(
            kind="short_document",
            subject=doc_id,
            detail=f"{count} words < attribution floor {min_words} "
            "(verification-only; never an attribution candidate)",
        )
        for doc_id, count in sorted(word_counts.items())
        if count < min_words
    ]
    violations += [
        PolicyViolation(
            kind="thin_baseline",
            subject=author,
            detail=f"{count} baseline docs < required {min_baseline_docs}",
        )
        for author, count in sorted(baseline_counts.items())
        if count < min_baseline_docs
    ]
    return violations


def conformal_informative_authors(
    baseline_counts: dict[str, int],
    band_threshold: float,
) -> dict[str, bool]:
    """Which authors have enough baseline docs for the typicality band to
    be reachable at all? Feeds gate informativeness (validation/power.py)."""
    from validation.power import band_reachable

    return {a: band_reachable(n, band_threshold) for a, n in baseline_counts.items()}


MAX_GENRE_SHARE = 0.6


def check_genre_balance(
    genre_word_counts: dict[str, int],
    max_share: float = MAX_GENRE_SHARE,
) -> list[PolicyViolation]:
    """
    Flag a derivation corpus dominated by one genre.

    Weights derived on a corpus that is overwhelmingly one register say
    more about that register than about the target task — the Instrument
    Report's standing caveat ("21 parts Plato to 2 parts student-like
    prose") made computable, so it cannot rot into a stale docstring.
    """
    total = sum(genre_word_counts.values())
    if total == 0:
        return []
    return [
        PolicyViolation(
            kind="genre_dominance",
            subject=genre,
            detail=f"{count / total:.1%} of corpus words ({count}/{total}) "
            f"exceeds the {max_share:.0%} single-genre ceiling — derived "
            "quantities describe this genre more than the target task",
        )
        for genre, count in sorted(genre_word_counts.items())
        if count / total > max_share
    ]
