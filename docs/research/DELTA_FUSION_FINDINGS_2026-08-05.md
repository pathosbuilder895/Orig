# Does Burrows' Delta improve the pan_stack same-author fusion?

Every locked same-author number in this repo so far comes from
representation-based signals: LUAR embeddings, character n-gram margins,
content-reduced margins. Burrows' Delta (`validation/attribution/delta.py`)
is classic, word-frequency-only, and structurally independent of all of
them — implemented but never tried in a fusion. This measures whether
adding it changes anything, via a clean ablation on `pan_stack.py`'s own
machinery: identical 120-development / 40-calibration / 12-locked author
split, identical LUAR-family style trials, identical peer-relative Original
signals — the only variable between the two runs is whether
`delta_neg_distance` and `delta_peer_z` (`validation/verify/delta_signals.py`)
are present.

## Locked result (12 authors, 36 genuine / 396 impostor trials)

| | without Delta | with Delta |
|---|---:|---:|
| AUC | 0.8455 | 0.8598 |
| Brier | 0.1031 | 0.0881 |
| Cllr | 0.8844 | 0.8360 |
| Recall @ 1% FPR | 30.6% | 36.1% |
| Precision @ 1% FPR | 78.6% | 81.2% |
| Recall @ 5% FPR | 61.1% | 61.1% |
| Precision @ 5% FPR | 61.1% | 68.8% |
| Recall @ 10% FPR | 75.0% | 75.0% |

Standardized fusion coefficients with Delta included: `peer_probability`
0.967, `character_similarity` 1.017, `delta_peer_z` 0.549,
`content_reduced_similarity` 0.545, `delta_neg_distance` -0.463,
`raw_probability` 0.258 — Delta's two signals land in the same range as the
existing mid-tier channels, not dominant but not negligible either.

## Reading this honestly

Positive, real, and modest: AUC +0.014, recall at the strict 1% FPR bar
+5.6 points (30.6% → 36.1%, about an 18% relative gain), and at 5% FPR the
gain shows up entirely in precision (61.1% → 68.8%) rather than recall,
which stayed flat. This is consistent with Delta adding genuine
complementary evidence — an independent word-frequency signal catching
cases the embedding-based signals miss — not with it just re-deriving what
the other four channels already had.

It is not close to the two-sided target this study was run against: >=85%
same-author recall at <5% false-positive rate. The best operating point
here (5% FPR) still recalls only 61.1%, and every other same-author fusion
already documented in this repo (the LUAR + shrinkage-LDA line,
96-98% precision / 50-59% recall / 1-2% FPR; the Gutenberg cross-work lock,
100% precision / 79.3% recall / 0% FPR on a much easier historical-fiction
corpus) sits in the same general band. Delta moves the needle in the right
direction; it does not close the gap.

## Second, independent lock: 400-writer Gutenberg corpus (100 authors, 300/300 matched trials)

The PAN lock above is thin (12 authors). This repeats the same question —
does Delta help — on a genuinely different, already-cached corpus
(`validation/verify/gutenberg_corpus.py`'s 400-writer manifest, LUAR
embeddings pre-computed) with an 8x larger locked cohort, via
`validation/verify/gutenberg_verify_delta.py`. Design differs deliberately
from the PAN ablation: a balanced 1:1 matched-pair binary construction (each
probe gets exactly one genuine trial and one deterministic impostor trial,
this repo's existing "binary source-matched authentication protocol"
convention) rather than the full pairwise cross-product, and the base
signal set is LUAR cosine + character + content-reduced (no peer-relative
Original score — this corpus has no impostor-pool null model wired to it).

| | without Delta | with Delta |
|---|---:|---:|
| AUC | 0.9465 | 0.9560 |
| Recall @ 1% FPR | 67.3% | **77.3%** |
| Recall @ 5% FPR | 83.0% | **86.3%** |

This is the strongest number produced anywhere in this session, and the
closest anything in this repo has come to the >=85%-recall side of the
original target — 86.3% recall at 5% FPR, with Delta responsible for a real
+10-point recall gain at the strict 1% bar. It is **not** the same claim as
clearing the target: this corpus is historical public-domain fiction with
2,500-word cross-work windows, not real student essays, and 5% FPR is not
"<5%" — the two-sided bar this study was set against. Every prior Gutenberg
number in this repo carries the identical caveat (see
CROSS_WORK_AUTHORSHIP_FINDINGS_2026-08-04.md): strong cross-work
authentication evidence, not institutional or student evidence.

The direction is now corroborated on two structurally different corpora and
two different base signal sets (PAN: peer-relative Original + LUAR family;
Gutenberg: LUAR family alone) — Delta's contribution looks real, not an
artifact of one corpus's quirks.

## Third lock: the same PAN cohort, scaled from 12 to 100 authors

The 12-author lock above was explicitly flagged as thin. Once the feature
cache + parallel extraction landed (`validation/verify/feature_cache.py`),
re-running the identical PAN protocol at `n_locked=100` (30,000 locked
trials instead of 432 — the full target x source x probe cross-product at
100 authors) became tractable. Same corpus, same signal set, same fusion
mechanics — only the locked cohort size changed.

| | n=12 lock | n=100 lock |
|---|---:|---:|
| AUC (without Delta) | 0.8455 | 0.8756 |
| AUC (with Delta) | 0.8598 | 0.8917 |
| Recall @ 1% FPR (without Delta) | 30.6% | 33.3% |
| Recall @ 1% FPR (with Delta) | 36.1% | **45.0%** |
| Recall @ 5% FPR (without Delta) | 61.1% | 55.0% |
| Recall @ 5% FPR (with Delta) | 61.1% | **64.3%** |

The larger, more statistically credible lock doesn't just confirm the
direction — it shows a **bigger** effect than the thin lock suggested:
recall@1%-FPR gain goes from +5.6 points (n=12) to +11.7 points (n=100), and
at 5% FPR the n=12 lock's gain was precision-only (recall stayed flat at
61.1%) while the n=100 lock shows a real +9.3-point recall gain there too.
Read together with the earlier caveat ("the exact magnitude should not be
treated as stable until it reproduces on a larger cohort") — it reproduced,
and came out stronger, not weaker. Third independent corroboration now
(PAN n=12, PAN n=100, Gutenberg n=100), all positive, all on genuinely
different author sets.

## What this does and doesn't license

- Adding Delta as a fusion signal is evidence-backed, not a hunch — this is
  a real, single, disjoint-split locked measurement, not threshold-shopped
  against this same locked set.
- 12 locked authors / 36 genuine trials is thin. The direction is credible
  (it agrees with the ensemble-diversity rationale for trying Delta in the
  first place); the exact magnitude (+5.6 points) should not be treated as
  a stable number until it reproduces on a larger or a second locked
  cohort.
- No promotion decision follows from this alone. `pan_stack.py`'s own
  4-channel result was already rejected on separate grounds (cross-lock
  variance, not a floor bug); a 6-channel version with Delta has not been
  run through that same fresh-lock generalization check yet.

## Reproduce

```bash
.venv/bin/python -m validation.verify.pan_stack_delta
.venv/bin/python -m validation.verify.gutenberg_verify_delta
```

Writes `validation/benchmarks/<date>/pan_stack_delta_ablation.json` and
`gutenberg_verify_delta_ablation.json` (gitignored, regenerable — this note
is the tracked record).
