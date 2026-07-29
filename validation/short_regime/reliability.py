"""Per-feature ICC(1) at the 500-word operating point.

ICC = between-author variance / total variance per feature. Answers: which
of the 103 features still separates authors at 500 words? Output feeds the
Task 6-8 decisions and any future refit of LENGTH_WEIGHT_SCHEDULE['short']
(constants.py:298 — read the Σ(w²) normalisation comment before refitting).

NOTE: COMPARISON_CODES (char_trigram_profile_divergence, function_word_profile_divergence)
are hardcoded 0.5 placeholders during extraction and are not real features yet. Their
ICC entries are marked as None with a note, not 0.0, to avoid false negatives in weighting.
The same treatment applies to any feature code currently in a DISABLED_FEATURE_GROUPS group
(e.g. the tier-17 behavioral-biometrics codes, disabled pending live keystroke data from
Bbook) — they also emit a constant 0.5 placeholder at extraction time, so a real 0.0 ICC
would be indistinguishable from "genuinely unreliable feature" when it is actually
"not measured yet." Both classes are reported as {"icc": null, "note": ...}, never {"icc": 0.0}.

NOTE ON REPRODUCIBILITY: measured ICC values vary at the 3rd-4th decimal place across runs
of this script (pipeline hash-order nondeterminism upstream in feature extraction); this is
tracked separately and does not affect which features are unmeasurable placeholders.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from original.constants import (  # noqa: E402
    ALL_FEATURE_CODES,
    COMPARISON_CODES,
    DISABLED_FEATURE_GROUPS,
    FEATURE_GROUPS,
    FEATURE_TIER,
)
from original.features.pipeline import feature_vector  # noqa: E402

from .corpus import build_pools  # noqa: E402

# Codes that emit a constant 0.5 placeholder at extraction time because their
# feature group is currently disabled (see original/constants.py::FEATURE_GROUPS /
# DISABLED_FEATURE_GROUPS) — e.g. tier-17 behavioral biometrics without live keystroke
# data. Their ICC is unmeasurable for the same reason COMPARISON_CODES's is: a computed
# 0.0 would look like "measured and unreliable" rather than "not measured yet."
DISABLED_GROUP_CODES: set[str] = {
    code
    for group in DISABLED_FEATURE_GROUPS
    for code in FEATURE_GROUPS.get(group, [])
}

# All codes that must be reported as icc: null with a note, rather than a computed float.
UNMEASURABLE_CODES: set[str] = set(COMPARISON_CODES) | DISABLED_GROUP_CODES


def icc_1(groups: list[np.ndarray]) -> float:
    """One-way ICC: var(group means) / (var(group means) + mean within-var)."""
    means = np.array([g.mean() for g in groups])
    within = float(np.mean([g.var(ddof=1) if g.size > 1 else 0.0 for g in groups]))
    between = float(means.var(ddof=1)) if means.size > 1 else 0.0
    total = between + within
    if total <= 1e-12:
        return 0.0
    return float(np.clip(between / total, 0.0, 1.0))


def feature_reliability(pools, words: int = 500, max_chunks: int = 30) -> dict[str, float]:
    per_author = {}
    for author, chunks in pools.items():
        if len(chunks) < 6:
            continue
        per_author[author] = np.stack([feature_vector(c) for c in chunks[:max_chunks]])
    out = {}
    for k, code in enumerate(ALL_FEATURE_CODES):
        groups = [V[:, k] for V in per_author.values()]
        out[code] = icc_1(groups)
    return out


def main() -> int:
    pools = build_pools(_ROOT / "validation" / "corpus", words=500)
    rel = feature_reliability(pools)
    # Sort by ICC descending, with unmeasurable codes (None) last
    sorted_items = sorted(
        rel.items(),
        key=lambda kv: (kv[0] in UNMEASURABLE_CODES, -kv[1]),
    )
    report = {
        "_meta": {
            "note": (
                "Measured ICC values vary at the 3rd-4th decimal place across runs of "
                "this script (pipeline hash-order nondeterminism upstream in feature "
                "extraction, tracked separately). icc: null entries below are features "
                "that emit a constant 0.5 placeholder at extraction time (comparison "
                "codes not yet computed, or codes in a currently-disabled feature "
                "group) — their reliability is unmeasured, not measured-and-zero."
            ),
        },
    }
    for code, v in sorted_items:
        if code in COMPARISON_CODES:
            report[code] = {
                "icc": None,
                "tier": FEATURE_TIER.get(code, 0),
                "note": "placeholder at extraction time; ICC unmeasurable",
            }
        elif code in DISABLED_GROUP_CODES:
            report[code] = {
                "icc": None,
                "tier": FEATURE_TIER.get(code, 0),
                "note": (
                    "feature group disabled (DISABLED_FEATURE_GROUPS); emits constant "
                    "0.5 placeholder at extraction time, not a real value; ICC unmeasurable"
                ),
            }
        else:
            report[code] = {"icc": round(v, 4), "tier": FEATURE_TIER.get(code, 0)}
    out = Path(__file__).parent / "reliability_500w.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
