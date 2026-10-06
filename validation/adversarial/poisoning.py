"""
validation/adversarial/poisoning.py — baseline-poisoning scenarios (Task 17).

Implements `poison_profile(profile, mode) -> VictimProfile`, the
baseline-tampering half of SP1's offline red-team harness
(docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md,
attacker taxonomy §1 "the student controls what becomes their own
baseline"). Where Task 14/15's generators simulate an adversary altering
the SUBMISSION, this module simulates an adversary altering the
BASELINE the submission is later compared against — a different, and in
some ways more powerful, attack surface: if the reference itself is
compromised, every future submission is scored against a corrupted
target.

Three modes, one dispatcher:

  - "obfuscated_baselines": the victim writes their OWN baselines in a
    deliberately thinned/simplified voice (Task 14's
    `MechanicalObfuscation`, run over every baseline document). Models a
    student who suspects stylometric monitoring and flattens their own
    writing style from day one.

  - "sigma_inflation": mixes a DIFFERENT author's material into a
    strict minority of the victim's baselines — at most
    floor((n-1)/2) of them, always strictly fewer replaced than kept —
    widening the baseline set's internal variance without discarding
    the victim's own voice entirely. Models a student padding their
    baseline submissions with borrowed/ghostwritten material some of
    the time, which (if it works) would widen the acceptance band
    future submissions are scored against.

  - "outsourced_baselines": replaces the ENTIRE baseline set with a
    different author's documents. Models a student who has someone else
    write 100% of their baseline material — the "ghostwriter from day
    one" attack.

`genuine_holdout` and `impostor_docs` are passed through unchanged in
every mode (only `baselines` is the attack surface here — Task 18's
harness scores the poisoned baselines against the ORIGINAL, unpoisoned
holdout/impostor pool, so those fields must stay put for that comparison
to mean anything).

Determinism: every random-ish choice this module makes (which
obfuscation seed, which other author, which baseline positions get
replaced) is derived from `profile.victim_id` via SHA-256, the same
content-addressed-determinism convention `profiles.py` already uses
(see its `_digest`/`_seeded_order`). Two calls with the same
(profile, mode) always return byte-identical output; no wall-clock
randomness anywhere.

Coupling decision — no `original.*` import
--------------------------------------------
`validation/adversarial/` currently has zero imports from `original.*`
(checked: profiles.py, generators.py, fetch_riddell_juola.py all stay
within `validation.*`/stdlib/spaCy/a public corpus). Task 17's
sigma_inflation mode needs SOME way to show "variance went up" for its
own test, and the two options are (a) a real per-feature std computed
via `original.features.pipeline`'s 109-dim extractor, or (b) a cheap
text-level proxy. This module takes (b): `baseline_variance_proxy()`
computes four inexpensive, stdlib-only per-document statistics (mean
word length, type-token ratio, mean sentence length, punctuation rate)
and sums their population standard deviation across a baseline set.
Tradeoffs considered:

  - Importing `original.features.pipeline.feature_vector` would give a
    "real" 109-dim std and let downstream harness code reuse the exact
    metric production scoring cares about. But it would also (1) pull
    spaCy-heavy, sentence-transformer-optional feature extraction into
    a package that currently has none of that dependency weight, (2)
    couple this validation module's correctness to `original/`'s
    internal feature contract (a change to `ALL_FEATURE_CODES` or a
    tier's neutral-value behavior would then silently change what
    "poisoned" means here), and (3) most importantly, the mechanism
    (which baselines get replaced, by whom) doesn't need real features
    to be validated — it only needs to show the poisoned SET is more
    heterogeneous than the original, which cheap text statistics
    already demonstrate directly.
  - The text-level proxy keeps this package's dependency footprint
    exactly what it already was, is fast enough to run in every test
    invocation without spaCy, and measures the same underlying claim
    (documents that read as if written by more than one person show
    more spread across a handful of style-adjacent statistics) that
    the real feature pipeline would eventually measure too. It's a
    proxy, not a replacement — Task 18's actual harness runs, if it
    wants scored deviation numbers, will go through the real scoring
    path in `original.quantum.scoring`, not through this function.

`baseline_variance_proxy()` is exported (not `_`-prefixed) specifically
so `tests/adversarial/test_poisoning.py` can use it directly, per the
brief's Step 1 instruction that the sigma_inflation test needs "some way
to measure this."
"""

from __future__ import annotations

import hashlib
import re
import statistics
from dataclasses import replace

from validation.adversarial.generators import MechanicalObfuscation
from validation.adversarial.profiles import VictimProfile, build_victim_profiles

MODES = ("obfuscated_baselines", "sigma_inflation", "outsourced_baselines")

# "Some, not all" for sigma_inflation: the number of positions replaced,
# k = floor((n - 1) / 2), is a STRICT minority — k < n - k holds for
# every n >= 3 (checked by direct computation for n=2..13; see
# `_sigma_inflation`'s docstring). A naive `round(n * 0.5)` looks like
# "half" but Python's banker's rounding pushes it to a MAJORITY at
# n=3, 7, 11, ... (round(1.5) == 2), which is what this replaced.


def poison_profile(profile: VictimProfile, mode: str) -> VictimProfile:
    """Return a new VictimProfile with `baselines` poisoned per `mode`.

    `genuine_holdout` and `impostor_docs` are always carried over
    unchanged from `profile` — only `baselines` differs between the
    input and output profiles, in every mode.

    Deterministic: two calls with the same `profile` and `mode` return
    byte-identical `baselines` (see module docstring).

    Raises:
        ValueError: if `mode` is not one of MODES.
    """
    if mode == "obfuscated_baselines":
        return _obfuscated_baselines(profile)
    if mode == "sigma_inflation":
        return _sigma_inflation(profile)
    if mode == "outsourced_baselines":
        return _outsourced_baselines(profile)
    raise ValueError(f"unknown poisoning mode {mode!r}; expected one of {MODES}")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _seed_int(namespace: str, victim_id: str) -> int:
    """Deterministic integer seed derived from victim_id, namespaced per
    call site so unrelated poisoning decisions don't collide on the same
    derived seed by coincidence."""
    return int(_digest(f"{namespace}:{victim_id}")[:16], 16)


def _obfuscated_baselines(profile: VictimProfile) -> VictimProfile:
    """Run every baseline through MechanicalObfuscation, seeded off the
    victim's own id so the transform is reproducible but not shared
    verbatim across different victims."""
    seed = _seed_int("obfuscated_baselines", profile.victim_id)
    obfuscator = MechanicalObfuscation(seed=seed)
    poisoned_baselines = [obfuscator.transform(text) for text in profile.baselines]
    return replace(profile, baselines=poisoned_baselines)


def _other_author_profile(profile: VictimProfile, namespace: str) -> VictimProfile:
    """Deterministically pick a DIFFERENT victim's profile to draw
    replacement baseline text from.

    Reuses `build_victim_profiles` (the same corpus-loading machinery
    `profiles.py` already built) rather than a second corpus loader —
    per the brief. `n_baselines` is matched to `profile`'s own baseline
    count so the pool is restricted to authors who actually have that
    many baseline documents available (build_victim_profiles's own
    eligibility filter). `seed=0` is passed because baseline/holdout
    selection there is content-addressed and seed-independent (see
    profiles.py's own docstring) — the seed argument has zero effect on
    which documents come back, only on impostor-pool composition, which
    this function doesn't use.
    """
    n = len(profile.baselines)
    pool = build_victim_profiles(n_baselines=n, seed=0)
    others = sorted(
        (p for p in pool if p.victim_id != profile.victim_id), key=lambda p: p.victim_id
    )
    if not others:
        raise ValueError(
            f"no other author has >= {n} baseline documents to draw from "
            f"(victim_id={profile.victim_id!r}, mode={namespace!r})"
        )
    index = _seed_int(namespace, profile.victim_id) % len(others)
    return others[index]


def _outsourced_baselines(profile: VictimProfile) -> VictimProfile:
    """Replace the entire baseline list with a different author's
    baseline documents (the "ghostwriter from day one" attack)."""
    other = _other_author_profile(profile, "outsourced_baselines")
    return replace(profile, baselines=list(other.baselines))


def _sigma_inflation(profile: VictimProfile) -> VictimProfile:
    """Replace a STRICT minority of baseline positions with a different
    author's documents, widening the set's internal variance while
    leaving a strict majority of the victim's own baselines intact.

    Replacement count: `k = (n - 1) // 2` (integer floor division),
    where `n = len(profile.baselines)`. This satisfies `k < n - k` —
    strictly fewer positions replaced than kept — for every `n >= 3`:

        n:  3  4  5  6  7  8  9 10 11 12 13
        k:  1  1  2  2  3  3  4  4  5  5  6

    An earlier version computed `k = max(1, round(n * 0.5))`, clamped
    only by `min(k, n - 1)`. That looks like "replace half," but
    Python's `round()` uses banker's rounding, so `round(n * 0.5)`
    rounds UP to `ceil(n / 2)` whenever `n` is odd (`round(1.5) == 2`,
    not 1) — making the replaced count a MAJORITY at n=3 (2/3), n=7
    (4/7), n=11 (6/11), etc. `n=3` is this file's own test corpus
    size, so every existing test was silently exercising a majority
    replacement despite the "minority" claim in this docstring and the
    module docstring. `(n - 1) // 2` is the correct "strictly fewer
    than half" formula for all n and needs no separate clamp.

    Mechanism (documented per the brief's request), two parts:

    1. WHICH POSITIONS get replaced: whole-document substitution at a
       deterministically chosen subset of positions (hash of
       victim_id+position index), rather than concatenating/
       interleaving chunks within each document. Whole-document
       substitution keeps the "widened variance" claim legible at the
       level the proxy metric measures (per-document aggregate
       statistics) — an untouched victim baseline and a
       fully-substituted other-author baseline sit at two distinct
       points in that statistic space, which is exactly what widens
       the spread; diluting each document with a smaller borrowed
       chunk would move every point only slightly and risks the effect
       washing out for authors whose style stats happen to already be
       close to the corpus median.

    2. WHICH OTHER AUTHOR donates the substituted documents: chosen to
       MAXIMIZE the resulting `baseline_variance_proxy`, among every
       eligible other author in the corpus (ties broken by victim_id
       for determinism). This was chosen over a single hash-picked
       author after empirically checking both: a fixed hash-based pick
       (one arbitrary other author per victim) INCREASES variance for
       10 of 13 victims at n_baselines=3 but DECREASES it for 3
       (augustine, douglass, thoreau — victims whose own baseline set
       already has unusually high internal spread, where a
       stylistically "unremarkable" donor pulls the mix toward the
       corpus middle instead of widening it). The variance-maximizing
       pick increases it for all 13. It's also the more defensible
       red-team simulation: an attacker actually running this attack
       would pick whichever donor material makes the attack work, not
       an arbitrary one. Still fully deterministic — it's a pure
       function of `profile`'s and every candidate's (content-
       addressed, on-disk) baseline text, no hash/seed involved in this
       part at all.

    n < 3: there is no way to replace at least one position while
    keeping the replaced count a STRICT minority below 3 baselines —
    n=2 would need exactly 1-of-2 replaced, which is a tie (1 == 1),
    not a minority, and n<2 has no meaningful "spread across
    baselines" at all (population stdev of zero or one value is always
    0). So this mode is a documented no-op below n=3 and returns
    `profile` unchanged rather than pretending to poison it or
    silently violating its own "strict minority" invariant.
    """
    n = len(profile.baselines)
    if n < 3:
        return profile
    k = (n - 1) // 2  # strict minority for every n >= 3 — see docstring table
    positions = sorted(
        range(n), key=lambda i: _digest(f"sigma_inflation_pos:{profile.victim_id}:{i}")
    )[:k]

    pool = build_victim_profiles(n_baselines=n, seed=0)
    candidates = sorted(
        (p for p in pool if p.victim_id != profile.victim_id), key=lambda p: p.victim_id
    )
    if not candidates:
        raise ValueError(
            f"no other author has >= {n} baseline documents to draw from "
            f"(victim_id={profile.victim_id!r}, mode='sigma_inflation')"
        )

    def _substitute(other: VictimProfile) -> list[str]:
        poisoned = list(profile.baselines)
        for slot, pos in enumerate(positions):
            poisoned[pos] = other.baselines[slot % len(other.baselines)]
        return poisoned

    best_baselines = _substitute(candidates[0])
    best_variance = baseline_variance_proxy(best_baselines)
    for other in candidates[1:]:
        candidate_baselines = _substitute(other)
        variance = baseline_variance_proxy(candidate_baselines)
        if variance > best_variance:
            best_variance = variance
            best_baselines = candidate_baselines

    return replace(profile, baselines=best_baselines)


# -- Text-level variance proxy (see module docstring) ------------------

_WORD_RE = re.compile(r"[A-Za-z']+")
_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")
_PUNCT_CHARS = set(".,;:!?")


def _word_tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _sentence_word_counts(text: str) -> list[int]:
    counts = [len(_word_tokens(s)) for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    return counts or [0]


def _text_stats(text: str) -> tuple[float, float, float, float]:
    """Four cheap, stdlib-only per-document style statistics:
    mean word length, type-token ratio (vocabulary diversity), mean
    sentence length in words, and punctuation rate — see module
    docstring for why these (not a real feature vector) are used."""
    words = _word_tokens(text)
    if not words:
        return (0.0, 0.0, 0.0, 0.0)
    avg_word_len = sum(len(w) for w in words) / len(words)
    ttr = len({w.lower() for w in words}) / len(words)
    sentence_counts = _sentence_word_counts(text)
    avg_sentence_len = sum(sentence_counts) / len(sentence_counts)
    punct_count = sum(1 for ch in text if ch in _PUNCT_CHARS)
    punct_rate = punct_count / max(1, len(text))
    return (avg_word_len, ttr, avg_sentence_len, punct_rate)


def baseline_variance_proxy(baselines: list[str]) -> float:
    """Sum, across the four `_text_stats` dimensions, of each
    dimension's population standard deviation over `baselines`.

    A single scalar "how stylistically spread out is this baseline
    set" proxy — see module docstring for why this (not a real 109-dim
    feature vector via `original.*`) is what this module and its test
    use to confirm sigma_inflation widens variance. Not a scoring
    metric; not used anywhere outside this module's own tests.

    Fewer than 2 baselines: 0.0 (population stdev of a single value, or
    of nothing, is degenerate either way).
    """
    if len(baselines) < 2:
        return 0.0
    stats = [_text_stats(text) for text in baselines]
    return sum(statistics.pstdev(dim) for dim in zip(*stats, strict=True))
