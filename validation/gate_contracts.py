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
    evaluate_g7_cross_topic_fpr,
    evaluate_g8_genre_discrimination,
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
            "the hollow-witness trap this task warns against. No "
            "label-destruction leg is possible for this gate at all: for "
            "an absence-of-pathology criterion like G2's, a pass under "
            "destroyed labels (identical holdout/impostor populations) is "
            "CORRECT behavior, not a blind spot — which is exactly what "
            "test_g2_identical_populations_legitimately_pass, registered "
            "above, asserts."
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
        "collapse toward chance (G1 shuffled mean deviation rises strictly "
        "above the real leg's; G3 shuffled attribution accuracy stays below "
        "0.30; a majority of G4 draws come out non-monotone) — this IS the "
        "suite's own label-destruction control",
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
    "evaluate_g7_cross_topic_fpr": GateContract(
        gate="G7",
        claims="genuine cross-topic submissions are not flagged (FP @ "
        "schedule_conversation+ <= 25%) WITHOUT buying that rate by "
        "suppressing impostor severity at the same bar (catch >= 29%) or by "
        "compressing scores (mean cross-genre deviation_score AUC >= 0.60)",
        failure_witness=lambda: evaluate_g7_cross_topic_fpr(
            cross_topic_fp_rate=0.05,
            impostor_catch_rate=0.03,
            mean_cross_genre_dev_auc=0.70,
        ),
        label_destruction=lambda: evaluate_g7_cross_topic_fpr(
            cross_topic_fp_rate=0.27,
            impostor_catch_rate=0.27,
            mean_cross_genre_dev_auc=0.5,
        ),
        notes=(
            "The failure witness is the LLR_ACTION_MODE=blend shape, "
            "reproduced deliberately: a 5% cross-topic false-positive rate "
            "(the best leg any candidate correction has produced) next to a "
            "3% impostor catch rate at the SAME severity bar. blend really "
            "did collapse that catch rate from 33% to 3% while looking like "
            "the best option on false positives alone, and it was caught "
            "only because someone checked both legs at a matched bar — so "
            "the witness fails via the CATCH leg specifically, with the FP "
            "and AUC legs both passing, pinned in "
            "TestWitnessesFailForTheRightReason.test_g7_fails_because_the_"
            "catch_leg_collapses_at_a_matched_severity_bar. A witness that "
            "tripped the FP or AUC leg instead would leave the design's "
            "highest-risk decision (inflating only the claimed-author side "
            "of the llr difference, which biases delta toward 'more like the "
            "claimed author' for everyone) untested — and that decision is "
            "exactly what the spec says this leg decides. No counts, fold "
            "count, or fire rate are supplied, so none of the three "
            "downgrade-to-uninformative paths run and the fail is a plain "
            "criterion fail.\n\n"
            "The label-destruction leg is registered — unlike G2/G2b/G6 — "
            "and it is a MATHEMATICAL GUARANTEE rather than a cherry-picked "
            "imbalance. Destroying author labels makes the genuine and "
            "impostor populations exchangeable draws from one pool, so (a) "
            "their flagged rates at any fixed severity bar converge to a "
            "single shared value and (b) the AUC converges to 0.5. Both "
            "properties are fatal here independently. On (a): the FP bar is "
            "an UPPER bound of 0.25 and the catch bar a LOWER bound of 0.29 "
            "on what has become the same number, and 0.25 < 0.29, so NO "
            "shared rate can satisfy both — the witness uses 0.27, which "
            "sits in that gap and misses both bars at once "
            "(test_g7_fp_and_catch_bars_cannot_both_hold_at_one_shared_rate "
            "checks the gap itself still exists, so the guarantee cannot be "
            "quietly voided by moving a bar). On (b): 0.5 is strictly below "
            "the 0.60 AUC bar, which the spec set above chance for precisely "
            "this reason. All three legs therefore fail, pinned in "
            "test_g7_label_destruction_fails_all_three_legs_by_construction."
        ),
    ),
    "evaluate_g8_genre_discrimination": GateContract(
        gate="G8",
        claims="the v2 genre resolver claims labels that are right "
        "(minimum per-class precision >= 80% on an author-disjoint hold-out), "
        "often enough to be useful (abstention <= 50%), for reasons that are "
        "about GENRE and not about recognising the author (accuracy under "
        "permuted genre labels collapses to within 10pt of chance)",
        failure_witness=lambda: evaluate_g8_genre_discrimination(
            min_class_precision=0.55,
            abstention_rate=0.40,
            shuffled_accuracy=0.22,
        ),
        label_destruction=lambda: evaluate_g8_genre_discrimination(
            min_class_precision=0.85,
            abstention_rate=0.40,
            shuffled_accuracy=0.85,
        ),
        notes=(
            "The failure witness isolates the PRECISION leg: 0.55 minimum "
            "per-class precision with a healthy abstention rate and a "
            "control that collapses properly. It is deliberately a MINIMUM "
            "rather than an average, because a macro-average lets one class "
            "sit at 0.4 while the mean clears the bar, and the cost of a "
            "wrong genre label is per-class -- creative_fiction mutes tier "
            "16, the academic genres expand the T8/T13 anchor set, and the "
            "label is a Bayesian prior pooling key. Pinned leg-by-leg in "
            "TestWitnessesFailForTheRightReason.test_g8_fails_because_one_"
            "class_is_weak_not_because_of_the_other_legs so the fail cannot "
            "be explained by the abstention or control legs tipping it.\n\n"
            "The label-destruction leg is registered and is not a "
            "cherry-pick: it IS the gate's own third leg, fed the result "
            "that destroyed labels are supposed to make impossible. "
            "Permuting genre labels across authors and re-fitting must "
            "collapse accuracy to chance (0.25 for the four classes); a "
            "shuffled accuracy of 0.85 means the model still predicts "
            "confidently when the labels no longer mean genre, which can "
            "only be because it is recognising authorial style. That is the "
            "exact confound this corpus has -- every Dickens document is one "
            "author AND one genre -- so unlike G2/G2b/G6, a "
            "label-destruction witness here is both possible and load-"
            "bearing. It can never pass: the control leg's bar is chance + "
            "0.10 = 0.35 for four classes, and 0.85 exceeds it by more than "
            "the whole width of the range above chance. Pinned in "
            "test_g8_label_destruction_is_the_shuffled_control.\n\n"
            "Neither witness supplies n_holdout, so the Wilson-interval "
            "downgrade path never runs and both are plain criterion fails "
            "rather than 'uninformative' outcomes that merely happen not to "
            "be passes."
        ),
    ),
}
