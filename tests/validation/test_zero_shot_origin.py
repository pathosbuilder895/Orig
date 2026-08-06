import hashlib
import json

import numpy as np

from validation.cause.zero_shot_origin import score_texts, threshold_at_fpr


def test_threshold_at_fpr_is_conservative_for_small_calibration() -> None:
    scores = np.arange(50, dtype=np.float64)
    threshold = threshold_at_fpr(scores, target_fpr=0.01)
    assert int((scores >= threshold).sum()) == 0


def test_threshold_at_fpr_allows_only_empirical_tail() -> None:
    scores = np.arange(200, dtype=np.float64)
    threshold = threshold_at_fpr(scores, target_fpr=0.01)
    assert int((scores >= threshold).sum()) == 1


def test_zero_fpr_threshold_respects_float32_score_resolution() -> None:
    scores = np.asarray([-6.0, -5.5, -5.259041786193847], dtype=np.float32)
    threshold = threshold_at_fpr(scores, target_fpr=0.0)
    assert threshold > float(scores.max())
    assert not (scores >= threshold).any()


def test_score_texts_reuses_exact_complete_cache(tmp_path) -> None:
    texts = ["one document", "another document"]
    hashes = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
    cache_key = hashlib.sha256(
        json.dumps(["not-a-real-model", 32, hashes], separators=(",", ":")).encode()
    ).hexdigest()
    cache = tmp_path / "scores.npz"
    np.savez_compressed(
        cache,
        cache_key=np.asarray(cache_key),
        scores=np.asarray([1.25, -0.5]),
    )
    result = score_texts(
        texts,
        model_name="not-a-real-model",
        cache_path=cache,
        device="cpu",
        max_tokens=32,
    )
    np.testing.assert_allclose(result, [1.25, -0.5])
