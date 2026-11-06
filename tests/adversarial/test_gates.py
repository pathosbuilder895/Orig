"""
tests/adversarial/test_gates.py: gates G-A1…G-A6 (Task 19).

The failure witnesses live in validation/gate_contracts.py and are enforced
by tests/test_gate_falsifiability.py. This file covers everything else the
evaluators decide: when a would-be pass is downgraded to uninformative
(small samples, an absent corpus, an attack that never fired), that a
measured failure is never softened, and the wiring from harness rows to
results.
"""

from __future__ import annotations

import pytest

import validation.calibration_gate as cg
from validation.calibration_gate import (
    ADVERSARIAL_LEGS,
    GATE_LEGS,
    _ga_auroc,
    _ga_auroc_lower,
    _parse_only,
    adversarial_results_from_rows,
    evaluate_g_a1_cold_start_fpr,
    evaluate_g_a2_imitation,
    evaluate_g_a3_paraphrase,
    evaluate_g_a4_peer_imitation,
    evaluate_g_a5_sigma_inflation,
    evaluate_g_a6_baseline_integrity,
)


def _pop(name, caught, n, attack_scores, genuine_scores):
    return {
        "name": name,
        "attack_actions": ["monitor"] * caught + ["no_action"] * (n - caught),
        "attack_scores": attack_scores,
        "genuine_scores": genuine_scores,
    }


class TestAuroc:
    def test_ties_count_half(self):
        assert _ga_auroc([0.5], [0.5]) == pytest.approx(0.5)
        assert _ga_auroc([0.9, 0.5], [0.5]) == pytest.approx(0.75)

    def test_empty_side_is_unmeasured(self):
        assert _ga_auroc([], [0.1]) is None
        assert _ga_auroc([0.1], []) is None

    def test_lower_bound_tightens_with_n(self):
        assert _ga_auroc_lower(0.8, 5, 5) < _ga_auroc_lower(0.8, 200, 200) < 0.8

    def test_lower_bound_does_not_collapse_at_perfect_separation(self):
        # Hanley-McNeil gives zero variance at 1.0; the smaller side rules.
        assert _ga_auroc_lower(1.0, 6, 1) < 0.6 < _ga_auroc_lower(1.0, 30, 30)


class TestGA1:
    def test_large_clean_corpus_passes(self):
        result = evaluate_g_a1_cold_start_fpr({n: ["no_action"] * 100 for n in (3, 5, 10)})
        assert result.verdict == "pass"

    def test_small_clean_corpus_is_uninformative_not_pass(self):
        result = evaluate_g_a1_cold_start_fpr({n: ["no_action"] * 12 for n in (3, 5, 10)})
        assert result.verdict == "uninformative"
        assert "straddles" in result.current_value

    def test_missing_n_withholds_a_pass(self):
        result = evaluate_g_a1_cold_start_fpr({3: ["no_action"] * 100, 5: ["no_action"] * 100})
        assert result.verdict == "uninformative"
        assert result.detail["unmeasured_legs"] == ["FPR@N=10"]

    def test_no_input_is_uninformative(self):
        assert evaluate_g_a1_cold_start_fpr(None).verdict == "uninformative"

    def test_failure_on_a_small_sample_is_never_softened(self):
        result = evaluate_g_a1_cold_start_fpr({3: ["monitor"] * 2, 5: [], 10: []})
        assert result.verdict == "fail"

    def test_refused_profiles_withhold_a_pass(self):
        result = evaluate_g_a1_cold_start_fpr(
            {n: ["no_action"] * 100 for n in (3, 5, 10)}, refused_by_n={3: 1}
        )
        assert result.verdict == "uninformative"
        assert "refused scoring" in result.current_value

    def test_per_bar_rates_are_reported(self):
        actions = ["no_action", "monitor", "schedule_conversation", "escalate"]
        result = evaluate_g_a1_cold_start_fpr({3: actions, 5: actions, 10: actions})
        rates = result.detail["per_n"][3]["rate_at_or_above"]
        assert rates == {"monitor": 0.75, "schedule_conversation": 0.5, "escalate": 0.25}


class TestCatchGates:
    @pytest.mark.parametrize(
        "evaluate",
        [evaluate_g_a2_imitation, evaluate_g_a3_paraphrase, evaluate_g_a4_peer_imitation],
    )
    def test_absent_corpus_is_uninformative_and_says_why(self, evaluate):
        result = evaluate([], absent_reason="LLM attack cache absent")
        assert result.verdict == "uninformative"
        assert "LLM attack cache absent" in result.current_value
        assert result.passed is False

    def test_population_without_attack_docs_contributes_nothing(self):
        result = evaluate_g_a2_imitation(
            [{"name": "llm_imitation N=3", "attack_actions": [], "attack_scores": [],
              "genuine_scores": [0.1]}],
            absent_reason="nothing cached",
        )
        assert result.verdict == "uninformative"
        assert result.detail["legs"] == []

    def test_strong_large_separation_passes(self):
        result = evaluate_g_a4_peer_imitation(
            [_pop(f"p N={n}", 95, 100, [0.9] * 100, [0.1] * 100) for n in (3, 5, 10)],
            required=("p",),
        )
        assert result.verdict == "pass"

    def test_every_required_n_must_be_measured(self):
        result = evaluate_g_a2_imitation(
            [_pop("llm_imitation N=3", 95, 100, [0.9] * 100, [0.1] * 100)]
        )
        assert result.verdict == "uninformative"
        assert "llm_imitation N=5, llm_imitation N=10" in result.current_value

    def test_g_a4_needs_the_same_prompt_peer_swap_for_a_pass(self):
        result = evaluate_g_a4_peer_imitation(
            [_pop("public_authors/peer_swap N=3", 95, 100, [0.9] * 100, [0.1] * 100)]
        )
        assert result.verdict == "uninformative"
        assert "riddell_juola/peer_swap_same_prompt" in result.current_value

    def test_g_a3_missing_route_withholds_a_pass(self):
        strong = [0.9] * 100, [0.1] * 100
        result = evaluate_g_a3_paraphrase(
            [
                _pop("llm_paraphrase N=3", 95, 100, *strong),
                _pop("llm_roundtrip_de N=3", 95, 100, *strong),
            ]
        )
        assert result.verdict == "uninformative"
        assert "llm_roundtrip_ja" in result.current_value

    def test_partial_cache_coverage_withholds_a_pass(self):
        pop = _pop("llm_imitation N=3", 95, 100, [0.9] * 100, [0.1] * 100)
        pop["coverage"] = [4, 13]
        result = evaluate_g_a2_imitation([pop])
        assert result.verdict == "uninformative"
        assert "covers 4 of 13" in result.current_value

    def test_refused_profiles_withhold_a_pass(self):
        pop = _pop("p N=3", 95, 100, [0.9] * 100, [0.1] * 100)
        pop["n_refused"] = 1
        result = evaluate_g_a4_peer_imitation([pop], required=("p",), required_ns=(3,))
        assert result.verdict == "uninformative"
        assert "refused scoring" in result.current_value

    def test_one_genuine_document_cannot_demonstrate_separation(self):
        result = evaluate_g_a4_peer_imitation(
            [_pop("p N=3", 100, 100, [0.9] * 100, [0.1])], required=("p",), required_ns=(3,)
        )
        assert result.verdict == "uninformative"
        auroc = result.detail["legs"][1]
        assert auroc["auc"] == 1.0 and auroc["auc_lower_95"] < 0.6

    def test_small_sample_pass_is_downgraded(self):
        result = evaluate_g_a4_peer_imitation(
            [_pop("p N=3", 5, 5, [0.9] * 5, [0.1] * 2)], required=("p",), required_ns=(3,)
        )
        assert result.verdict == "uninformative"

    def test_unmeasured_auroc_withholds_a_pass(self):
        result = evaluate_g_a2_imitation([_pop("llm_imitation N=3", 100, 100, [0.9] * 100, [])])
        assert result.verdict == "uninformative"
        assert result.detail["unmeasured_legs"] == ["llm_imitation N=3 AUROC"]

    def test_unmeasured_leg_never_buries_a_failure(self):
        result = evaluate_g_a2_imitation([_pop("llm_imitation N=3", 1, 10, [0.9] * 10, [])])
        assert result.verdict == "fail"

    def test_every_population_must_pass(self):
        result = evaluate_g_a4_peer_imitation(
            [
                _pop("a N=3", 100, 100, [0.9] * 100, [0.1] * 100),
                _pop("b N=3", 10, 100, [0.9] * 100, [0.1] * 100),
            ],
            required=("a", "b"),
        )
        assert result.verdict == "fail"
        assert result.detail["failed_legs"] == ["b N=3 catch"]


def _cell(**over):
    cell = dict(
        n=3,
        n_pairs=13,
        n_held=0,
        n_refused=0,
        clean_caught=90,
        clean_n=100,
        inflated_caught=90,
        inflated_n=100,
        clean_mean_sigma=0.08,
        inflated_mean_sigma=0.10,
        inflated_impostor_scores=[0.9] * 100,
        inflated_genuine_scores=[0.1] * 100,
    )
    cell.update(over)
    return cell


class TestGA5:
    def test_no_drop_with_grown_sigma_passes(self):
        cells = [_cell(n=n) for n in (3, 5, 10)]
        assert evaluate_g_a5_sigma_inflation(cells).verdict == "pass"

    def test_missing_n_withholds_a_pass(self):
        result = evaluate_g_a5_sigma_inflation([_cell()])
        assert result.verdict == "uninformative"
        assert "not measured at N=5, 10" in result.current_value

    def test_growth_below_the_minimum_effect_cannot_pass(self):
        result = evaluate_g_a5_sigma_inflation([_cell(inflated_mean_sigma=0.083)], required_ns=(3,))
        assert result.verdict == "uninformative"
        assert "did not grow by 5%" in result.current_value

    def test_sigma_that_did_not_grow_cannot_pass(self):
        result = evaluate_g_a5_sigma_inflation([_cell(inflated_mean_sigma=0.08)])
        assert result.verdict == "uninformative"
        assert "did not grow" in result.current_value

    def test_unmeasured_sigma_cannot_pass(self):
        result = evaluate_g_a5_sigma_inflation([_cell(clean_mean_sigma=None)])
        assert result.verdict == "uninformative"

    def test_injection_that_never_reached_the_baseline_cannot_pass(self):
        empty = _cell(n_pairs=0, n_held=13, clean_n=0, inflated_n=0,
                      inflated_impostor_scores=[], inflated_genuine_scores=[])
        result = evaluate_g_a5_sigma_inflation([empty], required_ns=(3,))
        assert result.verdict == "uninformative"
        assert "held the injection for 13 victim(s)" in result.current_value

    def test_low_clean_catch_cannot_pass(self):
        result = evaluate_g_a5_sigma_inflation(
            [_cell(clean_caught=5, inflated_caught=5)], required_ns=(3,)
        )
        assert result.verdict == "uninformative"
        assert "no room to observe" in result.current_value

    def test_refused_pairs_withhold_a_pass(self):
        result = evaluate_g_a5_sigma_inflation([_cell(n_refused=1)], required_ns=(3,))
        assert result.verdict == "uninformative"

    def test_drop_fails_even_when_sigma_did_not_grow(self):
        result = evaluate_g_a5_sigma_inflation(
            [_cell(inflated_caught=20, inflated_mean_sigma=0.08)]
        )
        assert result.verdict == "fail"
        assert "did not grow" in " ".join(result.detail["informativeness_caveats"])

    def test_every_n_is_its_own_leg(self):
        result = evaluate_g_a5_sigma_inflation([_cell(), _cell(n=10, inflated_caught=20)])
        assert result.detail["failed_legs"] == ["N=10 inflated catch vs clean 90.0%"]

    def test_nothing_scored_is_uninformative(self):
        assert evaluate_g_a5_sigma_inflation([_cell(clean_n=0)]).verdict == "uninformative"
        assert evaluate_g_a5_sigma_inflation(None).verdict == "uninformative"


class TestGA6:
    REQUIRED = ("pa/obf", "pa/clean", "rj/obf")

    def test_large_clean_separation_passes(self):
        result = evaluate_g_a6_baseline_integrity(
            {"pa/obf N=3": (95, 100)}, clean={"pa/clean N=3": (0, 100)}, required=("pa/obf",),
            required_ns=(3,),
        )
        assert result.verdict == "pass"

    def test_required_family_needs_every_n(self):
        result = evaluate_g_a6_baseline_integrity(
            {"pa/obf N=3": (95, 100)}, clean={"pa/clean N=3": (0, 100)}, required=("pa/obf",)
        )
        assert result.detail["missing_populations"] == ["pa/obf N=5", "pa/obf N=10"]

    def test_missing_required_family_withholds_a_pass(self):
        result = evaluate_g_a6_baseline_integrity(
            {"pa/obf N=3": (95, 100)}, clean={"pa/clean N=3": (0, 100)}, required=self.REQUIRED,
            required_ns=(3,),
        )
        assert result.verdict == "uninformative"
        assert result.detail["missing_populations"] == ["rj/obf N=3"]

    def test_missing_family_never_buries_a_failure(self):
        result = evaluate_g_a6_baseline_integrity(
            {"pa/obf N=3": (0, 100)}, clean={"pa/clean N=3": (0, 100)}, required=self.REQUIRED
        )
        assert result.verdict == "fail"

    def test_nothing_scored_is_uninformative(self):
        assert evaluate_g_a6_baseline_integrity(None).verdict == "uninformative"


# ── Wiring ──────────────────────────────────────────────────────────────────


def _row(kind, n=3, victim="v", corpus="public_authors", **over):
    row = {
        "corpus": corpus,
        "kind": kind,
        "n": n,
        "victim_id": victim,
        "injected_indices": [],
        "n_baseline_docs": n,
        "holdout_actions": ["monitor", "no_action"],
        "holdout_scores": [0.5, 0.3],
        "impostor_actions": ["monitor"] * 5,
        "impostor_scores": [0.6] * 5,
        "held_baseline_indices": [],
        "baseline_integrity": {"loo_outlier_samples": []},
        "mean_baseline_std": 0.09,
        "scoring_refused": False,
    }
    row.update(over)
    return row


META = {
    "seed": 1,
    "ns": [3],
    "llm_attacks": {
        "present": False,
        "manifest": "validation/adversarial/corpus/llm_attacks/manifest.json",
    },
    "riddell_juola": {"participant_baselines_present": False},
}


class TestWiring:
    def test_adversarial_legs_are_gate_legs(self):
        assert set(ADVERSARIAL_LEGS) <= set(GATE_LEGS)
        assert _parse_only("g-a1,G-A6") == {"G-A1", "G-A6"}

    def test_rows_reduce_to_one_result_per_leg(self):
        rows = [
            _row("clean"),
            _row("sigma_inflation", mean_baseline_std=0.1, injected_indices=[1]),
            _row("outsourced_baselines", injected_indices=[0, 1, 2]),
        ]
        results = adversarial_results_from_rows(rows, META)
        assert [r.name for r in results] == list(ADVERSARIAL_LEGS)
        by_name = {r.name: r for r in results}
        assert by_name["G-A2"].verdict == "uninformative"
        assert "gen_llm_attacks.py has not been run" in by_name["G-A2"].current_value
        assert by_name["G-A3"].verdict == "uninformative"
        assert by_name["G-A1"].verdict == "fail"
        assert all(r.detail["harness"]["seed"] == 1 for r in results)

    def test_one_leg_raising_is_a_machinery_error_for_that_leg_only(self, monkeypatch):
        from validation.adversarial import report

        def boom(rows):
            raise RuntimeError("reducer broke")

        monkeypatch.setattr(report, "ga5_inputs", boom)
        results = {r.name: r for r in adversarial_results_from_rows([_row("clean")], META)}
        assert results["G-A5"].current_value.startswith("ERROR (machinery)")
        assert not results["G-A1"].current_value.startswith("ERROR")

    def test_harness_crash_is_a_machinery_error_on_every_requested_leg(self, monkeypatch):
        from validation.adversarial import report

        def boom(legs):
            raise RuntimeError("harness broke")

        monkeypatch.setattr(report, "run_harness", boom)
        results = cg._compute_adversarial_gates(("G-A1", "G-A4"))
        assert [r.name for r in results] == ["G-A1", "G-A4"]
        assert all("harness broke" in r.current_value for r in results)

    def test_run_all_gates_runs_only_the_requested_adversarial_legs(self, monkeypatch):
        seen = {}

        def fake(legs):
            seen["legs"] = legs
            return [cg._machinery_error_result(leg, "c", RuntimeError("x")) for leg in legs]

        monkeypatch.setenv("TYPICALITY_SCORING", "0")  # restored after; run_all sets it
        monkeypatch.setattr(cg, "_compute_adversarial_gates", fake)
        results = cg._run_all_gates({"G-A2", "G-A5"})
        assert seen["legs"] == ("G-A2", "G-A5")
        assert [r.name for r in results] == ["G-A2", "G-A5"]
