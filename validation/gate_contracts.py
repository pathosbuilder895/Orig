"""
validation/gate_contracts.py — the falsifiability register.

For every calibration gate: what it claims to prove, one concrete input on
which it FAILS (proof it cannot pass by construction — the exact defect the
original G5 permutation-null control shipped with: its shuffle was
measurement-invariant, so it compared a quantity to itself and would have
recorded a confident, meaningless PASS), and where meaningful, an input
encoding label destruction (authorship structure removed) that must never
PASS.

tests/test_gate_falsifiability.py enforces: every evaluate_g* exported by
validation.calibration_gate has an entry here, every failure witness fails,
and every registered label-destruction result is not "pass". Adding a gate
without a registered failure mode is a test failure, not a review comment.

SIGNATURE TRAP (flagged explicitly because a prior reviewer caught it): every
evaluate_g* below except evaluate_g4_career_drift_monotone and
evaluate_g2_bland_impostor/evaluate_g2b_paraphrase_resistant's required pair
takes one or more OPTIONAL keyword-only-in-practice parameters after the
first one or two required ones (evaluate_g1_fpr's third positional slot is
`typicality_ns`, NOT `entity_baseline_counts`; evaluate_g3_attribution's
third is `n_essays`; evaluate_g5_permutation_null and evaluate_g6_fairness
both take a trailing `informational` dict). Every witness below passes every
argument beyond the first by keyword for exactly this reason — a positional
slip silently binds to the wrong parameter and can flip a witness from
"tests the guard" to "tests something else that happens to also fail".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from validation.calibration_gate import (
    GateResult,
    evaluate_g1_fpr,
    evaluate_g2_bland_impostor,
    evaluate_g2b_paraphrase_resistant,
    evaluate_g3_attribution,
    evaluate_g4_career_drift_monotone,
    evaluate_g5_permutation_null,
    evaluate_g6_fairness,
)


@dataclass(frozen=True)
class GateContract:
    gate: str
    claims: str
    failure_witness: Callable[[], GateResult]
    label_destruction: Optional[Callable[[], GateResult]] = None
    notes: str = ""


GATE_CONTRACTS: dict[str, GateContract] = {
    "evaluate_g1_fpr": GateContract(
        gate="G1",
        claims="pooled same-author flagged rate <= 5%",
        failure_witness=lambda: evaluate_g1_fpr(
            ["monitor"] * 20, per_corpus={"w": ["monitor"] * 20}
        ),
        label_destruction=None,
        notes=(
            "No label-destruction leg is registered at THIS evaluator's level "
            "on purpose, not by omission. evaluate_g1_fpr only ever sees a "
            "flagged-rate summary; the gate's own docstring (and "
            "evaluate_g5_permutation_null's, which implements the real "
            "shuffled-label rerun) explains why a shuffled-label rate is not "
            "a valid signal here: conformal p-values floor at 1/(N+1), every "
            "G1 corpus entity has at most ~a dozen LOO folds, and that pins "
            "the action band to no_action for real AND shuffled labels alike "
            "— 'a low shuffled rate is guaranteed by construction and "
            "carries no circularity information'. That is exactly why the "
            "codebase itself moved G1's label-destruction control to G5's "
            "mean-DEVIATION-shift criterion instead of testing a shuffled "
            "flagged rate through this function. Registering a "
            "label-destruction leg here would either (a) silently duplicate "
            "the ordinary failure witness above (feed a high rate, watch it "
            "fail — no label-destruction insight), or (b) feed a low/zero "
            "rate that the gate's own documentation says is uninformative by "
            "construction, which is not an honest 'must never pass' claim. "
            "See GATE_CONTRACTS['evaluate_g5_permutation_null'] for where "
            "G1's real label-destruction leg lives."
        ),
    ),
    "evaluate_g2_bland_impostor": GateContract(
        gate="G2",
        claims="impostors do not look MORE typical than genuine holdout "
        "(median(impostor q) <= median(holdout q))",
        failure_witness=lambda: evaluate_g2_bland_impostor(
            holdout_q=[0.1, 0.15, 0.2], impostor_q=[0.6, 0.7, 0.8]
        ),
        label_destruction=None,
        notes=(
            "No label-destruction leg is registered because none can be "
            "honestly claimed to 'never pass'. evaluate_g2_bland_impostor "
            "takes two already-summarized q-value lists with no author "
            "identity inside them — 'destroying labels' at this evaluator's "
            "level means feeding it a holdout population and an impostor "
            "population drawn from the SAME underlying distribution (no true "
            "separation). The gate's criterion is one-sided (impostor <= "
            "holdout), so under a genuinely destroyed label (identical "
            "distributions), the criterion is not just likely but "
            "GUARANTEED to pass at exact equality: "
            "evaluate_g2_bland_impostor(holdout_q=[0.3,0.4,0.5], "
            "impostor_q=[0.3,0.4,0.5]) has median(impostor)==median(holdout), "
            "so 'impostor <= holdout' holds and verdict=='pass' by "
            "construction (see "
            "TestG2FamilyLabelDestructionIsHonestlyNone.test_g2_identical_"
            "populations_legitimately_pass, which runs exactly this). A "
            "label-destruction witness that must 'never pass' would have to "
            "cherry-pick an unrepresentative imbalance instead — exactly "
            "the hollow-witness trap this task warns against. G2's real "
            "authorship-structure control is upstream, in the LOO scoring "
            "pipeline that produces holdout_q/impostor_q in the first place, "
            "not in this pure comparison function."
        ),
    ),
    "evaluate_g2b_paraphrase_resistant": GateContract(
        gate="G2b",
        claims="mechanically-paraphrased impostors still separate from "
        "genuine holdout (PROXY only — not an LLM-paraphrase robustness "
        "claim; see _G2B_PROXY_NOTE)",
        failure_witness=lambda: evaluate_g2b_paraphrase_resistant(
            holdout_q=[0.1, 0.2], paraphrased_impostor_q=[0.5, 0.6]
        ),
        label_destruction=None,
        notes=(
            "Same reasoning as evaluate_g2_bland_impostor: this evaluator is "
            "the identical median comparison over two already-summarized "
            "lists, so identical-distribution input legitimately passes by "
            "construction (see "
            "TestG2FamilyLabelDestructionIsHonestlyNone.test_g2b_identical_"
            "populations_legitimately_pass). Additionally, the PROXY label "
            "itself must survive in both criterion and detail — asserted "
            "directly in TestG2bProxyLabelSurvives and pinned again in "
            "TestWitnessesFailForTheRightReason, since a gate that silently "
            "dropped its own 'this is not LLM-paraphrase robustness' caveat "
            "would misrepresent what it measures regardless of its verdict."
        ),
    ),
    "evaluate_g3_attribution": GateContract(
        gate="G3",
        claims="public_authors top-1 attribution accuracy >= 0.7 "
        "(impostor-calibrated)",
        failure_witness=lambda: evaluate_g3_attribution(0.455),
        label_destruction=lambda: evaluate_g3_attribution(1.0 / 9.0),
        notes=(
            "1/9 is chance level for a 9-author pool. This is registered as "
            "the label-destruction leg because it is a MATHEMATICAL "
            "GUARANTEE, not a lucky draw: chance-level top-1 accuracy for "
            "any author pool of size n>=2 is 1/n <= 1/2, which is always "
            "strictly below the 0.7 bar — there is no author-pool size at "
            "which shuffled-label (chance) attribution could pass this gate. "
            "Neither call passes n_essays, so both witnesses exercise the "
            "plain top1_accuracy>=0.7 threshold directly and never enter the "
            "Wilson-interval informativeness branch (which can only ever "
            "soften a PASS to 'uninformative', never manufacture a fail) — "
            "pinned in TestWitnessesFailForTheRightReason via `'power' not "
            "in result.detail`."
        ),
    ),
    "evaluate_g4_career_drift_monotone": GateContract(
        gate="G4",
        claims="typicality distance from the early-career baseline is "
        "non-decreasing early -> middle -> late",
        failure_witness=lambda: evaluate_g4_career_drift_monotone(
            {"early": 0.9, "middle": 0.5, "late": 0.7}
        ),
        label_destruction=lambda: evaluate_g4_career_drift_monotone(
            {"early": 0.7, "middle": 0.65, "late": 0.6}
        ),
        notes=(
            "The label-destruction leg is a strictly DECREASING sequence — "
            "the shape you would expect if the early/middle/late chronology "
            "labels themselves were scrambled on otherwise-plausible "
            "monotone data (the same operation evaluate_g5_permutation_null's "
            "G4 leg performs for real, via repeated dialogue-list "
            "permutations). Any permutation of three distinct values that "
            "is not already sorted ascending violates the "
            "non-decreasing check by construction (only 1 of the 3! "
            "orderings of three distinct values is non-decreasing), so this "
            "is a guaranteed fail, not a cherry-picked one. Both witnesses "
            "are checked to supply all three group keys "
            "(TestWitnessesFailForTheRightReason) so the failure comes from "
            "the ORDER violation, not from the separate 'len(values) == 3' "
            "missing-group guard the same evaluator also enforces."
        ),
    ),
    "evaluate_g5_permutation_null": GateContract(
        gate="G5",
        claims="under permuted author labels, all three scoring legs "
        "collapse toward chance (G1 mean deviation does not drop below the "
        "real leg's; G3 attribution accuracy stays >= 0.30; a majority of "
        "G4 draws come out non-monotone) — this IS the suite's own "
        "label-destruction control",
        failure_witness=lambda: evaluate_g5_permutation_null(
            real_g1_mean_deviation=1.0,
            shuffled_g1_mean_deviation=0.9,  # insensitive to blending -> fail
            shuffled_g3_accuracy=0.9,  # still attributes confidently -> fail
            g4_nonmonotone_draws=0,
            g4_total_draws=3,  # still monotone every draw -> fail
        ),
        label_destruction=None,
        notes=(
            "G5 IS the label-destruction control for the suite (it exists "
            "specifically to catch a scoring pipeline that is invariant to "
            "shuffled authorship labels — the exact defect this whole task "
            "is a countermeasure for), so it has no separate "
            "label-destruction leg of its own; that would be circular. The "
            "failure witness reproduces the shape of that original defect "
            "directly: every one of the three sub-legs individually looks "
            "like the shuffle changed nothing (or even looks stronger), "
            "pinned leg-by-leg in "
            "TestWitnessesFailForTheRightReason.test_g5_fails_because_all_"
            "three_shuffled_legs_still_look_like_signal so the overall "
            "'fail' cannot be explained by only one leg tipping the vote "
            "while the other two would (wrongly) look fine."
        ),
    ),
    "evaluate_g6_fairness": GateContract(
        gate="G6",
        claims="native/non-native flagged-rate ratio on the p_central "
        "action does not exceed 2x",
        failure_witness=lambda: evaluate_g6_fairness(
            native_fpr=0.01, non_native_fpr=0.10
        ),
        label_destruction=None,
        notes=(
            "No label-destruction leg is registered for the same reason as "
            "G2/G2b: evaluate_g6_fairness's criterion is symmetric equality "
            "of two rates, so a genuinely destroyed native_english label "
            "(the two groups drawn from the same underlying population, no "
            "true difference) legitimately produces ratio==1.0 and "
            "verdict=='pass' by construction — proved directly in "
            "TestG2FamilyLabelDestructionIsHonestlyNone.test_g6_equal_rates_"
            "legitimately_pass via evaluate_g6_fairness(native_fpr=0.05, "
            "non_native_fpr=0.05). The failure witness above is pinned to "
            "fail via the ordinary both-nonzero ratio path "
            "(ratio_status=='both_nonzero', ratio>2.0), not via the "
            "one-group-zero infinite-disparity special case (a real but "
            "DIFFERENT failure mode) or the both-zero 'uninformative' "
            "can't-know case — see "
            "TestWitnessesFailForTheRightReason.test_g6_fails_on_the_ratio_"
            "not_on_a_zero_rate_special_case."
        ),
    ),
}
