# Does a topic-masked (POSNoise) distortion channel survive topic shift better than raw text?

The measured failure this phase targets is cross-topic false positives: on the
leave-one-genre-out Lewis corpus, raw `deviation_score` reaches AUC 0.387 —
*inverted* — because a student writing on a new topic looks like a different
author. Phase 2's hypothesis is that scoring a probe twice, once raw and once
with content vocabulary masked out, separates the two causes: raw-high +
masked-low ⇒ the match was topical; raw-low + masked-high ⇒ a genuine author
on a new topic, which is the false-positive mode.

Two validation modules were built, plus a corpus script:

- `validation/verify/distortion_signals.py` — the signal producer.
- `validation/verify/pan_stack_distortion.py` — the PAN ablation.
- `validation/genre_crossgenre_2026-08/distort_corpus.py` — the crossgenre
  distortion stage, **committed unexercised** (see below).

## The divergence construction, and why it is a subtraction

The contrast could have been a distributional divergence (KL/JS between raw
and masked distributions) or one scalar authorship quantity computed twice and
subtracted. It is the subtraction, for two reasons:

1. **Reuse.** It reuses Phase 1's already-reviewed character-LM machinery
   verbatim (`build_char_lm`, `char_cross_entropy`, `_peer_blob`) and adds
   exactly one new operation, `mask_text`. A distributional divergence needs a
   new estimator and a support-mismatch story — raw and masked text share no
   vocabulary, so a KL between them is not well posed without an alignment
   step that is itself a modelling choice.
2. **Apples-to-apples.** Both arms run the identical estimator at identical
   order over an identical peer-pool construction, so the difference isolates
   masking and nothing else.

A token-level LM over the POSNoise tuples was rejected: it changes the
estimator between arms and substantially duplicates
`validation/verify/lambdag_signals.py`, which already runs Kneser-Ney over
exactly those tuples as its own fusion channel.

Signals emitted: `undistorted_delta`, `distorted_delta`, `distorted_h_author`,
and `distorted_divergence = undistorted_delta − distorted_delta`.

## Pre-registered gate: G-P2

**Verdict: UNINFORMATIVE.** The gate's primary criterion could not be
evaluated, and the secondary guard it *could* evaluate failed.

G-P2 has two halves. The primary half — "on the crossgenre harness, the
distorted channel's same-author/cross-genre FPR must beat the raw channel's at
matched TPR" — is the only one that actually tests the hypothesis, because
only that corpus contains the genre shift the channel is meant to survive.
**It is not evaluable in this repository**: the Lewis/Chesterton corpus is not
committed (copyright) and `validation/genre_crossgenre_2026-08/raw/` is
absent. It is not merely unrun — there is no lawful way to run it here.

Per the repo's three-valued gate convention
(`validation/calibration_gate.py`), a gate whose criterion is unreachable at
the current corpus downgrades to uninformative and must never be quoted as a
pass.

The secondary half — "on PAN, stacked cllr must not regress" — was evaluated
on the pre-registered arm `with_distorted_divergence`:

| | base only | + distorted_divergence |
|---|---:|---:|
| AUC | 0.8455 | 0.8371 |
| Brier | 0.1031 | 0.1137 |
| Cllr | 0.8844 | 0.9823 |
| Recall @ 1% FPR (transferred threshold) | 30.6% | 27.8% |
| Precision @ 1% FPR | 78.6% | 66.7% |
| Recall @ 5% FPR | 61.1% | 63.9% |
| TPR @ locked-optimal 1% FPR | 38.9% | 25.0% |

- cllr does not regress: **no** (+0.0979 — it got worse, and crossed 1.0, the
  uninformative line)

Supporting quantities, reported but not part of the gate: ΔAUC −0.0084,
Δrecall @ 1% FPR −2.8 points. Everything moved slightly the wrong way.

**Abstention was 0.000 for all four signals on all three partitions.** The
channel fired on every trial, so this is a real measurement and not an unfired
mechanism — the trap `GENRE_INVARIANT_WEIGHTS_ENABLED` fell into.

Honest size statement: 36 genuine and 396 impostor locked trials. Recall moves
in 1/36 = 2.8-point steps, so the recall deltas here are one-trial noise and
ΔAUC −0.0084 is indistinguishable from zero. The correct reading is **"no
evidence that `distorted_divergence` helps on PAN"**, not "evidence that it
harms." The guard is failed on cllr, the criterion least sensitive to that
noise.

## Two structural reasons the PAN half was a weak test

Both were foreseeable, and neither is a reason to reweight the result upward.

**1. PAN does not contain the failure mode.** The channel is built to survive
topic shift. Passing or failing a do-no-harm guard on a corpus without a
systematic genre shift says little about whether it survives one. This is why
the crossgenre half is the primary criterion and the PAN half is only a guard.

**2. The divergence is collinear by construction in a linear fusion.**
`distorted_divergence` is exactly `undistorted_delta − distorted_delta`. A
logistic fusion that already has both constituents cannot extract anything
from their difference — and the measurement confirms it: in the all-signals
arm the divergence coefficient collapses to **−0.049**, versus **+0.582** in
the gate arm where its constituents are absent. A linear model cannot benefit
from a linear contrast of terms it already holds.

The consequence is that a raw-vs-masked *contrast* can only pay off in a
non-linear model or as a gating variable — which is precisely the shape Phase
2B proposed (a 2×2 verdict table, not a fusion weight). The PAN fusion harness
is structurally the wrong instrument for it. That is a finding about the
instrument, not a rescue of the result.

## The one genuinely interesting number, and its status

On the **development** partition (the selection partition — no locked
contamination), masked text carried *more* standalone authorship signal than
raw text at every configuration swept:

| config | `undistorted_delta` | `distorted_delta` |
|---|---:|---:|
| order 3, matched pool | 0.859 | 0.927 |
| order 3, 200k pool | 0.866 | 0.902 |
| order 4, matched pool | 0.877 | 0.913 |
| order 4, 200k pool | 0.884 | 0.893 |
| order 5, matched pool | 0.869 | 0.912 |
| order 5, 200k pool | 0.883 | 0.897 |

Stripping content vocabulary did not cost authorship signal on PAN; it
slightly improved it. That is consistent with the POSNoise literature and is
the strongest reason to think the idea is worth a properly-powered test on a
corpus that has the topic shift in it.

**This is a development-partition observation, not a claim and not a gate
result.** It is reportable precisely because it is the partition selection was
allowed to see.

## No unregistered arm to withhold

Phase 1 faced a dilemma: its unregistered zlib-NCD arm cleared all three bars
and was deliberately not claimed, because a criterion applied after seeing
locked results is not a held-out criterion. **That dilemma does not arise
here.** Every arm regresses on cllr:

| arm | Δcllr | guard met |
|---|---:|:--:|
| `with_distorted_divergence` (pre-registered) | +0.0979 | no |
| `with_distorted_delta` (exploratory) | +0.0412 | no |
| `with_distortion_all` (exploratory) | +0.2588 | no |

`with_distorted_delta` does move recall @ 1% FPR from 30.6% to 44.4%, but at
2.53% FPR — the 1% bar was not held — while AUC, Brier and cllr all worsen.
That is the same calibration-failure-on-a-discrimination-non-result pattern
Phase 1 documented, not evidence of benefit.

There is also the same substitution signature Phase 1 flagged for NCD: adding
`distorted_delta` drops `character_similarity`'s coefficient from **+1.077**
to **+0.233** (and to +0.612 in the gate arm), which reads as the masked
channel partly *replacing* the existing LUAR character channel rather than
contributing orthogonal evidence.

`distorted_h_author` is not inert the way `compression_h_author` was — it
takes coefficient +0.97 in the all-signals arm — but that arm is the worst of
the four on every calibration metric, so this is not a point in its favour.

## `distort_corpus.py` is committed unexercised

`validation/genre_crossgenre_2026-08/distort_corpus.py` slots between
`clean_corpus.py` and `extract_vectors.py`, masking every chunk's text and
carrying author/work/genre/chunk_id through unchanged so the downstream
harness partitions identically. Because `extract_vectors.py` hardcodes
`chunks.json`, it runs the *unmodified* downstream harness by swapping the
file (`--activate` / `--restore`, with a refuse-to-overwrite backup guard)
rather than by editing the harness.

**It has never been run against the real corpus.** Its masking call is covered
by `tests/test_distortion_signals.py` and its record-rewriting logic by
`--smoke-test` over synthetic records; the chunk-count, genre-balance and
downstream extraction behaviour on real distorted prose are unverified. Its
docstring says so prominently. Sourcing the corpus was explicitly out of scope
for this task.

Its masking output does reproduce the LambdaG paper's worked example exactly:
`"If they actually censor anything is another question."` →
`if they ADV VERB anything is another NOUN .`

## Consequence

**No production distortion channel ships.** Phase 2B — the persisted
`distorted_vector` baseline field, `original/distortion_scoring.py`, the four
attach sites and the `DISTORTION_SCORING_ENABLED` flag — is **not** built. The
gate did not pass, and could not have passed from this checkout.

The three validation modules, their tests, and this document are the whole
deliverable.

What would make this decidable, in order of value:

1. Populate `validation/genre_crossgenre_2026-08/raw/` and run the primary
   half of G-P2. That is one command away and is the only test that addresses
   the hypothesis.
2. If that half passes, re-pre-register the PAN half against a locked set this
   study has not read, and test the contrast in the non-linear/gating form it
   actually needs — not as a linear fusion weight, where it is collinear with
   terms the fusion already has.

## Reproducing

```bash
~/Desktop/Original/.venv/bin/python -m validation.verify.pan_stack_distortion --sweep  # development only
~/Desktop/Original/.venv/bin/python -m validation.verify.pan_stack_distortion          # locked run
~/Desktop/Original/.venv/bin/python -m pytest tests/test_distortion_signals.py -q
~/Desktop/Original/.venv/bin/python validation/genre_crossgenre_2026-08/distort_corpus.py --smoke-test
```

Requires the PAN 2020 cache at `.benchmark_cache/pan/2020`
(`scripts/fetch_benchmark_data.py --pan`) and spaCy `en_core_web_sm`. Runtime:
2 min 30 s for the six-configuration development sweep, 1 min 22 s for the
locked run, on the full 120/20/20/12 partition sizes — no partition was
reduced. Reports:
`validation/benchmarks/2026-08-10/pan_stack_distortion_ablation.json` and
`…_development_sweep.json` (benchmark JSONs are gitignored, matching the
compression run's convention).

Hyperparameters (order 4, 200k-char peer pool) were re-checked on the
**fusion_development** partition only and deliberately left at Phase 1's
values rather than re-tuned to the nominal development maximum — orders 4 and
5 differ by 0.007 AUC across 20 authors, which is noise. The locked partition
was read once, for the numbers above.
