# Fixing `resolve_genre` — problem statement and scoped approach

**Status:** ~~scoping only~~ — **implemented 2026-08-08/14** on a branch that
was already in flight when this was written, and merged alongside it. The
resolver ships as `GENRE_RESOLVER_V2` (default `off`, byte-identical); see
`docs/superpowers/specs/2026-08-08-genre-resolution-design.md` for the design
and its as-built deviations. **The four criteria in §"What would prove it
works" were fixed before that code was reviewed against them, so they are
kept verbatim below and answered in the addendum at the foot of this file —
one is met, one was not attempted, and two cannot be evaluated as written.**
Companion brief: `2026-08-13-genre-classification-approaches-brief.md`.

## The problem, precisely

`resolvers.resolve_genre` classifies a submission's genre from surface
rules. Measured failure (2026-08 cross-genre study,
`validation/genre_crossgenre_2026-08/`): **84% of an independent
10-author corpus lands in `correspondence`**, which is not a positive
classification — it is rule 8's terminal `else`. All six of Lewis's
hand-labelled genres collapse into it. Two shipped mechanisms are
casualties:

1. `GENRE_INVARIANT_WEIGHTS_ENABLED` is inert (its gate fired in 1 of 6
   leave-one-genre-out folds, and that one was classifier noise) — the
   flag is built, tested, and unenableable.
2. `manifest.baseline_match["genre_covered"]` reads ~100% covered in any
   deployment, which silently defeats the coverage telemetry.
3. Downstream, the genre-matched Bayesian prior
   (`BAYESIAN_PRIOR_ENABLED`) pools by this same genre label — a broken
   label means the "same-genre peers" pool is really an
   "everything" pool.

## Proposed approach (from the research brief)

Replace the rule chain with a **TF-IDF (word + char n-gram) linear
classifier** — calibrated logistic regression or linear SVM, one-vs-rest —
with an explicit **abstain** outcome replacing the terminal `else`:

- **Why linear + TF-IDF:** the CORE register literature puts linear
  models at ~74% F1 on 26-class register tasks (transformers: ~68–80%),
  at sklearn-only runtime cost, with per-class coefficients a professor
  can be shown ("classified as sermon because: second-person address,
  vocative openings, …"). Explainability is a product constraint, not a
  nicety.
- **Abstain, don't default:** when the max calibrated probability is
  below threshold, return `unknown` — downstream consumers already treat
  "genre not covered by baseline" conservatively, and `unknown` must
  flow through as "make no genre-based adjustment," never as a
  positive class. This alone fixes casualty #2 (coverage telemetry
  becomes honest even before accuracy improves).
- **Training data:** CORE-mapped categories + self-labeled public-domain
  theological texts (CCEL/Gutenberg — the same sources as
  `validation/public_authors/`). No labeled seminary-genre corpus
  exists; that gap is the schedule risk, not the modeling.
- **Optional second head:** sentence-transformer prototype similarity,
  A/B'd against the TF-IDF head, degrading exactly like Tier 10 when the
  dependency is absent.

## What would prove it works (decided now, before any code)

1. **Primary:** on the hand-labelled Lewis corpus (6 genres), macro-F1
   materially above the rule chain's (which is near-zero given the
   collapse), with `correspondence` no longer absorbing > 30% of
   non-correspondence texts.
2. **Distributional:** on `validation/public_authors/`, no single class
   receives > 40% of predictions (the current failure signature).
3. **Downstream re-run:** `genre_crossgenre_2026-08/genre_invariant_validate.py`
   end-to-end — the genre-invariant gate must fire in the majority of
   leave-one-genre-out folds on genuinely shifted submissions before
   `GENRE_INVARIANT_WEIGHTS_ENABLED` leaves its INERT warning.
4. **No regression:** with the resolver swapped but the flag off,
   scoring output stays byte-identical (the resolver only feeds the
   manifest until the flag is on).

## Explicit non-goals for the first iteration

- Perfect seminary-genre taxonomy — start with the six hand-labelled
  Lewis genres plus `unknown`.
- Enabling `GENRE_INVARIANT_WEIGHTS_ENABLED` — that remains its own
  gated decision after criterion 3 passes.
- Touching `resolve_topic` (separate resolver, separate failure modes,
  own spec: `2026-08-06-topic-invariant-scoring-design.md`).

---

## Addendum (2026-08-14): the shipped resolver against these four criteria

This section was written when the implementation branch was merged. The
criteria above are unedited. Two of them turn out not to be answerable as
written — recorded here as **uninformative** in the sense
`validation/calibration_gate.py` uses the word (the measurement runs, but
its result cannot discriminate a working classifier from a broken one), not
quietly restated at a bar the shipped code happens to clear.

The taxonomy changed under criteria 1 and 2. v2 carries **three** classes —
`academic_exegesis`, `scholarly_essay`, `narrative_prose` — plus `unknown`.
It does not carry `correspondence` or `sermon`: the corpus work found no
evidence for them (`sermon` had a single author, so leave-one-author-out
trained on zero others). Criteria 1 and 2 both name class sets that no
longer exist.

### 1. Primary — macro-F1 on the 6-genre Lewis corpus · **not evaluable**

The criterion names six hand-labelled Lewis genres. v2 emits three classes,
none of which is `correspondence`, so "`correspondence` no longer absorbs
> 30% of non-correspondence texts" is true by construction and measures
nothing. The corpus is also not committed
(`validation/genre_crossgenre_2026-08/`), so the macro-F1 leg cannot be run
from a fresh checkout at all. The substituted measurement is gate **G8**,
on an author-disjoint hold-out: minimum per-class precision **1.000** over
36 claimed documents, abstention **33.3%**, author-shuffled control
**0.353** against 0.333 chance. G8 is weaker than this criterion in one
respect — its hold-out was consulted repeatedly during derivation — and
stronger in another: it has a permutation control for author/genre
confounding, which this criterion does not.

### 2. Distributional — no class > 40% on `validation/public_authors/` · **uninformative**

Measured over the 61 manifest entries, 11 authors (the nine
`_full_work_cache.txt` files are fetch caches, excluded):

| | v1 rule chain | v2 |
|---|---|---|
| `correspondence` | 59 (96.7%) | — *(no such class)* |
| `scholarly_essay` | 2 (3.3%) | 21 (34.4%) |
| `narrative_prose` | — | 6 (9.8%) |
| `unknown` | — *(no such outcome)* | 34 (55.7%) |
| **largest class** | **96.7% — FAIL** | **55.7% — FAIL** |

v2 fails the criterion as written, and would still fail it counting claimed
labels only (21/27 = 77.8%). **But so would a perfect classifier**, which is
why the number is not reported as a failure. `public_authors` is an
*authorship* corpus — 11 authors, no genre labels in its manifest, never
built to be genre-balanced. Classifying each work by its published record:

| true mode of discourse | n | share |
|---|---|---|
| expository (Boethius, Chesterton, Emerson, James, Mill, Newman, Thoreau) | 38 | 62.3% |
| narrative (Augustine, Douglass) | 12 | 19.7% |
| sermon (Edwards) | 6 | 9.8% |
| devotional (Kempis) | 5 | 8.2% |

The true largest class is **62.3%**. A classifier that is right about every
document therefore puts 62.3% of predictions in one class and fails a ≤ 40%
bar. The criterion assumes a balanced corpus; this corpus is not one, and on
it the bar cannot separate a good classifier from a bad one. (v1's 96.7% is
still diagnostic, because 96.7% exceeds *any* plausible true share — that is
the collapse the criterion was written to catch, and it reproduces here at
96.7% against the 84% the body of this document reports for the Lewis
corpus.)

The informative cut of the same corpus is per-class precision by true mode:

| true mode | n | abstained | claimed |
|---|---|---|---|
| expository | 38 | 53% | `scholarly_essay` 18 |
| narrative | 12 | 58% | `narrative_prose` 5 |
| sermon | 6 | 50% | `scholarly_essay` 3 ⚠ |
| devotional | 5 | 80% | `narrative_prose` 1 ⚠ |

On the two modes v2 carries a label for, **23 of 23 claimed labels are
correct** and the two classes never cross-contaminate — an independent
corroboration of G8's precision leg on 11 authors that were not part of the
genre work, at the cost of abstaining on over half the corpus.

⚠ The rows worth arguing about are the 11 out-of-taxonomy documents. v2
abstained on 7 and assigned a nearest neighbour to 4. Whether those 4 are
errors depends on how the label is read: under the **mode-of-discourse** axis
the taxonomy was redefined on, an Edwards sermon *is* expository, arguing
claims at an audience, and `scholarly_essay` is defensible. Under the
**register** reading its name invites, it is wrong. This is a live defect in
the label's *name*, not in the model, and it is the first evidence that a
3-class taxonomy meeting a world with more than 3 genres does not always
abstain — it abstained on only 7 of 11 here. Real submissions will contain
sermons. Weigh this when reading the shadow soak.

### 3. Downstream re-run — genre-invariant gate fires in a majority of folds · **not attempted**

Not run, and not claimed. `GENRE_INVARIANT_WEIGHTS_ENABLED` keeps its
warning in `CLAUDE.md`, with the blocker restated: the classifier is no
longer the reason it cannot be enabled, but the attenuated tier set
(2/3/9/10, `weighting.GENRE_MISMATCH_ATTENUATE_TIERS`) has never been
measured by anything. This criterion remains the correct bar for that flag
and is still open.

### 4. No regression — flag off is byte-identical · **met**

`GENRE_RESOLVER_V2=off` is the default and dispatches to the v1 body
preserved verbatim as `resolvers._resolve_genre_v1`; equality is tested over
the committed corpora in `tests/context/test_genre_dispatch.py`. The
criterion's parenthetical — "the resolver only feeds the manifest until the
flag is on" — is **too weak, and was wrong when written**: the genre label
also drives tier-16 muting and T8/T13 anchor expansion
(`context/manifest.py`, `quantum/state.py`) and is a pooling key for the
Bayesian prior (`store.py:get_genre_stats`). Turning the resolver on is a
score- and drift-gating change, not a cleanup. That is why it shipped behind
a flag with a `shadow` mode rather than as a straight replacement.

### Still open

The one number no corpus can supply: the **abstention rate on real student
submissions**. Every figure above and in G8 comes from 19th-century
published prose plus 25 seminary papers. Run `GENRE_RESOLVER_V2=shadow` on
the deployment (inert — `primary` still comes from v1) and read it with
`validation/genre_2026-08/read_shadow_log.py`.
