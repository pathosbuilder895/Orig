"""
stability.py — Fisher discriminant ratio over (feature, length) buckets.

Inputs:
  - A dict ``{author_id: full_text}`` from the public-author corpus.
  - A list of window lengths to evaluate (e.g. [250, 500, 1000, 2000, 5000]).

For each length L:
  1. Slice each author's text into non-overlapping L-word windows.
  2. Run ``original.features.pipeline.feature_vector`` on each window to
     get a 103-dim feature vector per window.
  3. For each of the 103 features:
       within_var(i, L)  = mean over authors of var(matrix_a[:, i])
       between_var(i, L) = var across authors of mean(matrix_a[:, i])
       F(i, L)           = between_var / (within_var + eps)
  4. Record the F value, the per-author window count, and (for sanity)
     the per-author per-feature means.

Tier-17 (keystroke) features are explicitly excluded — ``feature_vector``
returns a constant 0.5 for them whenever no keystroke data is supplied,
so their variance is identically zero and F is undefined. The exclusion
is recorded in the report so a reader knows they were not measured.

Nothing in this module modifies state. Calling ``per_feature_stability``
twice with the same author texts must produce the same result, modulo
floating point. (We seed nothing here — ``feature_vector`` itself is
deterministic for a given input text once SECRET_KEY is locked.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM, FEATURE_TIER
from original.features.pipeline import feature_vector

from .slicer import slide


log = logging.getLogger("stability")

EPS = 1e-9                              # for the Fisher denominator
KEYSTROKE_TIER = 17                     # text-only inputs zero this tier


# Pre-compute the indices we actually measure (everything except tier 17).
_FEATURE_INDICES_MEASURED: List[int] = [
    idx for idx, code in enumerate(ALL_FEATURE_CODES)
    if FEATURE_TIER.get(code, 0) != KEYSTROKE_TIER
]
_FEATURE_INDICES_SKIPPED: List[int] = [
    idx for idx, code in enumerate(ALL_FEATURE_CODES)
    if FEATURE_TIER.get(code, 0) == KEYSTROKE_TIER
]


@dataclass(frozen=True)
class StabilityReport:
    """Result of ``per_feature_stability`` — everything the writer needs."""

    feature_codes: List[str]                  # length 103, ordered by ALL_FEATURE_CODES
    feature_tiers: List[int]                  # parallel to feature_codes
    lengths: List[int]                        # the window sizes evaluated, ascending
    fisher_matrix: List[List[float]]          # shape (n_features, n_lengths); NaN for tier-17 rows
    window_counts: List[Dict[str, int]]       # per length: {author_id: n_windows}
    author_word_counts: Dict[str, int]
    excluded_indices: List[int]               # tier-17 feature indices
    notes: List[str] = field(default_factory=list)


def compute_feature_matrix(
    author_texts: Dict[str, str],
    length: int,
    *,
    max_windows: Optional[int] = None,
) -> Dict[str, np.ndarray]:
    """
    Slice each author's text into ``length``-word windows and return a
    ``{author_id: (k_a, FEATURE_DIM)}`` matrix.

    Authors whose full text is shorter than ``length`` words get an
    empty matrix (shape ``(0, FEATURE_DIM)``); the caller is expected
    to filter them out before computing Fisher's ratio.

    Args:
        max_windows: hard cap on windows per author. With ~650ms per
            ``feature_vector`` call, an uncapped pass over an 800k-word
            corpus at L=250 would take ~30 min. The default at the
            ``run.py`` layer caps at 12 windows/author — enough for a
            stable within-author variance estimate. Windows beyond the
            cap are dropped from the END of the text (they would have
            been the lowest-numbered chronologically).
    """
    out: Dict[str, np.ndarray] = {}
    for author_id, text in author_texts.items():
        windows = slide(text, length, overlap=0.0)
        if max_windows is not None and len(windows) > max_windows:
            windows = windows[:max_windows]
        if not windows:
            out[author_id] = np.zeros((0, FEATURE_DIM), dtype=np.float64)
            continue
        rows: List[np.ndarray] = []
        for w in windows:
            try:
                fv = feature_vector(w)
            except Exception:                                       # pragma: no cover
                log.warning("feature_vector failed on a window for %s @ %d",
                            author_id, length, exc_info=True)
                continue
            rows.append(np.asarray(fv, dtype=np.float64))
        out[author_id] = np.vstack(rows) if rows else \
                         np.zeros((0, FEATURE_DIM), dtype=np.float64)
    return out


def fisher_ratio(
    matrices: Dict[str, np.ndarray],
) -> np.ndarray:
    """
    Fisher discriminant ratio per feature.

    For each feature index i:
        within_var[i]  = mean over authors of var(matrix_a[:, i])
        between_var[i] = var across authors of mean(matrix_a[:, i])
        F[i]           = between_var[i] / (within_var[i] + EPS)

    Authors with zero windows at this length are silently dropped from
    the per-author aggregates (they contribute neither a mean nor a
    variance). If fewer than 2 authors remain, F is all-NaN at this
    length — the report writer will flag the cell.
    """
    populated: List[np.ndarray] = [m for m in matrices.values() if m.shape[0] > 0]
    if len(populated) < 2:
        return np.full(FEATURE_DIM, np.nan, dtype=np.float64)

    # within_var[i] — average each author's per-feature variance.
    within = np.stack([m.var(axis=0, ddof=0) for m in populated], axis=0).mean(axis=0)

    # between_var[i] — variance of the per-author means across authors.
    author_means = np.stack([m.mean(axis=0) for m in populated], axis=0)
    between = author_means.var(axis=0, ddof=0)

    return between / (within + EPS)


def per_feature_stability(
    author_texts: Dict[str, str],
    lengths: Sequence[int] = (250, 500, 1000, 2000, 5000),
    *,
    max_windows_per_author: Optional[int] = None,
) -> StabilityReport:
    """
    Run the full study. Returns a ``StabilityReport`` ready to hand to
    ``validation.stability.report.write_report``.

    Tier-17 features are recorded in ``excluded_indices`` and their rows
    in ``fisher_matrix`` are filled with NaN — the writer omits them
    from the ranked top/bottom lists.

    Args:
        max_windows_per_author: see ``compute_feature_matrix``. The
            ``run.py`` orchestrator defaults this to 12 so the study
            finishes in a few minutes on a laptop.
    """
    lengths_sorted = sorted(set(int(L) for L in lengths))
    feature_codes = list(ALL_FEATURE_CODES)
    feature_tiers = [int(FEATURE_TIER.get(c, 0)) for c in feature_codes]

    n_features = len(feature_codes)
    fisher_matrix: List[List[float]] = [
        [float("nan")] * len(lengths_sorted) for _ in range(n_features)
    ]
    window_counts: List[Dict[str, int]] = []

    for col, L in enumerate(lengths_sorted):
        log.info("[stability] computing length=%d (%d authors)…", L, len(author_texts))
        matrices = compute_feature_matrix(
            author_texts, L, max_windows=max_windows_per_author,
        )
        window_counts.append({a: int(m.shape[0]) for a, m in matrices.items()})
        F = fisher_ratio(matrices)
        for row in _FEATURE_INDICES_MEASURED:
            fisher_matrix[row][col] = float(F[row])
        # tier-17 rows stay NaN

    notes: List[str] = []
    if _FEATURE_INDICES_SKIPPED:
        notes.append(
            f"{len(_FEATURE_INDICES_SKIPPED)} tier-17 (keystroke) features were "
            f"excluded — text-only input gives them constant 0.5, so F is undefined."
        )

    return StabilityReport(
        feature_codes=feature_codes,
        feature_tiers=feature_tiers,
        lengths=lengths_sorted,
        fisher_matrix=fisher_matrix,
        window_counts=window_counts,
        author_word_counts={a: len(text.split()) for a, text in author_texts.items()},
        excluded_indices=list(_FEATURE_INDICES_SKIPPED),
        notes=notes,
    )
