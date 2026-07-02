"""
binary_auc.py — per-author + aggregate metrics for the verification task.

Consumes the (author, y_true, y_score) rows the evaluator collects and
produces:

  - AUC + Brier
  - TPR at fixed FPR ∈ {0.01, 0.05, 0.10} — the Neyman-Pearson operating
    points a pilot would actually pick
  - Bootstrap 95% CI on each per-author AUC (percentile method, B=1000)

The math for TPR-at-FPR is standard: sort samples by y_score descending,
walk down until FPR is first satisfied, read the TPR at that point.
Nothing here re-implements the Born-rule scoring — the y_score values
are already ``authorship_probability`` from Original's scoring pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


BOOTSTRAP_B = 1000        # 1k iters gives ~1pp precision on the 95% CI
BOOTSTRAP_SEED = 1729     # match BENCHMARK_SEED for full reproducibility


@dataclass(frozen=True)
class AuthorMetrics:
    """Per-author metrics."""
    author: str
    n_same: int
    n_different: int
    auc: float
    auc_ci_lo: float          # bootstrap 95% CI lower
    auc_ci_hi: float          # bootstrap 95% CI upper
    brier: float
    tpr_at_fpr_01: Optional[float]
    tpr_at_fpr_05: Optional[float]
    tpr_at_fpr_10: Optional[float]


@dataclass(frozen=True)
class VerifyReport:
    """
    Whole-corpus summary + per-author breakdown.

    ``median_per_author_auc`` / ``iqr_per_author_auc`` are the HEADLINE
    numbers — each author's AUC is computed against ITS OWN baseline's
    score distribution, so it needs no cross-author calibration.

    ``pooled_uncalibrated_auc`` concatenates every author's rows into one
    big AUC computation. This is NOT directly comparable across authors:
    author A's deviation_score and author B's deviation_score are each
    computed relative to A's / B's own baseline statistics (mu, sigma),
    so pooling assumes those two distributions are on the same footing —
    an assumption this evaluator does not verify. Report it as a
    secondary/diagnostic number, not the pilot's headline claim.
    """
    n_authors: int
    skipped_authors: List[str]      # authors with n_same=0 or n_diff=0 — no metric possible
    total_same_pairs: int
    total_different_pairs: int
    pooled_uncalibrated_auc: float
    pooled_uncalibrated_auc_ci_lo: float
    pooled_uncalibrated_auc_ci_hi: float
    pooled_uncalibrated_brier: float
    pooled_uncalibrated_tpr_at_fpr_01: Optional[float]
    pooled_uncalibrated_tpr_at_fpr_05: Optional[float]
    pooled_uncalibrated_tpr_at_fpr_10: Optional[float]
    median_per_author_auc: float
    iqr_per_author_auc: Tuple[float, float]
    per_author: List[AuthorMetrics] = field(default_factory=list)


# ── AUC ─────────────────────────────────────────────────────────────────────

def auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """
    Mann-Whitney-U AUC, tie-corrected.

    AUC = P(score_positive > score_negative) + 0.5 · P(score_positive == score_negative).

    The earlier trapezoidal-rule implementation used ``np.argsort`` for
    ranking, which breaks ties by array position (mergesort is stable but
    NOT tie-aware) rather than averaging rank across tied scores. On
    heavily-tied inputs (e.g. every score = 0.5) that gave AUC = 1.0 or
    0.0 depending on which class happened to sort first — silently wrong
    in either direction. The correct answer for "no information content"
    is 0.5. This implementation computes the exact tie-corrected
    Mann-Whitney U statistic, which matches ``sklearn.metrics.roc_auc_score``.

    Returns 0.5 on a degenerate input (all one class, or empty).
    """
    y_true = np.asarray(y_true, dtype=np.int8)
    y_score = np.asarray(y_score, dtype=np.float64)
    if y_true.size == 0 or y_score.size == 0:
        return 0.5
    pos = y_score[y_true == 1]
    neg = y_score[y_true == 0]
    if pos.size == 0 or neg.size == 0:
        return 0.5
    # O(P·N) pairwise comparison — fine at our scale (hundreds of pairs).
    greater = (pos[:, None] > neg[None, :]).sum()
    equal = (pos[:, None] == neg[None, :]).sum()
    return float((greater + 0.5 * equal) / (pos.size * neg.size))


def brier(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    y_true = np.asarray(y_true, dtype=np.float64)
    y_score = np.asarray(y_score, dtype=np.float64)
    if y_true.size == 0:
        return float("nan")
    return float(np.mean((y_score - y_true) ** 2))


def tpr_at_fpr(y_true: np.ndarray, y_score: np.ndarray,
               target_fpr: float) -> Optional[float]:
    """
    Highest TPR achievable while keeping FPR ≤ ``target_fpr``.

    Returns None when:
      - there are no positives or no negatives to define TPR/FPR at all, OR
      - the negative count N is too small to express ``target_fpr`` (the
        finest achievable FPR step is 1/N; if that exceeds target_fpr,
        FPR=0 is the only reachable point ≤ target and the caller should
        not read a spurious 0.0 as "measured, and it's zero" — it means
        "this operating point isn't resolvable at this sample size").
        e.g. N=18 negatives → finest step 1/18 ≈ 0.056 > 0.01, so
        target_fpr=0.01 is unresolvable; only the exact-zero-FPR point
        (TPR at FPR=0) is available, which we still return since FPR=0
        does satisfy "≤ 0.01" — but we flag it via a stricter contract:
        return None only when NO row satisfies FPR ≤ target (which,
        since FPR starts at 0, only happens when P=0 or N=0).
    """
    y_true = np.asarray(y_true, dtype=np.int8)
    y_score = np.asarray(y_score, dtype=np.float64)
    P = int(y_true.sum())
    N = int(y_true.size - P)
    if P == 0 or N == 0:
        return None

    # Sort descending by score; walk down, computing (FPR, TPR) at each step.
    order = np.argsort(-y_score, kind="mergesort")
    y_sorted = y_true[order]
    tp = np.cumsum(y_sorted)
    fp = np.cumsum(1 - y_sorted)
    tpr = np.concatenate([[0.0], tp / P])
    fpr = np.concatenate([[0.0], fp / N])

    # We want the max TPR with FPR ≤ target. FPR[0] = 0.0 always satisfies
    # FPR ≤ target_fpr (target_fpr ≥ 0), so this array is never all-False
    # once we've passed the P==0/N==0 guard above.
    ok = fpr <= target_fpr
    return float(tpr[ok].max())


# ── Bootstrap AUC ────────────────────────────────────────────────────────────

def bootstrap_auc_ci(
    y_true: np.ndarray,
    y_score: np.ndarray,
    *,
    B: int = BOOTSTRAP_B,
    seed: int = BOOTSTRAP_SEED,
    alpha: float = 0.05,
) -> Tuple[float, float]:
    """
    Percentile-method 95% CI on the AUC, via STRATIFIED resampling.

    Resamples positives and negatives SEPARATELY (each with replacement,
    preserving their original counts), then computes AUC on the combined
    replicate. Stratifying is required at small sample sizes: with plain
    (unstratified) resampling of the full pool, a meaningful fraction of
    replicates draw zero positives or zero negatives by chance — each
    such replicate falls back to the degenerate AUC=0.5, and at small N
    those degenerate draws are common enough to pin the 2.5th percentile
    at exactly 0.5 even when the true AUC is 1.0. (Confirmed empirically:
    every N=3 public-authors author with a perfect same-author/different-
    author split reported auc_ci_lo=0.5 under the old unstratified draw.)
    Stratified resampling always has ≥1 positive and ≥1 negative per
    replicate (by construction — we resample from the non-empty original
    pools), which removes that failure mode.
    """
    y_true = np.asarray(y_true, dtype=np.int8)
    y_score = np.asarray(y_score, dtype=np.float64)
    if y_true.size == 0:
        return (0.5, 0.5)
    pos_idx = np.flatnonzero(y_true == 1)
    neg_idx = np.flatnonzero(y_true == 0)
    if pos_idx.size == 0 or neg_idx.size == 0:
        return (0.5, 0.5)
    rng = np.random.default_rng(seed)
    aucs = np.empty(B, dtype=np.float64)
    for b in range(B):
        p = rng.choice(pos_idx, size=pos_idx.size, replace=True)
        n = rng.choice(neg_idx, size=neg_idx.size, replace=True)
        idx = np.concatenate([p, n])
        aucs[b] = auc(y_true[idx], y_score[idx])
    lo = float(np.percentile(aucs, 100 * alpha / 2))
    hi = float(np.percentile(aucs, 100 * (1 - alpha / 2)))
    return (lo, hi)


# ── Per-author + aggregate ──────────────────────────────────────────────────

@dataclass
class _ScoringPair:
    """One (baseline_author, submission_author, deviation, probability) row."""
    baseline_author: str
    submission_author: str
    deviation: float
    probability: float

    @property
    def y_true(self) -> int:
        return 1 if self.baseline_author == self.submission_author else 0


def summarize(pairs: List[_ScoringPair]) -> VerifyReport:
    """Aggregate a list of scoring pairs into a full report."""
    import sys as _sys

    # Group by baseline_author.
    by_author: Dict[str, List[_ScoringPair]] = {}
    for p in pairs:
        by_author.setdefault(p.baseline_author, []).append(p)

    per_author: List[AuthorMetrics] = []
    skipped_authors: List[str] = []
    for author in sorted(by_author):
        rows = by_author[author]
        yt = np.array([r.y_true for r in rows], dtype=np.int8)
        ys = np.array([r.probability for r in rows], dtype=np.float64)
        n_same = int(yt.sum())
        n_diff = int(yt.size - n_same)
        if n_same == 0 or n_diff == 0:
            # Can't compute a meaningful binary metric — no same-author
            # or no different-author examples to contrast against.
            print(f"[verify] skip {author}: n_same={n_same}, n_diff={n_diff} "
                  f"(no metric possible)", file=_sys.stderr)
            skipped_authors.append(author)
            continue
        a = auc(yt, ys)
        lo, hi = bootstrap_auc_ci(yt, ys)
        per_author.append(AuthorMetrics(
            author=author,
            n_same=n_same,
            n_different=n_diff,
            auc=round(a, 4),
            auc_ci_lo=round(lo, 4),
            auc_ci_hi=round(hi, 4),
            brier=round(brier(yt, ys), 4),
            tpr_at_fpr_01=_maybe_round(tpr_at_fpr(yt, ys, 0.01)),
            tpr_at_fpr_05=_maybe_round(tpr_at_fpr(yt, ys, 0.05)),
            tpr_at_fpr_10=_maybe_round(tpr_at_fpr(yt, ys, 0.10)),
        ))

    # Pooled-uncalibrated: concatenate every eligible author's rows and
    # compute AUC + Brier on that pooled set. NOT the headline number —
    # see the VerifyReport docstring for why cross-author pooling needs
    # a calibration assumption this evaluator doesn't verify.
    all_yt = np.array([p.y_true for p in pairs], dtype=np.int8)
    all_ys = np.array([p.probability for p in pairs], dtype=np.float64)
    a = auc(all_yt, all_ys)
    lo, hi = bootstrap_auc_ci(all_yt, all_ys)

    author_aucs = np.array([am.auc for am in per_author], dtype=np.float64)
    return VerifyReport(
        n_authors=len(per_author),
        skipped_authors=skipped_authors,
        total_same_pairs=int(all_yt.sum()),
        total_different_pairs=int(all_yt.size - all_yt.sum()),
        pooled_uncalibrated_auc=round(a, 4),
        pooled_uncalibrated_auc_ci_lo=round(lo, 4),
        pooled_uncalibrated_auc_ci_hi=round(hi, 4),
        pooled_uncalibrated_brier=round(brier(all_yt, all_ys), 4),
        pooled_uncalibrated_tpr_at_fpr_01=_maybe_round(tpr_at_fpr(all_yt, all_ys, 0.01)),
        pooled_uncalibrated_tpr_at_fpr_05=_maybe_round(tpr_at_fpr(all_yt, all_ys, 0.05)),
        pooled_uncalibrated_tpr_at_fpr_10=_maybe_round(tpr_at_fpr(all_yt, all_ys, 0.10)),
        median_per_author_auc=round(float(np.median(author_aucs)), 4) if author_aucs.size else 0.5,
        iqr_per_author_auc=(
            round(float(np.percentile(author_aucs, 25)), 4) if author_aucs.size else 0.5,
            round(float(np.percentile(author_aucs, 75)), 4) if author_aucs.size else 0.5,
        ),
        per_author=per_author,
    )


def _maybe_round(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 4)
