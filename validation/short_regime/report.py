"""Write short-regime results as report.json + report.md."""
from __future__ import annotations

import json
from pathlib import Path


def write_report(out_dir: Path, results: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(results, indent=2))
    lines = [
        "# Short-regime operating point (3×500-word baseline, 500-word probes)",
        "",
        "| combo | AUC | AUC 95% CI | catch@5% | catch CI | threshold | llr fallbacks |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: -r["catch_rate"]):
        lines.append(
            f"| {r['combo']} | {r['auc']:.3f} | {r['auc_ci'][0]:.3f}–{r['auc_ci'][1]:.3f} "
            f"| {r['catch_rate']:.3f} | {r['catch_ci'][0]:.3f}–{r['catch_ci'][1]:.3f} "
            f"| {r['threshold']:.3f} | {r['llr_fallbacks']} |"
        )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n")
