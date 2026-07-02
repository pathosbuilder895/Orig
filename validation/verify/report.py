"""
report.py — JSON + Markdown emitter for the verification study.

Mirrors the pattern of ``validation/benchmark/report.py:47-65``.
Writes to ``validation/benchmarks/<YYYY-MM-DD>/verify_<label>/``.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .binary_auc import VerifyReport


@dataclass(frozen=True)
class VerifyPaths:
    root: Path
    json_path: Path
    md_path: Path


def paths_for(label: str, *, base: str = "validation/benchmarks") -> VerifyPaths:
    today = datetime.date.today().isoformat()
    root = Path(base) / today / f"verify_{label}"
    root.mkdir(parents=True, exist_ok=True)
    return VerifyPaths(root=root,
                       json_path=root / "report.json",
                       md_path=root / "report.md")


def write_report(paths: VerifyPaths,
                 *,
                 label: str,
                 report: VerifyReport,
                 env_lock: object,
                 corpus_dir: str,
                 manifest_path: str,
                 baselines: int,
                 extra: Optional[dict] = None) -> VerifyPaths:
    """Materialise the report family."""
    extra = extra or {}
    j = {
        "label": label,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "environment": _env_lock_to_dict(env_lock),
        "corpus": {"corpus_dir": corpus_dir, "manifest_path": manifest_path,
                   "baselines_per_author": baselines},
        "summary": {
            "n_authors":             report.n_authors,
            "skipped_authors":       report.skipped_authors,
            "total_same_pairs":      report.total_same_pairs,
            "total_different_pairs": report.total_different_pairs,
            # HEADLINE: each author's AUC needs no cross-author calibration.
            "median_per_author_auc": report.median_per_author_auc,
            "iqr_per_author_auc":    report.iqr_per_author_auc,
            # SECONDARY / diagnostic: pooling assumes cross-author score
            # comparability, which this evaluator does not verify. See
            # VerifyReport's docstring in binary_auc.py.
            "pooled_uncalibrated_auc":     report.pooled_uncalibrated_auc,
            "pooled_uncalibrated_auc_ci_95": [report.pooled_uncalibrated_auc_ci_lo,
                                              report.pooled_uncalibrated_auc_ci_hi],
            "pooled_uncalibrated_brier":   report.pooled_uncalibrated_brier,
            "pooled_uncalibrated_tpr_at_fpr": {
                "0.01": report.pooled_uncalibrated_tpr_at_fpr_01,
                "0.05": report.pooled_uncalibrated_tpr_at_fpr_05,
                "0.10": report.pooled_uncalibrated_tpr_at_fpr_10,
            },
        },
        "per_author": [asdict(am) for am in report.per_author],
        "extra": extra,
    }
    paths.json_path.write_text(json.dumps(j, indent=2, default=str))
    paths.md_path.write_text(_render_markdown(j))
    return paths


def _env_lock_to_dict(env_lock) -> dict:
    if env_lock is None:
        return {}
    if hasattr(env_lock, "__dict__"):
        return dict(env_lock.__dict__)
    return {}


def _render_markdown(j: dict) -> str:
    s = j["summary"]
    lines = []
    lines.append(f"# Binary authorship verification — {j['label']}")
    lines.append("")
    lines.append(f"_Generated {j['generated_at']}_")
    lines.append("")
    lines.append(f"Baselines per author: **{j['corpus']['baselines_per_author']}**")
    lines.append("")
    same_work = (j.get("extra") or {}).get("same_work_authors") or []
    if same_work:
        lines.append("> ⚠ **Corpus caveat**: for "
                     f"{len(same_work)} author(s) — {', '.join(same_work)} — "
                     "the baseline and held-out scoring essays are drawn from "
                     "the SAME source work (consecutive chunks of one book). "
                     "Their same-author AUC measures within-work continuity, "
                     "not just cross-work authorial voice. Read their numbers "
                     "as a narrower claim than the corpus-wide headline "
                     "implies until a disjoint second work is added per "
                     "author.")
        lines.append("")
    lines.append("## Headline: per-author AUC")
    lines.append("")
    lines.append("Each author's AUC is computed against ITS OWN baseline's score "
                 "distribution — no cross-author calibration assumption needed. "
                 "This is the number to quote.")
    lines.append("")
    lines.append(f"- **median AUC**: {s['median_per_author_auc']}  "
                 f"(IQR [{s['iqr_per_author_auc'][0]}, {s['iqr_per_author_auc'][1]}])")
    lines.append(f"- **authors evaluated**: {s['n_authors']}")
    if s["skipped_authors"]:
        lines.append(f"- **authors skipped** (no same-author or no different-author "
                     f"examples): {', '.join(s['skipped_authors'])}")
    lines.append(f"- **pair counts**: {s['total_same_pairs']} same-author, "
                 f"{s['total_different_pairs']} different-author")
    lines.append("")
    lines.append("## Secondary: pooled-uncalibrated AUC")
    lines.append("")
    lines.append("Concatenates every author's rows into one AUC. NOT directly "
                 "comparable across authors — each author's deviation_score is "
                 "relative to that author's own baseline mean/std, so pooling "
                 "assumes those distributions sit on the same footing, which is "
                 "not verified here. Reported as a diagnostic, not the headline claim.")
    lines.append("")
    lines.append(f"- **AUC**: {s['pooled_uncalibrated_auc']}  "
                 f"(95% CI [{s['pooled_uncalibrated_auc_ci_95'][0]}, "
                 f"{s['pooled_uncalibrated_auc_ci_95'][1]}])")
    lines.append(f"- **Brier**: {s['pooled_uncalibrated_brier']}")
    lines.append("")
    lines.append("### Pooled TPR at fixed FPR (Neyman-Pearson operating points)")
    lines.append("")
    lines.append("| target FPR | pooled TPR |")
    lines.append("|---|---|")
    for fpr in ("0.01", "0.05", "0.10"):
        v = s["pooled_uncalibrated_tpr_at_fpr"][fpr]
        lines.append(f"| {fpr} | {v if v is not None else 'n/a'} |")
    lines.append("")
    lines.append("## Per-author breakdown")
    lines.append("")
    lines.append("| author | n_same | n_diff | AUC | 95% CI | Brier | "
                 "TPR@FPR=0.01 | TPR@FPR=0.05 | TPR@FPR=0.10 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for am in j["per_author"]:
        ci = f"[{am['auc_ci_lo']}, {am['auc_ci_hi']}]"
        lines.append(
            f"| {am['author']} | {am['n_same']} | {am['n_different']} | "
            f"{am['auc']} | {ci} | {am['brier']} | "
            f"{am['tpr_at_fpr_01']} | {am['tpr_at_fpr_05']} | "
            f"{am['tpr_at_fpr_10']} |"
        )
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"
