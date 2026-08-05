import json

import numpy as np

from validation.verify.pan_luar_expert import (
    CACHE_SCHEMA,
    EmbeddingCache,
    LuarTrial,
    _episode_key,
    build_calibrator,
    apply_stratified_thresholds,
    fit_stratified_thresholds,
    matched_trials,
    fit_plda,
    fit_lda_metric,
    lda_score_matrix,
    plda_score_matrix,
    score_partition,
    signal_matrix,
)
from validation.verify.pan_style_expert import StyleAuthor


def test_episode_key_is_ordered_and_content_addressed():
    assert _episode_key(("one", "two")) == _episode_key(("one", "two"))
    assert _episode_key(("one", "two")) != _episode_key(("two", "one"))
    assert _episode_key(("one",)) != _episode_key(("one", ""))


def test_embedding_cache_round_trip(tmp_path):
    path = tmp_path / "cache.npz"
    cache = EmbeddingCache(path)
    vector = np.arange(512, dtype=np.float32)
    cache.put(("essay",), vector)
    cache.save()
    restored = EmbeddingCache(path)
    np.testing.assert_array_equal(restored.get(("essay",)), vector)
    with np.load(path, allow_pickle=False) as archive:
        assert json.loads(str(archive["metadata"].item()))["schema"] == CACHE_SCHEMA


def test_cosine_scoring_and_matched_protocol():
    authors = [
        StyleAuthor("a", "x", "y", ("a1", "a2", "a3"), ("ap",)),
        StyleAuthor("b", "x", "y", ("b1", "b2", "b3"), ("bp",)),
        StyleAuthor("c", "x", "y", ("c1", "c2", "c3"), ("cp",)),
    ]
    embeddings = {
        "baseline": np.asarray([[1, 0], [0, 1], [-1, 0]], dtype=float),
        "baseline_documents": np.asarray(
            [
                [[1, 0], [1, 0], [1, 0]],
                [[0, 1], [0, 1], [0, 1]],
                [[-1, 0], [-1, 0], [-1, 0]],
            ],
            dtype=float,
        ),
        "probes": np.asarray([[[1, 0]], [[0, 1]], [[-1, 0]]], dtype=float),
    }
    exhaustive = score_partition(authors, embeddings)
    assert len(exhaustive) == 9
    genuine = [trial for trial in exhaustive if trial.label]
    assert all(np.isclose(trial.cosine_similarity, 1.0) for trial in genuine)
    matched = matched_trials(exhaustive)
    assert len(matched) == 6
    assert sum(trial.label for trial in matched) == 3


def test_signal_matrix_has_raw_zscore_and_best_peer_margin():
    trials = [
        LuarTrial("a", "source", 0, 0.9),
        LuarTrial("b", "source", 0, 0.5),
        LuarTrial("c", "source", 0, 0.2),
    ]
    signals = signal_matrix(trials)
    assert signals.shape == (3, 12)
    np.testing.assert_allclose(signals[:, 0], [0.9, 0.5, 0.2])
    assert signals[0, 1] > signals[1, 1] > signals[2, 1]
    assert signals[0, 2] > 0
    assert signals[1, 2] < 0


def test_baseline_consistency_signals_reward_cohesive_matching_documents():
    trial = LuarTrial(
        "a", "a", 0, 0.9, 0.85, 0.8, 0.03, 0.88, 0.84
    )
    peers = [
        LuarTrial("b", "a", 0, 0.3, 0.25, 0.1, 0.2, 0.7, 0.6),
        LuarTrial("c", "a", 0, 0.2, 0.15, 0.0, 0.3, 0.6, 0.5),
    ]
    signals = signal_matrix([trial, *peers])
    np.testing.assert_allclose(signals[0, 3:8], [0.85, 0.8, 0.03, 0.88, 0.84])
    assert np.isclose(signals[0, 8], -0.03)


def test_plda_scores_matching_authors_above_cross_author_pairs():
    rng = np.random.default_rng(1729)
    author_centers = rng.normal(size=(12, 8))
    baseline = author_centers[:, None, :] + rng.normal(scale=0.05, size=(12, 3, 8))
    probes = author_centers[:, None, :] + rng.normal(scale=0.05, size=(12, 3, 8))
    joint = baseline.mean(axis=1)
    embeddings = {
        "baseline": joint,
        "baseline_documents": baseline,
        "probes": probes,
    }
    model = fit_plda(embeddings, dimensions=6)
    scores = plda_score_matrix(model, embeddings)
    genuine = np.asarray([scores[index, :, index].mean() for index in range(12)])
    impostor = np.asarray([scores[index, :, (index + 1) % 12].mean() for index in range(12)])
    assert genuine.mean() > impostor.mean()


def test_lda_metric_scores_matching_authors_above_cross_author_pairs():
    rng = np.random.default_rng(73)
    centers = rng.normal(size=(12, 20))
    baseline = centers[:, None, :] + rng.normal(scale=0.15, size=(12, 3, 20))
    probes = centers[:, None, :] + rng.normal(scale=0.15, size=(12, 3, 20))
    embeddings = {
        "baseline": baseline.mean(axis=1),
        "baseline_documents": baseline,
        "probes": probes,
    }
    model = fit_lda_metric(embeddings, dimensions=8)
    scores = lda_score_matrix(model, embeddings)
    genuine = np.asarray([scores[index, :, index].mean() for index in range(12)])
    impostor = np.asarray([scores[index, :, (index + 1) % 12].mean() for index in range(12)])
    assert genuine.mean() > impostor.mean()


def test_interaction_calibrator_expands_only_pairwise_channels():
    model = build_calibrator(interactions=True)
    X = np.arange(280, dtype=float).reshape(20, 14)
    y = np.asarray([0, 1] * 10)
    model.fit(X, y)
    assert model.named_steps["interactions"].n_output_features_ == 105
    assert model.predict_proba(X).shape == (20, 2)


def test_stratified_thresholds_allocate_one_global_false_positive_budget():
    labels = np.asarray([1] * 30 + [0] * 300)
    reliability = np.r_[np.repeat([0.1, 0.5, 0.9], 10), np.repeat([0.1, 0.5, 0.9], 100)]
    scores = np.r_[
        [0.7] * 10,
        [0.8] * 10,
        [0.9] * 10,
        [0.6] * 100,
        [0.7] * 100,
        [0.8] * 97 + [0.91] * 3,
    ]
    rule = fit_stratified_thresholds(labels, scores, reliability)
    selected = apply_stratified_thresholds(scores, reliability, rule)
    assert int(np.sum(selected & (labels == 0))) <= 3
    assert np.mean(labels[selected]) >= 0.90
