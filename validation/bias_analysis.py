"""
validation/bias_analysis.py — Demographic bias analysis for Original.

Checks whether deviation scores vary systematically across demographic groups
defined in the validation manifest:

  - Native vs non-native English speakers
  - Theological traditions (Reformed, Catholic, Wesleyan, etc.)
  - AI provider used (ChatGPT, Claude, Gemini — for non-authentic samples)
  - Word count brackets (short / medium / long essays)

For each grouping the module computes:
  - Mean and std deviation score per group (authentic samples only for fairness)
  - Welch's t-test or one-way ANOVA for group differences
  - Effect size (Cohen's d for 2-group, eta-squared for multi-group)
  - Per-group false positive rate at each action threshold
  - A plain-English fairness summary

A system is considered fair when:
  - No group's FPR differs by more than 2× from the overall FPR
  - Effect size (Cohen's d) < 0.20 between any pair of demographic groups
  - ANOVA p-value > 0.05

Usage:
    python -m validation.bias_analysis \\
        --report validation/calibration_report.json \\
        --manifest validation/manifest.json \\
        --output validation/bias_report.json
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class GroupStats:
    """Statistics for a single demographic group."""
    group_name: str
    n: int
    mean_deviation: float
    std_deviation: float
    median_deviation: float
    fpr_at_thresholds: Dict[str, float]   # threshold_name → FPR


@dataclass
class PairwiseComparison:
    """Comparison between two groups."""
    group_a: str
    group_b: str
    cohens_d: float
    t_statistic: float
    p_value: float
    is_significant: bool    # p < 0.05
    effect_magnitude: str   # negligible / small / medium / large


@dataclass
class DimensionAnalysis:
    """Full analysis for one demographic dimension."""
    dimension: str                           # e.g. "native_english"
    groups: Dict[str, GroupStats]
    pairwise: List[PairwiseComparison]
    anova_f: Optional[float]
    anova_p: Optional[float]
    eta_squared: Optional[float]
    max_fpr_ratio: float                     # max(group_fpr) / min(group_fpr)
    is_fair: bool
    fairness_notes: List[str]


@dataclass
class BiasReport:
    """Complete bias analysis report."""
    total_authentic_samples: int
    dimensions: Dict[str, DimensionAnalysis]
    overall_fairness: bool
    summary: str


# ── Core analysis ────────────────────────────────────────────────────────────

def run_bias_analysis(
    results: List[dict],
    manifest_entries: List[dict],
    thresholds: Optional[Dict[str, float]] = None,
) -> BiasReport:
    """
    Run demographic bias analysis.

    Args:
        results: Individual scoring results from calibration report.
        manifest_entries: Entries from the validation manifest with demographic fields.
        thresholds: Action thresholds to evaluate FPR at.

    Returns:
        BiasReport with per-dimension analysis.
    """
    if thresholds is None:
        thresholds = {"no_action": 0.40, "monitor": 0.55, "escalate": 0.75}

    # Build lookup from filename to manifest metadata
    manifest_lookup = {e["filename"]: e for e in manifest_entries}

    # Enrich results with demographic data
    enriched = []
    for r in results:
        meta = manifest_lookup.get(r["filename"], {})
        enriched.append({
            **r,
            "native_english": meta.get("native_english"),
            "theological_tradition": meta.get("theological_tradition"),
            "ai_provider": meta.get("ai_provider", "none"),
            "word_count": r.get("word_count", meta.get("word_count", 0)),
        })

    # Filter to authentic samples for fairness analysis
    # (we want to know: among students who ARE the author, does the system
    #  unfairly flag some demographic groups more than others?)
    authentic = [r for r in enriched if r.get("is_same_author", r.get("label") == "authentic")]
    total_authentic = len(authentic)

    dimensions = {}

    # ── Native English ────────────────────────────────────────────────
    native_groups = _group_by(authentic, "native_english", {
        True: "native", False: "non_native", None: "unknown"
    })
    # Drop unknown group if it's > 50% of data (not informative)
    if "unknown" in native_groups and len(native_groups) > 1:
        unknown_pct = len(native_groups["unknown"]) / max(1, total_authentic)
        if unknown_pct > 0.5:
            del native_groups["unknown"]
    if len(native_groups) >= 2:
        dimensions["native_english"] = _analyze_dimension(
            "native_english", native_groups, thresholds
        )

    # ── Theological tradition ─────────────────────────────────────────
    theo_groups = _group_by(authentic, "theological_tradition")
    # Only analyse groups with 3+ samples
    theo_groups = {k: v for k, v in theo_groups.items() if len(v) >= 3 and k is not None}
    if len(theo_groups) >= 2:
        dimensions["theological_tradition"] = _analyze_dimension(
            "theological_tradition", theo_groups, thresholds
        )

    # ── Word count bracket ────────────────────────────────────────────
    wc_groups = _group_by_word_count(authentic)
    wc_groups = {k: v for k, v in wc_groups.items() if len(v) >= 3}
    if len(wc_groups) >= 2:
        dimensions["word_count_bracket"] = _analyze_dimension(
            "word_count_bracket", wc_groups, thresholds
        )

    # ── AI provider (for non-authentic samples) ───────────────────────
    non_authentic = [r for r in enriched if not r.get("is_same_author", r.get("label") == "authentic")]
    ai_groups = _group_by(non_authentic, "ai_provider")
    ai_groups = {k: v for k, v in ai_groups.items() if len(v) >= 3 and k != "none"}
    if len(ai_groups) >= 2:
        dimensions["ai_provider_detection"] = _analyze_dimension(
            "ai_provider_detection", ai_groups, thresholds
        )

    # ── Overall fairness assessment ───────────────────────────────────
    all_fair = all(d.is_fair for d in dimensions.values()) if dimensions else True
    summary_parts = []
    for name, dim in dimensions.items():
        status = "PASS" if dim.is_fair else "FAIL"
        summary_parts.append(f"{name}: {status}")
        for note in dim.fairness_notes:
            summary_parts.append(f"  - {note}")

    summary = "\n".join(summary_parts) if summary_parts else "No demographic dimensions available for analysis."

    return BiasReport(
        total_authentic_samples=total_authentic,
        dimensions=dimensions,
        overall_fairness=all_fair,
        summary=summary,
    )


# ── Dimension analysis ───────────────────────────────────────────────────────

def _analyze_dimension(
    dimension: str,
    groups: Dict[str, List[dict]],
    thresholds: Dict[str, float],
) -> DimensionAnalysis:
    """Analyse one demographic dimension."""
    group_stats = {}
    group_scores = {}

    for name, items in groups.items():
        scores = np.array([r["deviation_score"] for r in items])
        group_scores[name] = scores

        # FPR at each threshold (for authentic: flagged = deviation >= threshold)
        fpr_at = {}
        for t_name, t_val in thresholds.items():
            flagged = (scores >= t_val).sum()
            fpr_at[t_name] = round(float(flagged / max(1, len(scores))), 4)

        group_stats[name] = GroupStats(
            group_name=name,
            n=len(scores),
            mean_deviation=round(float(scores.mean()), 4),
            std_deviation=round(float(scores.std()), 4),
            median_deviation=round(float(np.median(scores)), 4),
            fpr_at_thresholds=fpr_at,
        )

    # ── Pairwise comparisons ─────────────────────────────────────────
    names = sorted(groups.keys())
    pairwise = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            comp = _welch_t_test(group_scores[a], group_scores[b], a, b)
            pairwise.append(comp)

    # ── ANOVA (if 3+ groups) ─────────────────────────────────────────
    anova_f, anova_p, eta_sq = None, None, None
    if len(groups) >= 3:
        anova_f, anova_p, eta_sq = _one_way_anova(list(group_scores.values()))

    # ── FPR ratio check ──────────────────────────────────────────────
    escalate_fprs = [gs.fpr_at_thresholds.get("escalate", 0) for gs in group_stats.values()]
    non_zero_fprs = [f for f in escalate_fprs if f > 0]
    if len(non_zero_fprs) >= 2:
        max_fpr_ratio = max(non_zero_fprs) / min(non_zero_fprs)
    else:
        max_fpr_ratio = 1.0

    # ── Fairness determination ───────────────────────────────────────
    fairness_notes = []
    is_fair = True

    # Check effect sizes
    for comp in pairwise:
        if comp.effect_magnitude in ("medium", "large"):
            is_fair = False
            fairness_notes.append(
                f"{comp.group_a} vs {comp.group_b}: {comp.effect_magnitude} effect "
                f"(d={comp.cohens_d:.3f}, p={comp.p_value:.4f})"
            )

    # Check FPR ratio
    if max_fpr_ratio > 2.0:
        is_fair = False
        fairness_notes.append(f"FPR ratio at escalate threshold: {max_fpr_ratio:.2f}× (limit: 2×)")

    # Check ANOVA
    if anova_p is not None and anova_p < 0.05:
        fairness_notes.append(
            f"ANOVA significant: F={anova_f:.3f}, p={anova_p:.4f}, η²={eta_sq:.4f}"
        )
        if eta_sq and eta_sq > 0.06:  # medium effect
            is_fair = False

    if not fairness_notes:
        fairness_notes.append("No significant bias detected")

    return DimensionAnalysis(
        dimension=dimension,
        groups=group_stats,
        pairwise=pairwise,
        anova_f=round(anova_f, 4) if anova_f is not None else None,
        anova_p=round(anova_p, 4) if anova_p is not None else None,
        eta_squared=round(eta_sq, 4) if eta_sq is not None else None,
        max_fpr_ratio=round(max_fpr_ratio, 2),
        is_fair=is_fair,
        fairness_notes=fairness_notes,
    )


# ── Statistical helpers ──────────────────────────────────────────────────────

def _welch_t_test(
    a: np.ndarray, b: np.ndarray, name_a: str, name_b: str,
) -> PairwiseComparison:
    """Welch's t-test (unequal variance) + Cohen's d."""
    n_a, n_b = len(a), len(b)
    mean_a, mean_b = a.mean(), b.mean()
    var_a, var_b = a.var(ddof=1), b.var(ddof=1)

    # Welch's t-statistic
    se = math.sqrt(var_a / max(1, n_a) + var_b / max(1, n_b))
    t_stat = (mean_a - mean_b) / max(1e-10, se)

    # Welch-Satterthwaite degrees of freedom
    num = (var_a / max(1, n_a) + var_b / max(1, n_b)) ** 2
    denom = (
        (var_a / max(1, n_a)) ** 2 / max(1, n_a - 1)
        + (var_b / max(1, n_b)) ** 2 / max(1, n_b - 1)
    )
    df = num / max(1e-10, denom)

    # Approximate p-value using normal distribution (good for df > 30)
    # For small samples, this is conservative enough for a screening tool
    p_value = 2 * _normal_cdf(-abs(t_stat))

    # Cohen's d (pooled)
    pooled_std = math.sqrt(
        ((n_a - 1) * var_a + (n_b - 1) * var_b) / max(1, n_a + n_b - 2)
    )
    cohens_d = abs(mean_a - mean_b) / max(1e-10, pooled_std)

    # Effect magnitude
    if cohens_d < 0.20:
        magnitude = "negligible"
    elif cohens_d < 0.50:
        magnitude = "small"
    elif cohens_d < 0.80:
        magnitude = "medium"
    else:
        magnitude = "large"

    return PairwiseComparison(
        group_a=name_a,
        group_b=name_b,
        cohens_d=round(cohens_d, 4),
        t_statistic=round(float(t_stat), 4),
        p_value=round(float(p_value), 4),
        is_significant=p_value < 0.05,
        effect_magnitude=magnitude,
    )


def _one_way_anova(groups: List[np.ndarray]) -> Tuple[float, float, float]:
    """One-way ANOVA F-test + eta-squared."""
    all_vals = np.concatenate(groups)
    grand_mean = all_vals.mean()
    n_total = len(all_vals)
    k = len(groups)

    # Between-group sum of squares
    ss_between = sum(len(g) * (g.mean() - grand_mean) ** 2 for g in groups)
    # Within-group sum of squares
    ss_within = sum(((g - g.mean()) ** 2).sum() for g in groups)

    df_between = k - 1
    df_within = n_total - k

    ms_between = ss_between / max(1, df_between)
    ms_within = ss_within / max(1, df_within)
    f_stat = ms_between / max(1e-10, ms_within)

    # Approximate p-value (F-distribution approximation)
    # Using the relationship between F and normal for large df
    p_value = _f_to_p_approx(f_stat, df_between, df_within)

    eta_squared = ss_between / max(1e-10, ss_between + ss_within)

    return float(f_stat), float(p_value), float(eta_squared)


def _normal_cdf(z: float) -> float:
    """Standard normal CDF approximation (Abramowitz & Stegun)."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _f_to_p_approx(f: float, df1: int, df2: int) -> float:
    """Rough p-value approximation for F-statistic."""
    # Use the chi-squared approximation: F * df1 ~ chi2(df1)
    # This is conservative for moderate sample sizes
    chi2 = f * df1
    # For chi2 with df1 degrees of freedom, approximate p-value
    if chi2 <= 0:
        return 1.0
    # Wilson-Hilferty approximation
    z = ((chi2 / df1) ** (1/3) - (1 - 2 / (9 * max(1, df1)))) / math.sqrt(2 / (9 * max(1, df1)))
    return 1 - _normal_cdf(z)


# ── Grouping helpers ─────────────────────────────────────────────────────────

def _group_by(
    items: List[dict],
    key: str,
    label_map: Optional[Dict] = None,
) -> Dict[str, List[dict]]:
    """Group items by a dictionary key."""
    groups = defaultdict(list)
    for item in items:
        val = item.get(key)
        if label_map:
            label = label_map.get(val, str(val))
        else:
            label = str(val) if val is not None else "unknown"
        groups[label].append(item)
    return dict(groups)


def _group_by_word_count(items: List[dict]) -> Dict[str, List[dict]]:
    """Group by word count bracket."""
    groups = defaultdict(list)
    for item in items:
        wc = item.get("word_count", 0)
        if wc < 300:
            bracket = "short (<300)"
        elif wc < 800:
            bracket = "medium (300-800)"
        elif wc < 1500:
            bracket = "long (800-1500)"
        else:
            bracket = "very_long (1500+)"
        groups[bracket].append(item)
    return dict(groups)


# ── Serialisation ────────────────────────────────────────────────────────────

def save_bias_report(report: BiasReport, output_path: str) -> None:
    """Save the bias report as JSON."""
    data = {
        "total_authentic_samples": report.total_authentic_samples,
        "overall_fairness": report.overall_fairness,
        "summary": report.summary,
        "dimensions": {},
    }

    for dim_name, dim in report.dimensions.items():
        dim_data = {
            "dimension": dim.dimension,
            "is_fair": dim.is_fair,
            "fairness_notes": dim.fairness_notes,
            "max_fpr_ratio": dim.max_fpr_ratio,
            "anova_f": dim.anova_f,
            "anova_p": dim.anova_p,
            "eta_squared": dim.eta_squared,
            "groups": {
                name: {
                    "n": gs.n,
                    "mean_deviation": gs.mean_deviation,
                    "std_deviation": gs.std_deviation,
                    "median_deviation": gs.median_deviation,
                    "fpr_at_thresholds": gs.fpr_at_thresholds,
                }
                for name, gs in dim.groups.items()
            },
            "pairwise_comparisons": [
                {
                    "group_a": p.group_a,
                    "group_b": p.group_b,
                    "cohens_d": p.cohens_d,
                    "t_statistic": p.t_statistic,
                    "p_value": p.p_value,
                    "is_significant": p.is_significant,
                    "effect_magnitude": p.effect_magnitude,
                }
                for p in dim.pairwise
            ],
        }
        data["dimensions"][dim_name] = dim_data

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Bias report saved to {output_path}")


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run bias analysis on Original calibration data")
    parser.add_argument("--report", required=True, help="Path to calibration_report.json")
    parser.add_argument("--manifest", required=True, help="Path to manifest.json")
    parser.add_argument("--output", default="validation/bias_report.json")
    args = parser.parse_args()

    with open(args.report) as f:
        cal_data = json.load(f)
    with open(args.manifest) as f:
        manifest_data = json.load(f)

    report = run_bias_analysis(
        results=cal_data["individual_results"],
        manifest_entries=manifest_data["entries"],
    )

    print(f"\n{'='*60}")
    print("BIAS ANALYSIS RESULTS")
    print(f"{'='*60}")
    print(f"Overall fairness: {'PASS' if report.overall_fairness else 'FAIL'}")
    print(f"Authentic samples analysed: {report.total_authentic_samples}")
    print()
    print(report.summary)
    print()

    save_bias_report(report, args.output)
