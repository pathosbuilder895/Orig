# Topic-sensitivity derivation (2026-08) — NEGATIVE RESULT

**Question:** can the per-feature `TOPIC_SENSITIVITY` table that
`docs/superpowers/specs/2026-08-06-topic-invariant-scoring-design.md` designs be derived
from a public-domain, within-author, across-work corpus?

**Answer: no.** Do not ship a vector from this data. The empty
`TOPIC_SENSITIVITY = {}` currently in `original/constants.py` — which reads as
uniform sensitivity 1.0 for every feature — is more honest than any table this
corpus can produce.

## What was measured

`s_A(f) = drift_A(f) / (within_A(f) + 1e-3)`, where `drift_A` is the standard
deviation over author A's per-work means and `within_A` is the pooled
within-work standard deviation. It asks how far a feature moves when the *same
author* changes subject, relative to its ordinary chunk-to-chunk noise.

This deliberately omits the `separation` term in
`validation/genre_crossgenre_2026-08/dna_analysis.py`, which is measured
against exactly one contrast author and is the documented reason the DNA vector
failed to generalise (`original/context/weighting.py:66`). The quantity here is
purely within-author, so that particular failure mode does not apply.

Corpus: `validation/public_authors/cross_work_corpus`, expanded for this work
from 6 authors x 2 works x 3 chunks to **6 x 4 x 8 = 192 chunks** of 2500 words.

## Finding 1 — it does not generalise across authors

Leave-one-author-out: derive the vector from five authors, ask how well it
predicts the sixth author's own sensitivities (Spearman, over the 83 features
this corpus can actually speak to).

| held-out author | rho |
|---|---|
| chesterton | +0.264 |
| christie | +0.121 |
| dickens | +0.339 |
| emerson | +0.137 |
| mill | +0.168 |
| thoreau | **−0.025** |
| **mean** | **+0.168** |

rho = 0.168 is about 3% of shared rank variance, and one fold is negative. A
global constant built from this is noise wearing the shape of a measurement.

Excluding the tier-4 punctuation family it is *worse* (mean +0.124), so the
confound in Finding 2 is not the whole story — the premise that topic
sensitivity is a stable per-feature property across authors is simply not
supported here.

## Finding 2 — published corpora confound topic with transcription

The first run ranked `semicolon_colon_rate` the **2nd most topic-sensitive**
feature. The Lewis study measured it as the single most topic-*invariant*,
author-discriminating one (`validation/genre_crossgenre_2026-08/README.md`,
Finding 4). That flat contradiction was the thread worth pulling.

Cause: Project Gutenberg editions of the same author use different typographic
conventions depending on who transcribed them, and it varies *within* author,
essentially at random.

| author / work | curly quotes | straight quotes |
|---|---|---|
| chesterton/orthodoxy | 0.00 | **7.05** |
| chesterton/the_man_who_was_thursday | **23.35** | 0.00 |
| emerson/representative_men | 0.00 | **10.05** |
| emerson/essays_first_series | **1.15** | 0.00 |

Dashes are worse — perfectly bimodal, each work using either `--` or an em
dash and never both:

| author / work | `--` | em dash |
|---|---|---|
| chesterton/heretics | 0.00 | 2.15 |
| chesterton/orthodoxy | 1.65 | 0.00 |
| dickens/a_tale_of_two_cities | 5.25 | 0.00 |
| dickens/great_expectations | 0.00 | 6.25 |

Chesterton did not change his punctuation between *Orthodoxy* and *Heretics*.
His transcribers did. That variance lands in `drift_A(f)` and reads as topic
sensitivity — and it concentrates in tier 4, the char/punct fingerprint the
codebase treats as its most edit-resistant identity signal.

`extract.py` now folds curly quotes, en/em dashes and ellipses to a single
convention. It was **not enough**: mean rho went *down* (0.385 → 0.320 on the
then-current measure), and `dash_rate` pinned at the clip ceiling, because
folding em dash to `-` does not equalise it against `--`.

The general lesson is the one that matters: **within-author variation in
published books is dominated by edition and transcription, not by topic.**
A corpus of published works cannot isolate the quantity this design needs.

## Finding 3 — a quarter of the feature space is mute here

26 of 109 features have no variance anywhere in this corpus. All of tier 17
(behavioural biometrics) and tier 18 (uniformity) are disabled by default; the
citation family (`ibid_usage_rate`, `citation_density_cv`,
`source_loyalty_index`, `citation_style_consistency`) is identically zero
because novels and essays do not cite.

Those are **absent, not invariant**. On student coursework, which cites, they
are live. `derive.py` therefore omits them from the emitted table so the
scoring path's `.get(code, 1.0)` leaves them neutral, rather than shipping a
confident 0.0 meaning "never widen this feature."

This bit the analysis itself: including dead features in the leave-one-author-
out correlation reported **rho = +0.320**, because 26 features tied at exactly
0.0 for every author and rank-correlated perfectly. Excluding them gives the
true **+0.168**. That is the difference between "weak but arguably real" and
"essentially nothing" — the gap between shipping this vector and not.

## What this means for the design

The spec's per-feature table is not obtainable from public-domain literary
corpora. Two routes remain:

1. **Keep uniform sensitivity.** The shipped v0 — inflate in proportion to
   topic distance, equally across features — stands on its own and is what
   `TOPIC_VARIANCE_INFLATION` currently does. Its ceiling is 1.333x at the
   maximum reachable topic distance (`d <= 0.5`; see the flag entry in
   `CLAUDE.md`).
2. **Derive per-student, from pilot data.** Same author, same writing tools,
   same transcription pipeline, genuinely different topics — which is exactly
   what student coursework is and exactly what published books are not. This
   is the hybrid the spec deferred: a global prior shrunk toward a per-student
   estimate as baseline samples accumulate, damped by sample count the way
   `PRIOR_WEIGHT` already damps the Bayesian prior.

Route 2 is the real answer, and it reframes what shadow mode is for. Its
stated purpose was measuring the distribution of topic distance in production;
it is also the only route to the data this table needs.

## Reproducing

```bash
.venv/bin/python -m validation.public_authors.build_cross_work --force  # network
.venv/bin/python -m validation.topic_sensitivity_2026-08.extract        # ~55 min
.venv/bin/python -m validation.topic_sensitivity_2026-08.derive
```

`vectors.npy` is not committed (regenerate locally). The Lewis corpus is not
used here: its raw text is deliberately uncommitted because Lewis remains under
US/UK copyright, so the spec's Lewis-direction hold-out cannot run in CI.
Leave-one-author-out over six public-domain authors tests the same property —
cross-author generalisation — on data anyone can rebuild.
