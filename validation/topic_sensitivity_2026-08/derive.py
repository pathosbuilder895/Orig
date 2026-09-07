"""Derive TOPIC_SENSITIVITY from within-author, across-work feature drift.

    s_A(f) = drift_A(f) / (within_A(f) + EPS)

where drift_A is the standard deviation over author A's per-work means and
within_A is the pooled within-work standard deviation. The ratio asks: how far
does this feature move when the SAME author changes subject, relative to its
ordinary chunk-to-chunk noise?

Deliberately omits the `separation` term that `dna_analysis.py` uses. That term
is |mean_lewis - mean_chesterton|, measured against exactly one contrast
author, and it is the reason the DNA vector failed to generalise
(original/context/weighting.py:66). This quantity is purely within-author, so
that specific failure mode does not apply -- which is an argument for trying
it, not a guarantee, hence the leave-one-author-out check below.

Usage:
    .venv/bin/python -m validation.topic_sensitivity_2026-08.extract   # once
    .venv/bin/python -m validation.topic_sensitivity_2026-08.derive
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

from original.constants import ALL_FEATURE_CODES, FEATURE_TIER, TOPIC_INFLATE_MAX  # noqa: E402
from validation.measurability import measurable_indices  # noqa: E402

VECTORS = _HERE / "vectors.npy"
META = _HERE / "vectors_meta.json"
OUT_NPY = _HERE / "topic_sensitivity.npy"
OUT_SNIPPET = _HERE / "topic_sensitivity_constant.py"

# Matches dna_analysis.py:35 so the two derivations use the same guard.
EPS = 1e-3


def load():
    vectors = np.load(VECTORS)
    meta = json.loads(META.read_text(encoding="utf-8"))
    return vectors, meta


def per_author_sensitivity(vectors: np.ndarray, meta: list[dict]) -> dict[str, np.ndarray]:
    """s_A(f) for each author with >= 2 works. Shape (D,) per author."""
    by_author: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for i, m in enumerate(meta):
        by_author[m["author"]][m["work"]].append(i)

    out: dict[str, np.ndarray] = {}
    for author, works in sorted(by_author.items()):
        if len(works) < 2:
            print(f"  SKIP {author}: only {len(works)} work(s); drift undefined")
            continue
        work_means, within_stds = [], []
        for _work, idx in sorted(works.items()):
            block = vectors[idx]
            work_means.append(block.mean(axis=0))
            # ddof=1: these are samples of the work, not the population.
            within_stds.append(block.std(axis=0, ddof=1) if len(idx) > 1 else np.zeros(block.shape[1]))
        drift = np.stack(work_means).std(axis=0, ddof=1)
        within = np.stack(within_stds).mean(axis=0)
        out[author] = drift / (within + EPS)
    return out


def combine(per_author: dict[str, np.ndarray], exclude: str | None = None) -> np.ndarray:
    """Median across authors -- robust to one author with an odd corpus."""
    stack = np.stack([v for a, v in per_author.items() if a != exclude])
    return np.median(stack, axis=0)


def dead_on_corpus(vectors: np.ndarray, tol: float = 1e-6) -> np.ndarray:
    """Features with essentially no variance anywhere in this corpus.

    Citation features are the clear case: `ibid_usage_rate`,
    `citation_density_cv` and `source_loyalty_index` are identically zero
    across Dickens and Christie novels, so drift and within-noise are BOTH
    zero and the ratio comes out 0.0 — which the derivation would otherwise
    record as "perfectly topic-invariant, never widen this feature."

    That is a false reading. They are not invariant; they are absent. On
    student coursework, which cites, they are live. A feature this corpus
    cannot speak to must fall back to the neutral 1.0 that
    `TOPIC_SENSITIVITY.get(code, 1.0)` already supplies, not to a confident
    zero this data does not support.
    """
    return vectors.std(axis=0) < tol


def normalise(raw: np.ndarray) -> np.ndarray:
    """Divide by the median over MEASURABLE features, then clip.

    Measurability filtering happens HERE, at derivation time, and the result is
    baked into the committed constant -- original/ must never import
    validation/, so the scoring path cannot do this lookup itself.
    """
    idx = measurable_indices()
    med = float(np.median(raw[idx]))
    if med <= 0:
        raise ValueError(f"median sensitivity over measurable features is {med}; cannot normalise")
    return np.clip(raw / med, 0.0, TOPIC_INFLATE_MAX)


def leave_one_author_out(
    per_author: dict[str, np.ndarray], dead: np.ndarray
) -> list[tuple[str, float]]:
    """Does the vector derived WITHOUT an author predict that author's own?

    This is the check the DNA vector failed. If topic-sensitivity is a stable
    per-feature property, a vector built from five authors should rank features
    much the same way the sixth author does. If these correlations are near
    zero, the premise is wrong and no amount of tuning fixes it.

    Dead features are EXCLUDED. They sit at identically 0.0 for every author,
    so they tie-rank perfectly and inflate Spearman toward agreement that is
    an artifact of absent data rather than shared signal. Including them
    reported rho = +0.320 where the 83 live features actually give +0.168 --
    the difference between "weak but real" and "essentially nothing", so this
    exclusion is the difference between shipping this vector and not.
    """
    idx = [i for i in measurable_indices() if not dead[i]]
    results = []
    for held in sorted(per_author):
        others = combine(per_author, exclude=held)
        rho = spearmanr(others[idx], per_author[held][idx]).statistic
        results.append((held, float(rho)))
    return results


def main() -> int:
    if not VECTORS.exists():
        print(f"missing {VECTORS}; run extract.py first")
        return 1

    vectors, meta = load()
    print(f"vectors {vectors.shape} over {len({m['author'] for m in meta})} authors\n")

    per_author = per_author_sensitivity(vectors, meta)
    print(f"per-author sensitivity computed for {len(per_author)} authors: {sorted(per_author)}\n")

    dead = dead_on_corpus(vectors)

    # ── Does this generalise across authors at all? ──────────────────────────
    print("Leave-one-author-out (Spearman rho between the vector derived")
    print("WITHOUT an author and that author's own sensitivities):")
    folds = leave_one_author_out(per_author, dead)
    for author, rho in folds:
        print(f"  {author:12s} rho = {rho:+.3f}")
    rhos = [r for _, r in folds]
    print(f"  {'mean':12s} rho = {np.mean(rhos):+.3f}   min = {np.min(rhos):+.3f}\n")
    if np.mean(rhos) < 0.3:
        print("  ⚠️  WEAK: topic-sensitivity does not look like a stable per-feature")
        print("      property across authors. A global constant derived from it")
        print("      would be largely noise. DO NOT SHIP THIS VECTOR --")
        print("      the empty TOPIC_SENSITIVITY (uniform sensitivity) is more")
        print("      honest than a table this data cannot support.\n")

    raw = combine(per_author)
    s_norm = normalise(raw)

    # Features this corpus cannot speak to are OMITTED from the emitted table
    # rather than shipped as a confident 0.0; the scoring path's
    # `.get(code, 1.0)` then leaves them at neutral sensitivity.
    print(f"\ndead on this corpus (omitted, will read as neutral 1.0): {int(dead.sum())} features")
    for i in np.flatnonzero(dead):
        print(f"    {ALL_FEATURE_CODES[i]}")
    np.save(OUT_NPY, s_norm)

    idx = measurable_indices()
    order = np.argsort(-s_norm)
    measurable = set(idx) - set(np.flatnonzero(dead_on_corpus(vectors)).tolist())
    print("Most topic-SENSITIVE (widen most under a topic shift):")
    shown = 0
    for i in order:
        if i not in measurable:
            continue
        print(f"  {ALL_FEATURE_CODES[i]:38s} tier {FEATURE_TIER.get(ALL_FEATURE_CODES[i], '?'):>2}  {s_norm[i]:.2f}")
        shown += 1
        if shown >= 10:
            break
    print("\nMost topic-INVARIANT (barely widen -- the identity signal):")
    shown = 0
    for i in order[::-1]:
        if i not in measurable:
            continue
        print(f"  {ALL_FEATURE_CODES[i]:38s} tier {FEATURE_TIER.get(ALL_FEATURE_CODES[i], '?'):>2}  {s_norm[i]:.2f}")
        shown += 1
        if shown >= 10:
            break

    # ── Emit the constant ───────────────────────────────────────────────────
    lines = [
        '"""Generated by validation/topic_sensitivity_2026-08/derive.py.',
        "",
        "Paste the dict below into original/constants.py as TOPIC_SENSITIVITY.",
        "Values are ALREADY normalised (divided by the median over measurable",
        f"features) and clipped to [0, {TOPIC_INFLATE_MAX}], so the scoring path needs no",
        "measurability lookup.",
        '"""',
        "",
        "TOPIC_SENSITIVITY: dict[str, float] = {",
    ]
    for i, code in enumerate(ALL_FEATURE_CODES):
        if dead[i]:
            lines.append(f'    # "{code}": omitted - no variance in the derivation corpus')
            continue
        lines.append(f'    "{code}": {s_norm[i]:.4f},')
    lines.append("}")
    OUT_SNIPPET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT_NPY.name} and {OUT_SNIPPET.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
