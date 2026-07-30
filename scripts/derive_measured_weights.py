"""
scripts/derive_measured_weights.py — Phase 3 measured tier weights.

Author-level holdout split (never sample-level — see design spec §7):
splits each corpus's authors into a derivation set (Fisher-ratio weight
computation) and a gate-evaluation set (G1/G3/G4/G6 in
validation/calibration_gate.py). validation.stability.stability's
fisher_ratio/compute_feature_matrix take no split argument — this script
owns the split and pre-filters the author_texts dict before calling them,
per validation/stability/run.py's existing `--only` pattern.

Within-author variance (the Fisher ratio's denominator) is shrunk toward
the pooled cross-author estimate via the same weighted Ledoit-Wolf
closed-form already used for RANK_REMEDIATION=shrinkage
(original/quantum/state.py:_ledoit_wolf_shrink), since raw per-author
variance from 4-15 samples is the ratio's noisiest, most-rewarded input.

DOES NOT edit original/constants.py. Prints a diff-shaped TIER_WEIGHTS
block for a human to review and apply — TIER_WEIGHTS is on the CLAUDE.md
explicit-permission list.

Corpus loading — the three corpora scored by validation/calibration_gate.py's
G1/G3/G4 gates do NOT share one directory convention, so
validation.stability.run.load_corpus (which walks
``<corpus_dir>/<author>/_full_work_cache.txt``) only applies directly to
the public_authors corpus:

  * seminary   — flat files at validation/corpus/seminary_*.txt with no
                 natural per-author grouping; validation/calibration_gate.py's
                 _load_seminary_texts() buckets every 5 sequential files into
                 a pseudo-author "seminary_group_N" (same grouping the G1 gate
                 scores against — reused here verbatim so the derivation/gate
                 split lands on the exact same author-id space the gates use).
  * public_authors — validation/public_authors/corpus/<author>/_full_work_cache.txt
                 matches load_corpus's expected shape exactly; used as-is.
  * plato      — validation/plato/corpus/jowett/<dialogue>/*.txt chunks, no
                 _full_work_cache.txt; validation/calibration_gate.py's
                 _load_plato_texts_by_dialogue() groups chunks into a
                 pseudo-author "plato_<dialogue>" per dialogue — reused here
                 for the same reason as seminary above.

Reusing validation.calibration_gate's two helpers (rather than
reimplementing the grouping) is deliberate: the double-dipping guard this
script exists to provide only holds if the author-id space we split on is
the SAME one the gates later evaluate against.

Run:
    python -m scripts.derive_measured_weights --derivation-fraction 0.7 --seed 1729
"""

from __future__ import annotations

from validation.benchmark.reproducibility import lock_environment  # noqa: E402

ENV_LOCK = lock_environment()

import argparse
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

from original.constants import FEATURE_TIER, TIER_WEIGHTS
from validation.stability.stability import compute_feature_matrix, fisher_ratio


def split_authors(
    author_ids: list[str],
    derivation_fraction: float = 0.7,
    seed: int = 1729,
) -> tuple[set[str], set[str]]:
    """
    Deterministic author-level split. Never split by sample — an author's
    samples must never appear on both sides (design spec §7).
    """
    rng = np.random.default_rng(seed)
    shuffled = sorted(author_ids)  # sort first for determinism independent of dict order
    rng.shuffle(shuffled)
    cut = round(len(shuffled) * derivation_fraction)
    derivation = set(shuffled[:cut])
    gate = set(shuffled[cut:])
    return derivation, gate


def shrink_within_author_variance(per_author_var: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """
    Ledoit-Wolf-style shrinkage of each author's within-author variance
    vector toward the pooled (cross-author mean) variance vector. Mirrors
    original/quantum/state.py's _ledoit_wolf_shrink shape but operates on
    variance VECTORS (one per author) rather than a single density matrix.
    """
    if len(per_author_var) < 2:
        return dict(per_author_var)

    pooled = np.mean(list(per_author_var.values()), axis=0)
    n_authors = len(per_author_var)

    shrunk = {}
    for author, var in per_author_var.items():
        gamma = float(np.sum((var - pooled) ** 2))
        if gamma < 1e-18:
            shrunk[author] = var
            continue
        # Simple shrinkage intensity: more authors contributing to the
        # pooled estimate -> trust the per-author estimate more.
        alpha = min(1.0, 1.0 / max(1, n_authors - 1))
        shrunk[author] = (1.0 - alpha) * var + alpha * pooled
    return shrunk


def derive_weights(author_texts: dict[str, str], length: int = 2000) -> dict[int, float]:
    """
    Compute measured per-tier weights from a (pre-filtered, derivation-side-
    only) author_texts dict. Returns {tier_number: weight}, Sigma w^2-
    preserving normalized against the CURRENT TIER_WEIGHTS (same invariant
    the length schedule uses).
    """
    matrices = compute_feature_matrix(author_texts, length, max_windows=12)
    matrices = {a: m for a, m in matrices.items() if m.shape[0] > 0}

    per_author_var = {a: m.var(axis=0, ddof=0) for a, m in matrices.items()}
    shrunk_var = shrink_within_author_variance(per_author_var)

    # Rebuild fisher_ratio's between/within computation using the SHRUNK
    # within-author variance instead of the raw one, by re-deriving within
    # from shrunk_var directly (fisher_ratio itself always recomputes raw
    # variance internally, so it cannot be called as-is with pre-shrunk
    # values — this function reimplements the ratio using shrunk inputs).
    within = np.mean(list(shrunk_var.values()), axis=0)
    author_means = np.stack([m.mean(axis=0) for m in matrices.values()], axis=0)
    between = author_means.var(axis=0, ddof=0)
    per_feature_fisher = between / (within + 1e-9)

    # per_feature_fisher is indexed positionally by ALL_FEATURE_CODES order
    # (compute_feature_matrix's columns follow feature_vector()'s order,
    # which is ALL_FEATURE_CODES) — aggregate to per-tier by zipping against
    # ALL_FEATURE_CODES + FEATURE_TIER directly:
    from original.constants import ALL_FEATURE_CODES

    per_tier_values: dict[int, list[float]] = {}
    for code, f in zip(ALL_FEATURE_CODES, per_feature_fisher):
        tier = FEATURE_TIER[code]
        per_tier_values.setdefault(tier, []).append(float(f))

    per_tier_mean_fisher = {t: float(np.mean(v)) for t, v in per_tier_values.items()}

    # Sigma w^2-preserving normalization against the CURRENT weight table.
    current_sq_sum = sum(w**2 for w in TIER_WEIGHTS.values())
    raw_sq_sum = sum(v**2 for v in per_tier_mean_fisher.values())
    scale = (current_sq_sum / raw_sq_sum) ** 0.5 if raw_sq_sum > 0 else 1.0
    return {t: v * scale for t, v in per_tier_mean_fisher.items()}


# ── Corpus loading (see module docstring for why each corpus needs its own
#    loader rather than a single call to validation.stability.run.load_corpus) ──


def _load_seminary_author_texts() -> dict[str, str]:
    from validation.calibration_gate import _load_seminary_texts

    grouped = _load_seminary_texts()  # {pseudo_author: [text, ...]}
    return {author: "\n\n".join(texts) for author, texts in grouped.items()}


def _load_public_authors_author_texts() -> dict[str, str]:
    from validation.stability.run import DEFAULT_MIN_WORDS
    from validation.stability.run import load_corpus as load_public_authors_corpus

    corpus_dir = _ROOT / "validation" / "public_authors" / "corpus"
    return load_public_authors_corpus(corpus_dir, min_words=DEFAULT_MIN_WORDS)


def _load_plato_author_texts() -> dict[str, str]:
    from validation.calibration_gate import _load_plato_texts_by_dialogue

    grouped = _load_plato_texts_by_dialogue()  # {pseudo_author: [chunk, ...]}
    return {author: "\n\n".join(chunks) for author, chunks in grouped.items()}


_CORPUS_LOADERS = {
    "seminary": _load_seminary_author_texts,
    "public_authors": _load_public_authors_author_texts,
    "plato": _load_plato_author_texts,
}


def load_all_corpora(corpora: list[str]) -> dict[str, str]:
    """
    Union {author_id: full_text} across every named corpus. Author-id
    namespaces don't collide across corpora (seminary_group_N,
    <public-author-name>, plato_<dialogue>), but we check anyway so a
    future corpus addition can't silently merge two authors together.
    """
    combined: dict[str, str] = {}
    for name in corpora:
        loader = _CORPUS_LOADERS.get(name)
        if loader is None:
            raise ValueError(f"Unknown corpus {name!r}; choose from {sorted(_CORPUS_LOADERS)}")
        texts = loader()
        overlap = combined.keys() & texts.keys()
        if overlap:
            raise ValueError(f"Author-id collision between corpora: {sorted(overlap)}")
        print(f"[derive-weights] {name}: {len(texts)} authors", file=sys.stderr)
        combined.update(texts)
    return combined


_TIER_LABELS: dict[int, str] = {
    0: "Comparison (meta)",
    1: "Surface stylometrics",
    2: "Discourse structure",
    3: "Rhetorical & register",
    4: "Char/punct fingerprint",
    5: "POS & shallow syntax",
    6: "Idiosyncratic patterns",
    7: "AI detection markers",
    8: "Prosodic rhythm",
    9: "Argument topology",
    10: "Semantic gravity wells",
    11: "Error ecology",
    12: "Tension arc",
    13: "Prosodic depth",
    14: "Error topology",
    15: "Lexical architecture",
    16: "Citation fingerprint",
    17: "Behavioral biometrics",
    18: "Uniformity",
}


def print_tier_weights_diff(measured: dict[int, float]) -> None:
    """
    Print a paste-ready TIER_WEIGHTS block, mirroring
    scripts/calibrate_bounds.py's print_suggested_bounds() convention:
    a "paste this block" header comment, the dict literal with inline
    per-entry comments showing the CURRENT value so the direction of
    change is visible at a glance, and a closing note.
    """
    print()
    print("=" * 78)
    print("  MEASURED TIER_WEIGHTS (derivation-split Fisher ratio, shrinkage-regularized)")
    print("=" * 78)
    print()
    print("# ── Paste this block into original/constants.py → TIER_WEIGHTS ──────────────")
    print("TIER_WEIGHTS: dict[int, float] = {")
    for tier in sorted(measured):
        current = TIER_WEIGHTS.get(tier)
        new = measured[tier]
        label = _TIER_LABELS.get(tier, f"Tier {tier}")
        delta = "" if current is None else f", was {current:.2f} ({new - current:+.2f})"
        print(f"    {tier:>2}: {new:5.2f},   # {label}{delta}")
    print("}")
    print()
    print("# NOTE: hand-verify direction before applying — spec expects T1/T5 up,")
    print("# T4/T16 sharply down. Do not blind-paste; see task-11 STOP-AND-ASK step.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--derivation-fraction", type=float, default=0.7)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument(
        "--corpora",
        default="seminary,public_authors,plato",
        help="Comma-separated corpus names to union (default: all three).",
    )
    parser.add_argument(
        "--length",
        type=int,
        default=2000,
        help="Window length (words) fed to compute_feature_matrix. Default 2000.",
    )
    args = parser.parse_args(argv)

    corpora = [c.strip() for c in args.corpora.split(",") if c.strip()]
    author_texts = load_all_corpora(corpora)
    print(
        f"[derive-weights] {len(author_texts)} authors total across {corpora}",
        file=sys.stderr,
    )

    derivation_ids, gate_ids = split_authors(
        list(author_texts.keys()),
        derivation_fraction=args.derivation_fraction,
        seed=args.seed,
    )
    print(
        f"[derive-weights] split: {len(derivation_ids)} derivation / "
        f"{len(gate_ids)} gate-holdout authors",
        file=sys.stderr,
    )

    derivation_texts = {a: t for a, t in author_texts.items() if a in derivation_ids}
    measured = derive_weights(derivation_texts, length=args.length)

    print_tier_weights_diff(measured)
    return 0


if __name__ == "__main__":
    sys.exit(main())
