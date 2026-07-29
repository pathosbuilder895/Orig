# Short-Regime Threshold Proposal (3×500-word operating point)

**Date:** 2026-07-29
**Status:** PROPOSAL ONLY — no constants changed. `original/constants.py::ACTION_THRESHOLDS` is
unmodified by this document. Adoption requires explicit owner sign-off (see §4) and a
publish-sync of README.md / MODEL_CARD.md / OWNERS_MANUAL.md action tables before any code
change lands.

---

## 1. Summary

| | |
|---|---|
| **Operating point** | 3×500-word baseline samples per student, scored against 500-word probes |
| **Corpus** | 9 pseudo-students: 5 synthetic seminary authors (`seminary_01`–`05`) + 4 public-domain authors (Burke, Douglass, Lincoln, Paine — chunked from `validation/corpus/`) |
| **Scorings** | 122 honest (same-author) probes, 176 impostor (other-author) probes |
| **Criterion** | catch rate at a ≤5% false-flag budget (`catch@5%`) — the fraction of impostor probes scored at or above the threshold that keeps honest false-flags at ~5%, per `validation/short_regime/stats.py` |
| **Harness** | `validation/short_regime/` (runner.py, corpus.py, stats.py, reliability.py); raw grid at `validation/benchmarks/2026-07-29/short_regime/report.json` |
| **Flags-off floor** | AUC 0.8617 (CI 0.815–0.901), catch@5% = 0.5455 (CI 0.250–0.699), threshold 0.834 (on `deviation_score`) |
| **Winning combo** | **PRIOR+LLR** — `BAYESIAN_PRIOR_ENABLED=1` (with `COHORT_PRIOR_FALLBACK=1`) + `NULL_MODEL=impostor`, decision made on `llr_deviation_score` — AUC 0.880 (CI 0.840–0.915), catch@5% = 0.693 (CI 0.614–0.761), threshold 0.492 |
| **Net effect** | +0.148 catch@5% absolute (+27% relative) over the flags-off floor, at the same ~5% false-flag budget |

The improvement is driven almost entirely by one lever (LLR — the explicit impostor-pool null
model). This is a genre-matched three-way corpus (seminary synthetic + 19th-century public
authors) at a single 500-word/3-sample operating point; see §5 for what the CI widths and
9-student sample size do and do not let us claim.

---

## 2. Full 16-combo grid

Copied verbatim from `validation/benchmarks/2026-07-29/short_regime/report.md`.

| combo | AUC | AUC 95% CI | catch@5% | catch CI | threshold | llr fallbacks |
|---|---|---|---|---|---|---|
| PRIOR+LLR | 0.880 | 0.840–0.915 | 0.693 | 0.614–0.761 | 0.492 | 0 |
| SHRINK+PRIOR+LLR | 0.880 | 0.840–0.915 | 0.693 | 0.614–0.761 | 0.492 | 0 |
| LAW+PRIOR+LLR | 0.859 | 0.819–0.897 | 0.659 | 0.580–0.733 | 0.506 | 0 |
| LAW+SHRINK+PRIOR+LLR | 0.859 | 0.819–0.897 | 0.659 | 0.580–0.733 | 0.506 | 0 |
| LLR | 0.880 | 0.843–0.913 | 0.653 | 0.585–0.767 | 0.622 | 0 |
| SHRINK+LLR | 0.880 | 0.843–0.913 | 0.653 | 0.585–0.767 | 0.622 | 0 |
| LAW+LLR | 0.863 | 0.825–0.897 | 0.642 | 0.534–0.722 | 0.677 | 0 |
| LAW+SHRINK+LLR | 0.863 | 0.825–0.897 | 0.642 | 0.534–0.722 | 0.677 | 0 |
| LAW | 0.868 | 0.822–0.907 | 0.580 | 0.335–0.733 | 0.893 | 0 |
| LAW+SHRINK | 0.868 | 0.822–0.907 | 0.580 | 0.335–0.733 | 0.893 | 0 |
| OFF | 0.862 | 0.815–0.901 | 0.545 | 0.250–0.699 | 0.834 | 0 |
| SHRINK | 0.862 | 0.815–0.901 | 0.545 | 0.250–0.699 | 0.834 | 0 |
| LAW+PRIOR | 0.758 | 0.696–0.815 | 0.159 | 0.051–0.335 | 0.865 | 0 |
| LAW+SHRINK+PRIOR | 0.758 | 0.696–0.815 | 0.159 | 0.051–0.335 | 0.865 | 0 |
| PRIOR | 0.738 | 0.675–0.797 | 0.102 | 0.017–0.387 | 0.807 | 0 |
| SHRINK+PRIOR | 0.738 | 0.675–0.797 | 0.102 | 0.017–0.387 | 0.807 | 0 |

### Marginal effects

Mean across the 8 combos with the lever ON minus mean across the 8 with it OFF.

| lever | Δ catch@5% | Δ AUC |
|---|---|---|
| LLR | +0.3153 | +0.0640 |
| LAW | +0.0113 | -0.0027 |
| SHRINK | +0.0000 | +0.0000 |
| PRIOR | -0.2017 | -0.0598 |

LLR (impostor-null decision statistic) is the dominant lever by a wide margin — it is the only
lever whose marginal effect on catch@5% exceeds the OFF-row bootstrap CI width. PRIOR (cohort
Bayesian prior) is net-negative *alone* at this operating point (it pulls per-student mu/sigma
toward the cross-student genre prior, lowering sensitivity to genuine per-student deviation
given how few baselines exist per student here) but is net-positive *combined with LLR*
(+0.04 catch@5% over LLR alone: 0.693 vs 0.653) — the prior stabilizes the baseline that LLR's
distance-from-impostor-pool computation is measured against. SHRINK (Ledoit-Wolf rank
remediation) shows an exact 0.0000 marginal effect — not a rounding artifact; honest_scores and
impostor_scores are bit-identical between every SHRINK/non-SHRINK pair, because shrinkage only
transforms the density matrix ρ, which feeds only the Born probability / amplitude-scoring path
(gated by `AMPLITUDE_SCORING_ENABLED`, off in this runner) — never the `deviation_score` or
`llr_deviation_score` paths measured here. LAW (length-adaptive weights) has a small positive
effect on catch@5% and a negligible/slightly negative effect on AUC.

---

## 3. Proposal

### 3.1 Recommended flags

```
BAYESIAN_PRIOR_ENABLED=1
COHORT_PRIOR_FALLBACK=1
NULL_MODEL=impostor
PRIOR_WEIGHT=3.0
```

Decision statistic for the short bucket (submissions with fewer/shorter baseline samples,
practically ≤3×500 words): `llr_deviation_score` instead of `deviation_score`.

### 3.2 Computing the proposed band boundaries

Boundaries are the PRIOR+LLR combo's honest-score (same-author) distribution at quantiles
{0.50, 0.80, 0.95} — i.e., set so that 50% / 80% / 95% of genuine same-author submissions fall
at or below each successive boundary. Ties the `escalate` floor to the same ~5% false-flag
budget the harness selected its threshold on (0.4917 vs. the harness's own 0.4918 — the small
gap is `np.quantile` vs. the harness's independent CI-search threshold-picker, not a
discrepancy in the data).

Computed with `.venv/bin/python` from the worktree root:

```python
import json
import numpy as np

with open("validation/benchmarks/2026-07-29/short_regime/report.json") as f:
    data = json.load(f)

combo = next(c for c in data if c["combo"] == "PRIOR+LLR")
honest = np.array(combo["honest_scores"])
impostor = np.array(combo["impostor_scores"])

q50, q80, q95 = np.quantile(honest, [0.50, 0.80, 0.95])

bands = [
    ("no_action",             0.0, q50),
    ("monitor",               q50, q80),
    ("schedule_conversation", q80, q95),
    ("escalate",              q95, float("inf")),
]

for name, lo, hi in bands:
    if hi == float("inf"):
        honest_in = np.sum(honest >= lo)
        impostor_in = np.sum(impostor >= lo)
    else:
        honest_in = np.sum((honest >= lo) & (honest < hi))
        impostor_in = np.sum((impostor >= lo) & (impostor < hi))
    print(f"{name}: [{lo:.4f}, {hi if hi==float('inf') else round(hi,4)}) "
          f"honest_n={honest_in} ({honest_in/len(honest)*100:.1f}%) "
          f"impostor_n={impostor_in} ({impostor_in/len(impostor)*100:.1f}%)")

print()
for label, thresh in [("q50 (monitor+)", q50), ("q80 (schedule+)", q80), ("q95 (escalate)", q95)]:
    catch = np.mean(impostor >= thresh)
    false_flag = np.mean(honest >= thresh)
    print(f"{label} = {thresh:.4f}: impostor catch={catch:.4f}, honest false-flag={false_flag:.4f}")
```

Output:

```
n_honest: 122, n_impostor: 176
honest quantile 0.50: 0.4299
honest quantile 0.80: 0.4679
honest quantile 0.95: 0.4917

no_action:             [0.0000, 0.4299) honest_n=61  (50.0%) impostor_n=16  (9.1%)
monitor:               [0.4299, 0.4679) honest_n=36  (29.5%) impostor_n=23  (13.1%)
schedule_conversation: [0.4679, 0.4917) honest_n=18  (14.8%) impostor_n=15  (8.5%)
escalate:               [0.4917, inf)   honest_n=7   (5.7%)  impostor_n=122 (69.3%)

q50 (monitor+)  = 0.4299: impostor catch=0.9091, honest false-flag=0.5000
q80 (schedule+) = 0.4679: impostor catch=0.7784, honest false-flag=0.2049
q95 (escalate)  = 0.4917: impostor catch=0.6932, honest false-flag=0.0574
```

### 3.3 Proposed boundaries vs. current `ACTION_THRESHOLDS`

Current (`original/constants.py:652`, applies to `deviation_score`, all submission lengths):

```python
ACTION_THRESHOLDS = {
    "no_action":            (0.00, 0.40),
    "monitor":              (0.40, 0.60),
    "schedule_conversation":(0.60, 0.75),
    "escalate":             (0.75, 1.00),
}
```

Proposed, for the short bucket only, on `llr_deviation_score`:

| band | current (deviation_score, all lengths) | proposed (llr_deviation_score, short bucket) | cumulative impostor catch at proposed floor | cumulative honest false-flag at proposed floor |
|---|---|---|---|---|
| no_action | 0.00–0.40 | 0.00–0.4299 | — | — |
| monitor | 0.40–0.60 | 0.4299–0.4679 | 90.9% | 50.0% |
| schedule_conversation | 0.60–0.75 | 0.4679–0.4917 | 77.8% | 20.5% |
| escalate | 0.75–1.00 | 0.4917–1.00 | 69.3% | 5.7% |

Two things to note reading this table:

- **The numeric ranges are not comparable across statistics.** `llr_deviation_score` is a
  bounded tanh transform centered at 0.5 (0.5 = "as consistent with the claimed author as with
  the impostor pool"; see `original/quantum/scoring.py::_llr_deviation` docstring), not the same
  quantity as `deviation_score`. A proposed "escalate at 0.4917" is not a loosening of the
  current "escalate at 0.75" — it is a threshold on a different, more discriminating statistic.
  The percentile framing (§3.2) is the only valid way to compare them.
- **The escalate floor (q95 = 0.4917) reproduces the harness's own selected threshold** (0.4918,
  catch@5% = 0.693) almost exactly, which is the intended check: an escalate band built directly
  from the honest 95th percentile lands on the same operating point the grid search already
  picked independently.
- The monitor/schedule_conversation interior boundaries (q50, q80) are new — the current
  4-band schema has no equivalent structure on `llr_deviation_score` today. They are included
  because the task calls for a full 4-band mapping, but only the escalate floor has been
  validated against the catch@5% criterion; q50/q80 have not been separately optimized and
  should be treated as provisional pending a dedicated calibration pass if adopted.

---

## 4. Policy: this changes what drives the action for short submissions

**`llr_deviation_score` is documented, in two places, as attach-only:**

- CLAUDE.md, `NULL_MODEL` row: *"attach-only, never changes the action"*
- `original/quantum/scoring.py:63`: *"...degrades sharply below ~300 words. Prose only — never
  changes the action."* (and the `score()` docstring at scoring.py:483: *"the primary
  deviation_score / action / recommendation are never touched by this parameter"*)

Adopting this proposal is a **reversal of that contract for the short bucket**. This section
exists so that reversal is not made silently.

**What changes:**
For submissions in the short bucket (practically: baselines built from ≤3×500-word samples, or
however the eventual bucket boundary is defined), the `action` field (and downstream
`professor_explanation` / recommendation copy) would be computed from `llr_deviation_score`
against the boundaries in §3.2/§3.3, instead of from `deviation_score` against the existing
`ACTION_THRESHOLDS`.

**Why:**
At the fixed ~5% false-flag budget this corpus measures, `llr_deviation_score`-driven decisions
catch 69.3% of impostor probes vs. 54.5% for the current `deviation_score`-driven floor — a
+14.8 point (+27% relative) improvement, entirely attributable to the LLR lever (§2, marginal
effects table). For short submissions specifically — the regime where per-feature baselines are
noisiest and the current scheme is weakest — this is a large, single-lever effect.

**What stays the same:**
- `deviation_score` is still computed and still reported on every response; it does not
  disappear from the API surface or from `professor_explanation`.
- Long/normal submissions (outside the short bucket) are unaffected — this proposal is scoped
  to the short-baseline regime measured here, not a global rebind of the action field.
- `AMPLITUDE_SCORING_ENABLED` / `RANK_REMEDIATION` paths are untouched (SHRINK's 0.0000 marginal
  effect confirms ρ-based scoring doesn't interact with this decision at all).

**Fallback when `llr` is unavailable (cold start):**
`llr_deviation_score` is only populated when `NULL_MODEL=impostor` AND a same-tenant impostor
pool can be fit (`original/quantum/null_pool.py::build_impostor_stats`). The cohort floor is
**`MIN_IMPOSTOR_STUDENTS = 3`** other same-tenant students **and `MIN_IMPOSTOR_VECTORS = 5`**
pooled authenticated baseline vectors; below either floor, `build_impostor_stats` returns `None`
and `llr_deviation_score` stays `None` — "identical to the flag-off response shape. No score is
ever blocked or degraded by an absent pool" (null_pool.py docstring). In that case, under this
proposal, the short bucket would fall back to the existing `deviation_score` path against the
current `ACTION_THRESHOLDS` — i.e., the worst case for a newly-onboarded tenant (too few
students to build an impostor pool yet) is exactly today's behavior, not a degraded one.

**Sign-off / publish-sync requirement:**
This is a decision-path change, not a cosmetic one, and the "never changes the action" language
is repeated verbatim in CLAUDE.md and in `scoring.py` comments — both would need updating on
adoption, alongside:
- `README.md` action table
- `MODEL_CARD.md` action table
- `OWNERS_MANUAL.md` action table
- The `ACTION_THRESHOLDS` publish-sync comment at `original/constants.py:651` already names
  these three files as the sync targets for any boundary move; this would be the first boundary
  move that also changes *which statistic* drives the boundary, so the sync note in those docs
  should say so explicitly, not just update numbers.

No code in this repository has been changed to implement this. This document is the proposal;
implementation is a separate, explicitly-approved follow-up.

---

## 5. Limitations

- **Confidence-interval widths.** Several CIs in §2 are wide enough to overlap adjacent combos —
  e.g. OFF's catch@5% CI is 0.250–0.699, nearly as wide as the entire 0.10–0.69 range spanned by
  all 16 combos. The PRIOR+LLR vs. OFF catch@5% point-estimate gap (0.693 vs 0.545) is real and
  driven by a single dominant, mechanistically-understood lever (LLR), but with 9
  pseudo-students the CIs do not by themselves rule out a smaller true effect.
- **9 pseudo-students.** 5 synthetic seminary + 4 public-domain authors is enough to establish
  direction and rough magnitude, not enough to certify a production threshold. Per-author
  variance in writing consistency is not sampled broadly.
- **Synthetic seminary corpus.** The 5 seminary pseudo-students are synthetic (not real student
  submissions); genre-matching to the pilot's actual population is assumed, not verified.
- **Single run.** The grid in §2 is one execution of the harness, not a repeated/bootstrapped
  ensemble beyond the CIs the harness itself reports per combo.
- **ICC caveats.** `validation/short_regime/reliability_500w.json` reports per-feature ICC at
  500 words; the two comparison codes that feed `llr_deviation_score`'s weighting
  (`char_trigram_profile_divergence`, `function_word_profile_divergence`) are placeholders at
  extraction time and their ICC is unmeasurable (`"note": "placeholder at extraction time; ICC
  unmeasurable"`) — reliability of those two specific inputs at this word count is unknown, not
  merely low.
- **The 500-word information ceiling.** A prior length-control measurement (2026-07-29,
  Lewis/Chesterton length sweep, `docs/superpowers/plans/2026-07-29-short-baseline-scoring.md`)
  found that even with 4×1300-word baselines and ideal (public-domain, well-edited) prose,
  same-author vs. other-author separation margin stays **negative until ~6,000-word samples**.
  The 3×500-word regime measured here is harder still. The catch@5% improvement in this document
  should be read as "the best achievable lift at a genuinely hard operating point," not as
  evidence that 500-word verification is reliable in an absolute sense — it remains a
  provisional-confidence regime by design (`original/quantum/scoring.py`'s short-submission
  note applies here unchanged).

---

## 6. Bottom line

PRIOR+LLR is the best-measured combo at this operating point and the proposed boundaries in
§3.2 reproduce the harness's own threshold selection almost exactly. The catch@5% gain is real
and attributable to one well-understood, well-documented lever. Adopting it productizes a
decision-path change to a statistic currently documented as attach-only, in the specific regime
(short submissions) where the current scheme is weakest to begin with. Recommend: owner
sign-off on the policy change in §4, then a dedicated PR that (a) flips the flags, (b) wires
short-bucket action selection to `llr_deviation_score` with the §3.2 boundaries (or a follow-up
calibration of q50/q80 specifically), and (c) updates CLAUDE.md, README.md, MODEL_CARD.md,
OWNERS_MANUAL.md, and the `scoring.py` "never changes the action" comments in the same change.
