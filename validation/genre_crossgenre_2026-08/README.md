# Cross-genre recognition study (2026-08)

**Question:** when a claimed author's baseline is built from one set of
genres, does the scoring engine still recognize their own writing in a genre
it's never seen from them — and correctly tell it apart from a different
author's writing in that genre?

This is a different axis than `validation/public_authors/` (which measures
top-1 attribution across an author roster, each author writing mostly one
kind of thing). Here genre is the manipulated variable and author identity
is held fixed, isolating whether stylometric identity survives a register
shift.

## Corpus

- **Genuine:** 13 C.S. Lewis works across 6 genre buckets — Narnia (fantasy),
  the Space Trilogy (sci-fi), theology/apologetics, memoir, literary essays,
  and epistolary satire (*The Screwtape Letters*). Sourced from
  `gutenberg.ca` (Canadian public domain; Lewis died 1963, grandfathered
  under Canada's pre-2022 life+50 rule — **still under copyright in the
  US/UK**, so the raw text is not committed here; see `clean_corpus.py`'s
  `MANIFEST` for exact filenames/URLs to re-fetch).
- **Impostor:** G.K. Chesterton, 4 works (*Orthodoxy*, *Heretics*, *All
  Things Considered*, *The Wisdom of Father Brown*) — genuinely US public
  domain. `validation/public_authors/corpus/chesterton/` already has
  *Orthodoxy* committed; the other 3 are not yet added there.
- 35 chunks/work, evenly spaced, ~700 words each (`extract_vectors.py`,
  `CAP_PER_WORK`).

## Pipeline

1. `clean_corpus.py` — strip Gutenberg boilerplate/HTML, chunk into
   submission-sized samples. Requires a populated `raw/` dir (not committed;
   fetch per the MANIFEST above).
2. `extract_vectors.py` — `original.features.pipeline.feature_vector()` on
   every chunk, cached to `vectors.npy` / `vectors_meta.json` (also not
   committed — regenerate locally, ~10 min for 560 chunks).
3. `sweep_harness.py` — leave-one-genre-out: build a Lewis baseline from the
   other 5 genres, score the held-out genre (genuine) and a held-out
   Chesterton half (impostor) via `original.quantum.scoring.score()`
   in-memory. Reports AUC separating genuine from impostor, per genre
   bucket, under the raw `deviation_score` vs. the impostor-relative
   `llr_deviation_score` (`NULL_MODEL=impostor`).
4. `action_mode_sweep.py` — same corpus, but measures real recommended
   **actions** (not just raw scores) under each `llr_action_mode` value.

## Finding 1: the raw score fails at cross-genre recognition

| genre | raw `deviation_score` AUC | `llr_deviation_score` AUC |
|---|---|---|
| Narnia | 0.076 | 0.969 |
| Space Trilogy | 0.397 | 0.927 |
| Theology | 0.374 | 0.908 |
| Memoir | 0.350 | 0.952 |
| Essays (n=13) | 0.518 | 0.833 |
| Satire (Screwtape only) | 0.608 | 0.590 |
| **mean** | **0.387** | **0.863** |

AUC < 0.5 means the ranking is *inverted* — genuine cross-genre Lewis scores
*higher* deviation (looks more anomalous) than a different author's writing,
worst on Narnia (children's fantasy baselined on his adult work). The
impostor-relative `llr_deviation_score` recovers this almost completely,
confirming on an independent corpus what `null_pool.py`'s own docstring
already claims from the seminary benchmark (AUC 0.8125 → 1.0).

## Finding 2: that fix was documentation-only until now

`NULL_MODEL=impostor` computed `llr_deviation_score` but it was **attach-only
— it never touched the recommended action**. The metric that actually
recognizes the author across genres wasn't wired to the thing a professor
sees. `original/quantum/scoring.py` now has `ScoringConfig.llr_action_mode`
(default `"shadow"`, i.e. still a no-op) plus three real modes, gated behind
that flag so nothing changes unless explicitly opted in. See
`tests/quantum/test_llr_action_modes.py` for the unit/integration tests.

## Finding 3: only one of the three candidate modes is safe

Measured on real recommended actions, both false positives (genuine Lewis
wrongly escalated) and true positives (Chesterton correctly caught), at
**matched severity bars** on both sides:

| mode | Lewis FP @schedule_conversation+ | Lewis FP @escalate | Chesterton TP @schedule_conversation+ | Chesterton TP @escalate |
|---|---|---|---|---|
| shadow (today's shipped behavior) | 50.1% | 11.0% | 33.3% | 3.2% |
| **gate** | **42.4%** | **7.1%** | 31.9% | 2.2% |
| trigger | 50.1% | 11.0% | 33.3% | 3.2% |
| blend | 2.5% | 0.0% | 3.2% | 0.0% |

- **`gate`** (may only downgrade an action one severity step when llr
  confidently reads "more like the claimed author") is a real, modest,
  *safe* win — cuts genre-driven false positives with only a 1–2pt cost to
  Chesterton's catch rate. **Recommended.**
- **`trigger`** (may only upgrade `no_action`→`monitor`) is a no-op on this
  corpus — cross-genre submissions almost never land at `no_action` in the
  first place, so there's nothing for it to catch. Not disproven, just
  untested for the scenario it would actually help (same-genre cold starts).
- **`blend`** (50/50 average of `deviation_score` and `llr_deviation_score`)
  looked best on false-positive rate *alone* — until checked against
  Chesterton's true-positive rate at the same severity bar, where it
  collapses from 33%→3% (schedule_conversation+) and 3%→0% (escalate). It
  isn't discriminating better, it's compressing everything toward
  `monitor` — including genuine impostors. **Do not enable.**

## Finding 4: the authorial DNA lives in different tiers than the priors assume

`dna_analysis.py` measures, per feature: how much it drifts across Lewis's
six genres (genre_drift + within_noise) vs. how far apart Lewis and
Chesterton sit on it (separation). The ratio is a "DNA score" — high means
the feature barely moves when the same author changes register, yet still
separates authors.

Top of the ranking: `semicolon_colon_rate` (tier 4), `lexical_chain_density`
(tier 2), `adjective_rate` (tier 5), `dash_rate`, `contraction_rate`,
`type_token_ratio`, `hapax_legomena_rate`, `mean_sentence_length`, and the
tier-8 prosodic-rhythm features. Bottom (genre chameleons / no signal):
`theological_register_score`, `claim_density`, `imperative_density`,
`burstiness`, `function_word_ratio`.

Checked against the hand-assigned `TIER_WEIGHTS` priors, two disagreements
stand out on this corpus: **tier 8 (prosodic rhythm) is underweighted**
(median DNA 0.49, highest of any tier, prior only 1.1) and **tier 16
(citation fingerprint) + tier 12 (tension arc) are overweighted** (priors
1.4/1.2, median DNA 0.08/0.00 — mostly dead or genre-bound here). Tier 6
("idiosyncratic", prior 1.4) is mid-pack, not top.

`dna_weighted_logo.py` then validates causally, leakage-free (weights
derived per-fold from the 5 baseline genres + calibration half only):

| scoring route | mean cross-genre AUC | satire (Screwtape) |
|---|---|---|
| static tier weights, raw deviation | 0.387 | 0.608 |
| dna weights, raw deviation | 0.529 | 0.775 |
| dna² weights, raw deviation | 0.592 | 0.806 |
| static weights, llr route | 0.863 | 0.590 |
| **dna² weights + llr route** | **0.898** | **0.811** |

Two mechanisms, two different failure modes: DNA weights mute the
genre-chameleon features (recovering roughly half the raw-score gap alone —
the ceiling is that the baseline *mean* is still genre-shifted, which only
the impostor-relative reference can fix), while the llr route fixes the
reference point but was blind-sided by Screwtape's deliberate voice-shift.
Combined, each covers the other's weakness — the put-on voice changes
word choice and rhetoric but not semicolon habits and sentence rhythm.

Caveat: separation is measured against ONE contrast author. The DNA ranking
is directional evidence for which tiers deserve reweighting, not a
production-ready weight vector; re-derive against a multi-author corpus
(e.g. `validation/public_authors/`) before touching `TIER_WEIGHTS`.

## Finding 5: tier ablation — where the sand actually is (`tier_probe.py`)

Leave-one-tier-out from the combined (DNA-weighted + llr) score, plus a
weight-sharpness sweep. Reference dna² = 0.8984.

**Sharpness:** `dna^1` (linear) beats `dna^2` overall (0.9068 vs 0.8984) and
`dna^3` collapses (0.8451) — gentler weighting wins on average. But dna² is
better on the adversarial fold (Screwtape: 0.811 vs 0.752), so the choice is
average-case vs worst-case; for an integrity tool the adversarial case
arguably matters more. Take both to the multi-author corpus.

**Load-bearing tiers** (removal hurts, in order): tier 4 char/punct is the
keystone (−0.057, by far the largest single loss — the score partially
collapses without punctuation habits); then tier 6 idiosyncratic (−0.012),
tier 2 discourse (−0.012), tier 5 POS/syntax (−0.009), tier 16
block-quote/citation (−0.008), tier 1 surface (−0.003).

**Noise or redundant here:** tiers 3, 9, 10 (removal neutral-to-positive —
drop_t3 actually improved the score), and tiers 7, 8, 13, 14, 15 (≈ −0.001
or less each).

Two corrections to Finding 4's tier reading:
- Tier 8 (prosodic rhythm) has the highest per-feature *median* DNA, but
  removing it barely moves the combined score (−0.0007) — its information is
  largely **redundant** with tiers 1/13's length-and-rhythm features. High
  invariance ≠ unique contribution.
- Tier 2 (discourse) is production-downweighted to 0.6 as "topic-sensitive,"
  yet its removal costs −0.012 — `lexical_chain_density` (DNA 0.91, #2
  globally) is genuine authorial signal being suppressed by the tier-level
  prior. Per-feature weighting matters; tier-level weights paint with too
  broad a brush.

Forced tier diversity (`tier_top2`) did NOT beat the global ranking — tiers
do not carry enough independent information to justify quota-based
selection.

Methodology caveat: this sweep reads the held-out AUC ~21 times, so the
winning variant is partially fitted to this Lewis/Chesterton split. Treat
`dna^1` / `dna^2` + llr as the two hypotheses to confirm on
`validation/public_authors/`.

## Finding 6: multi-author test — DNA weights are a genre-shift specialist, not a universal upgrade

`multi_author_extract.py` + `multi_author_validate.py` froze the
Lewis-derived DNA weights (this corpus never touched their derivation) and
tested them on 10 authors from `validation/public_authors/` — per author:
60/40 baseline/held-out split, leave-target-out impostor pool, genuine vs
9-other-author AUC.

| config | mean AUC | min AUC |
|---|---|---|
| static raw | 0.867 | 0.715 |
| **static + llr** | **0.952** | **0.842** |
| dna¹ + llr | 0.929 | 0.838 |
| dna² + llr | 0.861 | 0.704 |

Two conclusions, one negative and one strongly positive:

- **The DNA weights did NOT generalize** to the same-register multi-author
  setting — static weights beat them (dna¹ −0.023, dna² −0.091). The reason
  is structural, not a bug: DNA weights deliberately mute genre-sensitive
  features. When each author writes in ONE stable register (this corpus),
  those features carry real between-author signal, so muting them costs
  accuracy. When one author spans MANY registers (the Lewis corpus), those
  same features are the false-positive engine, and muting them is a large
  win (0.863 → 0.907). Same mechanism, opposite sign — conditional on
  whether the submission's genre matches the baseline's.
- **The llr route generalized emphatically** — its second independent
  confirmation (third counting the seminary benchmark in `null_pool.py`):
  mean 0.867 → 0.952, worst-author floor 0.715 → 0.842, Augustine a
  perfect 1.0.

Production implication: do NOT globally reweight `TIER_WEIGHTS` from the DNA
ranking. The right shape is **conditional weighting** — invariance-based
weights only when the submission's genre falls outside the baseline's genre
coverage — which is exactly what the Phase 5 adaptive-weights/context-
manifest infrastructure (`ADAPTIVE_WEIGHTS_ENABLED`, `original/context/`)
already exists to do. The DNA vector becomes one more weight profile that
pipeline can select, not a new global default.

Incidental discovery (2026-08-01): the committed `validation/public_authors/`
corpus was contaminated — `edwards/` is entirely a French sci-fi novel,
`douglass/self_made_men.txt` is Stephen Leacock, James parts 06–08 are index
back-matter, mill/kempis part files are stubs, and Wikisource nav chrome
pollutes several authors. `multi_author_extract.py` documents the exclusions
it applies; the corpus itself (and the Test 2 benchmark results derived from
it) needs a proper rebuild — flagged as a separate task.

## What this does and doesn't prove

This validates one dimension: does authorial signal survive a genre shift,
and can a config change fix it without trading away detection of an actual
impostor. It does **not** by itself establish beta-readiness — that also
depends on the rest of the test suite, FERPA/auth handling, and validation
against real (not public-domain-substitute) pilot data. `gate` should still
be run against `scripts/measure_genre_prior_scope.py`-style real data before
a pilot cohort depends on it in production.

## Reproducing

```bash
# 1. populate raw/ per clean_corpus.py's MANIFEST (fetch the listed URLs)
.venv/bin/python validation/genre_crossgenre_2026-08/clean_corpus.py
.venv/bin/python validation/genre_crossgenre_2026-08/extract_vectors.py   # ~10 min
.venv/bin/python validation/genre_crossgenre_2026-08/sweep_harness.py
.venv/bin/python validation/genre_crossgenre_2026-08/action_mode_sweep.py
.venv/bin/python validation/genre_crossgenre_2026-08/dna_analysis.py
.venv/bin/python validation/genre_crossgenre_2026-08/dna_weighted_logo.py
.venv/bin/python validation/genre_crossgenre_2026-08/tier_probe.py        # ~15 min
.venv/bin/python validation/genre_crossgenre_2026-08/multi_author_extract.py   # ~5 min
.venv/bin/python validation/genre_crossgenre_2026-08/multi_author_validate.py
.venv/bin/python -m pytest tests/quantum/test_llr_action_modes.py -v
```
