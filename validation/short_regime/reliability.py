"""Per-feature ICC(1) at the 500-word operating point.

ICC = between-author variance / total variance per feature. Answers: which
of the 103 features still separates authors at 500 words? Output feeds the
Task 6-8 decisions and any future refit of LENGTH_WEIGHT_SCHEDULE['short']
(constants.py:298 — read the Σ(w²) normalisation comment before refitting).

NOTE: COMPARISON_CODES (char_trigram_profile_divergence, function_word_profile_divergence)
are hardcoded 0.5 placeholders during extraction and are not real features yet. Their
ICC entries are marked as None with a note, not 0.0, to avoid false negatives in weighting.
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
    FEATURE_TIER,
)
from original.features.pipeline import feature_vector  # noqa: E402

from .corpus import build_pools  # noqa: E402


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
    # Sort by ICC descending, with comparison codes (None) last
    sorted_items = sorted(
        rel.items(),
        key=lambda kv: (kv[0] in COMPARISON_CODES, -kv[1]),
    )
    report = {}
    for code, v in sorted_items:
        if code in COMPARISON_CODES:
            report[code] = {
                "icc": None,
                "tier": FEATURE_TIER.get(code, 0),
                "note": "placeholder at extraction time; ICC unmeasurable",
            }
        else:
            report[code] = {"icc": round(v, 4), "tier": FEATURE_TIER.get(code, 0)}
    out = Path(__file__).parent / "reliability_500w.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
