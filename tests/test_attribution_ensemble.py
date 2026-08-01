"""
tests/test_attribution_ensemble.py — 2-of-3 agreement routing. Forced
top-1 answers are what made the argmin failure invisible; the ensemble
returns None (manual review) on disagreement instead of guessing.
"""
from __future__ import annotations

from validation.attribution.ensemble import ensemble_vote, pairwise_agreement


class TestEnsembleVote:
    def test_unanimous(self):
        author, basis = ensemble_vote(
            {"deviation_calibrated": "mill", "cosine_delta": "mill", "mfw_delta": "mill"}
        )
        assert author == "mill" and "3-of-3" in basis

    def test_two_of_three(self):
        author, basis = ensemble_vote(
            {"deviation_calibrated": "mill", "cosine_delta": "mill", "mfw_delta": "kempis"}
        )
        assert author == "mill" and "2-of-3" in basis

    def test_three_way_split_routes_to_manual_review(self):
        author, basis = ensemble_vote(
            {"deviation_calibrated": "a", "cosine_delta": "b", "mfw_delta": "c"}
        )
        assert author is None and "manual review" in basis


class TestPairwiseAgreement:
    def test_rates(self):
        rows = [
            {"x": "a", "y": "a"},
            {"x": "a", "y": "b"},
        ]
        agreement = pairwise_agreement(rows)
        assert agreement == {"x|y": 0.5}
