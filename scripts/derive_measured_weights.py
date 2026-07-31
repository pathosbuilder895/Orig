"""
scripts/derive_measured_weights.py — Phase 3 measured tier weights (hardened).

Author-level holdout split (never sample-level — see design spec §7):
splits each corpus's authors into a derivation set (Fisher-ratio weight
computation) and a gate-evaluation set (G1/G3/G4/G6 in
validation/calibration_gate.py). validation.stability.stability's
fisher_ratio/compute_feature_matrix take no split argument — this script
owns the split and pre-filters the author_texts dict before calling
compute_feature_matrix, per validation/stability/run.py's existing `--only`
pattern.

DOES NOT edit original/constants.py. Prints a diff-shaped TIER_WEIGHTS
block for a human to review — TIER_WEIGHTS is on the CLAUDE.md
explicit-permission list. The block is INFORMATIONAL ONLY: the user has
HELD these weights (see task-11/13 history) — nothing in this script
applies anything to constants.py.

Revision history / why this looks the way it does:

  First cut (Task 11) computed a per-feature Fisher ratio over ALL 109
  columns and reported tiers 0, 11, 12, 17, 18 as measured at exactly 0.00.
  A reviewer traced this to real, structural degeneracy, not a genuine
  measurement:
    - Tier 0 (COMPARISON_CODES) and tier 11's error-ecology codes are
      baseline-comparison features; original/features/pipeline.py computes
      them only at scoring time and hardcodes 0.5 for every window fed
      through feature_vector() in isolation (no baseline exists yet) — so
      their in-corpus variance is identically zero by construction.
    - Tier 12's catastrophe_index and any DISABLED_FEATURE_GROUPS member
      (today: tier 17 "behavioral", tier 18 "uniformity") hit the same
      constant-fallback path for a different reason (missing capability /
      disabled group), but the practical effect is identical: zero
      in-corpus variance, Fisher ratio undefined, not "measured as zero."
  The first cut's `shrink_within_author_variance` also turned out to be
  inert: shrinking every author's per-feature variance vector toward the
  POOLED MEAN of those same vectors leaves the mean of the shrunk vectors
  bit-identical to the pooled mean, by definition (the exact operation
  `derive_weights` used it for — averaging the shrunk vectors back down to
  a single `within` estimate — undoes the shrinkage). It was also
  incorrectly described as "Ledoit-Wolf"; it did not implement that
  closed-form.

This revision fixes all of the above:
  1. `structurally_excluded_codes()` + `zero_variance_feature_indices()`
     remove unmeasurable features from the Fisher computation entirely
     (rather than letting them silently score as `F≈0`), following the
     precedent in validation/stability/stability.py's tier-17 exclusion
     (`_FEATURE_INDICES_SKIPPED`, recorded in `StabilityReport.notes`).
     A tier with zero surviving features KEEPS its current TIER_WEIGHTS
     value in the printed block, annotated accordingly; Sigma w^2-
     preserving normalization runs over the measured-tier subset only.
  2. `floor_within_variance()` replaces the inert shrink: it floors each
     feature's (already author-averaged) within-variance at a low
     percentile of the other features' within-variance, so one
     near-degenerate denominator cannot blow its Fisher ratio up and
     dominate a tier's aggregate.
  3. Tiers aggregate their surviving features' Fisher ratios by MEDIAN,
     not mean, so a single outlier feature cannot set the whole tier.
  4. `drop_short_authors()` requires >= 2 windows per author (ddof=1
     within-author variance is undefined below that) and warns loudly on
     every drop; the default `--length` is chosen so every derivation-side
     author in the current three corpora clears that floor.

A closing review of this revision flagged two more issues, fixed here:
  - Tiers 9 and 10 each have only 2 member codes today, and one of each
    pair is a comparison-shaped feature that's constant through this
    pipeline (see (1) above) — so both tiers routinely end up with exactly
    ONE surviving measured feature. A "median" of one value is a single-
    feature bet, not tier-level agreement; `compute_tier_weights_from_matrices`
    now exposes `tier_feature_counts` / `single_survivor_tiers` in its
    diagnostics, and `print_tier_weights_diff` annotates any such tier
    inline (e.g. "single surviving feature: semantic_field_dispersion —
    weak evidence") so it can't be mistaken for the same strength of
    evidence as a tier where several features agree.
  - `compute_tier_weights_from_matrices` printed ~26 exclusion lines to
    stderr on every call — fine for a one-shot CLI run, noisy for a
    library caller invoking it many times (Task 13's G5 permutation-null
    control is expected to re-derive weights once per label shuffle). A
    `verbose: bool = True` parameter (threaded through `drop_short_authors`
    and `derive_weights` too) suppresses all of it when set `False`; the
    CLI keeps the default `True`.

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

CAUTION printed with every generated block: this run's derivation-side
author pool is dominated by Plato dialogues (long-form philosophical
prose), not student essays. Whatever the Fisher ratios say about which
tiers carry between-author signal, treat it as directional lab-corpus
evidence, not evidence calibrated to the pilot's actual 300-2000 word
student-essay domain.

Run:
    python -m scripts.derive_measured_weights --derivation-fraction 0.7 --seed 1729
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

from validation.benchmark.reproducibility import lock_environment  # noqa: E402

ENV_LOCK = lock_environment()

import argparse  # noqa: E402

import numpy as np  # noqa: E402

from original.constants import (  # noqa: E402
    ALL_FEATURE_CODES,
    COMPARISON_CODES,
    FEATURE_TIER,
    TIER_WEIGHTS,
)
from validation.stability.stability import compute_feature_matrix  # noqa: E402

MIN_WINDOWS_PER_AUTHOR = 2  # ddof=1 within-author variance is undefined below this
DEFAULT_LENGTH = 800  # words — every derivation-side author in the current 3 corpora
                       # (shortest: a seminary pseudo-author at ~1.9k words) clears
                       # MIN_WINDOWS_PER_AUTHOR at this length; drop_short_authors()
                       # is still the enforced backstop if a future corpus doesn't.
DEFAULT_FLOOR_PERCENTILE = 10.0
DEFAULT_MAX_WINDOWS = 12  # named so the experiment spec's windowing block (Task 7)
                          # can record the same value derive_weights() defaults to,
                          # rather than a second hand-copied literal drifting from it.


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


def structurally_excluded_codes() -> set[str]:
    """
    Feature codes that can never carry a Fisher signal through this
    pipeline. Delegates to validation.measurability — the single source of
    truth (this function previously listed COMPARISON_CODES + disabled
    groups itself and relied on zero_variance_feature_indices to catch the
    rest empirically; the registry names all of them a-priori).
    """
    from validation.measurability import structurally_excluded_codes as _registry

    return _registry()


def zero_variance_feature_indices(
    matrices: dict[str, np.ndarray],
    atol: float = 1e-12,
) -> set[int]:
    """
    Indices of feature columns that are constant across every window of
    every author, pooled. A column with zero variance contributes nothing
    to a between/within ratio except a division-by-epsilon artifact (F -> 0
    by construction, not because the feature has low discriminative power)
    — must be structurally excluded, not silently reported as "measured
    at zero." This is the empirical backstop for exactly the tier 11/12
    placeholders `structurally_excluded_codes()` cannot name in advance
    (tier 11's error-ecology codes aren't all in ``COMPARISON_CODES``;
    tier 12's ``catastrophe_index`` is constant via a fallback path, not a
    structural placeholder).
    """
    populated = [m for m in matrices.values() if m.shape[0] > 0]
    if not populated:
        return set()
    pooled = np.vstack(populated)
    variances = pooled.var(axis=0, ddof=0)
    return {i for i, v in enumerate(variances) if v <= atol}


def floor_within_variance(
    within: np.ndarray,
    floor_percentile: float = DEFAULT_FLOOR_PERCENTILE,
) -> np.ndarray:
    """
    Floor each feature's (already author-averaged) within-author variance
    at a low percentile of the OTHER positive within-variances, so a
    single near-degenerate denominator (observed: a feature measured at
    within-var 3.5e-05 while its peers sit at 1e-2 to 1e-1) cannot blow its
    Fisher ratio up by orders of magnitude and dominate its tier's median.

    This is a floor, not a shrinkage-toward-the-mean blend. A prior version
    of this module called an analogous step "Ledoit-Wolf shrinkage" while
    doing something that left the aggregate mean bit-identical to the
    unshrunk mean (shrinking every author's variance vector toward the
    POOLED MEAN of those same vectors, then averaging the shrunk vectors
    back down, mathematically reproduces the original mean — max observed
    diff 2.8e-17, i.e. floating-point noise, not regularization). This
    function actually changes the denominator used downstream, and does
    not claim to be Ledoit-Wolf since it isn't that closed form.
    """
    positive = within[within > 0]
    if positive.size == 0:
        return within
    floor = np.percentile(positive, floor_percentile)
    return np.maximum(within, floor)


def drop_short_authors(
    matrices: dict[str, np.ndarray],
    min_windows: int = MIN_WINDOWS_PER_AUTHOR,
    verbose: bool = True,
) -> dict[str, np.ndarray]:
    """
    ddof=1 within-author variance is undefined for a single window (and
    ddof=0 silently returns exactly 0.0 — the variance of one point about
    its own mean) — either way, an author with < min_windows windows drags
    the pooled `within` estimate down and inflates every feature's Fisher
    ratio for that reason alone, not because the corpus supports it. Drop
    any such author, loudly (unless `verbose=False` — a library caller,
    e.g. Task 13's G5 permutation-null control running this pipeline many
    times over shuffled labels, doesn't want a warning per shuffle), rather
    than let it silently corrupt the denominator.
    """
    kept: dict[str, np.ndarray] = {}
    for author, m in matrices.items():
        if m.shape[0] < min_windows:
            if verbose:
                print(
                    f"[derive-weights] WARNING: dropping author {author!r} — only "
                    f"{m.shape[0]} window(s) at this length (need >= {min_windows} "
                    f"for a defined within-author variance)",
                    file=sys.stderr,
                )
            continue
        kept[author] = m
    return kept


def median_per_tier(per_tier_values: dict[int, list[float]]) -> dict[int, float]:
    """
    Aggregate each tier's surviving per-feature Fisher ratios by MEDIAN,
    not mean — a tier's weight must not be set by a single outlier feature
    (observed: tier 3's mean was 7.23 against a median of 0.83, driven by
    one feature). Tiers with no surviving values are omitted (the caller
    keeps their current TIER_WEIGHTS entry instead).
    """
    return {t: float(np.median(v)) for t, v in per_tier_values.items() if v}


def compute_tier_weights_from_matrices(
    matrices: dict[str, np.ndarray],
    floor_percentile: float = DEFAULT_FLOOR_PERCENTILE,
    verbose: bool = True,
) -> tuple[dict[int, float], dict]:
    """
    Pure (no I/O) core: {author_id: (n_windows, FEATURE_DIM)} matrices in,
    ({tier: weight}, diagnostics) out. Separated from `derive_weights` so
    the exclusion/floor/median/kept-tier logic is unit-testable without a
    real corpus, and so a future consumer (Task 13's G5 permutation-null
    control is expected to reuse this pipeline) can feed it matrices built
    from shuffled author labels directly.

    weights: {tier: weight} for every tier in TIER_WEIGHTS. Tiers with no
    measurable features (see structurally_excluded_codes /
    zero_variance_feature_indices) KEEP their current TIER_WEIGHTS value
    unchanged. Measured tiers are the per-tier MEDIAN Fisher ratio,
    Sigma w^2-preserving normalized against the CURRENT TIER_WEIGHTS
    restricted to the measured-tier subset only.

    diagnostics: {
        "window_counts_all": {author: n_windows} (before dropping short authors),
        "window_counts_used": {author: n_windows} (after dropping),
        "dropped_authors": [author, ...],
        "excluded_features": {code: reason},
        "kept_tiers": [tier, ...],
        "tier_feature_counts": {tier: n_surviving_features} (measured tiers only),
        "single_survivor_tiers": {tier: the_one_surviving_feature_code}
            (measured tiers with exactly 1 surviving feature — a median of
            one value is a single-feature bet, not tier-level agreement;
            print_tier_weights_diff annotates these as weak evidence).
    }

    `verbose=False` suppresses every print this function (and the
    `drop_short_authors` call inside it) would otherwise emit to stderr —
    for a library caller that runs this many times (e.g. G5's permutation-
    null control re-deriving weights per shuffle), the CLI keeps the
    default `True`.
    """
    window_counts_all = {a: int(m.shape[0]) for a, m in matrices.items()}
    usable = drop_short_authors(matrices, min_windows=MIN_WINDOWS_PER_AUTHOR, verbose=verbose)
    dropped_authors = sorted(set(matrices) - set(usable))

    if len(usable) < 2:
        raise RuntimeError(
            f"Only {len(usable)} author(s) with >= {MIN_WINDOWS_PER_AUTHOR} windows; "
            f"need >= 2 for between-author variance."
        )

    excluded_codes = structurally_excluded_codes()
    zero_var_idx = zero_variance_feature_indices(usable)

    excluded_reasons: dict[str, str] = {}
    for code in ALL_FEATURE_CODES:
        if code in excluded_codes:
            if code in COMPARISON_CODES:
                excluded_reasons[code] = (
                    "comparison feature — needs a baseline; constant through this "
                    "window-only pipeline"
                )
            else:
                excluded_reasons[code] = "member of a currently-disabled feature group"
    for idx in sorted(zero_var_idx):
        code = ALL_FEATURE_CODES[idx]
        excluded_reasons.setdefault(code, "zero variance across the derivation matrix")

    if verbose:
        for code in sorted(excluded_reasons):
            print(
                f"[derive-weights] excluding feature {code!r} from Fisher computation: "
                f"{excluded_reasons[code]}",
                file=sys.stderr,
            )

    per_author_var = {a: m.var(axis=0, ddof=1) for a, m in usable.items()}
    within_raw = np.mean(list(per_author_var.values()), axis=0)
    within = floor_within_variance(within_raw, floor_percentile=floor_percentile)

    author_means = np.stack([m.mean(axis=0) for m in usable.values()], axis=0)
    between = author_means.var(axis=0, ddof=1)
    per_feature_fisher = between / (within + 1e-9)

    surviving_codes = [code for code in ALL_FEATURE_CODES if code not in excluded_reasons]

    from validation.measurability import assert_aggregatable

    # Structural guard: aggregation over a non-measurable column is the
    # Instrument Report's root failure mode — refuse loudly, never average.
    assert_aggregatable(surviving_codes)

    per_tier_values: dict[int, list[float]] = {}
    per_tier_codes: dict[int, list[str]] = {}
    for code, f in zip(ALL_FEATURE_CODES, per_feature_fisher, strict=False):
        if code in excluded_reasons:
            continue
        tier = FEATURE_TIER[code]
        per_tier_values.setdefault(tier, []).append(float(f))
        per_tier_codes.setdefault(tier, []).append(code)

    per_tier_median = median_per_tier(per_tier_values)
    measured_tiers = set(per_tier_median)
    kept_tiers = {t: w for t, w in TIER_WEIGHTS.items() if t not in measured_tiers}

    tier_feature_counts = {t: len(v) for t, v in per_tier_values.items() if t in measured_tiers}
    single_survivor_tiers = {
        t: codes[0]
        for t, codes in per_tier_codes.items()
        if t in measured_tiers and len(codes) == 1
    }

    # Sigma w^2-preserving normalization over the MEASURED subset only.
    current_sq_sum = sum(TIER_WEIGHTS[t] ** 2 for t in measured_tiers if t in TIER_WEIGHTS)
    raw_sq_sum = sum(v**2 for v in per_tier_median.values())
    scale = (current_sq_sum / raw_sq_sum) ** 0.5 if raw_sq_sum > 0 else 1.0

    weights: dict[int, float] = {t: v * scale for t, v in per_tier_median.items()}
    weights.update(kept_tiers)

    diagnostics = {
        "window_counts_all": window_counts_all,
        "window_counts_used": {a: int(m.shape[0]) for a, m in usable.items()},
        "dropped_authors": dropped_authors,
        "excluded_features": excluded_reasons,
        "kept_tiers": sorted(kept_tiers),
        "tier_feature_counts": tier_feature_counts,
        "single_survivor_tiers": single_survivor_tiers,
    }
    if verbose:
        print(
            f"[derive-weights] excluded {len(excluded_reasons)}/{len(ALL_FEATURE_CODES)} feature "
            f"columns from Fisher computation; kept tiers (unmeasurable, current TIER_WEIGHTS "
            f"retained): {diagnostics['kept_tiers']}",
            file=sys.stderr,
        )
        if single_survivor_tiers:
            print(
                f"[derive-weights] single-survivor tiers (weak evidence — median of one "
                f"feature): {single_survivor_tiers}",
                file=sys.stderr,
            )
    return weights, diagnostics


def derive_weights(
    author_texts: dict[str, str],
    length: int = DEFAULT_LENGTH,
    max_windows: int = DEFAULT_MAX_WINDOWS,
    floor_percentile: float = DEFAULT_FLOOR_PERCENTILE,
    verbose: bool = True,
) -> tuple[dict[int, float], dict]:
    """
    Compute measured per-tier weights from a (pre-filtered, derivation-side-
    only) author_texts dict. Thin I/O wrapper around
    `compute_tier_weights_from_matrices` — see that function's docstring
    for the full contract, including `verbose`.
    """
    matrices = compute_feature_matrix(author_texts, length, max_windows=max_windows)
    return compute_tier_weights_from_matrices(
        matrices, floor_percentile=floor_percentile, verbose=verbose
    )


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


def load_all_corpora(corpora: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """
    Union {author_id: full_text} across every named corpus. Returns the
    union plus {author_id: corpus_name} so callers can print per-corpus
    breakdowns after windowing. Author-id namespaces don't collide across
    corpora (seminary_group_N, <public-author-name>, plato_<dialogue>), but
    we check anyway so a future corpus addition can't silently merge two
    authors together.
    """
    combined: dict[str, str] = {}
    author_corpus: dict[str, str] = {}
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
        for author in texts:
            author_corpus[author] = name
    return combined, author_corpus


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


def print_tier_weights_diff(measured: dict[int, float], diagnostics: dict) -> None:
    """
    Print a paste-ready TIER_WEIGHTS block, mirroring
    scripts/calibrate_bounds.py's print_suggested_bounds() convention:
    a "paste this block" header comment, the dict literal with inline
    per-entry comments showing the CURRENT value so the direction of
    change is visible at a glance, and a closing note. Tiers with no
    measurable features are annotated as kept, not silently printed as if
    measured.
    """
    kept_tiers = set(diagnostics.get("kept_tiers", []))
    n_excluded = len(diagnostics.get("excluded_features", {}))
    single_survivor_tiers = diagnostics.get("single_survivor_tiers", {})

    print()
    print("=" * 78)
    print("  MEASURED TIER_WEIGHTS (derivation-split Fisher ratio; median-aggregated,")
    print("  variance-floored, unmeasurable features excluded)")
    print("=" * 78)
    print()
    print("# CAUTION: this run's derivation-side author pool is dominated by Plato")
    print("# dialogues (long-form philosophical prose), with only a couple of seminary")
    print("# pseudo-authors and a handful of public-domain authors alongside them.")
    print("# Treat this as directional LAB-CORPUS evidence about which tiers carry")
    print("# between-author signal in this pipeline, NOT as evidence calibrated to")
    print("# short student essays — the pilot's actual target domain.")
    print(
        f"# {n_excluded}/{len(ALL_FEATURE_CODES)} feature columns were excluded from "
        f"measurement (comparison / disabled feature group / zero-variance)."
    )
    print(
        f"# Tiers kept at their CURRENT value (every member feature excluded): "
        f"{sorted(kept_tiers)}"
    )
    print()
    print("# ── Paste this block into original/constants.py → TIER_WEIGHTS ──────────────")
    print("TIER_WEIGHTS: dict[int, float] = {")
    for tier in sorted(measured):
        current = TIER_WEIGHTS.get(tier)
        new = measured[tier]
        label = _TIER_LABELS.get(tier, f"Tier {tier}")
        if tier in kept_tiers:
            print(f"    {tier:>2}: {new:5.2f},   # {label} (kept: not measurable in this pipeline)")
        else:
            delta = "" if current is None else f", was {current:.2f} ({new - current:+.2f})"
            survivor = single_survivor_tiers.get(tier)
            weak = f" (single surviving feature: {survivor} — weak evidence)" if survivor else ""
            print(f"    {tier:>2}: {new:5.2f},   # {label}{delta}{weak}")
    print("}")
    print()
    print("# NOTE: INFORMATIONAL ONLY — the user has HELD these weights; nothing in")
    print("# this script applies anything to constants.py. Hand-verify before ever")
    print("# proposing an edit; see task-11/13 STOP-AND-ASK history.")


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
        default=DEFAULT_LENGTH,
        help=f"Window length (words) fed to compute_feature_matrix. Default {DEFAULT_LENGTH} "
        f"— chosen so every current derivation-side author clears "
        f"MIN_WINDOWS_PER_AUTHOR={MIN_WINDOWS_PER_AUTHOR}.",
    )
    parser.add_argument(
        "--floor-percentile",
        type=float,
        default=DEFAULT_FLOOR_PERCENTILE,
        help="Percentile of positive within-author variances used as a floor for "
        "near-degenerate denominators. Default 10.0.",
    )
    args = parser.parse_args(argv)

    corpora = [c.strip() for c in args.corpora.split(",") if c.strip()]
    author_texts, author_corpus = load_all_corpora(corpora)
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
    weights, diagnostics = derive_weights(
        derivation_texts, length=args.length, floor_percentile=args.floor_percentile, verbose=True
    )

    # Task 8: turn this module's hand-written Plato-dominance CAUTION (see
    # module docstring) into a computed check. Genre is per-corpus here
    # (seminary=student_essay, plato=philosophy, public_authors=literary_essay);
    # manifest-level genre tags refine this once corpora carry them
    # (validation/manifest_schema.py v2). Measured over the SURVIVING
    # derivation-side authors only — i.e. after drop_short_authors (inside
    # derive_weights above) has removed anyone below MIN_WINDOWS_PER_AUTHOR
    # — since that's the population the weights above were actually derived
    # from, not the full pre-drop derivation split.
    from dataclasses import asdict

    from validation.corpus_policy import MAX_GENRE_SHARE, check_genre_balance

    _GENRE_BY_CORPUS = {
        "seminary": "student_essay",
        "plato": "philosophy",
        "public_authors": "literary_essay",
    }
    surviving_derivation_texts = {
        a: t for a, t in derivation_texts.items() if a not in diagnostics["dropped_authors"]
    }
    genre_words: dict[str, int] = {}
    for author, text in surviving_derivation_texts.items():
        corpus_name = author_corpus.get(author, "?")
        genre = _GENRE_BY_CORPUS.get(corpus_name, corpus_name)
        genre_words[genre] = genre_words.get(genre, 0) + len(text.split())
    genre_balance_violations = check_genre_balance(genre_words)
    for v in genre_balance_violations:
        print(f"  ⚠ CORPUS BALANCE: {v.subject} — {v.detail}", file=sys.stderr)

    # Per-corpus post-windowing report (requirement: visible before the diff).
    print("[derive-weights] post-windowing window counts by corpus:", file=sys.stderr)
    by_corpus: dict[str, list[tuple[str, int]]] = {}
    for author, n in sorted(diagnostics["window_counts_all"].items()):
        by_corpus.setdefault(author_corpus.get(author, "?"), []).append((author, n))
    for corpus in sorted(by_corpus):
        entries = by_corpus[corpus]
        total_windows = sum(n for _, n in entries)
        print(f"  {corpus}: {len(entries)} authors, {total_windows} windows", file=sys.stderr)
        for author, n in entries:
            flag = (
                " (DROPPED — below min-windows floor)"
                if author in diagnostics["dropped_authors"]
                else ""
            )
            print(f"    {author}: {n} window(s){flag}", file=sys.stderr)

    print_tier_weights_diff(weights, diagnostics)

    # Task 7: embed a machine-readable record of what this run measured,
    # alongside the human-readable diff block above.
    from validation.experiment import build_spec, spec_to_dict, summarize_author_docs

    corpora_summary = {}
    for corpus_name in corpora:
        # {author: text} -> {author: [text]} — summarize_author_docs wants a
        # list of documents per author; each corpus loader here hands back
        # one concatenated full-work string per (pseudo-)author.
        subset = {
            a: [t] for a, t in author_texts.items() if author_corpus.get(a) == corpus_name
        }
        provenance = "student_pilot" if corpus_name == "seminary" else "real_historical"
        corpora_summary[corpus_name] = summarize_author_docs(subset, provenance)

    # Task 8: the genre-balance skew travels with every number derived from
    # this run, not just the stderr warning above.
    corpora_summary["genre_balance"] = {
        "genre_words": genre_words,
        "max_share": MAX_GENRE_SHARE,
        "violations": [asdict(v) for v in genre_balance_violations],
    }

    spec = build_spec(
        task="weight_derivation",
        corpora=corpora_summary,
        windowing={"length": args.length, "max_windows": DEFAULT_MAX_WINDOWS},
        aggregation={
            "tier_rule": "median",
            "variance_floor_percentile": args.floor_percentile,
            "derivation_fraction": args.derivation_fraction,
        },
        thresholds={},
    )
    print()
    print("# ── experiment spec (machine-readable record of what this run measured) ──")
    print(json.dumps({"experiment": spec_to_dict(spec)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
