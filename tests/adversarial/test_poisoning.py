"""
tests/adversarial/test_poisoning.py — baseline-poisoning scenarios
(Task 17).

Covers `validation.adversarial.poisoning.poison_profile`, the
baseline-tampering half of SP1's offline red-team harness
(docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md,
attacker taxonomy §1). Three modes:

  - "obfuscated_baselines": victim's own baselines run through Task 14's
    MechanicalObfuscation.
  - "sigma_inflation": a minority of baselines swapped for a different,
    variance-maximizing author's documents — widens internal spread.
  - "outsourced_baselines": the entire baseline set replaced by a
    different author's documents.

In every mode, `genuine_holdout` and `impostor_docs` are passed through
unchanged — Task 18's harness will score the poisoned baselines against
the ORIGINAL holdout/impostor pool, so those fields must be untouched
for that comparison to be meaningful.
"""

from __future__ import annotations

import pytest

from validation.adversarial.poisoning import baseline_variance_proxy, poison_profile
from validation.adversarial.profiles import build_victim_profiles

_SEED = 20260921


def test_obfuscated_baselines_differ_from_original():
    profile = build_victim_profiles(3, seed=_SEED)[0]
    poisoned = poison_profile(profile, "obfuscated_baselines")

    assert poisoned.baselines != profile.baselines
    assert len(poisoned.baselines) == len(profile.baselines)
    assert poisoned.genuine_holdout == profile.genuine_holdout
    assert poisoned.impostor_docs == profile.impostor_docs
    assert poisoned.victim_id == profile.victim_id


def test_outsourced_baselines_come_from_a_different_author():
    profiles = build_victim_profiles(3, seed=_SEED)
    profile = profiles[0]
    poisoned = poison_profile(profile, "outsourced_baselines")

    assert len(poisoned.baselines) == len(profile.baselines)
    assert poisoned.genuine_holdout == profile.genuine_holdout
    assert poisoned.impostor_docs == profile.impostor_docs
    assert poisoned.victim_id == profile.victim_id

    # Not just "!= the specific 3 baselines" — genuinely absent from
    # everything the ORIGINAL victim's real corpus text contains
    # (baselines, genuine_holdout, and impostor_docs, which are other
    # authors' text but might coincidentally overlap if the mechanism
    # were broken and returned the victim's own impostor pool back).
    victim_corpus_texts = set(profile.baselines) | set(profile.genuine_holdout)
    for text in poisoned.baselines:
        assert text not in victim_corpus_texts

    # And genuinely sourced from one of the OTHER victims in the corpus,
    # not fabricated — cross-check against every other victim's own
    # baseline pool at the same n_baselines.
    other_baseline_pool = {
        text
        for other in profiles
        if other.victim_id != profile.victim_id
        for text in other.baselines
    }
    for text in poisoned.baselines:
        assert text in other_baseline_pool


def test_sigma_inflation_increases_variance():
    profile = build_victim_profiles(3, seed=_SEED)[0]
    poisoned = poison_profile(profile, "sigma_inflation")

    assert len(poisoned.baselines) == len(profile.baselines)
    assert poisoned.genuine_holdout == profile.genuine_holdout
    assert poisoned.impostor_docs == profile.impostor_docs
    assert poisoned.victim_id == profile.victim_id

    original_variance = baseline_variance_proxy(profile.baselines)
    poisoned_variance = baseline_variance_proxy(poisoned.baselines)
    assert poisoned_variance > original_variance

    # "Some, not all" — at least one of the victim's own baselines must
    # survive untouched.
    assert any(text in profile.baselines for text in poisoned.baselines)
    assert poisoned.baselines != profile.baselines


def test_sigma_inflation_increases_variance_for_every_victim():
    # The variance-maximizing donor selection (see poisoning.py's
    # _sigma_inflation docstring) is specifically designed to hold for
    # every victim in the corpus, not just profiles[0] — this is the
    # property a hash-fixed donor pick could NOT guarantee (empirically
    # measured: it failed for 3 of 13 victims). Confirm it holds across
    # the whole corpus at n_baselines=3.
    profiles = build_victim_profiles(3, seed=_SEED)
    for profile in profiles:
        poisoned = poison_profile(profile, "sigma_inflation")
        original_variance = baseline_variance_proxy(profile.baselines)
        poisoned_variance = baseline_variance_proxy(poisoned.baselines)
        assert poisoned_variance > original_variance, profile.victim_id


def test_sigma_inflation_replaces_a_strict_minority_from_one_donor():
    """Mechanism-level test independent of the variance-maximizing
    objective (code-review Finding 2 on commit ba26ad3c, Task 17):
    `test_sigma_inflation_increases_variance*` only assert the
    donor-selection search's own target (the variance proxy) went up,
    which the search is explicitly built to maximize — that alone can't
    distinguish a correct substitution mechanism from a buggy one that
    still stumbles onto *some* variance-increasing arrangement (e.g. an
    off-by-one in which slot gets replaced, or double-writing one
    position while leaving another untouched). This test instead pins
    down WHICH positions changed and WHERE the replacement text came
    from, for every victim in the corpus at n_baselines=3.
    """
    profiles = build_victim_profiles(3, seed=_SEED)
    donor_pools = {
        other.victim_id: set(other.baselines) for other in profiles
    }

    for profile in profiles:
        poisoned = poison_profile(profile, "sigma_inflation")
        n = len(profile.baselines)

        changed_positions = [
            i for i in range(n) if poisoned.baselines[i] != profile.baselines[i]
        ]
        unchanged_positions = [i for i in range(n) if i not in changed_positions]

        # Finding 1's fix, pinned at the mechanism level: a real STRICT
        # minority (exactly floor((n-1)/2) positions), not merely
        # ">= 1 and < n".
        expected_k = (n - 1) // 2
        assert len(changed_positions) == expected_k, profile.victim_id
        assert len(changed_positions) < len(unchanged_positions), profile.victim_id

        # Untouched positions must be byte-identical to the ORIGINAL
        # text at that same index — catches a bug that replaces the
        # right COUNT of positions but the wrong SLOTS (writing to
        # `slot` instead of `pos`, or replacing one position twice
        # while skipping another).
        for i in unchanged_positions:
            assert poisoned.baselines[i] == profile.baselines[i], (
                profile.victim_id,
                i,
            )

        # Every replaced baseline is drawn verbatim from exactly ONE
        # donor author's real baseline pool — not garbled, not a random
        # string, and not accidentally sourced from more than one donor
        # (which would indicate the donor-selection loop leaked state
        # across candidates instead of committing to a single winner).
        donors_used: set[str] = set()
        for i in changed_positions:
            text = poisoned.baselines[i]
            matching_donors = {
                vid
                for vid, pool in donor_pools.items()
                if vid != profile.victim_id and text in pool
            }
            assert matching_donors, (
                f"{profile.victim_id}: replaced baseline at position {i} is "
                "not verbatim text from any other author's baseline pool"
            )
            donors_used |= matching_donors

        assert len(donors_used) == 1, (
            f"{profile.victim_id}: replaced baselines should all come from "
            f"a single donor author, got {donors_used}"
        )


def test_deterministic_for_same_profile_and_mode():
    profile = build_victim_profiles(3, seed=_SEED)[0]

    for mode in ("obfuscated_baselines", "sigma_inflation", "outsourced_baselines"):
        a = poison_profile(profile, mode)
        b = poison_profile(profile, mode)
        assert a.baselines == b.baselines, mode


def test_unknown_mode_raises():
    profile = build_victim_profiles(3, seed=_SEED)[0]
    with pytest.raises(ValueError):
        poison_profile(profile, "not_a_real_mode")
