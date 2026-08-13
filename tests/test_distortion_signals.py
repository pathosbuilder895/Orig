"""Unit tests for the POSNoise distortion signal producer
(``validation/verify/distortion_signals.py``).

These pin the contracts the Phase 2 ablation depends on being true, and that a
reader of the findings doc has to be able to trust without re-running the
harness:

* masking actually removes content and keeps function words (the mechanism
  fires -- the ``GENRE_INVARIANT_WEIGHTS_ENABLED`` lesson);
* abstention is ``None``, never a neutral number that would be silently read
  as evidence by the fusion;
* ``distorted_divergence`` is exactly the raw-minus-distorted contrast it is
  documented to be, so the gate arm cannot quietly become some other quantity;
* the producer is deterministic, so a locked-partition number is reproducible.
"""

from __future__ import annotations

import pytest

pytest.importorskip("spacy")

from validation.verify import distortion_signals as ds
from validation.verify.pan_style_expert import StyleAuthor


def _spacy_model_available() -> bool:
    from validation.attribution.lambdag import _get_nlp

    return _get_nlp() is not None


requires_model = pytest.mark.skipif(
    not _spacy_model_available(),
    reason="spaCy en_core_web_sm not installed",
)


# Long enough to clear MIN_TRAIN_CHARS / MIN_UNKNOWN_CHARS in the harness
# tests below. Content words differ between authors; function-word habits are
# what masking is supposed to leave behind.
_SENTENCE_A = (
    "The gardener planted the roses because the soil was rich and warm. "
    "She had wanted a garden for years, and now it was hers to tend. "
)
_SENTENCE_B = (
    "A physicist measured the particle while the detector hummed quietly. "
    "He would repeat the experiment until the numbers finally agreed. "
)


class TestMaskText:
    @requires_model
    def test_keeps_function_words_and_masks_content_words(self):
        masked = ds.mask_text("If they actually censor anything is another question.")
        # Function words survive literally, lowercased.
        assert "if" in masked
        assert "they" in masked
        assert "is" in masked
        assert "another" in masked
        # Content words are replaced by their POS tag, so the surface forms go.
        assert "censor" not in masked
        assert "question" not in masked
        assert "VERB" in masked
        assert "NOUN" in masked

    @requires_model
    def test_returns_a_flat_string_not_sentence_tuples(self):
        masked = ds.mask_text(_SENTENCE_A)
        assert isinstance(masked, str)
        assert masked

    @requires_model
    def test_is_deterministic(self):
        assert ds.mask_text(_SENTENCE_A) == ds.mask_text(_SENTENCE_A)

    @requires_model
    def test_empty_and_whitespace_text_returns_empty_string(self):
        assert ds.mask_text("") == ""
        assert ds.mask_text("   \n  ") == ""

    @requires_model
    def test_topic_swap_changes_raw_text_far_more_than_masked_text(self):
        """The whole premise of the channel: masking should collapse the
        difference between two texts that differ mainly in topic."""
        raw_overlap = _token_overlap(_SENTENCE_A, _SENTENCE_B)
        masked_overlap = _token_overlap(ds.mask_text(_SENTENCE_A), ds.mask_text(_SENTENCE_B))
        assert masked_overlap > raw_overlap


def _token_overlap(a: str, b: str) -> float:
    left, right = set(a.lower().split()), set(b.lower().split())
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _author(author_id: str, seed_text: str, *, repeats: int = 40) -> StyleAuthor:
    """A StyleAuthor with enough text to clear the producer's training floors."""
    body = seed_text * repeats
    return StyleAuthor(
        author_id=author_id,
        baseline_fandom="f1",
        probe_fandom="f2",
        baselines=(body, body),
        probes=(body,),
    )


def _short_author(author_id: str) -> StyleAuthor:
    return StyleAuthor(
        author_id=author_id,
        baseline_fandom="f1",
        probe_fandom="f2",
        baselines=("tiny.", "tiny."),
        probes=("tiny.",),
    )


class TestTrialSignals:
    @requires_model
    def test_covers_the_full_target_by_source_by_probe_cross_product(self):
        authors = [_author("a", _SENTENCE_A), _author("b", _SENTENCE_B)]
        out = ds.distortion_trial_signals({"p": authors}, max_workers=1)
        # 2 targets x 2 sources x 1 probe
        assert len(out["p"]) == 4
        assert "a|b|probe-0" in out["p"]

    @requires_model
    def test_emits_every_declared_signal_name(self):
        authors = [_author("a", _SENTENCE_A), _author("b", _SENTENCE_B)]
        out = ds.distortion_trial_signals({"p": authors}, max_workers=1)
        for row in out["p"].values():
            assert set(row) == set(ds.SIGNAL_NAMES)

    @requires_model
    def test_divergence_is_exactly_raw_minus_distorted(self):
        authors = [_author("a", _SENTENCE_A), _author("b", _SENTENCE_B)]
        out = ds.distortion_trial_signals({"p": authors}, max_workers=1)
        checked = 0
        for row in out["p"].values():
            if row["distorted_divergence"] is None:
                continue
            assert row["distorted_divergence"] == pytest.approx(
                row["undistorted_delta"] - row["distorted_delta"]
            )
            checked += 1
        assert checked > 0, "no non-abstaining rows -- mechanism never fired"

    @requires_model
    def test_abstains_with_none_not_a_neutral_number(self):
        authors = [_short_author("a"), _short_author("b")]
        out = ds.distortion_trial_signals({"p": authors}, max_workers=1)
        for row in out["p"].values():
            for name in ds.SIGNAL_NAMES:
                assert row[name] is None

    @requires_model
    def test_is_deterministic_across_runs(self):
        authors = [_author("a", _SENTENCE_A), _author("b", _SENTENCE_B)]
        first = ds.distortion_trial_signals({"p": authors}, max_workers=1)
        second = ds.distortion_trial_signals({"p": authors}, max_workers=1)
        assert first == second

    @requires_model
    def test_mechanism_fires_on_adequate_text(self):
        """Abstention must be 0.0 when every input clears the floors -- a null
        result is only interpretable if the channel actually ran."""
        authors = [_author("a", _SENTENCE_A), _author("b", _SENTENCE_B)]
        out = ds.distortion_trial_signals({"p": authors}, max_workers=1)
        for name in ds.SIGNAL_NAMES:
            assert ds.abstention_rate(out["p"], name) == 0.0


class TestAbstentionRate:
    def test_counts_none_values(self):
        rows = {"t1": {"s": 1.0}, "t2": {"s": None}, "t3": {"s": None}, "t4": {"s": 2.0}}
        assert ds.abstention_rate(rows, "s") == 0.5

    def test_empty_rows_is_nan(self):
        import math

        assert math.isnan(ds.abstention_rate({}, "s"))
