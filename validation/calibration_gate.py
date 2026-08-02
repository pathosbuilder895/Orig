"""
validation/calibration_gate.py — Phase 0 calibration gates (G1-G6) for the
two-axis authorship verification redesign.

Run:
    python -m validation.calibration_gate
    python -m validation.calibration_gate --out /tmp/gate_report.json

Follows validation/plato/gate.py's shape: one dataclass per gate result
with a `passed: bool`, a pure `run()`, a `render()`, and a `main()` whose
exit code is 0 iff every gate passed — so CI fails automatically.

G1-G4 are implemented here against seminary + public_authors + Plato,
scored via the in-process TestClient with TYPICALITY_SCORING=1 (the same
"production-realistic in-process" pattern every other validation runner in
this repo uses — see validation/public_authors/run.py's docstring).
G5 (permutation-null control) shuffles author labels with a fixed seed and
re-runs the G1/G3/G4 machinery — see run_g5().
G2b repeats G2 with the Tier-18 uniformity features enabled and the ai_*.txt
impostors run through a paraphrase PROXY — a deterministic mechanical
transformation (fixed-table word substitution + adjacent-sentence
reordering), NOT an LLM paraphrase: a G2b pass is never evidence of
robustness against the real detector-guided LLM attacks the design spec's
research review cites (see evaluate_g2b_paraphrase_resistant).
G6 (native_english fairness) checks the ≤2x per-group flagged-rate bar on
the p_central/too-uniform action between native_english=true and =false
authentic samples, bridging validation/benchmark/bias_slicer.slice_by and
validation/bias_analysis._welch_t_test directly (run_bias_analysis's
dict-based shape doesn't match bias_slicer's ScoringResult-based shape, so
this gate does the bridging itself).
"""

from __future__ import annotations

# Lock the env BEFORE any original.* import.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402

ENV_LOCK = lock_environment()

import argparse
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    criterion: str
    current_value: str
    detail: dict = field(default_factory=dict)
    verdict: str = ""  # "pass" | "fail" | "uninformative"

    def __post_init__(self):
        if not self.verdict:
            object.__setattr__(self, "verdict", "pass" if self.passed else "fail")
        if self.verdict not in ("pass", "fail", "uninformative"):
            raise ValueError(f"invalid verdict: {self.verdict!r}")
        # FIX 6: `passed` and `verdict` must always agree. This subsumes the
        # narrower "uninformative gate cannot claim passed=True" check it
        # replaces — that check let `passed=False, verdict="pass"` and
        # `passed=True, verdict="fail"` both through, which is the same
        # drift class from the other two directions.
        if self.passed != (self.verdict == "pass"):
            raise ValueError(
                f"passed={self.passed!r} is inconsistent with "
                f"verdict={self.verdict!r} (passed must be True iff "
                "verdict == 'pass')"
            )


# ── Shared conformal-reachability guard ───────────────────────────────────────
#
# A conformal p-value over n leave-one-out distances is quantized: its support
# is {1/(n+1), 2/(n+1), … , 1}, so it can NEVER fall below 1/(n+1) no matter
# how extreme the submission is (original/quantum/typicality.py's module
# docstring; design spec §5's reachability-vs-N table). Any gate that
# thresholds a p-value therefore has to state whether its threshold was
# reachable at the N it actually observed — otherwise "zero flags" is a
# statement about the arithmetic, not about the students, and reads in the
# report as demonstrated fairness/discrimination when it is neither.


def _conformal_p_floor(n: int) -> float:
    """
    The smallest value a conformal p-value over n LOO distances can take.

    FIX 3(a): delegates to validation.power.conformal_p_floor rather than
    re-implementing the same arithmetic a second time. The two copies used
    to disagree at the degenerate n<=0 input: this one returned 1.0,
    power's raises ValueError. Checked every caller in this module before
    delegating — `_reachability_block` only ever calls this with n>=1 (it
    filters `typicality_ns` to `n >= 1` first), and `_min_n_for_threshold`
    below only reaches n-1==0 for a threshold >= ~0.5, far looser than any
    threshold actually used in this codebase (NO_ACTION_FAR_THRESHOLD=0.03,
    NO_ACTION_CENTRAL_THRESHOLD=0.02) — so no caller depends on the old
    degenerate return value, and it is safe to let power's ValueError
    surface instead of preserving a second definition of "degenerate".
    """
    from validation.power import conformal_p_floor

    return conformal_p_floor(n)


def _min_n_for_threshold(threshold: float) -> int:
    """
    Smallest n whose p-value floor reaches `threshold` (0.02 -> 49).

    FIX 3(a): delegates to validation.power.min_docs_for_band. The
    original carried a self-correcting double while-loop as insurance
    against float representation shifting the boundary; power's direct
    `max(1, ceil(1/threshold) - 1)` formula was checked against it (a
    200k-sample random-float scan plus every threshold this module's own
    tests use) with zero disagreements short of the unreachable edge
    threshold==1.0 (where the two clamp to 0 vs. 1 respectively — moot,
    since a conformal p-value is undefined below n=1 either way, and no
    gate in this codebase ever thresholds at 1.0).
    """
    from validation.power import min_docs_for_band

    return min_docs_for_band(threshold)


def _threshold_reachable(n: int, threshold: float) -> bool:
    """
    True iff a p-value over n LOO distances can reach `threshold` at all.

    FIX 3(a): delegates to validation.power.band_reachable. Its only caller
    in this module (`_reachability_block`) always passes n>=1, so
    band_reachable's ValueError on n<=0 is never triggered here.
    """
    from validation.power import band_reachable

    return band_reachable(n, threshold)


def _reachability_block(typicality_ns: list[int], threshold: float) -> dict:
    """
    Reachability summary for a leg that thresholds a conformal p-value, keyed
    off the BINDING (smallest) observed typicality_n — if the weakest fold
    can't reach the threshold, that fold's "not flagged" is structural.

    An empty/all-zero `typicality_ns` means no fold computed typicality at
    all (scoring.py needs >= 2 LOO distances), so the action came from the
    deviation path and the floor doesn't apply: the block records
    observed=False and reachable=None rather than inventing a verdict.
    """
    ns = [int(n) for n in typicality_ns if n and int(n) >= 1]
    required_n = _min_n_for_threshold(threshold)
    if not ns:
        return {
            "observed": False,
            "min_typicality_n": None,
            "p_floor": None,
            "threshold": threshold,
            "required_n": required_n,
            "reachable": None,
            "n_folds_with_typicality": 0,
            "note": (
                "no fold reported a typicality_n — these actions came from the "
                "deviation-score path, not the conformal band, so the "
                "1/(n+1) p-value floor does not apply to them"
            ),
        }
    min_n = min(ns)
    return {
        "observed": True,
        "min_typicality_n": min_n,
        "p_floor": _conformal_p_floor(min_n),
        "threshold": threshold,
        "required_n": required_n,
        "reachable": _threshold_reachable(min_n, threshold),
        "n_folds_with_typicality": len(ns),
        "note": (
            f"conformal p-values floor at 1/(n+1); at n={min_n} the floor is "
            f"{_conformal_p_floor(min_n):.3f} and the {threshold:g} threshold "
            f"needs n>={required_n} (design spec §5 reachability table)"
        ),
    }


# ── Pure gate-evaluation logic (unit-tested in tests/test_calibration_gate.py) ─


def evaluate_g1_fpr(
    pooled_actions: list[str],
    per_corpus: dict[str, list[str]],
    typicality_ns: list[int] | None = None,
    entity_baseline_counts: dict[str, int] | None = None,
    band_threshold: float | None = None,
) -> GateResult:
    """
    G1 — Same-author FPR. Pooled flagged rate (action != "no_action") must
    be <= 5%. Also reports per-corpus flagged rate so a pooled pass cannot
    hide an individual corpus running well above budget (Bates et al.'s
    marginal-not-conditional-validity finding — see design spec §10).

    `typicality_ns` (one per scored fold) drives the reachability
    ANNOTATION on current_value, via `_reachability_block`'s BINDING
    (smallest, i.e. worst-case) observed typicality_n — if even one fold's
    p-value floor is above NO_ACTION_FAR_THRESHOLD, a 0% rate at that N is
    guaranteed by construction. `entity_baseline_counts` (the per-fold LOO
    baseline count — see run_all()'s call site: this is len(texts) - 1, NOT
    len(texts), since a fold posts every text except the one held out) and
    `band_threshold` estimate the SAME reachability question from a
    different angle: any-reachable, i.e. MAX over entities (one
    well-sampled entity is enough to call the band reachable). The two
    mechanisms read different data (observed per-fold N vs. reconstructed
    per-entity document counts) and aggregate in OPPOSITE directions
    (pessimistic MIN-over-folds vs. optimistic MAX-over-entities), so they
    CAN legitimately disagree.

    Invariant (FIX 3(b), tightened by a later fix on the ANNOTATION side):
    a "pass" verdict can never coexist with an "UNINFORMATIVE" annotation
    in current_value — rendering `G1 [PASS] ... (UNINFORMATIVE: ...)` is
    exactly the self-contradiction this fix exists to eliminate. When
    `typicality_ns` is supplied it is the MORE accurate signal (observed
    per-fold N, not reconstructed from document counts), so a would-be
    pass with `flagged == 0` that EITHER mechanism finds unreachable is
    downgraded to "uninformative". A nonzero flagged count is real
    evidence, never arithmetic (FIX 2), so the DOWNGRADE is never applied
    regardless of reachability when flagged > 0 — and for that identical
    reason the current_value ANNOTATION is now *also* only ever appended
    when `flagged == 0`: once real flags exist, the annotation's own claim
    ("this rate is not evidence of calibration") is false, because those
    flags came from the deviation-score path rather than the conformal
    band, so the rate IS a real measurement, not arithmetic. (A prior
    version of this function gated the downgrade on `flagged == 0` but
    gated the annotation on reachability alone, so a nonzero flagged rate
    under an unreachable band still rendered `G1 [PASS] ... (UNINFORMATIVE:
    ...)` — the exact contradiction this invariant forbids. Both are now
    gated identically.) A genuine FAILURE (pooled_rate > 5%) is likewise
    never downgraded — only a would-be pass can become uninformative.
    Omitting both `typicality_ns` and `entity_baseline_counts` preserves
    the legacy two-valued (`pass`/`fail`) behavior exactly.

    A non-positive `entity_baseline_counts` value (a degenerate corpus
    entry with 0 or fewer LOO samples) is treated as unreachable directly
    rather than raised through validation.power's ValueError, so this gate
    can never crash on a degenerate corpus (FIX 5).
    """
    from original.quantum.typicality import NO_ACTION_FAR_THRESHOLD

    n = len(pooled_actions)
    flagged = sum(1 for a in pooled_actions if a != "no_action")
    pooled_rate = flagged / n if n else 1.0

    per_corpus_rate = {}
    for corpus, actions in per_corpus.items():
        cn = len(actions)
        cflagged = sum(1 for a in actions if a != "no_action")
        per_corpus_rate[corpus] = cflagged / cn if cn else 1.0

    # The loosest band boundary: below NO_ACTION_FAR_THRESHOLD nothing in
    # band_from_p() can move a fold off "no_action" (the stricter central /
    # monitor / escalate boundaries are unreachable a fortiori).
    reachability = _reachability_block(typicality_ns or [], NO_ACTION_FAR_THRESHOLD)
    current_value = f"{pooled_rate:.1%}"
    # Gated on flagged == 0, matching the downgrade below exactly: once real
    # flags exist, the annotation's own claim ("this rate is not evidence of
    # calibration") is false — those flags came from the deviation-score
    # path, not the conformal band, so the rate IS a real measurement. Not
    # gating on flagged here was the bug: a nonzero flagged rate under an
    # unreachable band used to render `G1 [PASS] ... (UNINFORMATIVE: ...)`,
    # violating this function's own invariant (see docstring).
    if flagged == 0 and reachability["observed"] and not reachability["reachable"]:
        current_value += (
            f" (UNINFORMATIVE: typicality thresholds unreachable at "
            f"n<={reachability['min_typicality_n']} — p-value floor "
            f"{reachability['p_floor']:.3f} exceeds the loosest flag boundary "
            f"{NO_ACTION_FAR_THRESHOLD:g}, which needs n>="
            f"{reachability['required_n']}; band-driven flags are impossible "
            f"by construction, so this rate is not evidence of calibration)"
        )

    verdict = "pass" if pooled_rate <= 0.05 else "fail"
    # The typicality_ns mechanism's unreachability signal, computed above
    # into current_value's annotation — reused below for the FIX 3(b)
    # invariant so the two mechanisms can't disagree in the rendered
    # verdict even when they disagree about the underlying reachability.
    typicality_unreachable = reachability["observed"] and not reachability["reachable"]
    detail = {
        "n": n,
        "flagged": flagged,
        "pooled_flagged_rate": pooled_rate,
        "per_corpus_flagged_rate": per_corpus_rate,
        "reachability": reachability,
    }

    entity_unreachable = False
    if entity_baseline_counts:
        from validation.power import (
            band_reachable,
            conformal_p_floor,
            min_docs_for_band,
            rule_of_three_upper,
        )

        if band_threshold is None:
            band_threshold = NO_ACTION_FAR_THRESHOLD
        # FIX 5: a non-positive count can never reach any band —
        # band_reachable/conformal_p_floor are undefined below n=1 and
        # raise ValueError — so treat it as unreachable directly instead of
        # crashing this gate on a degenerate corpus entry.
        reachable = {
            e: (band_reachable(cnt, band_threshold) if cnt > 0 else False)
            for e, cnt in entity_baseline_counts.items()
        }
        positive_counts = [cnt for cnt in entity_baseline_counts.values() if cnt > 0]
        max_n = max(positive_counts) if positive_counts else 0
        detail["power"] = {
            "band_threshold": band_threshold,
            "max_entity_n": max_n,
            "min_conformal_p_at_max_n": conformal_p_floor(max_n) if max_n > 0 else None,
            "entities_reachable": sum(reachable.values()),
            "entities_total": len(reachable),
            "min_docs_for_band": min_docs_for_band(band_threshold),
            "rule_of_three_fpr_upper": rule_of_three_upper(n) if flagged == 0 and n else None,
        }
        entity_unreachable = not any(reachable.values())

    # FIX 2 + FIX 3(b): only a would-be pass with ZERO real flags can be
    # downgraded — flagged > 0 is genuine evidence, never arithmetic, so it
    # must stay "pass" (and current_value must never grow a zero-rate
    # sentence it didn't earn). Once flagged == 0 is required, EITHER
    # mechanism finding the band unreachable downgrades the verdict, so a
    # "pass" can never render alongside an "UNINFORMATIVE" annotation.
    if verdict == "pass" and flagged == 0 and (entity_unreachable or typicality_unreachable):
        # The band is arithmetically unreachable: the clean rate is
        # arithmetic, not evidence (Instrument Report, G1).
        verdict = "uninformative"

    return GateResult(
        name="G1",
        passed=verdict == "pass",
        verdict=verdict,
        criterion="pooled flagged rate <= 5%",
        current_value=current_value,
        detail=detail,
    )


_G2_CRITERION = "median(impostor q) <= median(holdout q)"


def evaluate_g2_bland_impostor(holdout_q: list[float], impostor_q: list[float]) -> GateResult:
    """
    G2 — Bland impostor. q = min(p_far, p_central) (the two-sided
    typicality). Median impostor q must be <= median holdout q — an
    impostor must not look MORE typical than genuine work.
    """
    import statistics

    med_holdout = statistics.median(holdout_q) if holdout_q else float("nan")
    med_impostor = statistics.median(impostor_q) if impostor_q else float("nan")
    passed = med_impostor <= med_holdout
    return GateResult(
        name="G2",
        passed=passed,
        criterion=_G2_CRITERION,
        current_value=f"impostor={med_impostor:.3f}, holdout={med_holdout:.3f}",
        detail={"holdout_q": holdout_q, "impostor_q": impostor_q},
    )


_G2B_PROXY_LABEL = "paraphrase proxy (mechanical transformation, not LLM paraphrase)"

_G2B_CRITERION = (
    "median(paraphrased impostor q) <= median(holdout q) — " + _G2B_PROXY_LABEL
)

_G2B_PROXY_NOTE = (
    "The impostor texts were transformed by a deterministic "
    + _G2B_PROXY_LABEL
    + ": fixed-table word substitution plus within-paragraph adjacent-sentence "
    "reordering (_paraphrase_proxy). A pass here is NOT evidence of robustness "
    "against real detector-guided LLM paraphrase attacks (the published "
    "one-line 'elevate the language' attack the design spec's research review "
    "cites) — no LLM is wired into this validation harness. MEASURED LIMITS of "
    "the transform on validation/corpus/ai_*.txt: it substitutes ~1% of tokens "
    "(1.1% measured; the table has 37 entries but they are rare in this "
    "corpus), and three of the six Tier-18 uniformity features — "
    "sentence_length_dispersion_ratio, punctuation_dispersion_ratio and "
    "clause_depth_variance_ratio — are invariant under it BY CONSTRUCTION, "
    "since reordering sentences within a paragraph permutes but does not "
    "change the per-sentence length / punctuation / clause-depth "
    "distributions, and a ~1% synonym swap does not either. So this gate "
    "stresses at most half the uniformity family, weakly. A real LLM-based "
    "paraphrase gate remains an open follow-up."
)


def evaluate_g2b_paraphrase_resistant(
    holdout_q: list[float],
    paraphrased_impostor_q: list[float],
    informational: dict | None = None,
) -> GateResult:
    """
    G2b — Bland impostor, paraphrase-resistance PROXY. Repeats G2's criterion
    (q = min(p_far, p_central); an impostor must not look MORE typical than
    genuine work) with the Tier-18 uniformity features enabled and the
    ai_*.txt corpus run through _paraphrase_proxy — a mechanical
    transformation, NOT an LLM paraphrase. The proxy label travels in both
    the criterion string and detail["proxy_note"] so this gate can never be
    presented as an LLM-paraphrase robustness claim (standing decision; the
    design spec's own wording — "detector-guided paraphrase" — claims more
    than this harness can test without an LLM, so the claim is deliberately
    weakened here).

    `informational` is attach-only context merged into detail — it never
    affects the verdict, and it is merged FIRST so a stray key can never
    overwrite a verdict-bearing one (the proxy label above all).
    """
    import statistics

    med_holdout = statistics.median(holdout_q) if holdout_q else float("nan")
    med_impostor = (
        statistics.median(paraphrased_impostor_q) if paraphrased_impostor_q else float("nan")
    )
    passed = med_impostor <= med_holdout
    detail = dict(informational or {})
    detail.update(
        {
            "holdout_q": holdout_q,
            "paraphrased_impostor_q": paraphrased_impostor_q,
            "proxy_note": _G2B_PROXY_NOTE,
        }
    )
    return GateResult(
        name="G2b",
        passed=passed,
        criterion=_G2B_CRITERION,
        current_value=f"paraphrased_impostor={med_impostor:.3f}, holdout={med_holdout:.3f}",
        detail=detail,
    )


def evaluate_g3_attribution(
    top1_accuracy: float,
    top1_accuracy_raw_argmin: float | None = None,
    n_essays: int | None = None,
) -> GateResult:
    """
    G3 — Attribution non-regression. Existing bar: >= 0.7 (unchanged).
    top1_accuracy is the impostor-calibrated accuracy from
    validation/public_authors/run.py (summary.top1_accuracy); the raw
    argmin accuracy (summary.top1_accuracy_raw_argmin) is carried in
    detail for comparison when present, but never gated on.

    `n_essays` (held-out essay count behind top1_accuracy) drives the
    VERDICT via validation/power.py's Wilson interval: a point estimate
    above the 0.7 bar whose 95% CI straddles the bar is not evidence of a
    pass at this sample size (the sampling-uncertainty analogue of G1's
    conformal-floor argument), so the verdict is downgraded to
    "uninformative". A measured FAILURE is never downgraded — the interval
    only ever softens a pass. Omitting `n_essays` preserves the legacy
    two-valued (`pass`/`fail`) behavior exactly.
    """
    verdict = "pass" if top1_accuracy >= 0.7 else "fail"
    detail = {"top1_accuracy": top1_accuracy}
    if top1_accuracy_raw_argmin is not None:
        detail["top1_accuracy_raw_argmin"] = top1_accuracy_raw_argmin

    if n_essays:
        from validation.power import bar_decidable, wilson_interval

        successes = round(top1_accuracy * n_essays)
        lo, hi = wilson_interval(successes, n_essays)
        decision = bar_decidable(successes, n_essays, bar=0.7)
        detail["power"] = {
            "n_essays": n_essays,
            "wilson_ci": [lo, hi],
            "bar": 0.7,
            "bar_decidable": decision,
        }
        if verdict == "pass" and decision != "above":
            # Point estimate clears the bar but the interval straddles it:
            # this corpus cannot demonstrate the claim (see Task 5 notes).
            verdict = "uninformative"

    return GateResult(
        name="G3",
        passed=verdict == "pass",
        verdict=verdict,
        criterion="public_authors top-1 accuracy >= 0.7 (impostor-calibrated attribution)",
        current_value=f"{top1_accuracy:.3f}",
        detail=detail,
    )


_G4_CRITERION = "early <= middle <= late (typicality distance from early baseline)"


def evaluate_g4_career_drift_monotone(group_means: dict[str, float]) -> GateResult:
    """
    G4 — Career-drift sanity. group_means keyed by "early"/"middle"/"late",
    values are mean typicality distance from an early-group baseline.
    Must be non-decreasing early -> middle -> late.
    """
    order = ["early", "middle", "late"]
    values = [group_means[k] for k in order if k in group_means]
    passed = all(values[i] <= values[i + 1] for i in range(len(values) - 1)) and len(values) == 3
    return GateResult(
        name="G4",
        passed=passed,
        criterion=_G4_CRITERION,
        current_value=str(group_means),
        detail={"group_means": group_means},
    )


def evaluate_g5_permutation_null(
    real_g1_mean_deviation: float,
    shuffled_g1_mean_deviation: float,
    shuffled_g3_accuracy: float,
    g4_nonmonotone_draws: int,
    g4_total_draws: int,
    informational: dict | None = None,
) -> GateResult:
    """
    G5 — Selection-bias null control. Author labels are shuffled with a fixed
    seed and the SAME three scoring legs the real G1/G3/G4 gates use are
    re-run through the production pipeline. (The plan's original Task-13 text
    described re-deriving weights via scripts.derive_measured_weights; the
    gates as built score the production pipeline directly, so the faithful
    null is a label-shuffled rerun of the same scoring legs — reviewed
    deviation, 2026-07-30 fix round.) All three shuffled legs must collapse:

      - G1 leg: the shuffled corpus gives every pseudo-student a cross-author
        blended baseline, so its mean deviation_score must come out STRICTLY
        ABOVE the real same-author leg's mean. Insensitivity to blending
        (shuffled mean <= real mean) means the measurement is not measuring
        authorship. The flagged RATE is deliberately NOT the criterion:
        conformal typicality p-values floor at 1/(N+1) and every G1 corpus
        entity has at most ~a dozen LOO folds, which pins the action band to
        no_action for real AND shuffled labels alike — a low shuffled rate is
        guaranteed by construction and carries no circularity information
        (rates travel in detail as context only).
      - G3 leg: attribution accuracy must be near chance (roughly
        1/n_authors; generous < 0.30 threshold since n_authors varies by
        corpus).
      - G4 leg: a MAJORITY of the K seeded shuffle draws must be
        non-monotone. The shuffled draws score the early group held-out
        (score_early_loo cross-fit — no chunk is scored against a baseline
        containing it) so all three group means are exchangeable under the
        null: P(a single draw comes out monotone by chance) ~= 1/6, so one
        monotone draw among K is noise, while majority-of-3 non-monotone
        detects a genuine null with ~0.93 probability.

    Fails (correctly) if ANY of the three still looks like real signal.
    `informational` is attach-only context merged into detail — it never
    affects the verdict.
    """
    g1_is_suspicious = shuffled_g1_mean_deviation <= real_g1_mean_deviation
    g3_is_suspicious = shuffled_g3_accuracy >= 0.30
    g4_majority = g4_total_draws // 2 + 1
    g4_is_suspicious = g4_nonmonotone_draws < g4_majority

    passed = not (g1_is_suspicious or g3_is_suspicious or g4_is_suspicious)
    detail = {
        "real_g1_mean_deviation": real_g1_mean_deviation,
        "shuffled_g1_mean_deviation": shuffled_g1_mean_deviation,
        "shuffled_g3_accuracy": shuffled_g3_accuracy,
        "g4_nonmonotone_draws": g4_nonmonotone_draws,
        "g4_total_draws": g4_total_draws,
    }
    if informational:
        detail.update(informational)
    return GateResult(
        name="G5",
        passed=passed,
        criterion="G1/G3/G4 collapse to chance under permuted author labels",
        current_value=(
            f"g1_dev real={real_g1_mean_deviation:.3f} "
            f"shuffled={shuffled_g1_mean_deviation:.3f}, "
            f"g3_acc={shuffled_g3_accuracy:.3f}, "
            f"g4_nonmonotone={g4_nonmonotone_draws}/{g4_total_draws}"
        ),
        detail=detail,
    )


def _machinery_error_result(name: str, criterion: str, exc: Exception) -> GateResult:
    """
    run_all()'s crash wrapper for scoring-leg gates: a crash inside a gate's
    orchestration is a scoring-MACHINERY failure, not a gate verdict. It must
    neither discard the other completed gates nor masquerade as a genuine
    result — so it renders as a FAILED gate whose current_value is
    unmistakably an error.
    """
    return GateResult(
        name=name,
        passed=False,
        criterion=criterion,
        current_value=f"ERROR (machinery): {exc}",
        detail={"machinery_error": str(exc)},
    )


def _g5_machinery_error_result(exc: Exception) -> GateResult:
    """G5-specific wrapper around _machinery_error_result (its docstring
    applies; this predates the generic helper and keeps its call sites and
    tests stable)."""
    return _machinery_error_result(
        "G5", "G1/G3/G4 collapse to chance under permuted author labels", exc
    )


_G6_CRITERION = (
    "per-group flagged rate for the p_central/too-uniform action must not "
    "differ by more than 2x between native_english=true and =false authentic "
    "samples — verdict covers the p_central action ONLY; the spec's per-group "
    "uniformity-feature comparison is recorded in detail as measurement, not "
    "gated (pending Tier-18 NORM_BOUNDS calibration)"
)


def evaluate_g6_fairness(
    native_fpr: float,
    non_native_fpr: float,
    informational: dict | None = None,
    welch_effect_magnitude: str | None = None,
    welch_cohens_d: float | None = None,
) -> GateResult:
    """
    G6 — Non-native-English fairness. Per-group flagged rate for the
    p_central/too-uniform action must not differ by more than 2x between
    native_english=true and =false groups (design spec §4, G6 row).

    Zero-rate conventions, which deliberately DIVERGE from
    validation/bias_analysis._analyze_dimension's "<2 non-zero rates => ratio
    1.0" rule. That rule is safe there only because it sits beside
    effect-size and ANOVA checks that can independently fail the dimension;
    imported alone into a single-criterion gate it turns the two most
    fairness-relevant small-sample cases into silent passes. Here:

      - both rates non-zero: ratio = max/min, pass iff <= 2x (unchanged);
      - exactly one rate zero: an INFINITE disparity — one group is never
        flagged and the other is. A real signal, so verdict="fail"; ratio
        is recorded as inf;
      - both rates zero: the ratio is undefined and nothing about fairness
        has been demonstrated — a genuinely can't-know outcome, so
        verdict="uninformative" (never "fail": that would claim disparity
        evidence that isn't there, and never "pass": passed stays False).
        current_value still reads UNDEFINED (an absence of evidence must
        not render green). When the cause is the conformal floor rather
        than the data, _compute_g6_fairness_data catches it earlier and
        returns the louder "threshold unreachable" skip
        (_g6_insufficient_data_result, also verdict="uninformative").

    `welch_effect_magnitude`/`welch_cohens_d` come from the bridged
    validation/bias_analysis._welch_t_test. They never change the verdict
    (the spec's criterion is the ratio), but a medium/large effect is
    contradicting evidence — _analyze_dimension would call that NOT FAIR —
    so it is appended to current_value rather than buried in detail.

    `informational` is attach-only context merged into detail — it never
    affects the verdict, and it is merged FIRST so a stray key can never
    overwrite a verdict-bearing one.
    """
    native_zero = native_fpr <= 0.0
    non_native_zero = non_native_fpr <= 0.0
    rate_text = f"native={native_fpr:.1%}, non_native={non_native_fpr:.1%}"

    if native_zero and non_native_zero:
        ratio: float | None = None
        ratio_status = "undefined_both_zero"
        passed = False
        # Genuinely can't-know: no fairness has been demonstrated either way
        # (never "fail" — that would claim disparity evidence that isn't
        # there).
        verdict = "uninformative"
        current_value = (
            f"UNDEFINED: both group flagged rates are 0% ({rate_text}) — the "
            "ratio is undefined and no fairness has been demonstrated"
        )
    elif native_zero or non_native_zero:
        ratio = float("inf")
        ratio_status = "one_group_zero"
        passed = False
        # A real signal (one group never flagged, the other is) — a
        # genuine failure, not an absence of evidence.
        verdict = "fail"
        current_value = (
            f"ratio=inf ({rate_text}) — one group is never flagged and the "
            "other is: an infinite disparity, which exceeds the 2x bar"
        )
    else:
        ratio = max(native_fpr, non_native_fpr) / min(native_fpr, non_native_fpr)
        ratio_status = "both_nonzero"
        passed = ratio <= 2.0
        verdict = "pass" if passed else "fail"
        current_value = f"ratio={ratio:.2f}x ({rate_text})"

    if welch_effect_magnitude in ("medium", "large"):
        d_text = f", d={welch_cohens_d:.3f}" if welch_cohens_d is not None else ""
        current_value += (
            f" — CAVEAT: Welch effect size on p_central is "
            f"{welch_effect_magnitude}{d_text}, which "
            "bias_analysis._analyze_dimension would read as NOT FAIR"
        )

    detail = dict(informational or {})
    detail.update(
        {
            "native_fpr": native_fpr,
            "non_native_fpr": non_native_fpr,
            "ratio": ratio,
            "ratio_status": ratio_status,
            "welch_effect_magnitude": welch_effect_magnitude,
            "welch_cohens_d": welch_cohens_d,
        }
    )
    return GateResult(
        name="G6",
        passed=passed,
        verdict=verdict,
        criterion=_G6_CRITERION,
        current_value=current_value,
        detail=detail,
    )


def _g6_insufficient_data_result(
    missing: str,
    *,
    n_native_scored: int,
    n_non_native_scored: int,
    reason: str = "insufficient data",
    extra_detail: dict | None = None,
) -> GateResult:
    """
    Honest-instrument convention (same reasoning as _machinery_error_result):
    when G6's inputs cannot support a per-group rate — too few annotated
    entries, or a threshold the observed N cannot reach — it must record a
    LOUD skipped result: passed=False with a current_value that is
    unmistakably "no verdict", and a detail that says exactly what was
    missing. Never a silent pass. `reason` names the flavour of skip;
    `extra_detail` carries the flavour-specific numbers.

    This is a genuinely can't-know outcome (unlike _machinery_error_result's
    crash, which is a bug) — the underlying data simply cannot support a
    verdict either way, so it reports verdict="uninformative" rather than
    "fail".
    """
    detail = dict(extra_detail or {})
    detail.update(
        {
            "missing": missing,
            "n_native_scored": n_native_scored,
            "n_non_native_scored": n_non_native_scored,
        }
    )
    return GateResult(
        name="G6",
        passed=False,
        verdict="uninformative",
        criterion=_G6_CRITERION,
        current_value=f"SKIPPED ({reason}): {missing}",
        detail=detail,
    )


def _g6_unreachable_threshold_result(
    *,
    observed_n: int,
    threshold: float,
    n_native_scored: int,
    n_non_native_scored: int,
    extra_detail: dict | None = None,
) -> GateResult:
    """
    The vacuous-pass guard. With 5 essays per author scored leave-one-out,
    every fold has typicality_n=4, so p_central's whole support is
    {0.2, 0.4, 0.6, 0.8, 1.0} — the 0.02 flag threshold cannot be crossed by
    any submission whatsoever. Both groups then score a 0% flagged rate, the
    ratio comes out 1.0, and the gate would report a PASS indistinguishable
    from a genuine fairness result. Instead: a loud skip naming the floor,
    the observed n, and the n the spec's §5 reachability table requires.

    FIX E: observed_n<=0 used to crash here — _conformal_p_floor delegates
    to validation.power.conformal_p_floor (FIX 3(a)), which raises
    ValueError below n=1, where the OLD pre-delegation copy returned 1.0
    (see TestConformalReachability.test_p_floor_rejects_non_positive_n's
    history). That caller-audit gap was never closed for this function when
    the helpers were delegated. This has no production call site today
    (only a test exercises this helper directly), so the crash was latent,
    not observed — but a degenerate n=0 is exactly the kind of input FIX 5
    already treats as "unreachable" rather than fatal elsewhere in this
    module (evaluate_g1_fpr's non-positive entity_baseline_counts handling),
    so the same convention applies here: report the floor as undefined
    instead of raising.
    """
    if observed_n > 0:
        floor: float | None = _conformal_p_floor(observed_n)
        floor_text = f"{floor:.3f}"
    else:
        floor = None
        floor_text = "undefined (n<=0)"
    required_n = _min_n_for_threshold(threshold)
    detail = dict(extra_detail or {})
    detail.update(
        {
            "min_typicality_n": observed_n,
            "p_floor": floor,
            "threshold": threshold,
            "required_n": required_n,
        }
    )
    return _g6_insufficient_data_result(
        f"p_central floor 1/(n+1)={floor_text} at n={observed_n}, flag threshold "
        f"{threshold:g} needs n>={required_n}",
        n_native_scored=n_native_scored,
        n_non_native_scored=n_non_native_scored,
        reason="threshold unreachable",
        extra_detail=detail,
    )


def _g6_reachability_precheck(
    results_by_group: dict[bool, list[dict]],
    threshold: float,
    *,
    n_native_scored: int,
    n_non_native_scored: int,
) -> "GateResult | None":
    """
    Pure reachability pre-check, extracted from _compute_g6_fairness_data so
    it can be unit-tested without a live scoring client (see
    tests/test_calibration_gate.py::TestG6ReachabilityPrecheck).

    Given the already-scored entries for both groups (each dict must carry a
    "typicality_n" key), returns the loud "threshold unreachable" skip
    (_g6_unreachable_threshold_result) when the smallest observed
    typicality_n across BOTH groups cannot reach `threshold` at all — this is
    the vacuous-pass guard _g6_unreachable_threshold_result's own docstring
    describes (5 essays/author LOO gives typicality_n=4 everywhere, whose
    p_central support cannot cross the 0.02 flag threshold, so both groups'
    0% flagged rate is structural, not evidence of fairness).

    Returns None when the threshold is reachable, or when no fold reports a
    typicality_n at all (the action came from the deviation path, not the
    conformal band, so the floor doesn't apply — mirrors
    _reachability_block's "observed=False" convention) — either way, the
    caller should proceed to compute the real per-group flagged rates.
    """
    all_scored = results_by_group[True] + results_by_group[False]
    min_typicality_n = min(
        (x["typicality_n"] for x in all_scored if x["typicality_n"]), default=0
    )
    if min_typicality_n and not _threshold_reachable(min_typicality_n, threshold):
        return _g6_unreachable_threshold_result(
            observed_n=min_typicality_n,
            threshold=threshold,
            n_native_scored=n_native_scored,
            n_non_native_scored=n_non_native_scored,
        )
    return None


def _g6_short_group_message(n_native: int, n_non_native: int, minimum: int) -> str:
    """
    Insufficient-data message that names EVERY short group (the first cut
    named only one even when both were short, misattributing the shortfall).
    """

    def _phrase(label: str, n: int) -> str:
        return f"native_english={label} group has {n} scored authentic " + (
            "entry" if n == 1 else "entries"
        )

    short = [
        _phrase(label, n)
        for label, n in (("true", n_native), ("false", n_non_native))
        if n < minimum
    ]
    return f"{' and '.join(short)} (need >= {minimum} each)"


def _uniformity_slice_summary(per_group_features: dict[bool, list[dict[str, float]]]) -> dict:
    """
    The spec's G6 row also asks for a per-group comparison of the Phase-4
    uniformity features, not only the p_central action. This records that
    comparison as MEASUREMENT — per-group means of each Tier-18 feature —
    without inventing a second verdict rule the spec doesn't define (no bar
    exists for these until Tier-18 NORM_BOUNDS are calibrated), hence
    gated=False.

    `constant_across_slice` names features that never vary anywhere in the
    slice. Such a feature cannot carry a fairness signal in either
    direction, and it is exactly the fingerprint of the Tier-18 bounds
    miscalibration (features normalising to a pinned 0.0/1.0 for every
    text), so it is called out by name rather than left to be inferred from
    two identical means.
    """
    import statistics

    native = list(per_group_features.get(True) or [])
    non_native = list(per_group_features.get(False) or [])
    codes = sorted({code for row in native + non_native for code in row})

    def _means(rows: list[dict[str, float]]) -> dict[str, float]:
        return {
            code: statistics.fmean([row[code] for row in rows if code in row])
            for code in codes
            if any(code in row for row in rows)
        }

    all_rows = native + non_native
    constant = [
        code
        for code in codes
        if len({round(row[code], 12) for row in all_rows if code in row}) <= 1
    ]
    return {
        "native_english_true_means": _means(native),
        "native_english_false_means": _means(non_native),
        "constant_across_slice": constant,
        "n_native": len(native),
        "n_non_native": len(non_native),
        "gated": False,
        "note": (
            "per-group Tier-18 uniformity-feature means, recorded as "
            "measurement only — the spec defines no numeric bar for these "
            "until the Tier-18 NORM_BOUNDS are calibrated, so they do not "
            "affect G6's verdict. Features listed in constant_across_slice "
            "never vary in this slice and can carry no fairness signal at all."
        ),
    }


# ── Task 9: corpus-group-scoped pooled calibration (pure helpers) ─────────────
#
# The real G1 leg (_score_corpus_for_g1, below) scores THREE different
# corpora -- seminary, public_authors, and Plato -- under one flat "demo:"
# sid prefix: every fold's sid is demo:gate_g1_{entity_id}_{held_out_idx}, so
# every entity from every corpus shares the literal tenant "demo". Task 7's
# pooling_exchangeability audit only validated within-seminary and
# within-Plato exchangeability SEPARATELY -- never their union, and never
# public_authors at all. collect_tenant_distances (original/quantum/
# pooled_source.py) resolves tenant via tenant_of(sid) or DEMO_TENANT, and
# tenant_of only looks at the substring before the first ":" -- so calling it
# with tenant="demo" across the merged texts_by_id would silently pool all
# three corpora together, producing a p-value that rests on zero empirical
# exchangeability evidence. These two pure functions make the corpus-group
# boundary an explicit value instead of an implicit (and, for public authors
# like "augustine", nonexistent) property of sid strings, so the pooled-mode
# scorers below can filter BEFORE anything reaches collect_tenant_distances
# rather than rely on tenant-string matching to do it for them.


def _group_entities_for_pooling(
    seminary_texts: dict[str, list[str]],
    plato_texts: dict[str, list[str]],
    public_authors_texts: dict[str, list[str]],
) -> dict[str, str]:
    """entity_id -> corpus group ("seminary" | "plato" | "public_authors"),
    built directly from the three loader dicts' own keys -- NOT by parsing
    sid strings. Public-author entity ids (e.g. "augustine", "mill") carry
    no prefix a sid-parsing approach could use to recover their group, and
    every G1 sid is tenant-scoped to the same flat "demo:" regardless of
    which corpus it came from, so loader membership is the only source of
    truth for group boundaries.
    """
    group_of: dict[str, str] = {}
    for entity_id in seminary_texts:
        group_of[entity_id] = "seminary"
    for entity_id in plato_texts:
        group_of[entity_id] = "plato"
    for entity_id in public_authors_texts:
        group_of[entity_id] = "public_authors"
    return group_of


def _pool_peers_for_entity(
    entity_id: str,
    group_of: dict[str, str],
    entity_states,
) -> dict:
    """Subset of `entity_states` (an {entity_id: state} mapping) belonging to
    OTHER entities in `entity_id`'s corpus group -- the exact, group-scoped
    set that may be pooled when scoring `entity_id`. Never spans a group
    boundary (see the section docstring above for why that is
    non-negotiable); always excludes `entity_id` itself, even if
    `entity_states` happens to contain it. Exclusion is keyed on entity_id,
    not on dict identity, so a caller that never built a reference state for
    `entity_id` (e.g. it fell below the LOO minimum) still gets a
    correctly-scoped pool for everyone else.
    """
    my_group = group_of.get(entity_id)
    return {
        eid: state
        for eid, state in entity_states.items()
        if eid != entity_id and group_of.get(eid) == my_group
    }


def _pooled_reference_arithmetic(
    group_of: dict[str, str],
    sizes: dict[str, int],
    min_size: int = 5,
) -> dict[str, dict]:
    """Pure, HTTP-free projection of the pooled reference size each
    qualifying entity would actually get -- Task 9 Step 1's "assert
    reachability before believing any result", worked out by arithmetic
    before any real corpus run.

    Only entities with >= min_size texts participate, matching
    _score_corpus_for_g1's own `len(texts) < 5` LOO-fold participation bar
    (an entity that never gets scored is also never a usable peer). Each
    qualifying peer entity contributes exactly len(texts) leave-one-out
    distances once pooled -- one per its own contributing baseline sample,
    when that entity's pool-reference state is built from ALL of its own
    texts (see original/quantum/state.py's loo_distances: length == N for
    N >= 2 contributing samples).

    Returns {entity_id: {"group", "own_n", "pool_n", "n_peers"}} for every
    qualifying entity, where pool_n is the sum of every OTHER qualifying
    same-group entity's own text count.
    """
    qualifying = {e: n for e, n in sizes.items() if n >= min_size}
    out: dict[str, dict] = {}
    for entity_id, n in qualifying.items():
        peer_sizes = [
            other_n
            for other_id, other_n in qualifying.items()
            if other_id != entity_id and group_of.get(other_id) == group_of.get(entity_id)
        ]
        out[entity_id] = {
            "group": group_of.get(entity_id),
            "own_n": n,
            "pool_n": sum(peer_sizes),
            "n_peers": len(peer_sizes),
        }
    return out


# ── Corpus-driving orchestration (exercised by `main()`, not unit-tested) ──────


def _score_corpus_for_g1(
    client, sid_prefix: str, texts_by_id: dict[str, list[str]]
) -> tuple[list[str], dict[str, list[str]], list[float], int, list[int], int]:
    """
    For each id in texts_by_id with >= 5 texts: build a baseline from all
    but one text (leave-one-out over WHOLE documents, not chunks), score
    the held-out text, record its recommendation.action. Repeat holding out
    each text in turn. Requires TYPICALITY_SCORING=1 already set in os.environ
    before `client` was constructed (env is read at score() call time, so
    this also works if set right before this call — see
    validation/verify/run_null_model.py's docstring on this point).

    Returns (pooled_actions, per_corpus_actions, pooled_deviations, n_errors,
    pooled_typicality_ns, n_drift_rejected): pooled_deviations is each
    successful fold's deviation_score, index-aligned with pooled_actions —
    the real G1 evaluator (evaluate_g1_fpr) ignores it; G5's deviation-shift
    criterion consumes it. n_errors counts non-200 score responses AND folds
    skipped because one of their baseline uploads returned non-200 (a fold
    whose baseline is known incomplete must never be scored — see the
    module-level note on the 2026-07-28 vs 2026-07-30 drift) — so callers
    can distinguish "clean run" from "the numbers came from a broken leg"
    (see _require_healthy_leg). This is UNCHANGED from before
    n_drift_rejected existed: n_errors still counts every drift-rejected
    fold too, because the real (non-shuffled) G1 leg's own health accounting
    (run_g5's "G5 real G1 anchor leg" check on real_g1_n_errors) must keep
    treating a drift-rejection on a real student's baseline as a genuine
    signal about that leg, exactly as it does today.

    n_drift_rejected is a NEW, purely additive count, always <= n_errors: of
    the folds counted in n_errors because a baseline upload failed, this
    counts only those where EVERY failing baseline response had
    status_code in (202, 409) — i.e. the Phase-8 drift gate
    (original/routers/students_baseline.py's add_baseline) rejected the
    sample as `pending_review`/`rebaseline_required`, not a genuine 4xx/5xx
    or connection failure. A fold with a mix of drift and non-drift baseline
    failures is NOT counted here — any genuine failure in the mix means the
    fold is still evidence of real machinery trouble. Callers that want to
    treat drift-rejection as an expected, non-machinery outcome (G5's
    shuffled-G1 leg — see run_g5) can compute their own
    "genuine-failures-only" error count as n_errors - n_drift_rejected
    before calling _require_healthy_leg; callers that don't care (run_all()'s
    real G1 leg) simply discard this return value. pooled_typicality_ns is
    each successful fold's top-level payload["typicality_n"] (also
    index-aligned with pooled_actions) — evaluate_g1_fpr's reachability
    annotation consumes it.
    """
    pooled: list[str] = []
    per_corpus: dict[str, list[str]] = {}
    pooled_deviations: list[float] = []
    pooled_typicality_ns: list[int] = []
    n_errors = 0
    n_drift_rejected = 0
    for entity_id, texts in texts_by_id.items():
        if len(texts) < 5:
            continue
        actions: list[str] = []
        deviations: list[float] = []
        typicality_ns: list[int] = []
        for held_out_idx in range(len(texts)):
            sid = f"demo:gate_{sid_prefix}_{entity_id}_{held_out_idx}"
            baseline_failed = False
            # True iff every failing baseline response so far was a Phase-8
            # drift-gate rejection (202 pending_review / 409
            # rebaseline_required) rather than a genuine failure — see the
            # docstring above and original/routers/students_baseline.py's
            # add_baseline, whose only non-200 outcomes are 422 (invalid
            # provenance), 503 (persistence failure), or the drift gate's
            # 202/409.
            baseline_drift_only = True
            for i, text in enumerate(texts):
                if i == held_out_idx:
                    continue
                r = client.post(
                    f"/students/{sid}/baseline",
                    json={"text": text, "provenance": "verified", "submitted_at": "2026-01-01"},
                )
                if r.status_code != 200:
                    baseline_failed = True
                    if r.status_code not in (202, 409):
                        baseline_drift_only = False
            if baseline_failed:
                # A fold whose baseline is known incomplete must not be
                # scored — proceeding would silently shrink this fold's
                # effective LOO sample count instead of surfacing the drop.
                n_errors += 1
                if baseline_drift_only:
                    n_drift_rejected += 1
                continue
            r = client.post(
                f"/students/{sid}/score",
                json={"text": texts[held_out_idx], "submission_id": f"{entity_id}_{held_out_idx}"},
            )
            if r.status_code == 200:
                payload = r.json()
                actions.append(payload["recommendation"]["action"])
                deviations.append(float(payload["authorship"]["deviation_score"]))
                typicality_ns.append(int(payload.get("typicality_n", 0)))
            else:
                n_errors += 1
        if actions:
            per_corpus[entity_id] = actions
            pooled.extend(actions)
            pooled_deviations.extend(deviations)
            pooled_typicality_ns.extend(typicality_ns)
    return pooled, per_corpus, pooled_deviations, n_errors, pooled_typicality_ns, n_drift_rejected


def _build_pool_reference_states(
    client, sid_prefix: str, texts_by_id: dict[str, list[str]], min_size: int = 5
) -> dict:
    """Upload every qualifying entity's FULL text set (never leave-one-out
    reduced -- a peer is only ever a reference for OTHER folds, never itself
    being scored via this state) as its own baseline, under a sid distinct
    from any fold sid, then read back the resulting StudentState via
    ``original.store`` (== ``_repo().get`` whenever REPO_BACKEND is not
    postgres -- see original/repository.py's SqliteRepository, which is a
    thin passthrough to original.store; this is the same convention
    validation/audits/g2_floor_asymmetry.py's main() uses for
    store.reset_memory_conn()).

    Only entities with >= min_size texts participate -- the same bar the
    per-fold LOO loop below applies -- so a group's theoretical pool size
    (_pooled_reference_arithmetic's pool_n) matches what this function
    actually builds. Raises RuntimeError (via _require_healthy_leg) if the
    combined baseline-upload leg is unhealthy: a broken peer reference must
    not silently shrink the pool instead of failing loudly.
    """
    from original import store

    states: dict[str, object] = {}
    n_attempts = 0
    n_errors = 0
    for entity_id, texts in texts_by_id.items():
        if len(texts) < min_size:
            continue
        sid = f"demo:gate_{sid_prefix}_{entity_id}_poolref"
        for text in texts:
            n_attempts += 1
            r = client.post(
                f"/students/{sid}/baseline",
                json={"text": text, "provenance": "verified", "submitted_at": "2026-01-01"},
            )
            if r.status_code != 200:
                n_errors += 1
        state = store.get(sid)
        if state is not None:
            states[entity_id] = state
    _require_healthy_leg(
        f"{sid_prefix} pool-reference build", n_success=n_attempts - n_errors, n_errors=n_errors
    )
    return states


def _score_corpus_for_g1_pooled(
    client, sid_prefix: str, texts_by_id: dict[str, list[str]], group_of: dict[str, str]
) -> dict:
    """Pooled-calibration variant of _score_corpus_for_g1: identical LOO
    fold structure and identical baseline-upload health accounting, but each
    held-out fold is scored by calling original.quantum.scoring.score()
    DIRECTLY -- with typicality_pooled_calibration=True and a pooled_states
    dict restricted to entities in the SAME corpus group as the one being
    scored (via _pool_peers_for_entity) -- instead of through the live HTTP
    /score endpoint.

    This bypass is necessary, not stylistic: original/routers/
    students_scoring.py's score_submission() never threads pooled_states or
    student_id into quantum_score() at all (confirmed by reading that file
    and by `grep -rn pooled_states= original/` turning up nothing outside
    scoring.py/pooled_source.py's own parameter definitions and this
    project's tests/quantum/test_pooled_typicality_integration.py).
    TYPICALITY_POOLED_CALIBRATION is consulted only inside
    original/quantum/scoring.py's score() function itself -- the live API
    surface has no wiring for it yet. Calling score() directly is therefore
    the only way to exercise pooled calibration at all today; this function
    is deliberately NOT "the same production path with one flag flipped",
    and any report built from it must say so plainly.

    Every sid stays under the "demo:" tenant prefix (both the per-fold sids
    below and _build_pool_reference_states's "_poolref" sids) so baseline
    uploads never hit an unregistered-tenant rejection; the corpus-group
    boundary is enforced entirely by _pool_peers_for_entity, upstream of
    anything that would otherwise resolve tenancy from the sid string.

    Returns a dict (not the 6-tuple _score_corpus_for_g1 returns -- this is
    a new function with no pre-existing callers to stay compatible with):
    pooled_actions, per_corpus_actions, pooled_deviations, n_errors,
    pooled_typicality_ns, n_drift_rejected, per_corpus_typicality_ns
    (entity_id -> per-fold typicality_n list, for computing PER-GROUP
    reachability -- the whole point of keeping corpora separate),
    calibration_mode_counts ({"pooled"|"self"|"none": count} across every
    scored fold -- lets the report distinguish "pooling was attempted and
    reached bands" from "every fold silently fell back to self because the
    group's pool never cleared build_pooled_reference's min_students=3/
    min_total=30"), and pool_reference_sizes (entity_id -> that entity's own
    pool-reference state's loo_distances length, for auditing the arithmetic
    against _pooled_reference_arithmetic's prediction).
    """
    import dataclasses as _dc

    from original import store
    from original.features.pipeline import extract_features, feature_vector
    from original.quantum.scoring import ScoringConfig
    from original.quantum.scoring import score as quantum_score

    pool_reference_states = _build_pool_reference_states(client, sid_prefix, texts_by_id)

    base_config = _dc.replace(ScoringConfig.from_env(), typicality_pooled_calibration=True)

    pooled: list[str] = []
    per_corpus: dict[str, list[str]] = {}
    pooled_deviations: list[float] = []
    pooled_typicality_ns: list[int] = []
    per_corpus_typicality_ns: dict[str, list[int]] = {}
    calibration_mode_counts: dict[str, int] = {"pooled": 0, "self": 0, "none": 0}
    n_errors = 0
    n_drift_rejected = 0

    for entity_id, texts in texts_by_id.items():
        if len(texts) < 5:
            continue
        peer_states = _pool_peers_for_entity(entity_id, group_of, pool_reference_states)
        actions: list[str] = []
        deviations: list[float] = []
        typicality_ns: list[int] = []
        for held_out_idx in range(len(texts)):
            sid = f"demo:gate_{sid_prefix}_{entity_id}_{held_out_idx}"
            baseline_failed = False
            # Same drift-vs-genuine-failure distinction as
            # _score_corpus_for_g1 -- see its docstring.
            baseline_drift_only = True
            for i, text in enumerate(texts):
                if i == held_out_idx:
                    continue
                r = client.post(
                    f"/students/{sid}/baseline",
                    json={"text": text, "provenance": "verified", "submitted_at": "2026-01-01"},
                )
                if r.status_code != 200:
                    baseline_failed = True
                    if r.status_code not in (202, 409):
                        baseline_drift_only = False
            if baseline_failed:
                n_errors += 1
                if baseline_drift_only:
                    n_drift_rejected += 1
                continue

            own_state = store.get(sid)
            if own_state is None:
                n_errors += 1
                continue

            held_out_text = texts[held_out_idx]
            feat_dict = extract_features(held_out_text)
            vec = feature_vector(held_out_text)

            result = quantum_score(
                state=own_state,
                submission_vector=vec,
                feature_dict=feat_dict,
                submission_id=f"{entity_id}_{held_out_idx}",
                scoring_config=base_config,
                pooled_states=peer_states,
                student_id=sid,
            )
            actions.append(result.recommendation.action)
            deviations.append(float(result.authorship.deviation_score))
            typicality_ns.append(int(result.typicality_n))
            mode = result.typicality_calibration or "none"
            calibration_mode_counts[mode] = calibration_mode_counts.get(mode, 0) + 1
        if actions:
            per_corpus[entity_id] = actions
            per_corpus_typicality_ns[entity_id] = typicality_ns
            pooled.extend(actions)
            pooled_deviations.extend(deviations)
            pooled_typicality_ns.extend(typicality_ns)

    return {
        "pooled_actions": pooled,
        "per_corpus_actions": per_corpus,
        "pooled_deviations": pooled_deviations,
        "n_errors": n_errors,
        "pooled_typicality_ns": pooled_typicality_ns,
        "n_drift_rejected": n_drift_rejected,
        "per_corpus_typicality_ns": per_corpus_typicality_ns,
        "calibration_mode_counts": calibration_mode_counts,
        "pool_reference_sizes": {
            eid: len(getattr(s, "loo_distances", []) or [])
            for eid, s in pool_reference_states.items()
        },
    }


def _g1_entity_baseline_counts(
    texts_by_id: dict[str, list[str]], per_corpus_actions: dict[str, list[str]]
) -> dict[str, int]:
    """
    Per-entity PER-FOLD LOO baseline count, for evaluate_g1_fpr's
    `entity_baseline_counts` argument — drives its conformal-band
    reachability check (validation/power.py): a clean pooled rate at an N
    too small for the band to ever be crossed is arithmetic, not evidence
    (see evaluate_g1_fpr's docstring).

    FIX 1: this is len(texts) - 1, NOT len(texts) — a fold in
    _score_corpus_for_g1 posts every text EXCEPT the held-out one, so the
    conformal N behind a fold's typicality p-value is one less than the
    entity's total document count. Do not "correct" this back to
    len(texts): a 33-document entity's LOO folds see n=32, not n=33, and 32
    is one short of what the default 0.03 band needs.

    FIX C: extracted out of run_all() into this standalone, importable
    function so the `- 1` conversion itself is unit-testable without
    running the corpus-driven gate — the previous round's
    TestG1LooOffByOne tests passed already-decremented literals (e.g.
    `{"s1": 32}`) straight into evaluate_g1_fpr, so both tests passed
    unchanged against the buggy inline `len(texts)` (no `- 1`) version too.

    FIX 5: keyed off `per_corpus_actions` (the entities _score_corpus_for_g1
    actually produced a fold for, i.e. already passed its own
    `len(texts) < 5` skip) rather than the full `texts_by_id`, so an entity
    that never contributed a fold doesn't inflate entities_total in
    evaluate_g1_fpr's power block.
    """
    return {entity_id: len(texts_by_id[entity_id]) - 1 for entity_id in per_corpus_actions}


def _g3_inputs_from_pa_report(pa_report: dict) -> tuple[float, float | None, int | None]:
    """
    Extract G3's three evaluate_g3_attribution() inputs from
    validation/public_authors/run.py's run() report dict, and warn loudly
    (stderr; never crash the battery) if the summary is PRESENT but missing
    "n_scored_essays".

    FIX 1: n_essays=None is indistinguishable, from
    evaluate_g3_attribution's point of view, from "the corpus legitimately
    produced no summary at all" — both silently revert G3 to its legacy
    two-valued pass/fail rule (see that function's `if n_essays:` guard).
    That silent revert is exactly the fail-open path this validation layer
    exists to prevent: a renamed/dropped "n_scored_essays" key in run.py
    (it is set in exactly one place, run.py's `n_scored_essays = len(results)`)
    would make G3 report `verdict="pass"` on a sample size too small to
    support one, with nothing printed anywhere to say why.

    So the two "no n_essays" cases are handled differently here:
      - "summary" absent entirely: the LEGITIMATE error path (run() found
        fewer than 2 eligible authors and returns {"error": ..., ...} with
        no "summary" key — see run()'s docstring). Nothing is wrong here;
        stay silent, exactly as before this fix.
      - "summary" present but "n_scored_essays" absent: a machinery bug —
        the producer/consumer contract between run.py and this file broke.
        Loud stderr warning naming the missing key; still doesn't crash the
        battery (mirrors every other `_machinery_error_result`-style
        convention in this file of degrading loudly rather than aborting).

    Extracted to a standalone, importable function (same FIX C convention
    as `_g1_entity_baseline_counts` above) so this branch is unit-testable
    with synthetic report dicts, without running run_public_authors()'s own
    live-TestClient scoring.
    """
    pa_summary = pa_report.get("summary", {})
    if "summary" in pa_report and "n_scored_essays" not in pa_summary:
        print(
            "⚠ calibration_gate: public_authors summary is present but "
            "missing 'n_scored_essays' — G3's informativeness check will "
            "silently revert to legacy pass/fail behavior "
            "(see evaluate_g3_attribution's `if n_essays:` guard)",
            file=sys.stderr,
        )
    return (
        pa_summary.get("top1_accuracy", 0.0),
        pa_summary.get("top1_accuracy_raw_argmin"),
        pa_summary.get("n_scored_essays"),
    )


def run_all() -> list[GateResult]:
    # Defensive reset, before anything else: ENV_LOCK (module import time,
    # above) already put us on ORIGINAL_DB=":memory:", so this is a no-op
    # today (the first _get_conn() call in a fresh process already gets an
    # empty database). It's insurance against a second, currently-untaken
    # call path: nothing prevents run_all() from being invoked twice in one
    # process (e.g. a future test harness, or a REPL/notebook session), and
    # without this, a second call would silently reuse the first call's
    # leftover ":memory:" data — get_or_create() would double every gate
    # student's baseline sample count instead of starting fresh, corrupting
    # every gate's numbers without raising anything. This is exactly what
    # original/store.py's reset_memory_conn() exists to prevent; it's a
    # no-op on the file-backed path (see its docstring), so this line is
    # always safe regardless of ORIGINAL_DB.
    from original import store

    store.reset_memory_conn()

    os.environ["TYPICALITY_SCORING"] = "1"

    import run as _run_module  # the project's run.py at repo root — same
                                # convention as validation/public_authors/run.py:89,
                                # validation/verify/run.py:140, etc. Requires
                                # sys.path.insert(0, str(_ROOT)) above, already present.
    from fastapi.testclient import TestClient

    client = TestClient(_run_module.load_legacy_demo_app())

    results: list[GateResult] = []

    # G1: seminary + public_authors + Plato, LOO over whole documents.
    seminary_texts = _load_seminary_texts()
    public_authors_texts = _load_public_authors_baseline_texts()
    plato_texts = _load_plato_texts_by_dialogue()

    texts_by_id: dict[str, list[str]] = {**seminary_texts, **public_authors_texts, **plato_texts}
    (
        pooled_actions,
        per_corpus_actions,
        real_g1_deviations,
        real_g1_errors,
        real_g1_typicality_ns,
        _real_g1_drift_rejected,  # unused here — the real G1 leg keeps
        # treating a drift-rejection the same as any other error (see
        # _score_corpus_for_g1's docstring); only G5's shuffled-G1 leg
        # (run_g5) distinguishes it.
    ) = _score_corpus_for_g1(client, "g1", texts_by_id)

    # Per-entity PER-FOLD LOO count, keyed the same way as texts_by_id — see
    # _g1_entity_baseline_counts's docstring for the `- 1` rationale (FIX 1)
    # and why it's keyed off per_corpus_actions rather than texts_by_id
    # (FIX 5). FIX C: extracted to a standalone function so this conversion
    # is unit-tested directly (TestG1EntityBaselineCounts) rather than only
    # via already-decremented literals passed to evaluate_g1_fpr.
    entity_baseline_counts = _g1_entity_baseline_counts(texts_by_id, per_corpus_actions)

    # BOTH reachability sources are supplied, deliberately. They answer the
    # same question — can the conformal band fire at this N? — from different
    # evidence, and evaluate_g1_fpr's downgrade ORs them, so the more
    # pessimistic one wins:
    #   typicality_ns          observed per-fold typicality_n straight out of
    #                          each scoring payload, aggregated MIN (binding
    #                          weakest fold). The accurate source. Until this
    #                          merge nothing passed it in production, so it
    #                          annotated current_value and never reached the
    #                          verdict.
    #   entity_baseline_counts len(texts)-1 reconstructed per entity,
    #                          aggregated any-reachable. Less accurate, but it
    #                          is the ONLY signal when no fold reports a
    #                          typicality_n at all — the actions came from the
    #                          deviation path, so _reachability_block reports
    #                          observed=False and typicality_unreachable is
    #                          False by convention. Dropping it would leave
    #                          that case with no reachability check.
    g1_result = evaluate_g1_fpr(
        pooled_actions,
        per_corpus_actions,
        typicality_ns=real_g1_typicality_ns,
        entity_baseline_counts=entity_baseline_counts,
    )
    results.append(g1_result)

    # G2: bland impostor via q = min(p_far, p_central). A crash here (e.g.
    # _compute_g2_q_values's _require_healthy_leg call catching a dialogue
    # whose baseline uploads mostly failed) is a machinery failure, same
    # convention as G2b/G5/G6's wrappers.
    try:
        holdout_q, impostor_q, _g2_n_holdout_errors = _compute_g2_q_values(client)
        results.append(evaluate_g2_bland_impostor(holdout_q, impostor_q))
    except Exception as exc:  # noqa: BLE001 — see _machinery_error_result
        results.append(_machinery_error_result("G2", _G2_CRITERION, exc))

    # G2b: G2's criterion with uniformity features enabled (guarded window —
    # see _uniformity_features_enabled) and the ai_*.txt impostors run
    # through the mechanical paraphrase PROXY (_paraphrase_proxy; not an LLM
    # paraphrase — the proxy label travels in the criterion and detail).
    # A crash here is a machinery failure, same convention as G5's wrapper.
    try:
        g2b_holdout_q, g2b_impostor_q, g2b_stats = _compute_g2b_paraphrase_data(client)
        results.append(
            evaluate_g2b_paraphrase_resistant(
                g2b_holdout_q, g2b_impostor_q, informational=g2b_stats
            )
        )
    except Exception as exc:  # noqa: BLE001 — see _machinery_error_result
        results.append(_machinery_error_result("G2b", _G2B_CRITERION, exc))

    # G3: reuse the existing public_authors attribution accuracy computation.
    # validation/public_authors/run.py's run() returns a report dict shaped
    # {"summary": {"top1_accuracy": ..., ...}, "per_author": {...}, ...} —
    # NOT a flat "top1_accuracy" key (verified by reading run.py directly;
    # the original plan draft had not seen the real return shape). When the
    # corpus doesn't have >= 2 eligible authors, run() instead returns
    # {"error": ..., "skipped_authors": ...} with no "summary" key at all —
    # .get()-chain through that case rather than raising.
    from validation.public_authors.run import run as run_public_authors

    pa_report = run_public_authors()
    top1_accuracy, top1_accuracy_raw_argmin, n_essays = _g3_inputs_from_pa_report(pa_report)
    results.append(
        evaluate_g3_attribution(
            top1_accuracy,
            top1_accuracy_raw_argmin=top1_accuracy_raw_argmin,
            # "n_scored_essays" is the held-out essay count run.py actually
            # scored. It drives G3's informativeness check: at n=22 the Wilson
            # interval around a 0.727 accuracy straddles the 0.7 bar, so the
            # gate reports UNINFORMATIVE rather than banking the pass.
            n_essays=n_essays,
        )
    )

    # G4: Plato early/middle/late monotonicity. A crash here (e.g.
    # _compute_g4_group_means's _require_healthy_leg call catching a
    # mostly-failed early baseline upload) is a machinery failure, same
    # convention as G2b/G5/G6's wrappers.
    try:
        group_means, _g4_stats = _compute_g4_group_means()
        results.append(evaluate_g4_career_drift_monotone(group_means))
    except Exception as exc:  # noqa: BLE001 — see _machinery_error_result
        results.append(_machinery_error_result("G4", _G4_CRITERION, exc))

    # G5: permutation-null selection-bias control — seeded label shuffles,
    # then shuffled-label reruns of the G1/G3/G4 machinery above (see run_g5).
    # A crash inside the shuffled legs is a machinery failure: it must neither
    # discard the four completed real gates above nor read as a genuine null
    # verdict, so it renders as a failed ERROR-(machinery) result instead.
    try:
        results.append(
            run_g5(
                real_g1_deviations=real_g1_deviations,
                real_g1_flagged_rate=g1_result.detail["pooled_flagged_rate"],
                real_g1_n_errors=real_g1_errors,
            )
        )
    except Exception as exc:  # noqa: BLE001 — see _g5_machinery_error_result
        results.append(_g5_machinery_error_result(exc))

    # G6: native_english fairness on the p_central/too-uniform action, with
    # uniformity features enabled for its own leg. _compute_g6_fairness_data
    # returns the finished GateResult (evaluate, or a loud SKIPPED
    # insufficient-data result — never a silent pass); a crash is a
    # machinery failure, same convention as G5's wrapper.
    try:
        results.append(_compute_g6_fairness_data(client))
    except Exception as exc:  # noqa: BLE001 — see _machinery_error_result
        results.append(_machinery_error_result("G6", _G6_CRITERION, exc))

    # Attach a corpus_fingerprint to every result so a future report can be
    # checked for comparability against this one without re-deriving n's by
    # hand — see _corpus_fingerprint's docstring for why this exists. Built
    # from the corpora already loaded above (G6's is loaded fresh here since
    # it's a distinct manifest-driven corpus none of the other legs touch).
    corpus_fingerprints = {
        "seminary": _corpus_fingerprint(seminary_texts),
        "public_authors": _corpus_fingerprint(public_authors_texts),
        "plato": _corpus_fingerprint(plato_texts),
        "g6_native_english": _corpus_fingerprint(_load_g6_native_english_texts()),
    }
    result_corpus_keys = {
        "G1": ("seminary", "public_authors", "plato"),
        "G2": ("plato",),
        "G2b": ("plato",),
        "G3": ("public_authors",),
        "G4": ("plato",),
        "G5": ("seminary", "public_authors", "plato"),
        "G6": ("g6_native_english",),
    }
    for result in results:
        keys = result_corpus_keys.get(result.name)
        if not keys:
            continue
        if len(keys) == 1:
            result.detail["corpus_fingerprint"] = corpus_fingerprints[keys[0]]
        else:
            result.detail["corpus_fingerprint"] = {
                k: corpus_fingerprints[k] for k in keys
            }

    return results


def _load_seminary_texts() -> dict[str, list[str]]:
    corpus_dir = _ROOT / "validation" / "corpus"
    seminary_files = sorted(corpus_dir.glob("seminary_*.txt"))
    # Group by the pre-underscore-number topic prefix isn't right here;
    # seminary essays are single-author-simulated per file with no natural
    # per-author grouping — bucket every 4-5 sequential files as one
    # "student" to get the N>=5 LOO regime the spec's Problem section used
    # (310-460 word essays, 4-of-25 grouping). Concretely: chunk the sorted
    # file list into groups of 5.
    texts = [f.read_text(encoding="utf-8") for f in seminary_files]
    groups: dict[str, list[str]] = {}
    for i in range(0, len(texts) - 4, 5):
        groups[f"seminary_group_{i // 5}"] = texts[i : i + 5]
    return groups


def _load_public_authors_baseline_texts() -> dict[str, list[str]]:
    import json as _json

    manifest_path = _ROOT / "validation" / "public_authors" / "manifest.json"
    corpus_dir = _ROOT / "validation" / "public_authors" / "corpus"
    manifest = _json.loads(manifest_path.read_text())
    by_author: dict[str, list[str]] = {}
    for entry in manifest["entries"]:
        if not entry.get("is_baseline"):
            continue
        text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
        by_author.setdefault(entry["author_id"], []).append(text)
    return by_author


def _load_plato_texts_by_dialogue() -> dict[str, list[str]]:
    corpus_dir = _ROOT / "validation" / "plato" / "corpus" / "jowett"
    by_dialogue: dict[str, list[str]] = {}
    for dialogue_dir in sorted(corpus_dir.iterdir()):
        if not dialogue_dir.is_dir():
            continue
        chunks = sorted(dialogue_dir.glob("*.txt"))
        by_dialogue[f"plato_{dialogue_dir.name}"] = [
            c.read_text(encoding="utf-8") for c in chunks
        ]
    return by_dialogue


def _load_g6_native_english_texts() -> dict[str, list[str]]:
    """
    The native_english-annotated authentic corpus G6 actually scores (mirrors
    the entry/author bucketing _compute_g6_fairness_data does internally).
    Kept as its own loader purely so run_all() can fingerprint G6's corpus
    the same way it fingerprints seminary/public_authors/Plato, without
    reaching into that function's scoring internals.
    """
    manifest_path = _ROOT / "validation" / "manifest.json"
    corpus_dir = _ROOT / "validation" / "corpus"
    manifest = json.loads(manifest_path.read_text())
    by_author: dict[str, list[str]] = {}
    for entry in manifest["entries"]:
        if entry.get("native_english") is None or entry.get("label") != "authentic":
            continue
        text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
        by_author.setdefault(entry["author_id"], []).append(text)
    return by_author


def _corpus_fingerprint(texts_by_id: dict[str, list[str]]) -> str:
    """
    A short, order-independent fingerprint of a loaded corpus: hash the
    SORTED (entity_id, len(texts), total_chars) triple for every entity.

    This exists so a future corpus content change — a re-generated cache, an
    edited/added Plato chunk, a manifest.json edit — is flagged in the report
    itself instead of silently producing numbers that look comparable to a
    prior run but aren't. It hashes what the loader actually produced, so it
    WOULD catch that class of drift.

    It would NOT, on its own, have caught the specific 2026-07-28 vs
    2026-07-30 drift: `git diff` between the commits that produced those two
    reports shows zero changes to validation/plato/corpus/jowett/**, and
    TestCorpusDeterminism confirms the loader is already fully order-stable
    (sorted iterdir + sorted glob), so that drift's fingerprint would read
    identical on both runs. The actual divergence (G2's per-dialogue q-value
    denominators implying an effective n smaller than len(chunks)-1 on some
    runs) traced to _compute_g2_q_values's and _compute_g4_group_means's
    baseline-upload loops, which used to POST each baseline chunk without
    checking the response status — a dropped upload silently shrank that
    student's LOO sample count without touching anything on disk. Both loops
    now call _require_healthy_leg on their upload counts and fail loudly
    instead (see the Task 3 report for the original diagnosis). This
    fingerprint still would not catch a *future* instance of that class of
    scoring-time defect on its own — it only ever hashed corpus content, not
    what the scoring leg did with it — so a GateResult with a matching
    fingerprint is not, by itself, proof of a healthy scoring leg; it rules
    out corpus-content drift, and the health check above is what now rules
    out the sample-count drift.
    """
    triples = sorted(
        (entity_id, len(texts), sum(len(t) for t in texts))
        for entity_id, texts in texts_by_id.items()
    )
    payload = repr(triples).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _compute_g2_q_values(client) -> tuple[list[float], list[float], int]:
    """
    q = min(p_far, p_central) for genuine Plato holdouts vs. the Eryxias +
    synthetic-AI impostor pool.

    NOTE on the API response shape: original/schemas.py's Layer7OutputResponse
    puts typicality_p_far / typicality_p_central / typicality_band /
    typicality_n at the TOP LEVEL of the JSON body (siblings of "authorship",
    "recommendation", etc — see original/routers/_shared.py's _to_response()),
    not nested under a "typicality" sub-object. Both fields are None unless
    TYPICALITY_SCORING=1, adaptive weights are off, AND the scored student has
    >= 2 leave-one-out baseline distances (original/quantum/scoring.py's
    typicality block) — treat that as "no signal for this sample", not an
    error, and skip it.

    Returns (holdout_q, impostor_q, n_holdout_errors): n_holdout_errors
    counts per-dialogue holdout folds skipped because a baseline upload (or
    the score call itself) returned non-200 — same skip-and-count convention
    as _score_corpus_for_g1's n_errors. _require_healthy_leg is called once
    on the pooled holdout-leg counts (raises RuntimeError on an unhealthy
    leg) and, separately and more strictly, on the impostor leg's SHARED
    reference pool: that pool is built once and reused for every impostor
    score, so even a single failed baseline upload there poisons every
    subsequent impostor score in the leg, not just one fold — a "count and
    continue" policy would routinely stay under _require_healthy_leg's 10%
    pooled-error threshold while still contaminating 100% of the impostor
    q-values, so this raises immediately instead of accumulating an error
    count. Both raises are converted to a G2 "ERROR (machinery)" result by
    run_all()'s try/except (see _machinery_error_result), matching the
    convention G2b/G5/G6 already use.
    """
    holdout_q: list[float] = []
    n_holdout_errors = 0
    plato_dialogues = _load_plato_texts_by_dialogue()
    for dialogue, chunks in plato_dialogues.items():
        if "eryxias" in dialogue or len(chunks) < 5:
            continue
        sid = f"demo:gate_g2_{dialogue}"
        baseline_failed = False
        for chunk in chunks[:-1]:
            r = client.post(
                f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"}
            )
            if r.status_code != 200:
                baseline_failed = True
        if baseline_failed:
            # A fold whose baseline is known incomplete must not be scored
            # — see the module-level note on the 2026-07-28 vs 2026-07-30
            # drift and _score_corpus_for_g1's identical convention.
            n_holdout_errors += 1
            continue
        r = client.post(
            f"/students/{sid}/score",
            json={"text": chunks[-1], "submission_id": f"{dialogue}_holdout"},
        )
        if r.status_code == 200:
            payload = r.json()
            p_far_val = payload.get("typicality_p_far")
            p_central_val = payload.get("typicality_p_central")
            if p_far_val is not None and p_central_val is not None:
                holdout_q.append(min(p_far_val, p_central_val))
        else:
            n_holdout_errors += 1
    _require_healthy_leg("G2 holdout leg", n_success=len(holdout_q), n_errors=n_holdout_errors)

    impostor_q: list[float] = []
    eryxias_chunks = plato_dialogues.get("plato_eryxias", [])
    ai_corpus_dir = _ROOT / "validation" / "corpus"
    ai_texts = [p.read_text(encoding="utf-8") for p in sorted(ai_corpus_dir.glob("ai_*.txt"))]
    reference_dialogues = [
        c for name, chunks in plato_dialogues.items() if "eryxias" not in name for c in chunks
    ][:20]
    sid = "demo:gate_g2_impostor_reference"
    n_reference_baseline_errors = 0
    for chunk in reference_dialogues:
        r = client.post(
            f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"}
        )
        if r.status_code != 200:
            n_reference_baseline_errors += 1
    if n_reference_baseline_errors:
        raise RuntimeError(
            f"G2 impostor leg: {n_reference_baseline_errors}/{len(reference_dialogues)} "
            "shared reference-pool baseline uploads failed — every impostor score in "
            "this leg would be computed against a poisoned shared reference"
        )
    for text in eryxias_chunks + ai_texts:
        r = client.post(f"/students/{sid}/score", json={"text": text, "submission_id": "impostor"})
        if r.status_code == 200:
            payload = r.json()
            p_far_val = payload.get("typicality_p_far")
            p_central_val = payload.get("typicality_p_central")
            if p_far_val is not None and p_central_val is not None:
                impostor_q.append(min(p_far_val, p_central_val))

    return holdout_q, impostor_q, n_holdout_errors


# ── G2b / G6 — uniformity-enabled legs ─────────────────────────────────────────


@contextmanager
def _uniformity_features_enabled():
    """
    Context manager that enables the Tier-18 uniformity features for exactly
    one gate leg's scoring, then restores DISABLED_FEATURE_GROUPS to its
    EXACT prior state.

    Why the ceremony: DISABLED_FEATURE_GROUPS is a process-global
    module-level set that original/features/pipeline.py reads at feature-
    extraction CALL time — a leaked discard("uniformity") would silently
    change the feature vectors of every leg scored after it (and, in a test
    process, of every later test). The try/finally guarantees restoration
    even when a leg raises mid-run (e.g. _require_healthy_leg), and
    clear()+update(saved) restores the exact prior membership rather than
    guessing at add/discard inverses. Profiles CREATED while enabled carry
    real Tier-18 values and live in the shared :memory: store, so G2b/G6
    keep their own sid namespaces (demo:gate_g2b_*/demo:gate_g6_*) — no
    other leg ever scores against a uniformity-enabled profile.
    """
    from original.constants import DISABLED_FEATURE_GROUPS

    saved = set(DISABLED_FEATURE_GROUPS)
    DISABLED_FEATURE_GROUPS.discard("uniformity")
    try:
        yield
    finally:
        DISABLED_FEATURE_GROUPS.clear()
        DISABLED_FEATURE_GROUPS.update(saved)


# Fixed word-substitution table for the G2b paraphrase PROXY. Deliberately
# "elevate the language"-flavoured (the direction of the published attack),
# but mechanical: same table for every text, no randomness, no LLM.
_G2B_WORD_SUBSTITUTIONS: dict[str, str] = {
    "however": "nevertheless",
    "therefore": "consequently",
    "thus": "hence",
    "but": "yet",
    "because": "since",
    "also": "additionally",
    "important": "significant",
    "importance": "significance",
    "shows": "demonstrates",
    "show": "demonstrate",
    "showed": "demonstrated",
    "use": "utilize",
    "uses": "utilizes",
    "used": "utilized",
    "using": "utilizing",
    "make": "create",
    "makes": "creates",
    "made": "created",
    "many": "numerous",
    "big": "substantial",
    "good": "beneficial",
    "bad": "detrimental",
    "help": "assist",
    "helps": "assists",
    "think": "believe",
    "thinks": "believes",
    "very": "quite",
    "often": "frequently",
    "begin": "commence",
    "begins": "commences",
    "end": "conclude",
    "ends": "concludes",
    "idea": "notion",
    "ideas": "notions",
    "way": "manner",
    "ways": "manners",
    "people": "individuals",
}

_G2B_SUBSTITUTION_PATTERN = None  # compiled lazily by _paraphrase_proxy


def _paraphrase_proxy(text: str) -> str:
    """
    Deterministic paraphrase PROXY for G2b — a mechanical transformation,
    NOT an LLM paraphrase (see _G2B_PROXY_NOTE; the label is load-bearing).

    Two passes, both seed-free:
      1. Adjacent-sentence reordering WITHIN each paragraph — swap each
         adjacent pair (s1 s0 s3 s2 ...), never across a paragraph
         boundary. Paragraph separators and inter-sentence whitespace are
         carried through verbatim, so the transform perturbs discourse
         order without changing paragraph structure. An earlier version
         joined every sentence with a single space, collapsing each
         document to one paragraph; that moved avg_paragraph_length by
         ~0.77 normalized and forced two features to their "cannot
         compute" placeholder, which swamped the uniformity signal this
         gate exists to measure.
      2. Fixed-table word substitution (_G2B_WORD_SUBSTITUTIONS), case-
         insensitive match with initial-capital preservation — the
         "elevate the language" direction of the published attack, minus
         the LLM. Word count is preserved (every entry is 1->1); wording
         is not, so this is a perturbation, not a meaning-preserving
         rewrite. See _G2B_PROXY_NOTE for the measured limits.
    """
    import re

    global _G2B_SUBSTITUTION_PATTERN
    if _G2B_SUBSTITUTION_PATTERN is None:
        alternation = "|".join(
            sorted(_G2B_WORD_SUBSTITUTIONS, key=len, reverse=True)
        )
        _G2B_SUBSTITUTION_PATTERN = re.compile(rf"\b({alternation})\b", re.IGNORECASE)

    # Odd indices are the captured blank-line separators — reinserted
    # untouched so paragraph count and newline count survive the transform.
    blocks = re.split(r"(\n\s*\n)", text)
    for b, block in enumerate(blocks):
        if b % 2:  # a separator, not a paragraph
            continue
        # Odd indices here are the captured inter-sentence whitespace, which
        # stays in its original slot while the sentence texts move around it.
        parts = re.split(r"((?<=[.!?])\s+)", block)
        sentences = parts[0::2]
        for i in range(0, len(sentences) - 1, 2):
            sentences[i], sentences[i + 1] = sentences[i + 1], sentences[i]
        parts[0::2] = sentences
        blocks[b] = "".join(parts)
    reordered = "".join(blocks)

    def _substitute(match: "re.Match[str]") -> str:
        word = match.group(0)
        replacement = _G2B_WORD_SUBSTITUTIONS[word.lower()]
        if word[0].isupper():
            replacement = replacement[0].upper() + replacement[1:]
        return replacement

    return _G2B_SUBSTITUTION_PATTERN.sub(_substitute, reordered)


def _compute_g2b_paraphrase_data(client) -> tuple[list[float], list[float], dict]:
    """
    G2b leg: _compute_g2_q_values's machinery with (a) the Tier-18
    uniformity features enabled for the WHOLE leg — baselines and scoring
    alike, holdout and impostor alike, so both sides of the comparison are
    measured by the same instrument and no baseline is built with tier-18
    pinned at 0.5 while its submissions carry real values — and (b) the
    ai_*.txt impostors run through _paraphrase_proxy (the spec's G2b row
    scopes the paraphrase to the ai_*.txt essays; Eryxias is G2's concern).

    Fresh demo:gate_g2b_* sids keep the uniformity-enabled profiles this leg
    creates in the shared :memory: store from ever being scored by another
    leg. Returns (holdout_q, paraphrased_impostor_q, leg_stats); raises
    RuntimeError via _require_healthy_leg on an unhealthy leg, which
    run_all() renders as a failed ERROR-(machinery) G2b result.
    """
    holdout_q: list[float] = []
    paraphrased_impostor_q: list[float] = []
    n_holdout_errors = 0
    n_impostor_errors = 0
    n_null_typicality = 0

    plato_dialogues = _load_plato_texts_by_dialogue()
    ai_corpus_dir = _ROOT / "validation" / "corpus"
    ai_files = sorted(ai_corpus_dir.glob("ai_*.txt"))

    with _uniformity_features_enabled():
        for dialogue, chunks in plato_dialogues.items():
            if "eryxias" in dialogue or len(chunks) < 5:
                continue
            sid = f"demo:gate_g2b_{dialogue}"
            baseline_failed = False
            for chunk in chunks[:-1]:
                r = client.post(
                    f"/students/{sid}/baseline",
                    json={"text": chunk, "provenance": "verified"},
                )
                if r.status_code != 200:
                    baseline_failed = True
            if baseline_failed:
                # A fold whose baseline is known incomplete must not be
                # scored — see _score_corpus_for_g1's identical convention.
                n_holdout_errors += 1
                continue
            r = client.post(
                f"/students/{sid}/score",
                json={"text": chunks[-1], "submission_id": f"{dialogue}_holdout"},
            )
            if r.status_code == 200:
                payload = r.json()
                p_far_val = payload.get("typicality_p_far")
                p_central_val = payload.get("typicality_p_central")
                if p_far_val is not None and p_central_val is not None:
                    holdout_q.append(min(p_far_val, p_central_val))
                else:
                    n_null_typicality += 1
            else:
                n_holdout_errors += 1

        reference_dialogues = [
            c
            for name, chunks in plato_dialogues.items()
            if "eryxias" not in name
            for c in chunks
        ][:20]
        sid = "demo:gate_g2b_impostor_reference"
        n_reference_baseline_errors = 0
        for chunk in reference_dialogues:
            r = client.post(
                f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"}
            )
            if r.status_code != 200:
                n_reference_baseline_errors += 1
        if n_reference_baseline_errors:
            # Same reasoning as G2's impostor leg (_compute_g2_q_values):
            # ONE shared reference pool is reused for every paraphrased
            # impostor score in this leg, so a single failed baseline
            # upload poisons all of them, not just one fold — "skip and
            # count" would routinely stay under _require_healthy_leg's 10%
            # threshold while still contaminating every paraphrased_impostor_q
            # value. Raise immediately instead; run_all()'s existing
            # try/except around _compute_g2b_paraphrase_data already
            # converts this to a G2b "ERROR (machinery)" result.
            raise RuntimeError(
                f"G2b impostor leg: {n_reference_baseline_errors}/{len(reference_dialogues)} "
                "shared reference-pool baseline uploads failed — every paraphrased-impostor "
                "score in this leg would be computed against a poisoned shared reference"
            )
        for path in ai_files:
            paraphrased = _paraphrase_proxy(path.read_text(encoding="utf-8"))
            r = client.post(
                f"/students/{sid}/score",
                json={"text": paraphrased, "submission_id": f"g2b_{path.stem}"},
            )
            if r.status_code == 200:
                payload = r.json()
                p_far_val = payload.get("typicality_p_far")
                p_central_val = payload.get("typicality_p_central")
                if p_far_val is not None and p_central_val is not None:
                    paraphrased_impostor_q.append(min(p_far_val, p_central_val))
                else:
                    n_null_typicality += 1
            else:
                n_impostor_errors += 1

    _require_healthy_leg(
        "G2b holdout leg", n_success=len(holdout_q), n_errors=n_holdout_errors
    )
    _require_healthy_leg(
        "G2b paraphrased-impostor leg",
        n_success=len(paraphrased_impostor_q),
        n_errors=n_impostor_errors,
    )
    leg_stats = {
        "n_holdout": len(holdout_q),
        "n_paraphrased_impostors": len(paraphrased_impostor_q),
        "n_ai_files": len(ai_files),
        "n_holdout_scoring_errors": n_holdout_errors,
        "n_impostor_scoring_errors": n_impostor_errors,
        "n_null_typicality_skipped": n_null_typicality,
        "uniformity_enabled_during_leg": True,
    }
    return holdout_q, paraphrased_impostor_q, leg_stats


# G6 sample-size policy: a per-group rate from fewer than one author's worth
# of essays (5) is noise, so the gate SKIPs loudly below that; the plan's
# thin-coverage note (~20 per group) becomes a low-sample warning in detail,
# since today's manifest tops out at 15 native / 10 non-native.
_G6_MIN_PER_GROUP = 5
_G6_WARN_PER_GROUP = 20


def _compute_g6_fairness_data(client) -> GateResult:
    """
    G6 leg: score every native_english-annotated AUTHENTIC entry in
    validation/manifest.json leave-one-out within its author (baseline =
    the author's other annotated essays), read typicality_p_central off each
    response, threshold it against NO_ACTION_CENTRAL_THRESHOLD to get the
    per-entry too-uniform flag, and compare per-group flagged rates via
    evaluate_g6_fairness. Runs with the Tier-18 uniformity features enabled
    (same guarded window as G2b) because G6 exists to gate that family's
    fairness before it leaves DISABLED_FEATURE_GROUPS (spec §4/§8).

    Bridging (per the plan's Interfaces note): validation/benchmark/
    bias_slicer.slice_by and validation/bias_analysis._welch_t_test are
    called DIRECTLY on this leg's results — run_bias_analysis's dict-based
    input shape doesn't match bias_slicer's ScoringResult-based shape, so
    the gate constructs real ScoringResult rows itself. Both bridges are
    attach-only context in detail; the verdict is the 2x flagged-rate ratio.

    Returns the finished GateResult (evaluate/skip dispatch lives here, next
    to the data realities that decide it). Raises RuntimeError via
    _require_healthy_leg on an unhealthy scoring leg — a 4xx-riddled leg is
    a machinery failure, not "insufficient data".
    """
    import json as _json
    import time
    from dataclasses import asdict as _asdict

    import numpy as np

    from original.constants import TIER18_CODES
    from original.quantum.typicality import NO_ACTION_CENTRAL_THRESHOLD
    from validation.benchmark.bias_slicer import slice_by
    from validation.bias_analysis import _welch_t_test
    from validation.calibration import ScoringResult
    from validation.manifest_schema import AuthorshipLabel

    manifest_path = _ROOT / "validation" / "manifest.json"
    corpus_dir = _ROOT / "validation" / "corpus"
    manifest = _json.loads(manifest_path.read_text())
    entries = [
        e
        for e in manifest["entries"]
        if e.get("native_english") is not None and e.get("label") == "authentic"
    ]
    if not entries:
        return _g6_insufficient_data_result(
            "validation/manifest.json has no authentic entries with a "
            "native_english annotation",
            n_native_scored=0,
            n_non_native_scored=0,
        )

    by_author: dict[str, list[dict]] = {}
    for entry in entries:
        by_author.setdefault(entry["author_id"], []).append(entry)

    results_by_group: dict[bool, list[dict]] = {True: [], False: []}
    per_group_features: dict[bool, list[dict[str, float]]] = {True: [], False: []}
    scoring_rows: list[ScoringResult] = []
    n_errors = 0
    n_null_typicality = 0

    with _uniformity_features_enabled():
        for author_id, author_entries in sorted(by_author.items()):
            if len(author_entries) < 3:
                # Typicality needs >= 2 LOO baseline distances, so an author
                # needs >= 3 annotated essays for a LOO fold to carry signal.
                continue
            for held_out_idx, held_out in enumerate(author_entries):
                sid = f"demo:gate_g6_{author_id}_{held_out_idx}"
                baseline_failed = False
                for i, other in enumerate(author_entries):
                    if i == held_out_idx:
                        continue
                    r = client.post(
                        f"/students/{sid}/baseline",
                        json={
                            "text": (corpus_dir / other["filename"]).read_text(
                                encoding="utf-8"
                            ),
                            "provenance": "verified",
                        },
                    )
                    if r.status_code != 200:
                        baseline_failed = True
                if baseline_failed:
                    # A fold whose baseline is known incomplete must not be
                    # scored — see _score_corpus_for_g1's identical
                    # convention.
                    n_errors += 1
                    continue
                t0 = time.perf_counter()
                r = client.post(
                    f"/students/{sid}/score",
                    json={
                        "text": (corpus_dir / held_out["filename"]).read_text(
                            encoding="utf-8"
                        ),
                        "submission_id": f"g6_{held_out['filename']}",
                    },
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                if r.status_code != 200:
                    n_errors += 1
                    continue
                payload = r.json()
                p_central = payload.get("typicality_p_central")
                typicality_n = int(payload.get("typicality_n", 0))
                if p_central is None:
                    # "No signal for this sample", not an error — see
                    # _compute_g2_q_values's response-shape note.
                    n_null_typicality += 1
                    continue
                results_by_group[bool(held_out["native_english"])].append(
                    {
                        "filename": held_out["filename"],
                        "p_central": float(p_central),
                        "typicality_n": typicality_n,
                        "flagged": p_central <= NO_ACTION_CENTRAL_THRESHOLD,
                    }
                )
                tier18_values = {
                    c: float(payload["feature_vector"][c]) for c in TIER18_CODES
                }
                per_group_features[bool(held_out["native_english"])].append(tier18_values)
                scoring_rows.append(
                    ScoringResult(
                        filename=held_out["filename"],
                        author_id=author_id,
                        label=AuthorshipLabel.AUTHENTIC,
                        deviation_score=float(
                            payload["authorship"]["deviation_score"]
                        ),
                        authorship_probability=float(
                            payload["authorship"]["authorship_probability"]
                        ),
                        recommended_action=payload["recommendation"]["action"],
                        is_same_author=True,
                        word_count=int(held_out.get("word_count", 0)),
                        scoring_time_ms=elapsed_ms,
                    )
                )

    n_scored = sum(len(v) for v in results_by_group.values())
    _require_healthy_leg("G6 native_english leg", n_success=n_scored, n_errors=n_errors)

    n_native = len(results_by_group[True])
    n_non_native = len(results_by_group[False])
    if n_native < _G6_MIN_PER_GROUP or n_non_native < _G6_MIN_PER_GROUP:
        return _g6_insufficient_data_result(
            _g6_short_group_message(n_native, n_non_native, _G6_MIN_PER_GROUP),
            n_native_scored=n_native,
            n_non_native_scored=n_non_native,
        )

    # The vacuous-pass guard: on an unreachable-threshold sample (e.g. 5
    # essays/author LOO -> typicality_n=4 everywhere), a 0% flagged rate in
    # both groups is structural, not evidence of fairness — check this
    # AFTER the short-group check (an unreachable threshold on a
    # healthy-sized sample is a more specific diagnosis than "insufficient
    # data") but BEFORE computing the flagged rates the rest of this
    # function would otherwise treat as a real measurement.
    reachability_skip = _g6_reachability_precheck(
        results_by_group,
        NO_ACTION_CENTRAL_THRESHOLD,
        n_native_scored=n_native,
        n_non_native_scored=n_non_native,
    )
    if reachability_skip is not None:
        return reachability_skip

    native_fpr = sum(1 for x in results_by_group[True] if x["flagged"]) / n_native
    non_native_fpr = (
        sum(1 for x in results_by_group[False] if x["flagged"]) / n_non_native
    )

    # Bridged context (attach-only, never gated): the standard bias-audit
    # slice on deviation scores, and Welch's t on the p_central samples the
    # verdict actually thresholds.
    manifest_lookup = {e["filename"]: e for e in entries}
    bias_slices = [
        _asdict(s)
        for s in slice_by(scoring_rows, "native_english", manifest_lookup=manifest_lookup)
    ]
    welch = _asdict(
        _welch_t_test(
            np.array([x["p_central"] for x in results_by_group[True]]),
            np.array([x["p_central"] for x in results_by_group[False]]),
            "native_english=true",
            "native_english=false",
        )
    )

    uniformity_summary = _uniformity_slice_summary(per_group_features)

    informational = {
        "n_native_scored": n_native,
        "n_non_native_scored": n_non_native,
        "n_scoring_errors": n_errors,
        "n_null_typicality_skipped": n_null_typicality,
        "flag_rule": f"typicality_p_central <= {NO_ACTION_CENTRAL_THRESHOLD}",
        "uniformity_enabled_during_leg": True,
        "bias_slices_deviation_score": bias_slices,
        "welch_t_on_p_central": welch,
        "uniformity_slice": uniformity_summary,
    }
    if n_native < _G6_WARN_PER_GROUP or n_non_native < _G6_WARN_PER_GROUP:
        informational["low_sample_warning"] = (
            f"fewer than {_G6_WARN_PER_GROUP} scored entries per group "
            f"(native={n_native}, non_native={n_non_native}) — the manifest's "
            "native_english coverage is thin (25/807 entries annotated); "
            "treat the ratio as a screening number, not a precise estimate"
        )
    return evaluate_g6_fairness(
        native_fpr,
        non_native_fpr,
        informational=informational,
        welch_effect_magnitude=welch["effect_magnitude"],
        welch_cohens_d=welch["cohens_d"],
    )


def _compute_g6_fairness_data_pooled(client) -> GateResult:
    """Pooled-calibration variant of _compute_g6_fairness_data: same corpus,
    same per-author LOO fold structure, same Tier-18 uniformity window, same
    bias-audit bridging -- the only change is that each held-out fold's
    typicality band comes from original.quantum.scoring.score() called
    DIRECTLY (typicality_pooled_calibration=True, pooled_states = every
    OTHER author's own pool-reference state) instead of the live /score
    endpoint, for the same reason _score_corpus_for_g1_pooled bypasses it
    (original/routers/students_scoring.py never threads pooled_states into
    quantum_score() -- see that function's docstring for the full
    verification).

    No cross-corpus segregation is needed here, unlike G1: every entry in
    this corpus comes from _load_g6_native_english_texts's single
    homogeneous seminary population (5 authors, 5 essays each -- see the
    module docstring / Task 9 brief), so pooling across every OTHER author
    is the correct scope by construction, not an approximation.
    _pool_peers_for_entity is still reused (with every author mapped to one
    constant group label) purely to inherit its already-tested
    "always exclude the entity itself" guarantee from a single code path
    shared with G1's real segregation logic, rather than reimplementing
    self-exclusion here.
    """
    import json as _json
    import time
    from dataclasses import asdict as _asdict
    from dataclasses import replace as _replace

    import numpy as np

    from original import store
    from original.constants import TIER18_CODES
    from original.features.pipeline import extract_features, feature_vector
    from original.quantum.scoring import ScoringConfig
    from original.quantum.scoring import score as quantum_score
    from original.quantum.typicality import NO_ACTION_CENTRAL_THRESHOLD
    from validation.benchmark.bias_slicer import slice_by
    from validation.bias_analysis import _welch_t_test
    from validation.calibration import ScoringResult
    from validation.manifest_schema import AuthorshipLabel

    manifest_path = _ROOT / "validation" / "manifest.json"
    corpus_dir = _ROOT / "validation" / "corpus"
    manifest = _json.loads(manifest_path.read_text())
    entries = [
        e
        for e in manifest["entries"]
        if e.get("native_english") is not None and e.get("label") == "authentic"
    ]
    if not entries:
        return _g6_insufficient_data_result(
            "validation/manifest.json has no authentic entries with a "
            "native_english annotation",
            n_native_scored=0,
            n_non_native_scored=0,
        )

    by_author: dict[str, list[dict]] = {}
    for entry in entries:
        by_author.setdefault(entry["author_id"], []).append(entry)

    # Single homogeneous group -- see the docstring above.
    group_of = {author_id: "g6" for author_id in by_author}
    base_config = _replace(ScoringConfig.from_env(), typicality_pooled_calibration=True)

    results_by_group: dict[bool, list[dict]] = {True: [], False: []}
    per_group_features: dict[bool, list[dict[str, float]]] = {True: [], False: []}
    scoring_rows: list[ScoringResult] = []
    n_errors = 0
    n_null_typicality = 0
    calibration_mode_counts: dict[str, int] = {"pooled": 0, "self": 0, "none": 0}

    with _uniformity_features_enabled():
        # One full-baseline pool-reference state per author (same >= 3
        # participation bar the LOO loop below applies), built BEFORE any
        # fold is scored, so every fold's pool is the fixed "every other
        # author" set -- see _build_pool_reference_states's docstring for
        # why a peer's reference is never leave-one-out reduced.
        pool_reference_states: dict[str, object] = {}
        n_poolref_attempts = 0
        n_poolref_errors = 0
        for author_id, author_entries in sorted(by_author.items()):
            if len(author_entries) < 3:
                continue
            poolref_sid = f"demo:gate_g6pooled_{author_id}_poolref"
            for entry in author_entries:
                n_poolref_attempts += 1
                r = client.post(
                    f"/students/{poolref_sid}/baseline",
                    json={
                        "text": (corpus_dir / entry["filename"]).read_text(encoding="utf-8"),
                        "provenance": "verified",
                    },
                )
                if r.status_code != 200:
                    n_poolref_errors += 1
            state = store.get(poolref_sid)
            if state is not None:
                pool_reference_states[author_id] = state
        _require_healthy_leg(
            "G6 pooled pool-reference build",
            n_success=n_poolref_attempts - n_poolref_errors,
            n_errors=n_poolref_errors,
        )

        for author_id, author_entries in sorted(by_author.items()):
            if len(author_entries) < 3:
                continue
            peer_states = _pool_peers_for_entity(author_id, group_of, pool_reference_states)
            for held_out_idx, held_out in enumerate(author_entries):
                sid = f"demo:gate_g6pooled_{author_id}_{held_out_idx}"
                baseline_failed = False
                for i, other in enumerate(author_entries):
                    if i == held_out_idx:
                        continue
                    r = client.post(
                        f"/students/{sid}/baseline",
                        json={
                            "text": (corpus_dir / other["filename"]).read_text(
                                encoding="utf-8"
                            ),
                            "provenance": "verified",
                        },
                    )
                    if r.status_code != 200:
                        baseline_failed = True
                if baseline_failed:
                    n_errors += 1
                    continue

                own_state = store.get(sid)
                if own_state is None:
                    n_errors += 1
                    continue

                held_out_text = (corpus_dir / held_out["filename"]).read_text(
                    encoding="utf-8"
                )
                feat_dict = extract_features(held_out_text)
                vec = feature_vector(held_out_text)

                t0 = time.perf_counter()
                result = quantum_score(
                    state=own_state,
                    submission_vector=vec,
                    feature_dict=feat_dict,
                    submission_id=f"g6pooled_{held_out['filename']}",
                    scoring_config=base_config,
                    pooled_states=peer_states,
                    student_id=sid,
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000.0

                mode = result.typicality_calibration or "none"
                calibration_mode_counts[mode] = calibration_mode_counts.get(mode, 0) + 1
                p_central = result.typicality_p_central
                typicality_n = int(result.typicality_n)
                if p_central is None:
                    n_null_typicality += 1
                    continue
                results_by_group[bool(held_out["native_english"])].append(
                    {
                        "filename": held_out["filename"],
                        "p_central": float(p_central),
                        "typicality_n": typicality_n,
                        "flagged": p_central <= NO_ACTION_CENTRAL_THRESHOLD,
                    }
                )
                tier18_values = {c: float(feat_dict[c]) for c in TIER18_CODES if c in feat_dict}
                per_group_features[bool(held_out["native_english"])].append(tier18_values)
                scoring_rows.append(
                    ScoringResult(
                        filename=held_out["filename"],
                        author_id=author_id,
                        label=AuthorshipLabel.AUTHENTIC,
                        deviation_score=float(result.authorship.deviation_score),
                        authorship_probability=float(result.authorship.authorship_probability),
                        recommended_action=result.recommendation.action,
                        is_same_author=True,
                        word_count=int(held_out.get("word_count", 0)),
                        scoring_time_ms=elapsed_ms,
                    )
                )

    n_scored = sum(len(v) for v in results_by_group.values())
    _require_healthy_leg("G6 pooled native_english leg", n_success=n_scored, n_errors=n_errors)

    n_native = len(results_by_group[True])
    n_non_native = len(results_by_group[False])
    if n_native < _G6_MIN_PER_GROUP or n_non_native < _G6_MIN_PER_GROUP:
        return _g6_insufficient_data_result(
            _g6_short_group_message(n_native, n_non_native, _G6_MIN_PER_GROUP),
            n_native_scored=n_native,
            n_non_native_scored=n_non_native,
            extra_detail={"calibration_mode_counts": calibration_mode_counts},
        )

    reachability_skip = _g6_reachability_precheck(
        results_by_group,
        NO_ACTION_CENTRAL_THRESHOLD,
        n_native_scored=n_native,
        n_non_native_scored=n_non_native,
    )
    if reachability_skip is not None:
        reachability_skip.detail["calibration_mode_counts"] = calibration_mode_counts
        return reachability_skip

    native_fpr = sum(1 for x in results_by_group[True] if x["flagged"]) / n_native
    non_native_fpr = (
        sum(1 for x in results_by_group[False] if x["flagged"]) / n_non_native
    )

    manifest_lookup = {e["filename"]: e for e in entries}
    bias_slices = [
        _asdict(s)
        for s in slice_by(scoring_rows, "native_english", manifest_lookup=manifest_lookup)
    ]
    welch = _asdict(
        _welch_t_test(
            np.array([x["p_central"] for x in results_by_group[True]]),
            np.array([x["p_central"] for x in results_by_group[False]]),
            "native_english=true",
            "native_english=false",
        )
    )

    uniformity_summary = _uniformity_slice_summary(per_group_features)

    informational = {
        "n_native_scored": n_native,
        "n_non_native_scored": n_non_native,
        "n_scoring_errors": n_errors,
        "n_null_typicality_skipped": n_null_typicality,
        "flag_rule": f"typicality_p_central <= {NO_ACTION_CENTRAL_THRESHOLD}",
        "uniformity_enabled_during_leg": True,
        "calibration_mode": "pooled (direct score() call -- see docstring)",
        "calibration_mode_counts": calibration_mode_counts,
        "bias_slices_deviation_score": bias_slices,
        "welch_t_on_p_central": welch,
        "uniformity_slice": uniformity_summary,
    }
    if n_native < _G6_WARN_PER_GROUP or n_non_native < _G6_WARN_PER_GROUP:
        informational["low_sample_warning"] = (
            f"fewer than {_G6_WARN_PER_GROUP} scored entries per group "
            f"(native={n_native}, non_native={n_non_native}) — the manifest's "
            "native_english coverage is thin (25/807 entries annotated); "
            "treat the ratio as a screening number, not a precise estimate"
        )
    return evaluate_g6_fairness(
        native_fpr,
        non_native_fpr,
        informational=informational,
        welch_effect_magnitude=welch["effect_magnitude"],
        welch_cohens_d=welch["cohens_d"],
    )


def _compute_g4_group_means(
    plato_texts: dict[str, list[str]] | None = None,
    sid: str = "demo:gate_g4_early_baseline",
    score_early_loo: bool = False,
    client=None,
) -> tuple[dict[str, float], dict[str, int]]:
    """
    `client` defaults to a fresh real TestClient (production behaviour,
    unchanged); tests may inject a fake one scoped to what this function
    calls (.post(url, json=...) -> an object with .status_code/.json()) to
    unit-test the early-baseline health check below without standing up the
    real app.

    Defaults reproduce the real G4 leg exactly. run_g5() passes a
    label-shuffled `plato_texts` dict plus a DIFFERENT `sid` per draw: the
    store is a process-wide :memory: database, so reusing the real G4 sid on
    a later call would silently stack the shuffled early-group baselines on
    top of the real ones instead of starting a fresh student.

    score_early_loo (G5's shuffled draws pass True): with the default False,
    every early chunk is scored against a baseline that CONTAINS it, so the
    early group is near-guaranteed the lowest mean by construction — even
    under shuffled labels — and "monotone" degenerates to the single
    comparison P(middle <= late) ~= 1/2 per draw, which no majority-of-K
    vote can improve (at p=0.5, majority-of-3 is still 0.5). With True, the
    early chunks are scored held-out via 2-fold cross-fit: the group is
    split into alternating halves, and each half is scored against a fresh
    student (sid "{sid}_loo_a"/"{sid}_loo_b") whose baseline is the OTHER
    half — so no chunk is ever scored against a baseline containing it, and
    under the null all three groups' scores are draws from (approximately —
    the cross-fit baseline is half-sized, but deviation_score is
    self-normalized against the profile's own spread, so baseline size
    barely shifts its distribution) the same distribution. The three group
    means become exchangeable, P(a draw comes out monotone by chance) drops
    to ~1/6, and majority-of-3 non-monotone detects a genuine null with
    ~0.93 probability. Cross-fit rather than per-chunk LOO is a cost
    decision, not a statistical one: the shuffled early group runs ~100
    chunks, so per-chunk LOO would need E*(E-1) ~= 9,900 baseline uploads
    per draw (hours of feature extraction), while cross-fit re-uploads each
    early chunk exactly once (~100 posts) and leaves the score-call count
    unchanged. The REAL G4 leg keeps False: there, early-in-baseline is the
    intended anchor semantics ("distance from the early-period profile").

    Returns (group_means, {"n_scored": int, "n_errors": int}); the stats let
    G5 distinguish "genuinely non-monotone" from "NaN means because every
    score call 4xx'd" (see _require_healthy_leg). The real G4 evaluator
    ignores them.
    """
    from validation.plato.chronology import GROUP_NAMES, ranked

    dialogues = ranked()
    if plato_texts is None:
        plato_texts = _load_plato_texts_by_dialogue()
    groups = {"early": [], "middle": [], "late": []}
    for d in dialogues:
        if d.group is None:
            continue  # excluded from chronology (e.g. Eryxias, spurious=True)
        group_key = GROUP_NAMES[d.group]
        groups[group_key].extend(plato_texts.get(f"plato_{d.slug}", []))
    # Baseline built from the "early" group; score middle and late against it.
    if client is None:
        from fastapi.testclient import TestClient

        import run as _run_module  # repo-root run.py — see run_all()'s identical import

        client = TestClient(_run_module.load_legacy_demo_app())
    n_baseline_errors = 0
    for chunk in groups["early"]:
        r = client.post(
            f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"}
        )
        if r.status_code != 200:
            n_baseline_errors += 1
    # A dropped upload here silently shrinks the early-group baseline that
    # middle/late (and, with score_early_loo, early's own cross-fit halves)
    # are scored against, without touching anything on disk — see
    # _corpus_fingerprint's docstring for the reproducibility bug this class
    # of defect was traced to for G2. _require_healthy_leg fails loudly
    # instead of letting that pass unnoticed.
    _require_healthy_leg(
        "G4 early baseline upload",
        n_success=len(groups["early"]) - n_baseline_errors,
        n_errors=n_baseline_errors,
    )

    means = {}
    n_scored = 0
    n_errors = 0
    for group_key in ("early", "middle", "late"):
        devs = []
        if group_key == "early" and score_early_loo:
            early_chunks = groups["early"]
            half_a, half_b = early_chunks[0::2], early_chunks[1::2]
            for half_tag, held_out, baseline_pool in (
                ("a", half_a, half_b),
                ("b", half_b, half_a),
            ):
                loo_sid = f"{sid}_loo_{half_tag}"
                n_half_baseline_errors = 0
                for other in baseline_pool:
                    r = client.post(
                        f"/students/{loo_sid}/baseline",
                        json={"text": other, "provenance": "verified"},
                    )
                    if r.status_code != 200:
                        n_half_baseline_errors += 1
                # Same shared-sub-pool reasoning as the early-baseline check
                # above, at half-scale: baseline_pool is reused for every
                # held_out chunk scored in THIS half, so a dropped upload
                # here undersizes every one of that half's scores, not just
                # one fold.
                _require_healthy_leg(
                    f"G4 cross-fit baseline upload ({half_tag})",
                    n_success=len(baseline_pool) - n_half_baseline_errors,
                    n_errors=n_half_baseline_errors,
                )
                for chunk in held_out:
                    r = client.post(
                        f"/students/{loo_sid}/score",
                        json={"text": chunk, "submission_id": "early_loo"},
                    )
                    if r.status_code == 200:
                        devs.append(r.json()["authorship"]["deviation_score"])
                    else:
                        n_errors += 1
        else:
            for chunk in groups[group_key]:
                r = client.post(
                    f"/students/{sid}/score", json={"text": chunk, "submission_id": group_key}
                )
                if r.status_code == 200:
                    devs.append(r.json()["authorship"]["deviation_score"])
                else:
                    n_errors += 1
        n_scored += len(devs)
        means[group_key] = sum(devs) / len(devs) if devs else float("nan")
    return means, {"n_scored": n_scored, "n_errors": n_errors}


# ── G5 — permutation-null orchestration ────────────────────────────────────────
#
# One seeded label shuffle (seed 1730 by default — BENCHMARK_SEED + 1, so the
# shuffle is decorrelated from the scoring-stack seed lock_environment() sets),
# three shuffled-label reruns of the SAME machinery the real gates use, then
# the pure evaluate_g5_permutation_null() on the three collapsed metrics.
#
# Per the plan (Task 13) the shuffle is a PLAIN permutation, not a derangement:
# fixed points (a label mapped back to its own texts) are acceptable noise at
# this corpus size — they can only push the shuffled metrics TOWARD "real
# signal", i.e. toward a G5 failure, so they never mask circularity.


def _shuffle_value_lists_across_keys(
    texts_by_id: dict[str, list[str]], rng
) -> dict[str, list[str]]:
    """
    Label shuffle at the whole-list level: key N gets key M's entire text
    list for a seeded random permutation over sorted keys ("student N's
    baseline is built from student M's texts"). Used for the G4 and G3
    shuffled legs, where the KEY carries meaning beyond a student id
    (chronology group membership / attribution identity).
    """
    keys = sorted(texts_by_id)
    perm = rng.permutation(len(keys))
    return {keys[i]: texts_by_id[keys[int(perm[i])]] for i in range(len(keys))}


def _shuffle_documents_across_keys(
    texts_by_id: dict[str, list[str]], rng
) -> dict[str, list[str]]:
    """
    Label shuffle at the document level: flatten every (key, text) pair over
    sorted keys, permute the texts with the seeded rng, and re-bucket them
    into the original keys' list LENGTHS.

    Why not _shuffle_value_lists_across_keys for the G1 leg: G1's LOO scorer
    (_score_corpus_for_g1) pairs baseline and held-out text from the SAME
    value list and uses the key only to name the student id, so permuting
    whole lists across keys re-measures the real G1 leg exactly — it is not
    a shuffled-label rerun at all. Destroying the label→document assignment
    itself is what makes the null genuine: each pseudo-student's baseline
    becomes a cross-author grab-bag and its held-out document is (almost
    surely) by a different author, so a pipeline with real authorship signal
    must flag far more than the calibrated ~5%.
    """
    keys = sorted(texts_by_id)
    all_docs = [t for k in keys for t in texts_by_id[k]]
    perm = rng.permutation(len(all_docs))
    shuffled_docs = [all_docs[int(i)] for i in perm]
    out: dict[str, list[str]] = {}
    pos = 0
    for k in keys:
        n = len(texts_by_id[k])
        out[k] = shuffled_docs[pos : pos + n]
        pos += n
    return out


def _require_healthy_leg(leg: str, *, n_success: int, n_errors: int) -> None:
    """
    Trivial-pass guard for any scoring leg (G5's shuffled legs, where an
    all-errors leg produces numbers that READ as "collapsed to chance" —
    n=0 -> G1 rate 1.0; G3 error dict -> accuracy 0.0; all-4xx G4 -> NaN
    means -> non-monotone — silently converting a machinery failure into a
    G5 pass; likewise G2b's and G6's legs, where an all-errors leg would
    gate on empty or skewed samples). Zero successful folds or a >10%
    scoring-error rate raises RuntimeError, which run_all() renders as a
    failed ERROR-(machinery) result (_machinery_error_result). `leg` should
    carry the gate name (e.g. "G5 shuffled G1 leg") since it becomes the
    error message's prefix.
    """
    if n_success == 0:
        raise RuntimeError(f"{leg}: zero successful scoring folds")
    total = n_success + n_errors
    if n_errors / total > 0.10:
        raise RuntimeError(f"{leg}: {n_errors}/{total} scoring calls failed (>10%)")


def _shuffled_public_authors_top1(rng) -> tuple[float, dict]:
    """
    G3 shuffled leg: rerun the FULL public_authors attribution machinery
    (validation/public_authors/run.py — baselines, impostor reference
    distributions, calibrated argmin) with author labels shuffled at the
    corpus-manifest level: each author keeps their own held-out (scored)
    essays but receives another author's ENTIRE baseline-document list,
    via a seeded permutation over sorted author ids.

    Mechanically: write a temp manifest whose baseline entries are
    re-assigned across authors, prefix every author_id with "g5perm_" so the
    rerun's student ids (demo:pa_g5perm_*) can never collide with the real
    G3 run's demo:pa_* students in the process-wide :memory: store, and call
    run() with report artifacts routed to a temp dir (removed in a finally).
    Eligibility rules (>= 3 baseline docs etc.) are applied by run() itself
    to the SHUFFLED assignment, same as the real run applies them to the
    real one.

    Returns (top1_accuracy, informational dict). Unlike the real G3 wiring's
    .get chain, an error report or a >10% per-essay scoring failure rate
    raises RuntimeError here: on this leg a silent 0.0 would read as
    "collapsed to chance" and fake a G5 pass (see _require_healthy_leg).
    """
    import json as _json
    import shutil
    import tempfile
    from collections import defaultdict

    from validation.public_authors.run import run as run_public_authors

    manifest_path = _ROOT / "validation" / "public_authors" / "manifest.json"
    corpus_dir = _ROOT / "validation" / "public_authors" / "corpus"
    manifest = _json.loads(manifest_path.read_text())

    baseline_entries: dict[str, list[dict]] = defaultdict(list)
    scored_entries: dict[str, list[dict]] = defaultdict(list)
    for entry in manifest["entries"]:
        (baseline_entries if entry.get("is_baseline") else scored_entries)[
            entry["author_id"]
        ].append(entry)

    author_ids = sorted(set(baseline_entries) | set(scored_entries))
    perm = rng.permutation(len(author_ids))

    shuffled_entries: list[dict] = []
    for i, aid in enumerate(author_ids):
        donor = author_ids[int(perm[i])]
        for entry in baseline_entries.get(donor, []):
            shuffled_entries.append({**entry, "author_id": f"g5perm_{aid}"})
        for entry in scored_entries.get(aid, []):
            shuffled_entries.append({**entry, "author_id": f"g5perm_{aid}"})

    tmp_dir = Path(tempfile.mkdtemp(prefix="gate_g5_public_authors_"))
    try:
        shuffled_manifest_path = tmp_dir / "manifest.json"
        shuffled_manifest_path.write_text(
            _json.dumps({**manifest, "entries": shuffled_entries}, indent=2)
        )
        report = run_public_authors(
            manifest_path=shuffled_manifest_path,
            corpus_dir=corpus_dir,
            report_dir=tmp_dir / "report",
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if "summary" not in report:
        raise RuntimeError(
            f"G5 shuffled G3 leg: public_authors rerun errored: "
            f"{report.get('error', 'no summary in report')}"
        )
    essays = report.get("results", [])
    n_essay_errors = sum(1 for e in essays if e.get("error"))
    _require_healthy_leg(
        "G5 shuffled G3 leg",
        n_success=len(essays) - n_essay_errors,
        n_errors=n_essay_errors,
    )
    info = {
        "shuffled_g3_n_essays": len(essays),
        "shuffled_g3_n_scoring_errors": n_essay_errors,
        "shuffled_g3_n_eligible_authors": report["summary"].get("n_eligible_authors"),
        "shuffled_g3_attribution_method": report["summary"].get("attribution_method"),
    }
    return report["summary"]["top1_accuracy"], info


def run_g5(
    real_g1_deviations: list[float],
    real_g1_flagged_rate: float | None = None,
    real_g1_n_errors: int = 0,
    seed: int = 1730,
) -> GateResult:
    """
    G5 orchestration — seeded label shuffles, then shuffled-label reruns of
    the G1/G3/G4 machinery, then the pure evaluate_g5_permutation_null().
    All the expensive shuffled scoring happens here, exactly once per gate
    run; the verdict stays a pure function of the collapsed metrics.

    Args:
        real_g1_deviations: pooled per-fold deviation_scores from the REAL G1
            leg (run_all() forwards _score_corpus_for_g1's third return) —
            the comparison point for the G1-leg deviation-shift criterion.
        real_g1_flagged_rate: the real leg's flagged rate, attached to detail
            as context only (see the evaluator's docstring on why flagged
            rates are never gated here).
        real_g1_n_errors: the real leg's non-200 score-call count — the
            anchor is health-checked exactly like the shuffled legs, because
            a 4xx-riddled anchor is a machinery failure, not a weakened
            comparison baseline.
        seed: one np.random.default_rng(seed) instance drives every shuffle,
            consumed in a fixed order — G1 document shuffle, then the G3
            author permutation, then the three G4 dialogue-list permutations
            (draws 0, 1, 2) — so the whole gate reproduces from this single
            seed. 1730 = BENCHMARK_SEED + 1, decorrelated from the
            scoring-stack seed lock_environment() sets.

    Raises:
        RuntimeError: when any shuffled leg fails the machinery-health guard
            (_require_healthy_leg), or real_g1_deviations is empty. run_all()
            converts this into a failed "ERROR (machinery)" G5 result rather
            than letting it read as a genuine null verdict.

    NOTE vs. the original Task-13 plan text: weights are NOT re-derived via
    scripts.derive_measured_weights here — the gates as they exist today
    score through the production pipeline directly, so the faithful null is
    a label-shuffled rerun of the same three scoring legs (the plan's Step-3
    wiring note), not a weight re-derivation.
    """
    import statistics

    if not real_g1_deviations:
        raise RuntimeError(
            "G5: the real G1 leg produced zero deviation samples — nothing to "
            "compare the shuffled leg against"
        )
    _require_healthy_leg(
        "G5 real G1 anchor leg",
        n_success=len(real_g1_deviations),
        n_errors=real_g1_n_errors,
    )

    import numpy as np

    rng = np.random.default_rng(seed)

    os.environ["TYPICALITY_SCORING"] = "1"  # same contract as run_all()

    import run as _run_module  # repo-root run.py — see run_all()'s identical import
    from fastapi.testclient import TestClient

    client = TestClient(_run_module.load_legacy_demo_app())

    # Shuffled G1: same merged corpus, same LOO scorer, document-level label
    # shuffle (see _shuffle_documents_across_keys docstring for why not the
    # list-level shuffle here). The "g5" sid prefix keeps these pseudo-students
    # distinct from the real G1 leg's in the process-wide :memory: store.
    # The criterion input is the MEAN DEVIATION, not the flagged rate — see
    # evaluate_g5_permutation_null's docstring for why the conformal floor
    # makes the rate uninformative at this corpus size; both rates still
    # travel in detail as context.
    texts_by_id: dict[str, list[str]] = {
        **_load_seminary_texts(),
        **_load_public_authors_baseline_texts(),
        **_load_plato_texts_by_dialogue(),
    }
    shuffled_g1_corpus = _shuffle_documents_across_keys(texts_by_id, rng)
    s_actions, s_per_corpus, s_deviations, s_errors, _, s_drift_rejected = _score_corpus_for_g1(
        client, "g5", shuffled_g1_corpus
    )
    # Drift-rejected folds (Phase-8 drift gate 202/409 on a baseline upload —
    # see _score_corpus_for_g1's docstring) are EXPECTED on this leg: the
    # shuffled corpus deliberately builds cross-author grab-bag baselines,
    # and the drift detector correctly recognizing many of them as anomalous
    # mid-construction is a working safety feature, not evidence the
    # machinery is broken. Exclude them from the >10% health-check count —
    # s_errors still includes them (that count is unchanged and also
    # reported below), so subtracting s_drift_rejected here yields exactly
    # the genuine-machinery-failure count. A leg with genuine failures alone
    # exceeding 10% still raises, exactly as _require_healthy_leg always has.
    s_genuine_errors = s_errors - s_drift_rejected
    _require_healthy_leg(
        "G5 shuffled G1 leg", n_success=len(s_actions), n_errors=s_genuine_errors
    )
    shuffled_g1_flagged_rate = evaluate_g1_fpr(s_actions, s_per_corpus).detail[
        "pooled_flagged_rate"
    ]
    shuffled_g1_total_folds = len(s_actions) + s_errors
    shuffled_g1_drift_rejected_rate = (
        s_drift_rejected / shuffled_g1_total_folds if shuffled_g1_total_folds else None
    )

    # Shuffled G3: full public_authors rerun with baseline lists permuted
    # across author labels.
    shuffled_g3_accuracy, g3_info = _shuffled_public_authors_top1(rng)

    # Shuffled G4: K=3 seeded draws. Dialogue keys keep their chronology-group
    # membership, but each key receives another dialogue's ENTIRE chunk list,
    # so the early/middle/late groups become random blends. score_early_loo
    # makes the three group means exchangeable under the null (without it,
    # in-baseline early scoring degenerates each draw to a P~0.5 coin flip
    # that majority voting cannot improve — see _compute_g4_group_means);
    # with it, P(one draw monotone by chance) ~= 1/6 and majority-of-3
    # non-monotone detects a genuine null with ~0.93 probability. Each draw
    # gets a fresh student sid and its own permutation from the shared rng
    # stream.
    plato_texts = _load_plato_texts_by_dialogue()
    g4_draws: list[dict] = []
    for draw_idx in range(3):
        shuffled_plato = _shuffle_value_lists_across_keys(plato_texts, rng)
        draw_means, draw_stats = _compute_g4_group_means(
            plato_texts=shuffled_plato,
            sid=f"demo:gate_g5_g4_early_baseline_{draw_idx}",
            score_early_loo=True,
        )
        _require_healthy_leg(
            f"G5 shuffled G4 draw {draw_idx}",
            n_success=draw_stats["n_scored"],
            n_errors=draw_stats["n_errors"],
        )
        g4_draws.append(
            {
                "group_means": draw_means,
                # Monotonicity judged by the SAME rule as the real gate.
                "monotone": evaluate_g4_career_drift_monotone(draw_means).passed,
                **draw_stats,
            }
        )
    g4_nonmonotone_draws = sum(1 for d in g4_draws if not d["monotone"])

    return evaluate_g5_permutation_null(
        real_g1_mean_deviation=statistics.fmean(real_g1_deviations),
        shuffled_g1_mean_deviation=statistics.fmean(s_deviations),
        shuffled_g3_accuracy=shuffled_g3_accuracy,
        g4_nonmonotone_draws=g4_nonmonotone_draws,
        g4_total_draws=len(g4_draws),
        informational={
            "seed": seed,
            "real_g1_flagged_rate": real_g1_flagged_rate,
            "shuffled_g1_flagged_rate": shuffled_g1_flagged_rate,
            "flagged_rate_note": (
                "context only, never gated: conformal typicality p-values "
                "floor at 1/(N+1) and every G1 entity has at most ~a dozen "
                "LOO folds, pinning the action band to no_action for real "
                "and shuffled labels alike"
            ),
            "shuffled_g1_n_folds": len(s_actions),
            "shuffled_g1_n_scoring_errors": s_errors,
            "shuffled_g1_n_genuine_scoring_errors": s_genuine_errors,
            "shuffled_g1_drift_rejected_count": s_drift_rejected,
            "shuffled_g1_drift_rejected_rate": shuffled_g1_drift_rejected_rate,
            "drift_rejected_note": (
                "folds where the Phase-8 drift gate (original/routers/"
                "students_baseline.py) rejected a baseline upload as "
                "pending_review/rebaseline_required (202/409) — this is "
                "expected on a shuffled-label corpus (cross-author "
                "grab-bag baselines) and is independent, complementary "
                "evidence of real authorship coherence, not a machinery "
                "failure. Excluded from shuffled_g1_n_genuine_scoring_errors "
                "and from this leg's >10% health-check threshold; still "
                "excluded from the deviation-shift comparison (its baseline "
                "genuinely wasn't built)."
            ),
            **g3_info,
            "g4_draws": g4_draws,
        },
    )


def render(results: list[GateResult]) -> str:
    lines = ["╭─ Calibration gates (G1-G6) ─────────────────────────────────╮"]
    for r in results:
        status = r.verdict.upper()
        lines.append(f"│ {r.name} [{status}] {r.criterion}")
        lines.append(f"│      current: {r.current_value}")
        power = r.detail.get("power")
        if r.verdict == "uninformative" and power:
            if "wilson_ci" in power:
                lo, hi = power["wilson_ci"]
                lines.append(
                    f"│      n={power['n_essays']} → 95% CI [{lo:.3f}, {hi:.3f}] "
                    f"straddles the {power['bar']} bar; this corpus cannot "
                    f"demonstrate a pass."
                )
            elif "max_entity_n" in power:
                # FIX 2: rule_of_three_fpr_upper is now guaranteed non-None
                # on this path — reaching "uninformative" via the
                # entity_baseline_counts mechanism requires flagged == 0
                # (see evaluate_g1_fpr), and rule_of_three_upper(n) is only
                # ever None when flagged != 0. The old None -> "n/a" guard
                # is therefore dead for an unreachable state; removed
                # rather than kept around it.
                upper = power["rule_of_three_fpr_upper"]
                # min_conformal_p_at_max_n CAN still be None here (FIX 5: a
                # degenerate entity_baseline_counts with every count <= 0),
                # so that one guard stays — it is not provably unreachable
                # the way rule_of_three_fpr_upper is.
                min_p = power["min_conformal_p_at_max_n"]
                min_p_text = f"{min_p:.3f}" if min_p is not None else "n/a"
                lines.append(
                    f"│      max entity N={power['max_entity_n']} → min conformal "
                    f"p={min_p_text} > band "
                    f"{power['band_threshold']}; needs N >= {power['min_docs_for_band']}. "
                    f"Observed 0-rate bounds FPR only above {upper:.1%} "
                    "(rule of three)."
                )
    lines.append("╰────────────────────────────────────────────────────────────╯")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="write JSON report to this path")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat uninformative gates as failures (use before quoting results)",
    )
    args = parser.parse_args(argv)

    results = run_all()
    print(render(results))
    if args.out:
        from original.quantum.typicality import (
            MONITOR_FAR_THRESHOLD,
            NO_ACTION_CENTRAL_THRESHOLD,
            NO_ACTION_FAR_THRESHOLD,
            SCHEDULE_FAR_THRESHOLD,
        )
        from validation.experiment import build_spec, spec_to_dict, summarize_author_docs

        # Reload the same three corpora run_all() scored — cheap (text-file
        # reads only) and keeps run_all()'s own return type (list[GateResult])
        # untouched, so the monkeypatched-run_all tests in
        # tests/test_calibration_gate.py (which replace run_all with a bare
        # lambda returning a plain list) don't have to change shape.
        seminary_texts = _load_seminary_texts()
        public_authors_texts = _load_public_authors_baseline_texts()
        plato_texts = _load_plato_texts_by_dialogue()

        # FIX 2: "seminary" / "public_authors" / "plato" below are the three
        # LOADED corpora (43 authors / 271 documents) — the correct
        # denominator for G4 (early/middle/late grouping over the full Plato
        # set) and G6 (native_english fairness slice), which both consume
        # these texts as-is with no per-entity filter. G1 alone additionally
        # applies its own >= 5-texts-per-entity LOO eligibility filter
        # (_score_corpus_for_g1 skips anything shorter) and therefore scores
        # a narrower pool — 24 entities / 216 folds. Reporting only the
        # loaded totals would let a reader attribute G1's flagged rate to
        # all 271 documents across 43 authors, when it was actually measured
        # over the 216 held-out folds behind "g1_scored" below — exactly
        # the raw-vs-measured conflation this validation layer exists to
        # prevent (see validation/public_authors/run.py's identical
        # eligible-narrowing precedent, ~line 229: "a run narrowed by --only
        # or by corpus policy must report what it measured, not what the raw
        # manifest contains"). Kept ALONGSIDE the loaded totals, rather than
        # narrowing them in place, because those totals are also the
        # genuinely correct denominator for G4/G6 above — narrowing this
        # dict to G1's subset would make it wrong for the other two gates.
        g1_scored_texts_by_id = {
            entity_id: texts
            for entity_id, texts in {**seminary_texts, **public_authors_texts, **plato_texts}.items()
            if len(texts) >= 5
        }

        spec = build_spec(
            task="calibration_suite",
            corpora={
                "seminary": summarize_author_docs(seminary_texts, "student_pilot"),
                "public_authors": summarize_author_docs(public_authors_texts, "real_historical"),
                "plato": summarize_author_docs(plato_texts, "real_historical"),
                "g1_scored": summarize_author_docs(
                    g1_scored_texts_by_id, "g1_loo_eligible_subset"
                ),
            },
            windowing={"source": "corpus documents as-is"},
            aggregation={"tier_rule": "median"},
            thresholds={
                "g1_flagged_rate": 0.05,
                "g3_top1": 0.7,
                "g6_ratio": 2.0,
                "no_action_far_threshold": NO_ACTION_FAR_THRESHOLD,
                "no_action_central_threshold": NO_ACTION_CENTRAL_THRESHOLD,
                "monitor_far_threshold": MONITOR_FAR_THRESHOLD,
                "schedule_far_threshold": SCHEDULE_FAR_THRESHOLD,
            },
        )
        Path(args.out).write_text(
            json.dumps(
                {
                    "experiment": spec_to_dict(spec),
                    "gates": [asdict(r) for r in results],
                },
                indent=2,
            )
        )
    failing = [r for r in results if r.verdict == "fail"]
    uninformative = [r for r in results if r.verdict == "uninformative"]
    if uninformative:
        # FIX 4: the lenient default (an uninformative gate does not fail
        # unless --strict) is a deliberate plan-level policy — it stays the
        # default here — but a green exit code must never be quotable in
        # silence. Print this in BOTH strict and non-strict runs so the
        # trailing line always names what a bare exit code hides.
        #
        # FIX D: the tail sentence must be mode-conditional. Under --strict
        # these gates WERE folded into `failing` (below), so "not counted as
        # failure; re-run with --strict" is false and self-referential in
        # that mode — say what actually happened in each mode instead.
        names = ", ".join(r.name for r in uninformative)
        if args.strict:
            tail = "counted as a failure because --strict is set."
        else:
            tail = "not counted as failure; re-run with --strict to fail on these."
        print(f"{len(uninformative)} gate(s) UNINFORMATIVE ({names}) — {tail}")
    if args.strict:
        failing = failing + uninformative
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
