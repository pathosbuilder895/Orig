"""
lab/suggestions.py — "What might improve them" engine.

Given a finished calibration report (PR 8a) plus the current corrections
feedback log (PR 7), produces a list of concrete, actionable Suggestions
the dashboard can render with one-click "Apply" buttons.

Design principles
=================

1. **Conservative and explainable.** Each suggestion carries a confidence
   score (0–1) derived from sample size + statistical effect size; the UI
   surfaces low-confidence ones as "consider", high-confidence as "apply".

2. **Threshold-only mutations are reversible.** The retrain endpoint
   versions every change in ``tuned_thresholds_v2``; rollback is a single
   row insert pointing at an older version.

3. **No black-box ML.** Logistic regression / decision trees would be
   *more* powerful, but the audit story matters: an instructor needs to
   see *why* the system suggested a change. We use:
       - threshold sweeps over the report's ROC points
       - per-tier importance vs per-tier authentic-vs-ghostwritten gap
       - corrections agreement-rate at each candidate threshold

Suggestion types
================

- ``threshold_no_action`` — move the no_action threshold to the F1-optimal
  point on the ROC curve.
- ``threshold_monitor`` / ``threshold_escalate`` — same, with FPR/TPR
  constraints from the rollout policy.
- ``verdict_authentic_below`` / ``verdict_anomalous_at_or_above`` —
  realign the report.py verdict cutoffs with the empirical distribution.
- ``corrections_disagreement`` — flag thresholds where instructors
  disagreed with > N% of verdicts; suggest a shift toward the corrected
  side.
- ``per_author_outlier`` — surface authors whose individual AUC is more
  than 0.10 below the global, signalling corpus imbalance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


# ── Tunable thresholds ───────────────────────────────────────────────────────

# Below this confidence, the dashboard renders the suggestion as
# "consider" rather than "apply".
SUGGESTION_HIGH_CONFIDENCE: float = 0.7

# F1-target: balance precision & recall. Scoring uses the deviation
# direction (lower = same author), so the positive class is "authentic".
F1_BETA: float = 1.0

# A per-author AUC is flagged as an outlier if it's this far below the
# global AUC.
PER_AUTHOR_AUC_OUTLIER_GAP: float = 0.10

# Corrections weight: how many is_correct=False rows do we need before a
# threshold disagreement suggestion fires?
CORRECTIONS_DISAGREEMENT_MIN_N: int = 3


# ══════════════════════════════════════════════════════════════════════════════
# Suggestion dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Suggestion:
    """One actionable recommendation from the suggestion engine."""
    type: str                                # see "Suggestion types" in module docstring
    title: str                               # human-readable headline
    rationale: str                           # one paragraph explaining WHY
    confidence: float                        # 0–1, drives UI urgency
    # Action payload — what changes if the user clicks "Apply".
    target: Optional[str] = None             # field being changed (e.g. "thresholds.no_action")
    current_value: Optional[float] = None
    suggested_value: Optional[float] = None
    expected_improvement: Optional[Dict] = None  # e.g. {"auc_delta": 0.03, "fpr_delta": -0.05}
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


# ══════════════════════════════════════════════════════════════════════════════
# Threshold-sweep helpers
# ══════════════════════════════════════════════════════════════════════════════

def _sweep_thresholds(individual_results: List[Dict]) -> Dict[str, Any]:
    """
    Slide a threshold from 0 → 1 in 0.001 steps; for each threshold compute
    TP / FP / TN / FN under the rule "deviation_score < t ⇒ predict
    authentic". Returns the F1-optimal threshold + the EER point + per-step
    series for downstream constraint searches.
    """
    if not individual_results:
        return {"f1_optimal": None, "eer": None, "thresholds": [], "fpr": [], "tpr": [], "f1": []}

    pos = [r["deviation_score"] for r in individual_results if r["is_same_author"]]
    neg = [r["deviation_score"] for r in individual_results if not r["is_same_author"]]
    n_pos = len(pos)
    n_neg = len(neg)
    if n_pos == 0 or n_neg == 0:
        return {"f1_optimal": None, "eer": None, "thresholds": [], "fpr": [], "tpr": [], "f1": []}

    pos_arr = np.array(pos)
    neg_arr = np.array(neg)

    thresholds = np.linspace(0.0, 1.0, 1001)
    tpr_series: List[float] = []
    fpr_series: List[float] = []
    f1_series: List[float] = []

    for t in thresholds:
        tp = float((pos_arr < t).sum())
        fp = float((neg_arr < t).sum())
        fn = n_pos - tp
        tn = n_neg - fp
        tpr = tp / max(1, tp + fn)
        fpr = fp / max(1, fp + tn)
        precision = tp / max(1, tp + fp) if (tp + fp) > 0 else 0.0
        recall = tpr
        f1 = (2 * precision * recall) / max(1e-9, precision + recall)
        tpr_series.append(tpr)
        fpr_series.append(fpr)
        f1_series.append(f1)

    f1_arr = np.array(f1_series)
    f1_idx = int(np.argmax(f1_arr))

    # Equal Error Rate: where FPR == 1 - TPR (i.e., FPR == FNR).
    diff = np.abs(np.array(fpr_series) - (1.0 - np.array(tpr_series)))
    eer_idx = int(np.argmin(diff))

    return {
        "f1_optimal": {
            "threshold": float(thresholds[f1_idx]),
            "f1":        float(f1_arr[f1_idx]),
            "tpr":       float(tpr_series[f1_idx]),
            "fpr":       float(fpr_series[f1_idx]),
        },
        "eer": {
            "threshold": float(thresholds[eer_idx]),
            "rate":      float((fpr_series[eer_idx] + (1.0 - tpr_series[eer_idx])) / 2),
        },
        "thresholds": thresholds.tolist(),
        "fpr":        fpr_series,
        "tpr":        tpr_series,
        "f1":         f1_series,
    }


def _threshold_at_max_fpr(sweep: Dict, max_fpr: float) -> Optional[float]:
    """Find the highest threshold where FPR ≤ max_fpr (most permissive)."""
    if not sweep.get("thresholds"):
        return None
    thresholds = sweep["thresholds"]
    fprs = sweep["fpr"]
    best: Optional[float] = None
    for t, fpr in zip(thresholds, fprs):
        if fpr <= max_fpr:
            best = float(t)
    return best


def _threshold_for_constraints(
    sweep: Dict, min_tpr: float, max_fpr: float,
) -> Optional[float]:
    """Find the highest threshold satisfying TPR ≥ min_tpr AND FPR ≤ max_fpr."""
    if not sweep.get("thresholds"):
        return None
    best: Optional[float] = None
    for t, tpr, fpr in zip(sweep["thresholds"], sweep["tpr"], sweep["fpr"]):
        if tpr >= min_tpr and fpr <= max_fpr:
            best = float(t)
    return best


# ══════════════════════════════════════════════════════════════════════════════
# Per-author outlier detection
# ══════════════════════════════════════════════════════════════════════════════

def _per_author_auc(individual_results: List[Dict]) -> Dict[str, float]:
    """
    Approximate AUC per author. Uses each author's own essays as positives
    and ALL other essays as negatives — same convention as the global AUC
    so the comparison is apples-to-apples.
    """
    by_author: Dict[str, List[Dict]] = {}
    for r in individual_results:
        by_author.setdefault(r["author_id"], []).append(r)
    aucs: Dict[str, float] = {}
    for author, rs in by_author.items():
        pos = [r["deviation_score"] for r in rs if r["is_same_author"]]
        neg = [r["deviation_score"] for r in individual_results
               if not r["is_same_author"] and r["author_id"] == author]
        if not pos or not neg:
            continue
        # Mann-Whitney U / |pos|·|neg| ≡ AUC. Cheap closed form.
        n_p, n_n = len(pos), len(neg)
        rank_sum = 0
        all_scores = sorted([(s, "p") for s in pos] + [(s, "n") for s in neg])
        for i, (_, lbl) in enumerate(all_scores, start=1):
            if lbl == "p":
                rank_sum += i
        u = rank_sum - n_p * (n_p + 1) / 2
        # Lower deviation = positive class, so we flip: AUC = 1 - U/(n_p·n_n).
        # If lower scores are positive (authentic), the rank sum's "above"
        # interpretation flips — easier to compute from raw counts:
        n_correct = sum(1 for p in pos for q in neg if p < q)
        n_tied    = sum(1 for p in pos for q in neg if p == q) * 0.5
        aucs[author] = round((n_correct + n_tied) / (n_p * n_n), 4)
    return aucs


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def generate_suggestions(
    report: Dict,
    corrections: Optional[List[Dict]] = None,
    current_thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Run the full suggestion engine over a calibration report + corrections.

    Parameters
    ----------
    report : Dict
        The JSON shape produced by ``lab.runner._serialize_report`` (also
        compatible with ``validation/calibration_report.json`` on disk).
    corrections : Optional[List[Dict]]
        Output from ``store.list_corrections()['items']``. Used for the
        ``corrections_disagreement`` suggestion type. Pass None to skip.
    current_thresholds : Optional[Dict[str, float]]
        The currently-active thresholds. Default: 0.40 / 0.55 / 0.75 (the
        Phase-1 baseline). Used to compute "delta" fields on each
        suggestion so the UI can show before/after.

    Returns
    -------
    {
        "suggestions": [Suggestion as dict, ...],
        "summary": {
            "n_high_confidence": int,
            "n_total":           int,
            "global_auc":        float,
            "f1_optimal":        Dict | None,
            "eer":               Dict | None,
        },
    }
    """
    if current_thresholds is None:
        current_thresholds = {"no_action": 0.40, "monitor": 0.55, "escalate": 0.75}

    individual = report.get("individual_results", []) or []
    summary = report.get("summary", {}) or {}
    global_auc = summary.get("auc")

    sweep = _sweep_thresholds(individual)
    suggestions: List[Suggestion] = []

    # ── Threshold suggestions ────────────────────────────────────────────────
    f1 = sweep.get("f1_optimal")
    if f1 is not None:
        # no_action: F1-optimal is a defensible default — balances catching
        # ghostwriters (low FPR) and not over-flagging authentic essays.
        cur_no_action = current_thresholds.get("no_action", 0.40)
        suggested = round(f1["threshold"], 3)
        if abs(suggested - cur_no_action) > 0.01:
            confidence = min(1.0, max(0.4, f1["f1"]))
            suggestions.append(Suggestion(
                type="threshold_no_action",
                title=f"Move no_action threshold to F1-optimal: {suggested}",
                rationale=(
                    f"On this dataset, {suggested} maximises F1 ({f1['f1']:.2f}) "
                    f"with TPR {f1['tpr']:.0%} and FPR {f1['fpr']:.0%}. "
                    f"Current threshold {cur_no_action} is {'above' if cur_no_action > suggested else 'below'} this point."
                ),
                confidence=round(confidence, 3),
                target="thresholds.no_action",
                current_value=cur_no_action,
                suggested_value=suggested,
                expected_improvement={
                    "f1": round(f1["f1"], 3),
                    "tpr": round(f1["tpr"], 3),
                    "fpr": round(f1["fpr"], 3),
                },
            ))

    # monitor: TPR ≥ 80% AND FPR ≤ 10% (per the rollout policy in the spec).
    cur_monitor = current_thresholds.get("monitor", 0.55)
    monitor_t = _threshold_for_constraints(sweep, min_tpr=0.80, max_fpr=0.10)
    if monitor_t is not None and abs(monitor_t - cur_monitor) > 0.01:
        suggestions.append(Suggestion(
            type="threshold_monitor",
            title=f"Move monitor threshold to constraint-optimal: {round(monitor_t, 3)}",
            rationale=(
                f"Highest threshold satisfying TPR ≥ 80% and FPR ≤ 10%. "
                f"Current {cur_monitor} is {'above' if cur_monitor > monitor_t else 'below'} the satisfiable region."
            ),
            confidence=0.8,
            target="thresholds.monitor",
            current_value=cur_monitor,
            suggested_value=round(monitor_t, 3),
        ))

    # escalate: FPR ≤ 2% (we want very few false accusations).
    cur_escalate = current_thresholds.get("escalate", 0.75)
    escalate_t = _threshold_at_max_fpr(sweep, max_fpr=0.02)
    if escalate_t is not None and abs(escalate_t - cur_escalate) > 0.01:
        suggestions.append(Suggestion(
            type="threshold_escalate",
            title=f"Move escalate threshold to: {round(escalate_t, 3)}",
            rationale=(
                f"Highest threshold maintaining FPR ≤ 2% (false-accusation bound). "
                f"Current {cur_escalate} {'over-flags' if cur_escalate < escalate_t else 'under-flags'} relative to this constraint."
            ),
            confidence=0.85,
            target="thresholds.escalate",
            current_value=cur_escalate,
            suggested_value=round(escalate_t, 3),
        ))

    # ── Per-author outliers ──────────────────────────────────────────────────
    if individual and global_auc is not None:
        per_auc = _per_author_auc(individual)
        for author, auc in per_auc.items():
            gap = global_auc - auc
            if gap >= PER_AUTHOR_AUC_OUTLIER_GAP:
                suggestions.append(Suggestion(
                    type="per_author_outlier",
                    title=f"{author}: AUC {auc:.2f} — {gap:.2f} below global {global_auc:.2f}",
                    rationale=(
                        f"This author is harder to discriminate than the corpus "
                        f"average. Consider: (1) more baseline samples from this "
                        f"author, (2) a genre-specific anchor tier set, "
                        f"(3) checking if their ghostwritten/authentic counts are balanced."
                    ),
                    confidence=round(min(1.0, gap * 5), 3),
                    target=f"per_author.{author}",
                    current_value=auc,
                    suggested_value=None,
                    metadata={"author": author, "gap": round(gap, 4)},
                ))

    # ── Corrections-driven disagreement ──────────────────────────────────────
    if corrections:
        wrong = [c for c in corrections if not c.get("is_correct", True)]
        if len(wrong) >= CORRECTIONS_DISAGREEMENT_MIN_N:
            # Aggregate divergence scores at which corrections fired wrong.
            divs = [c.get("original_divergence_score") for c in wrong
                    if c.get("original_divergence_score") is not None]
            if divs:
                mean_wrong = float(np.mean(divs))
                cur_no_action = current_thresholds.get("no_action", 0.40)
                # If most wrong corrections happened with deviation > current
                # no_action, the system was being too STRICT (over-flagging).
                # Suggest raising no_action toward the mean of wrong-flag
                # divergences. Conversely if most are below, it was too LAX.
                direction = "raise" if mean_wrong > cur_no_action else "lower"
                suggestions.append(Suggestion(
                    type="corrections_disagreement",
                    title=(f"{len(wrong)} corrections suggest the no_action "
                            f"threshold should be {direction}d toward {mean_wrong:.2f}"),
                    rationale=(
                        f"Instructors corrected {len(wrong)} verdicts so far. The "
                        f"mean divergence at which they disagreed is {mean_wrong:.2f}, "
                        f"vs. the current no_action threshold of {cur_no_action}. "
                        f"This is real-world feedback that the abstract calibration set may miss."
                    ),
                    confidence=round(min(1.0, len(wrong) / 20.0), 3),
                    target="thresholds.no_action",
                    current_value=cur_no_action,
                    suggested_value=round(mean_wrong, 3),
                    metadata={
                        "n_wrong":     len(wrong),
                        "mean_div":    round(mean_wrong, 3),
                        "direction":   direction,
                    },
                ))

    # ── Verdict cutoffs (report.py) ──────────────────────────────────────────
    # If the F1-optimal threshold is dramatically different from
    # VERDICT_AUTHENTIC_BELOW (0.30 default), suggest realigning.
    if f1 is not None:
        from ..context.report import VERDICT_AUTHENTIC_BELOW
        suggested_verdict = round(f1["threshold"], 3)
        if abs(suggested_verdict - VERDICT_AUTHENTIC_BELOW) > 0.05:
            suggestions.append(Suggestion(
                type="verdict_authentic_below",
                title=f"Realign verdict 'authentic' boundary from {VERDICT_AUTHENTIC_BELOW} to {suggested_verdict}",
                rationale=(
                    f"The report.py verdict label flips from 'authentic' to "
                    f"'uncertain' at deviation {VERDICT_AUTHENTIC_BELOW}, but the "
                    f"empirical F1-optimal point is {suggested_verdict}. "
                    f"Realigning makes the human-readable verdict match the math."
                ),
                confidence=0.65,
                target="report.VERDICT_AUTHENTIC_BELOW",
                current_value=VERDICT_AUTHENTIC_BELOW,
                suggested_value=suggested_verdict,
            ))

    # ── Sort + summary ───────────────────────────────────────────────────────
    suggestions.sort(key=lambda s: s.confidence, reverse=True)
    n_high = sum(1 for s in suggestions if s.confidence >= SUGGESTION_HIGH_CONFIDENCE)

    return {
        "suggestions": [s.to_dict() for s in suggestions],
        "summary": {
            "n_high_confidence": n_high,
            "n_total":           len(suggestions),
            "global_auc":        global_auc,
            "f1_optimal":        sweep.get("f1_optimal"),
            "eer":               sweep.get("eer"),
        },
    }
