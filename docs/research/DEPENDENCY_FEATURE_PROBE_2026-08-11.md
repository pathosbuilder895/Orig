# Do dependency-parse features earn a place in the 109-dim vector?

The production pipeline is 109 features over 18 tiers, of which exactly two are
syntax-complexity numbers: `subordination_ratio` — a count of SCONJ *tokens*
divided by sentence count, i.e. a POS tally rather than a dependency relation —
and `clause_depth_mean`. Meanwhile a full dependency parse is already computed
and thrown away: `original/features/tier5.py::_get_dep_depths` walks
`token.children` for a per-sentence max depth and discards every arc label,
every arc direction, every arc length, and all of `token.morph`, which is
referenced nowhere in the repository. Tier 2's docstring still claims "no
dependency parser available in offline deployment"; that has been stale since
Tier 5 started loading one.

The literature's claim — the one under test — is that grammatical habits are
comparatively robust to topic and paraphrase, because they are choices about
structure rather than subject matter.

Fourteen candidates were built (`validation/verify/dependency_signals.py`):
seven dependency-relation rates (`nsubj`, `dobj`, `advcl`, `ccomp`, `relcl`,
`conj`, `amod`, each per 100 word tokens), head→child POS-pair entropy, mean
dependency distance and its coefficient of variation, left-branching ratio,
length-normalised tree depth, an arc-based subordination-to-coordination ratio,
and `token.morph` feature entropy.

## Verdict: G-P5a is **UNINFORMATIVE**. Frozen list: **empty**. No production code.

Every one of the fourteen candidates cleared every pre-registered criterion.
That is not a fourteen-feature result; it is a gate with no discriminating
power, and under this repository's three-valued convention
(`validation/README.md`) a gate that cannot separate the cases it exists to
separate is **uninformative** and must never be quoted as a pass.

The demonstration is in [the calibration baseline](#the-gate-does-not-separate-anything):
the seven features **already in the vector** would also clear every bar, and no
candidate beats the best of them. "Passes G-P5a" therefore means "is an
ordinary stylometric feature," not "adds something the vector lacks."

Phase 5B does not run. `original/constants.py` is untouched, the committed
AI-detector artifact is not retrained, no dimension literals move, and no
baselines are re-extracted.

## Pre-registered criteria

Fixed in `validation/verify/dependency_probe.py` and committed in `b87c4fca`,
**before the probe was run for the first time**. The results commit is separate
and later. A candidate was to be kept only if it cleared all of:

| id | criterion | threshold |
|---|---|---:|
| G-P5a.1 | same-author vs different-author AUC | ≥ 0.550 |
| G-P5a.2 | within-author stability, ICC(1) | ≥ 0.30 |
| G-P5a.3 | max abs Pearson r against the seven tier-5 features | < 0.90 |
| G-P5a.4 | max abs Pearson r against higher-AUC survivors | < 0.90 |
| G-P5a.5 | corroboration corpus AUC does not invert | ≥ 0.50 |

0.550 was chosen because with ~1,000 same-author pairs the standard error of an
AUC near 0.5 is about 0.015, putting 0.550 more than three standard errors
above chance; it is also the floor the task brief proposed for a single weak
member of a 109-dim ensemble. 0.30 is the conventional lower edge of "moderate"
ICC reliability.

Pair construction was pre-registered too. **Same-author pairs are cross-group
only** — cross-fandom on PAN, cross-work on the public-author corpus — because
two documents from one fandom share topic as well as author, and a feature that
tracks topic would be flattered by them. Different-author pairs are every
cross-author document pair, with no sampling. The feature-level comparison is
the absolute difference between the two documents' values; the discriminant is
its negation, so "small difference" ranks as "same author."

## Corpora

**Primary** — PAN 2020, development partition: 120 authors x (3 baseline + 3
probe) documents in two disjoint fandoms, 2,500-word deterministic windows.
720 documents, **1,080 cross-fandom same-author pairs** and **257,040
different-author pairs**. The 12 locked and 40 calibration authors that every
`pan_stack` ablation in this repo evaluates on were never loaded, so this study
cannot contaminate them.

**Corroboration** — `validation/public_authors/cross_work_corpus`: 6 authors x
2 works x 3 chunks, same-author pairs restricted to cross-work. **54
same-author** and **540 different-author** pairs. That is far too small to
support a magnitude claim and is used only for the directional non-inversion
check in G-P5a.5. (The larger `validation/public_authors/manifest.json` corpus
was rejected: nine of its eleven authors are represented by chunks of a *single
work*, so its same-author pairs are same-work pairs and would have inflated
every AUC.)

There is no RNG anywhere in either harness. Author selection is PAN's existing
deterministic SHA-256 ordering and document windows are its existing
deterministic `_fixed_window`; repeat runs are bit-identical.

## Results

AUC and ICC(1) are on PAN development. "max abs r" is the largest absolute
Pearson correlation against any of the seven tier-5 features as the production
pipeline computes them. "CV R² vs 109-dim" is the post-hoc measure described
below. Sorted by AUC; **every row passed the gate**.

| feature | AUC | ICC(1) | max abs r (existing) | with | CV R² vs 109-dim | cross-work AUC |
|---|---:|---:|---:|---|---:|---:|
| `dep_distance_mean` | 0.647 | 0.674 | 0.70 | `clause_depth_mean` | 0.72 | 0.773 |
| `dep_conj_rate` | 0.643 | 0.639 | 0.26 | `clause_depth_mean` | 0.24 | 0.830 |
| `dep_nsubj_rate` | 0.630 | 0.638 | 0.62 | `adjective_rate` | 0.71 | 0.730 |
| `dep_normalized_tree_depth` | 0.626 | 0.606 | 0.82 | `clause_depth_mean` | 0.79 | 0.707 |
| `dep_ccomp_rate` | 0.614 | 0.643 | 0.39 | `noun_verb_ratio` | 0.52 | 0.619 |
| `dep_subord_coord_ratio` | 0.607 | 0.596 | 0.23 | `subordination_ratio` | 0.19 | 0.719 |
| `dep_left_branching_ratio` | 0.605 | 0.556 | 0.26 | `clause_depth_mean` | 0.19 | 0.793 |
| `dep_amod_rate` | 0.597 | 0.548 | 0.85 | `adjective_rate` | 0.72 | 0.714 |
| `dep_distance_cv` | 0.593 | 0.306 | 0.49 | `clause_depth_mean` | 0.36 | 0.747 |
| `dep_morph_entropy` | 0.593 | 0.488 | 0.49 | `pos_trigram_entropy` | 0.49 | 0.510 |
| `dep_advcl_rate` | 0.587 | 0.480 | 0.42 | `subordination_ratio` | 0.36 | 0.540 |
| `dep_pos_pair_entropy` | 0.579 | 0.466 | 0.66 | `pos_trigram_entropy` | 0.48 | 0.610 |
| `dep_dobj_rate` | 0.559 | 0.405 | 0.31 | `adjective_rate` | 0.17 | 0.620 |
| `dep_relcl_rate` | 0.557 | 0.395 | 0.49 | `clause_depth_mean` | 0.34 | 0.662 |

G-P5a.4 dropped nothing: the largest mutual correlation among candidates is
`dep_conj_rate` ~ `dep_subord_coord_ratio` at r = −0.834, then
`dep_distance_cv` ~ `dep_distance_mean` at +0.760 and `dep_distance_mean` ~
`dep_normalized_tree_depth` at −0.739. All sit under the 0.90 bar while being
obviously three descriptions of two ideas.

### The gate does not separate anything

The number G-P5a.1 could not supply on its own is what an AUC of 0.60 *means*
here. Running the **seven features already in the production vector** through
the identical pair construction answers it:

| existing tier-5 feature | AUC | ICC(1) | would pass G-P5a.1 and .2? |
|---|---:|---:|---|
| `adverb_rate` | 0.650 | 0.680 | yes |
| `subordination_ratio` | 0.634 | 0.641 | yes |
| `adjective_rate` | 0.619 | 0.583 | yes |
| `clause_depth_mean` | 0.608 | 0.664 | yes |
| `pos_bigram_entropy` | 0.599 | 0.576 | yes |
| `pos_trigram_entropy` | 0.598 | 0.592 | yes |
| `noun_verb_ratio` | 0.582 | 0.503 | yes |

The existing features span AUC 0.582–0.650 and ICC 0.503–0.680. The candidates
span AUC 0.557–0.647 and ICC 0.306–0.674. **The candidate band lies inside the
existing band, and not one candidate beats the best existing feature**
(`dep_distance_mean` 0.647 vs. `adverb_rate` 0.650).

So the pre-registered bars admit everything already in the vector as readily as
everything proposed for it. A filter that accepts both the thing you have and
the thing you are considering buying has not told you to buy anything. This is
the same reasoning `validation/README.md` applies to a gate whose criterion is
unreachable at the current corpus size — the verdict is uninformative, not
pass.

This calibration baseline was computed **after** the gate result was seen. It
is reported as what it is: a description of why the pre-registered criteria are
not selective. It is not a new criterion, and nothing in this document treats
it as one.

### Redundancy against the vector as a whole

Pairwise `|r| < 0.90` answers "is this a near-copy of *one* existing feature?"
The question that governs Phase 5B's cost is "is this predictable from the
existing vector *as a whole*?" — a candidate can sit at r ≈ 0.6 against every
production feature individually and still be a near-exact linear combination of
four of them.

`validation/verify/dependency_redundancy.py` measures that: each candidate
regressed on the 109-dim production vector (81 of the 109 columns are
non-constant on this corpus; tiers 17 and 18 are disabled placeholders), ridge
with the penalty chosen inside each training fold, folds grouped by author so a
candidate cannot be predicted from the same author's other documents. All 720
documents were already present in the repo's content-addressed `FeatureCache`,
so this cost nothing beyond the parse.

Four candidates are largely reconstructible from what already exists —
`dep_normalized_tree_depth` (CV R² 0.79), `dep_amod_rate` (0.72),
`dep_distance_mean` (0.72), `dep_nsubj_rate` (0.71) — despite all four passing
the pairwise 0.90 test. `dep_amod_rate` is essentially "count the ADJ tokens
that attach as modifiers," and `adjective_rate` already counts ADJ tokens
(r = 0.85). `dep_normalized_tree_depth` was designed to be distinct from
`clause_depth_mean` by dividing out sentence length; at r = −0.82 and CV R²
0.79 it did not succeed enough to matter.

Four are genuinely not reconstructible: `dep_dobj_rate` (0.17),
`dep_subord_coord_ratio` (0.19), `dep_left_branching_ratio` (0.19),
`dep_conj_rate` (0.24). Coordination-vs-subordination balance and branching
direction are the two ideas in the candidate set that the current vector really
does not contain.

## Cost

Measured over twelve 2,581-word documents, warm model:

| | ms/document |
|---|---:|
| spaCy parse (`en_core_web_sm`, tier 5's disable list) | 311 |
| **all fourteen candidates, from an already-parsed `Doc`** | **6.5** |
| `extract_tier5` exactly as production runs it today | 2,396 |

The candidate set costs **2.1% of one parse**. A shared parse is not merely
achievable — tier 5 currently parses each document **seven** times, because
`_get_pos_tags` is called independently by six feature functions and
`_get_dep_depths` parses again. Adding a dependency tier that reuses one parse
would cost about 0.3% of what tier 5 already spends, and fixing tier 5's
seven-fold re-parse would save roughly 2 seconds per document — a far larger
win than anything in this study, and available regardless of its outcome.
(These three numbers are wall clock and vary a few percent between runs; every
other number in this document is bit-identical across runs.)

**Cost is not the reason to decline these features.** The reason is evidential.

## What this probe does *not* establish

- **It does not measure incremental value.** A per-feature pairwise AUC says a
  feature is individually non-degenerate. It says nothing about whether adding
  it to a 109-dim ensemble moves verification performance, which is the only
  question that justifies the Phase 5B cascade. The design that answers it is
  the one Phases 1 and 2 already used: a `pan_stack` ablation with and without
  the candidate block, pre-registered, evaluated once on the locked partition.
- **One corpus.** PAN is cross-*fandom*, which is topic disjointness within
  fan fiction — not cross-genre within an author, and not student coursework.
  The corroboration corpus is six public-domain essayists and novelists at 54
  same-author pairs; it can detect an inversion and nothing finer.
- **Nothing here shows these features survive paraphrase.** That was the
  literature claim that motivated the probe and it was not tested. No
  paraphrased or LLM-rewritten pairs appear anywhere in this study.
- **Nothing here shows they help with the failure this project actually has** —
  cross-topic false positives on real student submissions, where raw
  `deviation_score` reaches AUC 0.387 (inverted) on the leave-one-genre-out
  Lewis corpus.
- **The parser is a dependency.** Every candidate returns its neutral value if
  spaCy is unavailable, exactly as tier 5's do today; a tier of fourteen such
  features would widen an existing silent-degradation surface.

## If this is pursued

Not as Phase 5B, and not on this evidence. A future study should:

1. Take **two** features, not fourteen: `dep_conj_rate` and
   `dep_left_branching_ratio` are the pair with the best combination of
   mid-band AUC (0.643, 0.605), adequate stability (ICC 0.639, 0.556), low
   reconstructibility from the existing vector (CV R² 0.24, 0.19), and the
   strongest corroboration-corpus agreement (0.830, 0.793). They are also two
   different ideas — coordination density and branching direction — rather than
   two spellings of one. `dep_subord_coord_ratio` is not a third: it is
   `dep_conj_rate` at r = −0.834.

   **This shortlist is post-hoc and is not a gate pass.** It is named so a
   future pre-registration has somewhere to start, in the same spirit as the
   compression study's refusal to claim its unregistered NCD arm.

2. Pre-register on **incremental fusion performance**, not per-feature AUC:
   ΔAUC / Δcllr on a locked partition with the block added, mirroring
   `validation/verify/pan_stack_compression.py`.

3. Fix `_get_pos_tags`' seven-fold re-parse first. It is a 2-second-per-document
   saving that needs no gate.

## Reproducing

```bash
~/Desktop/Original/.venv/bin/python -m validation.verify.dependency_probe        # ~280 s
~/Desktop/Original/.venv/bin/python -m validation.verify.dependency_redundancy   # ~330 s
```

Requires the PAN 2020 cache at `.benchmark_cache/pan/2020`
(`scripts/fetch_benchmark_data.py --pan`) and spaCy's `en_core_web_sm`. The
redundancy harness additionally requires the 109-dim `FeatureCache` at
`.benchmark_cache/features/feature_vectors.npz`, which already contains all 720
documents; it raises rather than silently re-extracting if any are missing.
Both runs are deterministic: the probe was run twice at full size and every
AUC, ICC, correlation and pair count matched exactly — only the wall-clock
fields differ. Reports:
`validation/verify/dependency_probe_results.json` and
`validation/verify/dependency_redundancy_results.json`.
