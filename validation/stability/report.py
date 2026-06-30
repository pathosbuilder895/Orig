"""
report.py — JSON + Markdown + CSV emitter for the length-stability study.

Mirrors the pattern of ``validation/benchmark/report.py:47-65`` but
writes to a separate ``validation/stability/<YYYY-MM-DD>/`` tree so the
stability output doesn't pollute the benchmarks tree.

Emits four files:

  report.json              — full 103×L Fisher matrix + corpus state + env lock
  report.md                — readable summary (top-30, bottom-20, per-tier)
  length_stability.csv     — one row per feature
  per_tier_summary.csv     — one row per tier (excluding 0 = comparison
                             and 17 = keystroke)

A reviewer should be able to read report.md alone and walk away knowing
which 30 features to lean on at 500 words and which tiers to be most
suspicious of on short inputs.
"""

from __future__ import annotations

import csv
import datetime
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .stability import StabilityReport


# Tier 0 = comparison features (not really a coherent "tier" in the
# weight-schedule sense); tier 17 = keystroke features (excluded
# entirely because feature_vector returns constant 0.5 for them).
_TIERS_TO_AGGREGATE = list(range(1, 17))


# ── Paths ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StabilityPaths:
    root: Path
    json_path: Path
    md_path: Path
    feature_csv: Path
    tier_csv: Path


def paths_for(base: str = "validation/stability") -> StabilityPaths:
    """Today's directory for the stability study; mkdir-p'd."""
    today = datetime.date.today().isoformat()
    root = Path(base) / today
    root.mkdir(parents=True, exist_ok=True)
    return StabilityPaths(
        root=root,
        json_path=root / "report.json",
        md_path=root / "report.md",
        feature_csv=root / "length_stability.csv",
        tier_csv=root / "per_tier_summary.csv",
    )


# ── Main writer ──────────────────────────────────────────────────────────────

def write_report(
    paths: StabilityPaths,
    *,
    report: StabilityReport,
    env_lock: object,
    extra: Optional[dict] = None,
) -> StabilityPaths:
    """Materialise the full report family from a ``StabilityReport``."""
    extra = extra or {}
    lengths = report.lengths

    # ── JSON ──
    j = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "environment": _env_lock_to_dict(env_lock),
        "corpus": {
            "authors": sorted(report.author_word_counts.keys()),
            "n_authors": len(report.author_word_counts),
            "word_counts": report.author_word_counts,
            "window_counts_per_length": [
                {"length": L, "per_author": wc}
                for L, wc in zip(lengths, report.window_counts)
            ],
        },
        "lengths": lengths,
        "fisher_matrix": [
            {
                "feature": code,
                "tier": int(tier),
                "F": _row_to_json(report.fisher_matrix[idx]),
                "stability_ratio_500_over_5000": _stability_ratio(
                    report.fisher_matrix[idx], lengths
                ),
            }
            for idx, (code, tier) in enumerate(
                zip(report.feature_codes, report.feature_tiers)
            )
        ],
        "excluded_indices": report.excluded_indices,
        "notes": report.notes,
        "extra": extra,
    }
    paths.json_path.write_text(json.dumps(j, indent=2))

    # ── CSVs ──
    _write_feature_csv(paths.feature_csv, report)
    _write_tier_csv(paths.tier_csv, report)

    # ── Markdown ──
    paths.md_path.write_text(_render_markdown(report, extra=extra))

    return paths


# ── Tabular helpers ─────────────────────────────────────────────────────────

def _stability_ratio(row: List[float], lengths: List[int]) -> Optional[float]:
    """F(500) / F(5000) — close to 1 = stable, close to 0 = fragile."""
    if 500 not in lengths or 5000 not in lengths:
        return None
    a = row[lengths.index(500)]
    b = row[lengths.index(5000)]
    if math.isnan(a) or math.isnan(b) or b <= 0:
        return None
    return round(a / b, 4)


def _row_to_json(row: List[float]) -> List[Optional[float]]:
    """JSON-friendly variant of a Fisher row (NaN → None, round to 4 dp)."""
    return [None if math.isnan(v) else round(v, 4) for v in row]


def _write_feature_csv(path: Path, report: StabilityReport) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        headers = ["feature_code", "tier"] + [f"F_{L}" for L in report.lengths] + ["stability_ratio_500_over_5000"]
        w.writerow(headers)
        for idx, (code, tier) in enumerate(zip(report.feature_codes, report.feature_tiers)):
            row_vals = report.fisher_matrix[idx]
            csv_row = [code, tier]
            for v in row_vals:
                csv_row.append("" if math.isnan(v) else f"{v:.4f}")
            sr = _stability_ratio(row_vals, report.lengths)
            csv_row.append("" if sr is None else f"{sr:.4f}")
            w.writerow(csv_row)


def _write_tier_csv(path: Path, report: StabilityReport) -> None:
    """One row per tier (1..16). Tier 0 + 17 are excluded."""
    rows_by_tier: Dict[int, List[List[float]]] = {t: [] for t in _TIERS_TO_AGGREGATE}
    for idx, tier in enumerate(report.feature_tiers):
        if tier in rows_by_tier:
            rows_by_tier[tier].append(report.fisher_matrix[idx])

    lengths = report.lengths
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tier", "n_features"]
                   + [f"mean_F_{L}" for L in lengths]
                   + ["mean_stability_ratio_500_5000", "flag"])
        for tier in sorted(rows_by_tier.keys()):
            rows = [r for r in rows_by_tier[tier] if not all(math.isnan(v) for v in r)]
            if not rows:
                continue
            means_by_length = [
                _mean_skipnan([r[col] for r in rows])
                for col in range(len(lengths))
            ]
            ratios = [_stability_ratio(r, lengths) for r in rows]
            mean_ratio = _mean_skipnan([r for r in ratios if r is not None])
            csv_row = [tier, len(rows)]
            csv_row.extend("" if v is None else f"{v:.4f}" for v in means_by_length)
            csv_row.append("" if mean_ratio is None else f"{mean_ratio:.4f}")
            csv_row.append(_flag_for(mean_ratio))
            w.writerow(csv_row)


def _mean_skipnan(values) -> Optional[float]:
    vs = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return None if not vs else float(sum(vs) / len(vs))


def _flag_for(ratio: Optional[float]) -> str:
    if ratio is None:
        return "n/a"
    if ratio >= 0.7:
        return "HOLDS"
    if ratio >= 0.3:
        return "DEGRADES"
    return "COLLAPSES"


# ── Markdown render ─────────────────────────────────────────────────────────

def _render_markdown(report: StabilityReport, *, extra: dict) -> str:
    lines: List[str] = []
    lines.append("# Length-stability study")
    lines.append("")
    lines.append(f"_Generated {datetime.datetime.utcnow().isoformat()}Z_")
    lines.append("")
    lines.append("## Corpus")
    lines.append("")
    lines.append("| author | word count | " + " | ".join(f"windows@{L}" for L in report.lengths) + " |")
    lines.append("|---|---|" + "|".join("---" for _ in report.lengths) + "|")
    for author in sorted(report.author_word_counts.keys()):
        wc = report.author_word_counts[author]
        per_length = " | ".join(str(report.window_counts[col].get(author, 0))
                                for col in range(len(report.lengths)))
        lines.append(f"| {author} | {wc:,} | {per_length} |")
    lines.append("")
    if report.notes:
        lines.append("**Notes:**")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")

    # Ranked feature lists.
    measured = [
        (idx, report.feature_codes[idx], report.feature_tiers[idx],
         _stability_ratio(report.fisher_matrix[idx], report.lengths))
        for idx in range(len(report.feature_codes))
    ]
    measured = [m for m in measured if m[3] is not None]

    robust = sorted(measured, key=lambda x: -x[3])[:30]
    fragile = sorted(measured, key=lambda x: x[3])[:20]

    lines.append("## Top 30 length-robust features (F(500) / F(5000) descending)")
    lines.append("")
    lines.append("Features that keep most of their discriminating power on short inputs. "
                 "Phase-2 weight schedule should LEAN INTO these at low word count.")
    lines.append("")
    lines.append("| rank | feature | tier | F(500) | F(5000) | ratio |")
    lines.append("|---|---|---|---|---|---|")
    for i, (idx, code, tier, ratio) in enumerate(robust, start=1):
        f500 = _format_F(report.fisher_matrix[idx], report.lengths, 500)
        f5000 = _format_F(report.fisher_matrix[idx], report.lengths, 5000)
        lines.append(f"| {i} | `{code}` | {tier} | {f500} | {f5000} | {ratio:.3f} |")
    lines.append("")

    lines.append("## Bottom 20 length-fragile features (F(500) / F(5000) ascending)")
    lines.append("")
    lines.append("Features that lose most of their discriminating power on short inputs. "
                 "Phase-2 weight schedule should DOWN-WEIGHT these at low word count.")
    lines.append("")
    lines.append("| rank | feature | tier | F(500) | F(5000) | ratio |")
    lines.append("|---|---|---|---|---|---|")
    for i, (idx, code, tier, ratio) in enumerate(fragile, start=1):
        f500 = _format_F(report.fisher_matrix[idx], report.lengths, 500)
        f5000 = _format_F(report.fisher_matrix[idx], report.lengths, 5000)
        lines.append(f"| {i} | `{code}` | {tier} | {f500} | {f5000} | {ratio:.3f} |")
    lines.append("")

    # Per-tier aggregate.
    lines.append("## Per-tier aggregate")
    lines.append("")
    lines.append("Mean Fisher ratio per tier across the 5 length buckets. "
                 "**HOLDS** = stability ratio ≥ 0.7; **DEGRADES** = 0.3 ≤ ratio < 0.7; "
                 "**COLLAPSES** = ratio < 0.3. Tier 0 (comparison features) and tier 17 "
                 "(keystroke) are excluded from this aggregate.")
    lines.append("")
    lines.append("| tier | n features | "
                 + " | ".join(f"mean F({L})" for L in report.lengths)
                 + " | mean ratio | flag |")
    lines.append("|---|---|" + "|".join("---" for _ in report.lengths) + "|---|---|")

    for tier in _TIERS_TO_AGGREGATE:
        rows = [report.fisher_matrix[idx]
                for idx, t in enumerate(report.feature_tiers) if t == tier]
        rows = [r for r in rows if not all(math.isnan(v) for v in r)]
        if not rows:
            continue
        means = [_mean_skipnan([r[col] for r in rows])
                 for col in range(len(report.lengths))]
        ratios = [_stability_ratio(r, report.lengths) for r in rows]
        mean_ratio = _mean_skipnan([r for r in ratios if r is not None])
        flag = _flag_for(mean_ratio)
        per_L = " | ".join("n/a" if v is None else f"{v:.3f}" for v in means)
        ratio_str = "n/a" if mean_ratio is None else f"{mean_ratio:.3f}"
        lines.append(f"| {tier} | {len(rows)} | {per_L} | {ratio_str} | {flag} |")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_F(row: List[float], lengths: List[int], target: int) -> str:
    if target not in lengths:
        return "n/a"
    v = row[lengths.index(target)]
    return "n/a" if math.isnan(v) else f"{v:.3f}"


def _env_lock_to_dict(env_lock) -> dict:
    if env_lock is None:
        return {}
    if hasattr(env_lock, "__dict__"):
        return dict(env_lock.__dict__)
    if hasattr(env_lock, "_asdict"):
        return env_lock._asdict()
    return {}
