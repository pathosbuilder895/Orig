"""validation/verify/compression_signals.py -- character-LM cross-entropy and
zlib NCD as pan_stack fusion signals. No corpus dependency: synthetic
StyleAuthor-shaped fixtures only (same convention as test_delta_signals.py)."""

from __future__ import annotations

import random
from dataclasses import dataclass

import pytest

from validation.verify.compression_signals import (
    build_char_lm,
    char_cross_entropy,
    compression_trial_signals,
    normalized_compression_distance,
)


@dataclass(frozen=True)
class _Author:
    author_id: str
    baselines: tuple
    probes: tuple


# Two deliberately different character regimes. Each sample is generated from a
# fixed seed so fixtures are reproducible, but every sample uses a DIFFERENT
# seed so the text is not periodic -- a repeated block compresses to almost
# nothing and makes both NCD and an n-gram LM behave unlike real prose.
_COMMON = (
    "the of and to in a is that it was for on with as he but they her had at from "
    "she which or an we been more when will who so no if out up what about would "
    "there their said them one all into time has him some could because while"
).split()
_ODD = ["ZZQ", "XKV", "jjq", "vzx", "qqzz", "kkvv", "xxjj", "zqk", "vjx", "kzq", "jvz"]


def _synth(words: list[str], seed: int, n: int = 1200) -> str:
    rng = random.Random(seed)
    return " ".join(rng.choice(words) for _ in range(n))


def _author(author_id: str, words: list[str], seed: int, n_baselines=3, n_probes=2) -> _Author:
    return _Author(
        author_id,
        tuple(_synth(words, seed + i) for i in range(n_baselines)),
        tuple(_synth(words, seed + 100 + i) for i in range(n_probes)),
    )


def test_cross_entropy_is_lower_under_the_texts_own_model():
    """The core claim the compression_delta signal rests on."""
    own = build_char_lm([_synth(_COMMON, s) for s in (1, 2, 3)], order=5)
    foreign = build_char_lm([_synth(_ODD, s) for s in (11, 12, 13)], order=5)
    probe = _synth(_COMMON, 99)

    h_own = char_cross_entropy(probe, own)
    h_foreign = char_cross_entropy(probe, foreign)
    assert h_own < h_foreign, f"h_own={h_own} h_foreign={h_foreign}"
    assert h_own > 0.0  # bits/char is a positive quantity


def test_cross_entropy_is_deterministic():
    texts = [_synth(_COMMON, s) for s in (1, 2, 3)]
    probe = _synth(_COMMON, 99)
    lm = build_char_lm(texts, order=5)
    assert char_cross_entropy(probe, lm) == char_cross_entropy(probe, lm)
    # ...and independent of the model object, i.e. no training-time RNG.
    assert char_cross_entropy(probe, lm) == char_cross_entropy(probe, build_char_lm(texts, order=5))


def test_ncd_of_a_text_with_itself_is_near_zero_and_lower_than_with_a_stranger():
    text = _synth(_COMMON, 5, n=2000)
    self_ncd = normalized_compression_distance(text, text)
    stranger_ncd = normalized_compression_distance(text, _synth(_ODD, 6, n=2000))
    assert self_ncd < 0.1, f"self NCD should be near zero, got {self_ncd}"
    assert self_ncd < stranger_ncd


def test_ncd_lzma_backend_agrees_on_ordering():
    text = _synth(_COMMON, 5, n=2000)
    assert normalized_compression_distance(text, text, backend="lzma") < (
        normalized_compression_distance(text, _synth(_ODD, 6, n=2000), backend="lzma")
    )


def test_abstains_with_none_on_too_short_input():
    """None -- not 0.0, not a neutral value -- is the abstention contract the
    fusion layer's SimpleImputer(add_indicator=True) is built around."""
    from validation.verify.pan_stack import trial_id

    short = _Author("short", ("hi",), ("yo",))
    other = _author("other", _COMMON, 200)
    rows = compression_trial_signals({"locked": [short, other]}, order=4, max_workers=1)["locked"]

    row = rows[trial_id("short", "short", 0)]
    assert set(row) == {"compression_delta", "compression_h_author", "compression_ncd"}
    assert all(value is None for value in row.values()), row


def test_trial_signals_cover_every_combine_trials_identifier():
    from validation.verify.pan_stack import trial_id

    authors = [_author("alpha", _COMMON, 300), _author("beta", _ODD, 400)]
    rows = compression_trial_signals({"locked": authors}, order=4, max_workers=1)["locked"]

    expected = {
        trial_id(target.author_id, source.author_id, probe_index)
        for target in authors
        for source in authors
        for probe_index in range(len(source.probes))
    }
    assert set(rows) == expected
    for row in rows.values():
        assert set(row) == {"compression_delta", "compression_h_author", "compression_ncd"}


def test_compression_delta_favours_the_true_author():
    """Positive compression_delta == the claimed author's own model predicts
    the unknown text better than the peer pool does."""
    from validation.verify.pan_stack import trial_id

    authors = [_author("alpha", _COMMON, 300), _author("beta", _ODD, 400)]
    rows = compression_trial_signals({"locked": authors}, order=4, max_workers=1)["locked"]

    for author in authors:
        for probe_index in range(len(author.probes)):
            genuine = rows[trial_id(author.author_id, author.author_id, probe_index)]
            impostors = [
                rows[trial_id(other.author_id, author.author_id, probe_index)]["compression_delta"]
                for other in authors
                if other.author_id != author.author_id
            ]
            assert genuine["compression_delta"] > max(impostors)


def test_trial_signals_are_deterministic_across_runs():
    authors = [_author("alpha", _COMMON, 300), _author("beta", _ODD, 400)]
    first = compression_trial_signals({"locked": authors}, order=4, max_workers=1)
    second = compression_trial_signals({"locked": authors}, order=4, max_workers=1)
    assert first == second


def test_peer_reference_never_includes_the_claimed_author():
    """A peer pool contaminated with the target's own text would collapse
    compression_delta toward zero; assert the exclusion structurally."""
    from validation.verify.compression_signals import _peer_blob

    alpha = _author("alpha", _COMMON, 300)
    alpha = _Author("alpha", tuple("ALPHAMARKER " + t for t in alpha.baselines), alpha.probes)
    authors = [alpha, _author("beta", _ODD, 400), _author("gamma", _COMMON, 500)]
    blob = _peer_blob(authors, "alpha", peer_pool_chars=100_000)
    assert blob  # non-empty
    assert "ALPHAMARKER" not in blob


def test_build_char_lm_rejects_empty_training_text():
    with pytest.raises(ValueError):
        build_char_lm(["", "   "], order=4)
