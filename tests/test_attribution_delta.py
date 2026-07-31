"""
tests/test_attribution_delta.py — distance-based attribution engines.

The raw argmin of per-author z-scores let the author with the loosest
baseline absorb 11 of 12 misattributions (Instrument Report). These
engines normalize at POOL level, so per-author variance scales cannot
create a black hole — the scale-invariance tests below pin exactly that
property.
"""
from __future__ import annotations

import numpy as np
import pytest

from validation.attribution.delta import cosine_delta_attribution, mfw_delta_attribution


def _matrices():
    rng = np.random.default_rng(1729)
    # Three authors with distinct 6-dim signatures, 5 baseline docs each.
    centers = {
        "alpha": np.array([0.2, 0.8, 0.4, 0.6, 0.3, 0.7]),
        "beta": np.array([0.7, 0.2, 0.6, 0.3, 0.8, 0.2]),
        "gamma": np.array([0.5, 0.5, 0.9, 0.1, 0.5, 0.5]),
    }
    return {
        a: c + rng.normal(0, 0.02, size=(5, 6)) for a, c in centers.items()
    }, centers


class TestCosineDelta:
    def test_recovers_true_author(self):
        matrices, centers = _matrices()
        for author, center in centers.items():
            test_vec = center + 0.01
            predicted, dists = cosine_delta_attribution(
                matrices, test_vec, feature_indices=list(range(6))
            )
            assert predicted == author
            assert set(dists) == set(centers)

    def test_loose_baseline_cannot_become_a_black_hole(self):
        # Inflate ONE author's within-baseline spread 50x. Under the old
        # own-z argmin this makes them absorb everything; pool-level
        # normalization must not care about within-author spread.
        matrices, centers = _matrices()
        rng = np.random.default_rng(7)
        matrices["gamma"] = centers["gamma"] + rng.normal(0, 1.0, size=(5, 6))
        test_vec = centers["alpha"] + 0.01
        predicted, _ = cosine_delta_attribution(
            matrices, test_vec, feature_indices=list(range(6))
        )
        assert predicted == "alpha"

    def test_restricts_to_given_feature_indices(self):
        matrices, centers = _matrices()
        # Make dims 3..5 pure noise for the test vector; dims 0..2 decide.
        test_vec = np.concatenate([centers["beta"][:3], np.array([9.0, 9.0, 9.0])])
        predicted, _ = cosine_delta_attribution(
            matrices, test_vec, feature_indices=[0, 1, 2]
        )
        assert predicted == "beta"

    def test_empty_author_matrix_is_skipped(self):
        matrices, centers = _matrices()
        matrices["empty"] = np.zeros((0, 6))
        predicted, dists = cosine_delta_attribution(
            matrices, centers["alpha"], feature_indices=list(range(6))
        )
        assert "empty" not in dists and predicted == "alpha"

    def test_fewer_than_two_authors_raises(self):
        matrices, centers = _matrices()
        with pytest.raises(ValueError):
            cosine_delta_attribution(
                {"alpha": matrices["alpha"]}, centers["alpha"], list(range(6))
            )

    def test_empty_feature_indices_raises(self):
        # No feature columns selected must fail loudly instead of returning
        # the alphabetically-first author on an all-1.0 distance dict.
        matrices, centers = _matrices()
        with pytest.raises(ValueError):
            cosine_delta_attribution(matrices, centers["alpha"], feature_indices=[])

    def test_non_finite_test_vector_raises(self):
        matrices, centers = _matrices()
        test_vec = centers["alpha"].copy()
        test_vec[2] = np.nan
        with pytest.raises(ValueError):
            cosine_delta_attribution(
                matrices, test_vec, feature_indices=list(range(6))
            )

    def test_non_finite_baseline_row_raises_and_names_author(self):
        matrices, centers = _matrices()
        matrices["gamma"] = matrices["gamma"].copy()
        matrices["gamma"][1, 3] = np.inf
        with pytest.raises(ValueError, match="gamma"):
            cosine_delta_attribution(
                matrices, centers["alpha"], feature_indices=list(range(6))
            )

    def test_non_finite_in_unselected_column_does_not_raise(self):
        # A NaN in a column nobody selected must not block a valid
        # attribution — validation is restricted to the selected columns.
        matrices, centers = _matrices()
        matrices["gamma"] = matrices["gamma"].copy()
        matrices["gamma"][1, 5] = np.nan  # column 5 excluded below
        test_vec = np.concatenate([centers["beta"][:5], np.array([9.0])])
        predicted, dists = cosine_delta_attribution(
            matrices, test_vec, feature_indices=[0, 1, 2, 3, 4]
        )
        assert predicted == "beta"
        assert set(dists) == set(centers)

    def test_single_row_baseline_matrix_attributes_correctly(self):
        matrices, centers = _matrices()
        matrices["alpha"] = centers["alpha"].reshape(1, -1)
        matrices["beta"] = centers["beta"].reshape(1, -1)
        matrices["gamma"] = centers["gamma"].reshape(1, -1)
        test_vec = centers["beta"] + 0.01
        predicted, dists = cosine_delta_attribution(
            matrices, test_vec, feature_indices=list(range(6))
        )
        assert predicted == "beta"
        assert set(dists) == set(centers)


def _letter_suffix(i):
    # Distinct filler tokens for the fixture below. A numeric suffix would
    # NOT work here: the tokenizer regex is [a-z']+, so "fill123" would
    # tokenize as just "fill" and collapse every filler token into one
    # word -- which would then compete with "so" for the top_n=2 vocab
    # slot. Letters-only suffixes stay distinct under the real tokenizer.
    letters = "abcdefghijklmnopqrstuvwxyz"
    out = []
    n = i
    while True:
        n, r = divmod(n, 26)
        out.append(letters[r])
        if n == 0:
            break
        n -= 1
    return "".join(reversed(out))


def _mfw_fixture_text(the_count, so_count, filler_count, filler_prefix):
    # Builds a document with an exact word count: `the_count` copies of
    # "the", `so_count` copies of "so", and `filler_count` DISTINCT filler
    # tokens (so none of them can outrank "so" in pooled frequency and
    # sneak into a top_n=2 vocabulary).
    parts = ["the "] * the_count + ["so "] * so_count
    parts += [f"{filler_prefix}{_letter_suffix(i)} " for i in range(filler_count)]
    return "".join(parts)


def _texts():
    # Two authors with opposite function-word tilts; enough tokens for
    # stable relative frequencies.
    a = ("the cat sat upon the mat and the dog lay upon the rug and "
         "the bird sat upon the branch and the sun shone upon the field ") * 30
    b = ("a child walks with a kite while a friend runs with a ball since "
         "a day begins with a song while a night ends with a story ") * 30
    return {"upon_author": [a, a], "with_author": [b, b]}


class TestMfwDelta:
    def test_recovers_true_author(self):
        texts = _texts()
        pred_a, deltas_a = mfw_delta_attribution(texts, texts["upon_author"][0])
        pred_b, deltas_b = mfw_delta_attribution(texts, texts["with_author"][0])
        assert pred_a == "upon_author"
        assert pred_b == "with_author"
        assert set(deltas_a) == {"upon_author", "with_author"}

    def test_pool_z_scoring_is_load_bearing_not_just_argmin_direction(self):
        """
        Pins the z-scoring step itself, not just the min()-direction: the
        fixture is built so that a variant with NO z-scoring at all (raw
        relative-frequency L1 distance), and a variant that z-scores the
        candidate profiles but forgets to z-score the test vector, both
        misattribute -- while the real pool-z-scored implementation gets
        it right.

        Two words carry the signal, deliberately in TENSION:
        - "so" is the rare word that genuinely distinguishes the authors:
          true_author's baseline so-rate (0.020) is double the rival's
          (0.010), and the test text's so-rate (0.021) matches
          true_author almost exactly.
        - "the" is the frequent word with a much larger absolute
          cross-candidate gap (0.800 rival vs 0.300 true_author) that is
          NOT the author signal here -- it is owned by the RIVAL, and the
          test text's the-rate (0.700) is dragged toward the rival's
          value, far from true_author's.

        An un-normalized distance is swamped by "the"'s large raw gap and
        picks the rival. Z-scoring both the candidate profiles AND the
        test vector against the same pool mu/sigma puts every word on
        equal footing, so the genuinely discriminating "so" dimension
        decides -- correctly, in favor of true_author. (Verified against
        both broken variants in isolation, outside this suite, before
        writing this test; see task report.)

        All three documents are exactly 1000 tokens, split between "the",
        "so", and DISTINCT filler tokens (via _letter_suffix) so that a
        top_n=2 call locks the vocabulary onto exactly {"the", "so"} --
        no accidental filler word can outrank "so" and steal its slot.
        """
        true_author_doc = _mfw_fixture_text(300, 20, 680, "afill")
        rival_doc = _mfw_fixture_text(800, 10, 190, "bfill")
        test_text = _mfw_fixture_text(700, 21, 279, "tfill")

        baseline = {"true_author": [true_author_doc], "rival": [rival_doc]}
        predicted, deltas = mfw_delta_attribution(baseline, test_text, top_n=2)

        assert predicted == "true_author"
        assert set(deltas) == {"true_author", "rival"}

    def test_unseen_words_do_not_crash(self):
        pred, _ = mfw_delta_attribution(
            _texts(), "zyx qwv completely novel vocabulary upon upon the the"
        )
        assert pred == "upon_author"

    def test_fewer_than_two_authors_raises(self):
        with pytest.raises(ValueError):
            mfw_delta_attribution({"solo": ["some text here"]}, "test")

    def test_empty_pooled_vocabulary_raises(self):
        # Every baseline text has zero [a-z'] characters (digits/punctuation
        # only) -> pooled vocab is empty. min() over an all-identical (0.0)
        # distance dict would silently return the alphabetically-first
        # candidate; raise instead.
        baseline = {"a": ["123 456", "789 000"], "b": ["!!! ???", "..."]}
        with pytest.raises(ValueError):
            mfw_delta_attribution(baseline, "111 222")

    def test_too_few_candidates_with_baseline_docs_raises(self):
        # "b" has an entirely empty list of baseline texts; only one
        # candidate is left with usable docs, below the attribution floor.
        # A single-word vocab is used deliberately: with the guard removed,
        # b's NaN profile is the same shape as a's real one, so np.vstack
        # does NOT crash on a shape mismatch -- the NaN quietly propagates
        # through mu/sd/z-scores into an all-NaN deltas dict, and min()
        # over NaNs silently returns the first candidate with no exception
        # at all. A shorter vocab would coincidentally raise a numpy
        # ValueError instead, masking whether this guard is doing anything.
        baseline = {"a": ["word"], "b": []}
        with pytest.raises(ValueError):
            mfw_delta_attribution(baseline, "word")

    def test_candidate_with_empty_baseline_list_is_skipped(self):
        # A candidate contributing zero baseline docs must not corrupt the
        # pool (np.mean of an empty list is NaN) or count toward the
        # result -- it is excluded, mirroring cosine_delta_attribution's
        # treatment of an empty baseline matrix.
        texts = _texts()
        texts["ghost_author"] = []
        pred, deltas = mfw_delta_attribution(texts, texts["upon_author"][0])
        assert pred == "upon_author"
        assert "ghost_author" not in deltas
        assert set(deltas) == {"upon_author", "with_author"}

    def test_degenerate_baseline_doc_does_not_crash(self):
        # One of two baseline docs for a candidate tokenizes to nothing;
        # _rel_freqs falls back to a zero vector for it instead of dividing
        # by zero, and the candidate still attributes using the signal
        # from its other (real) doc.
        texts = _texts()
        texts["upon_author"] = [texts["upon_author"][0], "1234 !!! ???"]
        pred, deltas = mfw_delta_attribution(texts, texts["upon_author"][0])
        assert pred == "upon_author"
        assert set(deltas) == {"upon_author", "with_author"}

    def test_degenerate_test_text_does_not_crash(self):
        # The disputed text itself has no recognizable words; it must
        # still receive a real (if uncertain) attribution rather than
        # raising or crashing on a divide-by-zero.
        pred, deltas = mfw_delta_attribution(_texts(), "1234 5678 !!! ???")
        assert pred in {"upon_author", "with_author"}
        assert set(deltas) == {"upon_author", "with_author"}
