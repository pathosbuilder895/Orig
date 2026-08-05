import numpy as np

from validation.cause.repreguard_origin import fit_directions, projection_scores


def test_layerwise_pca_directions_orient_machine_differences_positive():
    rng = np.random.default_rng(1729)
    human = rng.normal(scale=0.1, size=(20, 3, 8))
    shift = np.zeros((3, 8))
    shift[:, 0] = [1.0, 2.0, 3.0]
    machine = human + shift + rng.normal(scale=0.01, size=human.shape)
    directions = fit_directions(human, machine)
    assert directions.shape == (3, 8)
    np.testing.assert_allclose(np.linalg.norm(directions, axis=1), 1.0)
    assert np.all(np.einsum("ld,ld->l", (machine - human).mean(axis=0), directions) > 0)


def test_projection_scores_rank_shifted_machine_summaries_higher():
    directions = np.eye(3, 5, dtype=np.float32)
    human = np.zeros((4, 3, 5), dtype=np.float32)
    machine = human + directions[None, :, :]
    assert projection_scores(machine, directions).mean() > projection_scores(human, directions).mean()


def test_projection_shape_mismatch_fails_closed():
    summaries = np.zeros((2, 3, 4))
    directions = np.zeros((2, 4))
    try:
        projection_scores(summaries, directions)
    except ValueError as error:
        assert "align" in str(error)
    else:
        raise AssertionError("shape mismatch should fail")
