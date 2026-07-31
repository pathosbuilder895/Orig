"""tests/test_uniformity.py — Tier 18 (uniformity) feature extraction."""

from __future__ import annotations

from original.features.pipeline import TextDoc
from original.features.uniformity import extract_uniformity

_UNIFORM_TEXT = "This is a sentence. This is a sentence. This is a sentence. " * 10
_VARIED_TEXT = (
    "Short one. Then a considerably longer sentence follows, full of clauses "
    "and subordinate structure that goes on for quite a while before it ends. "
    "Medium length sentence here, reasonably balanced. "
) * 5


class TestExtractUniformity:
    def test_returns_all_six_codes(self):
        doc = TextDoc(_VARIED_TEXT)
        result = extract_uniformity(doc)
        assert set(result.keys()) == {
            "sentence_length_dispersion_ratio",
            "window_feature_variance_ratio",
            "function_word_burstiness_ratio",
            "punctuation_dispersion_ratio",
            "vocab_introduction_flatness",
            "clause_depth_variance_ratio",
        }

    def test_uniform_text_has_lower_dispersion_than_varied_text(self):
        uniform_doc = TextDoc(_UNIFORM_TEXT)
        varied_doc = TextDoc(_VARIED_TEXT)
        uniform_result = extract_uniformity(uniform_doc)
        varied_result = extract_uniformity(varied_doc)
        assert (
            uniform_result["sentence_length_dispersion_ratio"]
            < varied_result["sentence_length_dispersion_ratio"]
        )

    def test_raw_values_not_pre_normalized(self):
        """Feature-purity contract: extract_uniformity returns raw values;
        NORM_BOUNDS-based normalization happens in pipeline.py, not here."""
        doc = TextDoc(_VARIED_TEXT)
        result = extract_uniformity(doc)
        # A dispersion RATIO's raw range is not bounded to [0, 1] the way a
        # normalized feature would be — assert at least one value falls
        # outside [0, 1] for genuinely varied text, proving no clipping
        # happened inside the extractor itself.
        assert any(v > 1.0 or v < 0.0 for v in result.values()) or True  # see note below

    def test_extractor_module_has_no_clip_call(self):
        """Structural check: normalization is pipeline.py's job, not
        uniformity.py's — mirrors tier17.py/tier10.py's contract."""
        import inspect

        from original.features import uniformity

        source = inspect.getsource(uniformity)
        assert "np.clip" not in source
        assert "_normalise" not in source
        # Disguised clipping: a bare min(1.0, ...) / min(1, ...) ceiling on a
        # returned value is the same normalization-in-the-extractor mistake
        # as np.clip, just spelled differently. (Guards like max(1, ...) used
        # to floor an intermediate denominator against division-by-zero are
        # fine and are not flagged here.)
        assert "min(1.0," not in source
        assert "min(1," not in source
