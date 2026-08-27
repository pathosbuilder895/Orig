"""Render honest JSON/Markdown TermSim scorecards and baseline diffs."""
from __future__ import annotations

import json

HONESTY = (
    "Corpus-derived synthetic students (public-domain historical prose and committed "
    "seminary analogues), not real student data. Absolute rates do not transfer; "
    "same-script configuration differences are the meaningful result."
)


def build(cell: str, seed: int, metrics: dict, flags: dict, baseline: dict | None = None) -> dict:
    out = {"cell": cell, "seed": seed, "honesty": HONESTY, "flags": flags, "metrics": metrics}
    if baseline is not None:
        current = metrics["honest_term_flag_probability"]
        reference = baseline["honest_term_flag_probability"]
        out["diff_vs_baseline"] = {
            action: (
                current[action]["rate"] - reference[action]["rate"]
                if current[action]["rate"] is not None and reference[action]["rate"] is not None
                else None
            )
            for action in current
        }
    return out


def markdown(scorecard: dict) -> str:
    lines = [f"# TermSim scorecard: {scorecard['cell']}", "", f"> {scorecard['honesty']}", "",
             f"Seed: `{scorecard['seed']}`", "", "## Honest-term flag probability", ""]
    for action, result in scorecard["metrics"]["honest_term_flag_probability"].items():
        value = "unavailable" if result["rate"] is None else f"{result['rate']:.1%}"
        lines.append(f"- {action}: {value} (n={result['n']}, CI95={result['wilson_ci95']})")
    if "diff_vs_baseline" in scorecard:
        lines += ["", "## Difference from baseline", ""]
        movements = sorted(scorecard["diff_vs_baseline"].items(),
                           key=lambda item: abs(item[1] or 0), reverse=True)
        lines.extend(f"- {name}: {value:+.3f}" if value is not None else f"- {name}: unavailable"
                     for name, value in movements)
    return "\n".join(lines) + "\n"


def json_text(scorecard: dict) -> str:
    return json.dumps(scorecard, indent=2, sort_keys=True) + "\n"


def verify_diff_directions(metrics_by_cell: dict[str, dict]) -> list[dict]:
    """Directional sanity checks between matrix cells on identical scripts.

    LLR_ACTION_MODE=gate may only DOWNGRADE actions relative to shadow, so on
    the same script the TRANSFER term-flag probability under `baseline` (gate)
    must not exceed `llr-shadow`'s at any threshold. A violation means the
    harness compared different scripts or the mode leaked — either way the
    run's diffs are not trustworthy.
    """
    checks = []
    gate = metrics_by_cell.get("baseline")
    shadow = metrics_by_cell.get("llr-shadow")
    if gate and shadow:
        for threshold in ("monitor", "schedule_conversation", "escalate"):
            lhs = gate["scenario_term_flag_probability"]["TRANSFER"][threshold]["rate"]
            rhs = shadow["scenario_term_flag_probability"]["TRANSFER"][threshold]["rate"]
            comparable = lhs is not None and rhs is not None
            checks.append({
                "check": f"gate<=shadow TRANSFER {threshold}",
                "gate_rate": lhs, "shadow_rate": rhs,
                "ok": (lhs <= rhs) if comparable else None,
            })
    return checks
