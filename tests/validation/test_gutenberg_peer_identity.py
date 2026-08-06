import numpy as np

from validation.verify.gutenberg_peer_identity import identity_features, select_threshold


def test_identity_features_rank_matching_enrolled_baseline():
    baseline = np.eye(3)
    documents = np.repeat(baseline[:, None, :], 3, axis=1)
    probes = np.repeat(baseline[:, None, :], 2, axis=1)
    embeddings = {
        "baseline": baseline,
        "baseline_documents": documents,
        "probes": probes,
    }
    features, top = identity_features(embeddings, embeddings)
    np.testing.assert_array_equal(top, [0, 0, 1, 1, 2, 2])
    assert features.shape == (6, 12)
    assert np.all(features[:, 1] > 0)


def test_threshold_enforces_exact_precision_and_outside_abstention():
    correct = np.asarray([True, True, True, False, True])
    known = np.asarray([0.99, 0.95, 0.90, 0.85, 0.80])
    outside = np.asarray([0.88, 0.40, 0.30, 0.20, 0.10])
    threshold = select_threshold(correct, known, outside, max_outside_rate=0.0)
    selected = known >= threshold
    assert correct[selected].mean() >= 0.90
    assert not np.any(outside >= threshold)


def test_threshold_abstains_when_no_safe_naming_point_exists():
    correct = np.asarray([False, False])
    known = np.asarray([0.9, 0.8])
    outside = np.asarray([0.95, 0.85])
    threshold = select_threshold(correct, known, outside, max_outside_rate=0.0)
    assert not np.any(known >= threshold)
    assert not np.any(outside >= threshold)
