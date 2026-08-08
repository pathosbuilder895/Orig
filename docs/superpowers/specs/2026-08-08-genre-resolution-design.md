# Genre Resolution v2 — Design

**Date:** 2026-08-08
**Status:** Approved, not yet implemented
**Owner:** context / validation
**Flag:** `GENRE_RESOLVER_V2` (default `off`)

Unblocks `GENRE_INVARIANT_WEIGHTS_ENABLED`, inert since the 2026-08 cross-genre
study (`validation/genre_crossgenre_2026-08/`) and documented as blocked on
this resolver at `original/context/weighting.py:76`.

---

## Problem

`resolvers.resolve_genre` does not classify genre. It sorts almost everything
into one bucket.

Measured 2026-08-08 over every committed corpus — 356 documents across 23
provenance groups, spanning seminary papers, 19th-century political pamphlets,
oratory, philosophical essays, devotional theology and AI-generated text:

| label | share |
|---|---|
| `correspondence` | 86% |
| `scholarly_essay` | 9% |
| `personal_essay` | 3% |
| `blog_post` | 2% |
| `academic_exegesis`, `sermon`, `creative_fiction`, `structured_template` | **0%** |

Four of the eight labels are never produced at all. Seminary papers — the
product's actual target genre — classify as `correspondence` (14), `blog_post`
(7) and `personal_essay` (4), and never once as `academic_exegesis`.

`correspondence` is rule 8's terminal `else`, not a positive class. So the
modal output of this resolver is "none of the above", reported with a
hardcoded `confidence` of 0.5.

### Root cause

The decision tree keys on signals that are absent from ordinary prose. Median
values against the thresholds in `GENRE_RULES`:

| signal | threshold | seminary | lincoln | douglass | fed_hamilton | chesterton |
|---|---|---|---|---|---|---|
| citation density | ≥ 1.5 | **0.00** | 0.10 | **0.00** | **0.00** | **0.00** |
| signal verbs | ≥ 3 | **0** | **0** | **0** | **0** | 1.5 |
| imperative density | ≥ 3.0 | **0.00** | **0.00** | **0.00** | **0.00** | 0.04 |
| looks structured | — | **0%** | **0%** | **0%** | **0%** | **0%** |
| mean sentence length | — | 15.5 | 21.6 | 22.5 | 34.5 | 20.9 |
| first-person ratio | — | 0.11 | 0.35 | 0.38 | 0.21 | 0.32 |

Consequences, rule by rule:

1. **Rules 1–2** (`academic_exegesis`, `scholarly_essay`) require
   `signal_verb_total >= 3`. Median is 0 everywhere. Unreachable.
2. **Rule 3** (`sermon`) requires `imperative_density >= 3.0` per 100 words.
   Median is 0.00 everywhere, including oratory. Unreachable.
3. **Rule 6** (`creative_fiction`) requires `re.search(r'"[^"]{1,80}"', text)` —
   **straight double quotes only**. Douglass is 0% straight / 64% curly;
   fed_hamilton 0% / 36%. Gutenberg-sourced prose uses typographic quotes, so
   the rule cannot fire on it. This is a plain bug independent of the
   calibration problem.
4. **Rule 7** (`structured_template`) requires bullet/heading markup. 0% of
   documents. Unreachable on prose, though legitimately reachable on real
   student submissions.
5. **Rules 4–5** (`personal_essay`, `blog_post`) are the only live branches,
   and both are gated on sentence length: rule 4 needs `msl <= 18`, rule 5
   needs `msl <= 14`. Lincoln (21.6), Douglass (22.5) and Chesterton (20.9)
   all clear the 0.30 first-person bar and then fail the length clause.

The two signals that *do* separate these groups — mean sentence length and
first-person ratio — are each conjoined with a signal that is always zero. The
tree therefore falls through to rule 8, and `cite_density > 0` is false, so:
`correspondence`.

This is not a threshold that needs nudging. The rule set was written against
an imagined corpus and never measured against a real one.

### Why it matters beyond the inert gate

Genre is not report-only metadata. It drives four behaviours:

| consumer | effect |
|---|---|
| `context/manifest.py:223` | `creative_fiction` → **mute tier 16** |
| `context/manifest.py:225`, `quantum/state.py:427` | academic/sermon genres → **add T8, T13 as anchor tiers**, which gates drift detection on baseline ingestion |
| `store.py:1275` `get_genre_stats(genre, tenant, …)` | the label is a **Bayesian prior pooling key** |
| `context/baseline_match.py:291` `genre_covered_by_baseline` | the `GENRE_INVARIANT_WEIGHTS_ENABLED` attenuation gate |

The labels that currently never fire — `creative_fiction`,
`academic_exegesis`, `sermon` — are exactly the ones wired to T16 muting and
anchor-tier expansion. **Making the classifier work therefore changes scores
and changes drift gating.** A correct classifier is not a safe drop-in
replacement for a broken one, and this design treats it as a score-affecting
change throughout.

---

## Approach

Two stages behind one flag, honesty before accuracy.

**Stage 1 — abstention.** Teach the resolver to say "I don't know". The
terminal `else` returns `unknown`; `confidence` stops being a hardcoded
constant and starts carrying a real value. Nothing downstream may treat
ignorance as a genre.

**Stage 2 — discrimination.** Replace the rule tree with a calibrated
classifier trained on a hand-labelled corpus, abstaining below a confidence
floor.

Stage 1 ships first and is independently valuable: it removes the dangerous
behaviour (a confident-looking label that means "none of the above") and its
shadow measurement produces the evidence that sizes Stage 2.

### Alternatives rejected

**Hand-recalibrate the existing rules.** Smallest diff — fix the unreachable
conjunctions, the curly-quote bug, the thresholds. Rejected as the primary
approach because fitting thresholds by eye against a labelled set is the
method that produced the current failure, and because it yields no principled
confidence, which is the load-bearing property here. Remains a reasonable
fallback if Stage 2 fails validation.

**Fit a shallow decision tree offline and transcribe its thresholds into
code.** Keeps the resolver readable with no runtime artifact. Rejected because
confidence degrades to leaf purity, making the abstention threshold arbitrary.

**Retire genre entirely** and let topic distance carry the cross-topic
correction, as `2026-08-06-topic-invariant-scoring-design.md` already does.
Rejected: genre also feeds prior pooling and drift anchoring, so retiring it is
a larger change than fixing it, and those two consumers want a genre signal
rather than a topic signal.

---

## Mechanism

### Flag

`GENRE_RESOLVER_V2` ∈ `off` | `shadow` | `on`, parsed by the same
normalise-and-fall-back-to-off helper as `TOPIC_VARIANCE_INFLATION`
(`_parse_topic_inflation_mode`), so an unparseable value can never silently
enable a score-changing path. `1` is accepted as an alias for `on`.

- **`off` (default)** — v1 rules, byte-identical to today. v2 is not computed.
- **`shadow`** — v2 computed; v1's label remains `primary` and is what every
  consumer sees. v2's verdict rides along as `shadow_primary` /
  `shadow_confidence`.
- **`on`** — v2's verdict becomes `primary`.

### Module layout

`resolvers.resolve_genre` becomes a thin dispatcher. The v2 implementation
lives in a new `original/context/genre_v2.py`. `resolvers.py` is already 652
lines covering four unrelated resolvers; adding a classifier, a signal
extractor and an artifact loader to it would make the file the thing this
codebase warns about.

### Stage 1 — abstention

v2 begins as today's rule tree with three changes:

1. The terminal `else` returns `unknown` rather than `correspondence`.
2. `confidence` carries a real value: 0.0 for `unknown`, and for rule hits a
   fixed per-rule value reflecting that rules are uncalibrated (see below).
3. The curly-quote bug in rule 6 is fixed — the regex accepts `"…"`, `“…”` and
   `‘…’` — because it is a defect regardless of which stage lands.

`unknown` is added to `GENRE_LABELS`. The other eight entries are untouched:
persisted `sample.genre` values and `get_genre_stats` pooling keys stay valid,
so no data migration is required.

Rule-hit confidence in Stage 1 is deliberately fixed rather than estimated. A
rule tree produces no probability, and inventing one would repeat the mistake
this design exists to correct. Stage 1's `confidence` is therefore
three-valued in practice: `0.0` (`unknown`), `0.5` (rule hit, uncalibrated),
`1.0` (structured-template markup rule, syntactic certainty).

**`GENRE_CONFIDENCE_MIN` is not applied in Stage 1.** It thresholds a
*calibrated* probability and arrives with Stage 2; applying it to Stage 1's
placeholder 0.5 would abstain on every rule hit and make Stage 1's `on` mode
classify nothing at all. Stage 1 `on` is therefore a deliberately modest
change — `correspondence` becomes `unknown`, the curly-quote bug is fixed, and
nothing else moves. The consumer rule that matters in Stage 1 is the label
check (`primary == "unknown"`), not a threshold comparison.

### Stage 2 — the discriminator

A multinomial logistic regression over signals the pipeline already computes,
so no new feature extraction is introduced:

`mean_sentence_length`, `sentence_length_dispersion`, `first_person_ratio`,
`second_person_ratio`, `dialogue_quote_density`, `citation_density`,
`imperative_density`, `signal_verb_rate`, `question_rate`,
`mean_word_length`.

Class set: `academic_exegesis`, `scholarly_essay`, `sermon`, `personal_essay`,
`creative_fiction`. Five classes — the ones the corpus can evidence.
`blog_post` and `correspondence` are **not in the class set** and are never
predicted; they remain in `GENRE_LABELS` for stored-value compatibility only.
`structured_template` is not learned either: it is markup rather than style,
has no corpus examples, and is served by a high-precision syntactic rule
evaluated *before* the model, validated by unit test.

Abstention: emit `unknown` when `max(P(class)) < GENRE_CONFIDENCE_MIN`.
The threshold is selected on the derivation split against a per-class
precision floor of **0.80** for any claimed label, then **frozen before the
hold-out is opened**.

Artifact and loader follow `original/style_authorship.py`: a committed,
versioned artifact at `GENRE_MODEL_PATH`, with a loader that fails closed on
schema drift, signal-order drift, and reference-prediction drift. A resolver
that cannot load its artifact returns `unknown` at confidence 0.0 — it does
not fall back to v1 rules, because silently swapping mechanisms is how a
measurement stops meaning what its label says.

---

## Ground truth

Labels are hand-assigned. This is a deliberate choice, made with its cost
understood: the labeller and the implementer are the same agent, so the labels
could encode the classifier's own biases. Four mitigations, all structural
rather than promissory.

**1. Codebook first.** `validation/genre_2026-08/CODEBOOK.md` defines each
label with inclusion criteria, exclusion criteria, and two worked examples,
and is committed **before** any document is labelled.

**2. Labels committed before the classifier exists.** `labels.json` lands in
its own commit, ahead of any `genre_v2.py` modelling code. Git history is then
the evidence that labels were not fitted to a model's behaviour — a claim that
is otherwise unfalsifiable.

**3. Author-disjoint split.** Derivation and hold-out are split **by author**,
not by document. Chesterton appears in the corpus as both essayist
(`public_authors/corpus/chesterton`) and novelist
(`public_authors/cross_work_corpus/chesterton`); a document-level split would
let the model score well by recognising him. Stratify sampling by
(author × source group) so no single author dominates a class.

**4. Author-shuffled control.** On G5's precedent
(`validation/calibration_gate.py:run_g5`): permute genre labels across authors
with a fixed seed, retrain, and confirm accuracy collapses toward chance. This
is the direct test for "this is secretly an author classifier", and it is the
single most important check in the plan, because the confound is real and the
corpus cannot fully remove it.

### Available material

| genre | source | note |
|---|---|---|
| `creative_fiction` | Dickens, Christie, Chesterton (`cross_work_corpus`, 36 files); Plato dialogues (263 files) | dialogue-heavy narrative |
| `academic_exegesis` | seminary papers (25) | the target genre |
| `scholarly_essay` | Mill, James, Federalist, Burke, Paine | argumentative prose |
| `sermon` | Edwards, Newman | genuine homiletic texts |
| `personal_essay` | Thoreau, Emerson, Douglass | first-person reflective |

Plato is labelled `creative_fiction` under the codebook's dialogue criterion.
This is a judgement call and must be recorded as one: Socratic dialogue is
philosophical argument in dramatic form, and a reasonable labeller could call
it `scholarly_essay`. Because Plato is 263 of the available documents, that
single decision dominates the class balance — so the labelled set caps Plato's
contribution at the size of the next-largest class, and the sensitivity of the
result to this choice is reported alongside the headline accuracy.

---

## Consumer semantics for `unknown`

Ignorance must never change a score. Each consumer, explicitly:

| consumer | behaviour on `unknown` |
|---|---|
| T16 mute (`manifest.py:223`) | no mute — same as any non-`creative_fiction` label |
| T8/T13 anchoring (`manifest.py:225`, `state.py:427`) | base anchors `{4, 6}` — the existing legacy-sample fallback |
| `get_genre_stats` pooling | **excluded**. `unknown` is not a pooling key. Pooling "we don't know" samples together rebuilds `correspondence` under a new name — one bucket holding everything, with a prior estimated from an arbitrary mixture of genres |
| `genre_covered_by_baseline` | attenuate only on a **confident mismatch**: the submission's genre is known, the baseline's genres are known, and they do not overlap. `unknown` on either side → treated as covered → no attenuation |

The `genre_covered_by_baseline` rule is the one that changes the most. Today it
returns True almost always because every label is `correspondence`; under v2 it
returns True whenever either side is unknown. Both produce "no attenuation" —
but for opposite reasons, and only the second is honest.

---

## Integration points

| where | change |
|---|---|
| `original/constants.py` | add `unknown` to `GENRE_LABELS` (9 entries; the existing 8 untouched); add `GENRE_CONFIDENCE_MIN`. **Additive only** — no reordering of `ALL_FEATURE_CODES`, no `NORM_BOUNDS` change |
| env | `GENRE_RESOLVER_V2` (Stage 1); `GENRE_MODEL_PATH` (Stage 2, path to the committed artifact) |
| `original/context/genre_v2.py` | new — signal extraction, structured-template rule, model inference, abstention |
| `original/context/resolvers.py` | `resolve_genre` becomes a mode dispatcher; v1 body preserved verbatim as `_resolve_genre_v1` |
| `original/context/baseline_match.py` | `genre_covered_by_baseline` gains the confident-mismatch rule |
| `original/store.py` | `get_genre_stats` excludes `unknown`-labelled samples |
| `validation/genre_2026-08/` | new — `CODEBOOK.md`, `labels.json`, `derive.py`, `evaluate.py` |
| `validation/calibration_gate.py` | gate G8 (below) |
| `validation/gate_contracts.py` | G8's failure witness. Mandatory — `tests/test_gate_falsifiability.py` fails the suite without it |

---

## Validation

### Gate G8 — genre discrimination

Measured on the author-disjoint hold-out. Passes only if **all** hold:

| | bar |
|---|---|
| **minimum** per-class precision, over claimed labels only | ≥ 0.80 |
| abstention rate over hold-out documents | ≤ 0.50 |
| author-shuffled control accuracy | ≤ 0.30 (chance is 0.20 for 5 classes) |

Minimum per-class precision, not macro-average: a macro-average lets one
class sit at 0.4 while the mean clears the bar, and the consequence of a wrong
label is per-class — `creative_fiction` mutes tier 16, `sermon` expands the
anchor set. This mirrors G7's conjunction, for the same reason: an aggregate
that can hide a failing component is not an acceptance criterion.

The precision floor is the operative bar — a claimed label that is wrong is
worse than `unknown`, because it silently changes scoring. The abstention
ceiling exists only to block the degenerate solution of abstaining on
everything, which would score perfect precision while classifying nothing;
0.50 is a judgement call, not a derived number, and is stated as such. The
shuffled control is what distinguishes a genre classifier from an author
classifier.

Three-valued like every other gate: if the hold-out cannot support the
criterion at its current size, G8 returns `uninformative`, which `--strict`
folds into `fail`. Sample-size informativeness uses `validation/power.py`'s
Wilson interval, as G3 and G7 do.

### Also verified

1. **Byte-identity with the flag off.** `resolve_genre` output is unchanged
   for every document in the committed corpora — the property that makes the
   default safe by inspection rather than by measurement.
2. **Shadow inertness.** In `shadow`, `primary` equals what v1 would return,
   asserted over the same corpora.
3. **Loader fails closed** on schema, signal-order and reference-prediction
   drift, mirroring `style_authorship.py`'s tests.
4. **No G1–G7 regression.** `python -m validation.calibration_gate --strict`.
5. **Consumer semantics.** Unit tests pinning each of the four `unknown`
   behaviours above, including that `unknown` never becomes a pooling key.

---

## Rollout

**The two stages are two implementation plans, not one.** Stage 1 is fully
specified here and is the plan to write next. Stage 2's plan should be written
only after shadow has reported a real abstention rate, because that number
determines whether the five-class set is right for student writing — and
writing a training plan before knowing it is the same premature commitment
that left `GENRE_INVARIANT_WEIGHTS_ENABLED` inert.

**Stage 1 — shadow.** Land the flag, the dispatcher, `unknown`, real
confidence, the consumer semantics and the curly-quote fix. Run `shadow` in
the pilot. The question shadow answers is the one no corpus can: **what
fraction of real student submissions does v2 abstain on?** If it is very high,
Stage 2's class set is wrong for student writing, and that is worth knowing
before training anything.

**Stage 2 — model.** Codebook, labels, derivation, G8. Enable only after G8
passes *and* shadow shows an abstention rate that leaves the resolver useful.

### Documented limitations

Both belong in the `CLAUDE.md` flag-table entry, not a follow-up:

- **Fixing the classifier probably does not make
  `GENRE_INVARIANT_WEIGHTS_ENABLED` fire often.** If most student prose lands
  in `unknown`, the attenuation gate stays largely inert — but honestly inert,
  and correct on the minority where genre is confidently known and mismatched.
  The gate firing *rarely and correctly* is the success condition here; a high
  firing rate would be a reason for suspicion, not celebration.
- **Validated against published authors, not student writing.** The same
  accepted risk already recorded for `LLR_ACTION_MODE=gate` and
  `TOPIC_VARIANCE_INFLATION`. Seminary papers are the only student-like text in
  the corpus and they are a single genre, so four of the five classes are
  evidenced entirely by published prose.

---

## Out of scope

- Changing the `GENRE_LABELS` vocabulary beyond adding `unknown`, or migrating
  stored `sample.genre` values. Old labels stay readable; v2 simply stops
  producing most of them.
- Enabling `GENRE_INVARIANT_WEIGHTS_ENABLED`. That flag's tier set (2/3/9/10)
  is independently unvalidated (`weighting.py:88`) and needs its own
  measurement once a working genre signal exists.
- `blog_post` and `correspondence` detection. No corpus evidence exists for
  either; adding it means sourcing new corpora, which is its own task.
- Per-student genre priors, and any use of genre in the professor narrative.
