"""Branch tests for the RANK_REMEDIATION=shrinkage estimator (part 8, task 1)."""

from __future__ import annotations

import numpy as np

from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState, _ledoit_wolf_shrink


def _unit(v):
    return v / np.linalg.norm(v)


class TestLedoitWolfShrink:
    def test_isotropic_rho_returns_unchanged(self):
        # rho already equals the target I/D → gamma ≈ 0 → early-return arm.
        D = 8
        rho = np.eye(D) / D
        vectors = np.stack([_unit(np.ones(D))])
        out = _ledoit_wolf_shrink(rho, vectors, np.array([1.0]))
        assert out is rho  # the early return hands back the same object

    def test_rank_deficient_rho_gains_full_support(self):
        # N=2 rank-2 rho in D=8 → normal path: every eigenvalue > 0 after
        # shrinking, trace preserved, alpha strictly inside (0, 1].
        rng = np.random.default_rng(7)
        D = 8
        vecs = np.stack([_unit(rng.random(D)) for _ in range(2)])
        w = np.array([0.5, 0.5])
        rho = sum(wi * np.outer(v, v) for wi, v in zip(w, vecs))
        out = _ledoit_wolf_shrink(rho, vecs, w)
        eigvals = np.linalg.eigvalsh(out)
        assert eigvals.min() > 0.0                      # no dead directions left
        assert np.isclose(np.trace(out), 1.0)           # convex combo of tr=1
        assert not np.allclose(out, rho)                # something actually moved

    def test_alpha_is_clamped_to_at_most_one(self):
        # D=3 (not 6): shrinking target_scale=1/D pulls gamma down faster
        # than pi_hat as D shrinks, so the unclamped ratio pi_hat/gamma
        # crosses 1 and the min(1, ·) clamp actually engages. Hand-derived:
        #   vecs = eye(3)[:2] = [e0, e1] (orthogonal unit vectors), w=[0.5,0.5]
        #   rho = diag(0.5, 0.5, 0)
        #   target_scale = tr(rho)/D = 1/3 → target = diag(1/3, 1/3, 1/3)
        #   rho - target = diag(1/6, 1/6, -1/3)
        #   gamma = (1/6)^2 + (1/6)^2 + (1/3)^2 = 1/36 + 1/36 + 4/36 = 1/6
        #   outer_0 - rho = diag(0.5, -0.5, 0)  → sum-sq = 0.5
        #   outer_1 - rho = diag(-0.5, 0.5, 0)  → sum-sq = 0.5
        #   pi_hat = 0.5^2*0.5 + 0.5^2*0.5 = 0.125 + 0.125 = 0.25
        #   alpha_raw = pi_hat / gamma = 0.25 / (1/6) = 1.5  → clamped to 1.0
        # Verified against a live run of _ledoit_wolf_shrink (not just by
        # hand): with alpha=1 the output must equal the isotropic target
        # exactly, which is asserted below rather than treated as one
        # branch of an either/or.
        D = 3
        vecs = np.eye(D)[:2]                            # orthogonal, max disagreement
        w = np.array([0.5, 0.5])
        rho = sum(wi * np.outer(v, v) for wi, v in zip(w, vecs))
        out = _ledoit_wolf_shrink(rho, vecs, w)
        target = np.trace(rho) / D * np.eye(D)
        assert np.allclose(out, target)          # alpha hit the clamp: out IS the target
        assert np.isclose(np.trace(out), 1.0)    # convex combo of tr=1 matrices


class TestRankRemediationFlag:
    """Flag-level pair test: closes _build_density_matrix's shrinkage arm
    (1/6) and pins the flag-off default (byte-identical rank-deficient rho)
    in the same breath."""

    @staticmethod
    def _state_with_3_samples(seed=3) -> StudentState:
        rng = np.random.default_rng(seed)
        state = StudentState(student_id="rank-remediation-test")
        for i in range(3):
            state.add_sample(
                BaselineSample(
                    text=f"baseline {i}",
                    vector=rng.random(FEATURE_DIM),
                    provenance="proctored",
                    auth_weight=1.0,
                    assignment=f"a{i}",
                )
            )
        return state

    def test_flag_off_rho_is_rank_deficient(self, monkeypatch):
        monkeypatch.delenv("RANK_REMEDIATION", raising=False)
        state = self._state_with_3_samples()
        rho = state.density_matrix
        eigvals = np.linalg.eigvalsh(rho)  # ascending
        # N=3 samples in D=FEATURE_DIM → rank <= 3: all but the top 3
        # eigenvalues are ~0.
        assert np.allclose(eigvals[: FEATURE_DIM - 3], 0.0, atol=1e-9)
        assert eigvals[-3:].min() > 1e-9

    def test_flag_shrinkage_rho_has_full_support(self, monkeypatch):
        monkeypatch.setenv("RANK_REMEDIATION", "shrinkage")
        state = self._state_with_3_samples()
        rho = state.density_matrix
        eigvals = np.linalg.eigvalsh(rho)
        assert eigvals.min() > 0.0  # every direction now carries mass
        assert np.isclose(np.trace(rho), 1.0)
