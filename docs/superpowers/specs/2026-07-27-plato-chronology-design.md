# Plato Chronology Study — validating Original against a known career arc

**Status:** Phase 1 (corpus + gate) in progress
**Date:** 2026-07-27

## Context

Original scores a submission against a student's baseline and reports a
`deviation_score`. Every existing validation asks the same question: *can it
tell two different authors apart?* (`validation/public_authors/`,
`validation/verify/`, the Federalist corpus). Nothing asks the complementary
question: **does the measurement track a real, externally-documented change in
style within a single author over time?**

That matters for the product, because a seminary student's writing changes
across a degree programme, and Original's current architecture treats
within-author drift as *evidence of authenticity*:

- `RECENCY_DECAY = 0.85` (`original/quantum/state.py`) biases the baseline
  toward recent work, so slow drift is absorbed rather than detected.
- `trajectory.direction == "growth"` multiplies the deviation score by **0.75**
  (`original/quantum/scoring.py:684`).
- `_compute_trajectory` (`state.py:487`) claims to order samples
  "chronologically (oldest first)" but regresses on **list insertion order** —
  `BaselineSample.submitted_at` is never parsed or sorted on anywhere.
- `professor_narrative._build_hypotheses` offers no "the author's style has
  legitimately evolved" explanation.

Plato is the canonical test case: dating his dialogues is the founding problem
of stylometry (Campbell 1867; Lutosławski coined the term in 1897 for exactly
this). The early/middle/late grouping is public, citable ground truth.

## Goals

1. **Scientific validity** — an honest finding, published either way.
2. **Credibility artifact** — gated on (1) being positive.
3. **Drift diagnosis and fix** — informed by *where* the signal is lost.

## Constraint that shapes everything

The feature pipeline is hard-locked to English: ~60 of 103 features are English
lexical/surface measures, 14 require `en_core_web_sm`, and both prosodic tiers
(T8, T13) use an English vowel-cluster + penultimate-stress heuristic. Raw Greek
fails *silently* — `_split_sentences` requires `[A-Z"'(]` after terminal
punctuation, so a Greek document collapses to a single sentence and most
features are masked out with no warning.

Greek is therefore off the table. The study uses a single-translator English
corpus (Benjamin Jowett translated the complete dialogues), which means it
necessarily measures Plato *as rendered by Jowett*. The gate below bounds that
problem; it does not eliminate it, and no claim from this corpus may pretend
otherwise.

## Corpus

Verified against Project Gutenberg during design:

| Need | Status |
|---|---|
| Jowett Plato, individual dialogues | ✅ 27 ebooks, PG author id 94 |
| Jowett Thucydides | ❌ not on PG |
| Jowett Aristotle *Politics* | ❌ PG 6762 is the **Ellis** translation |
| Second translator, overlapping dialogues | ✅ **PG 13726 — Henry Cary**, *Apology, Crito, Phaedo* |

An earlier design used "same translator, different author" (Jowett-Thucydides)
as the gate. No such source exists on PG, so it is replaced by the stronger
variance decomposition below, which measures the translator-vs-source ratio
directly rather than testing a proxy for it.

**Fixed 2000-word chunks**, inside the `medium` bucket of
`LENGTH_BUCKETS_BY_TOKENS` (750–2500), so length cannot vary as a confound and
every chunk clears the ~300-word reliability floor from `MODEL_CARD.md:31`.
Each work is capped at **12 chunks sampled evenly across the whole work**, so
the Republic and Laws (~200k words each) do not swamp the Crito.

### Two corpus traps, both hit during implementation

1. **Jowett's own introductions.** Every Jowett PG file opens with Jowett's
   Victorian academic prose. Left in, the study would substantially measure his
   essay style — and *differentially*, since the introduction is a far larger
   fraction of a short early dialogue than of the Laws, so the contamination
   would correlate with the ground truth itself.

   The first implementation passed with zero reported failures while five files
   (Apology, Gorgias, Republic, Cratylus, Timaeus) had stripped only ~9–27 words.
   Those files carry a `Contents` block that repeats every heading verbatim, so
   the heading search matched the table-of-contents entry near the top. Fixed by
   skipping the contents block, plus a `MIN_CUT_FRACTION = 0.05` guard that
   converts this class of silent partial strip into a hard failure. Post-fix cut
   fractions range 10–55%.

2. **Chunking must preserve document structure.** Rejoining `text.split()`
   flattens every chunk onto one line, which destroys paragraph boundaries —
   and the pipeline reads them (Tier 2's 13 paragraph features split on blank
   lines; speaker labels are line-anchored). The chunker slices the original
   string between word boundaries instead.

## Design

### Gate — translator variance decomposition (must pass first)

Three dialogues × two translators. Decompose feature-space variance into
`within` (same dialogue, same translator — the noise floor),
`between_translator` (same dialogue, different translator), and
`between_dialogue` (same translator, different dialogue).

**Pass criterion:** `between_dialogue >= between_translator`. If the translator
owns more variance than the source text, Original is measuring Jowett and no
downstream result is interpretable — stop, and report that as the finding.

Conservative by construction: Apology, Crito and Phaedo are chronological
near-neighbours, so passing here implies passing across the full span.

### Arm A — the product's own verdict

For each group G ∈ {early, middle, late}: build a baseline from G's chunks via
`POST /students/{sid}/baseline`, score all other chunks via
`POST /students/{sid}/score`. Reuse the client pattern at
`validation/public_authors/run.py:128-186`.

Hypothesis: mean `deviation_score` rises with chronological distance from the
baseline group. Also capture `trajectory.direction`,
`catastrophic_drift_rms_z`, and `recommendation.action` — in particular, *what
action does Original take when Plato's Laws is scored against a baseline of his
own early dialogues?*

### Arm B — the raw feature space

Bypass scoring: `feature_vector()` → n×103 matrix → z-standardise → distance
matrix → classical MDS. Correlate axis-1 position with the ordinal group rank
(Spearman ρ). Plus per-tier ablation (which tiers carry the signal) and partial
ρ controlling `direct_speech_ratio`.

**Arm B is what makes a null result diagnosable.** Arm A alone cannot separate
"the features are blind to career drift" from "the features see it and the
scoring layer discards it." Strong B + null A localises the loss to the scoring
layer, which is what the drift-fix goal needs.

The genre confound is real and was measured during corpus construction: mean
speaker-label density runs early 12.96 → middle 14.56 → late 29.05. It more
than doubles across the career, so it must be partialled out.

### Gate outcome and the orthographic confound

The pre-registered gate **failed**: `between_dialogue` 12.00 vs
`between_translator` 12.81, ratio 0.937.

Two things came out of diagnosing that failure.

**1. The gate trio was degenerate — a design error.** Apology, Crito and Phaedo
were chosen as chronological near-neighbours and described as "conservative".
They are also the *Trial and Death of Socrates* sequence. Noise-corrected
(subtracting the within-dialogue floor of 9.05), their between-dialogue
separation is **−0.33**: chunks from different dialogues in that trio are on
average *closer* than chunks from within a single one. The gate's source-signal
term was therefore measuring nothing. Re-estimating the source effect across the
whole Jowett corpus:

| comparison (noise-corrected) | effect | vs translator |
|---|---|---|
| translator (Jowett↔Cary) | 2.94 | — |
| gate trio | −0.33 | −0.11× |
| all ranked dialogue pairs | 2.10 | 0.71× |
| early-vs-late pairs | 4.06 | 1.38× |

Feature distance rises monotonically with chronological separation
(−0.33 → 2.10 → 4.06), which is the Arm B hypothesis appearing unprompted.

**2. Much of the translator gap is edition convention, not prose.** A per-tier
decomposition of squared separation shows a sharp dissociation:

| tier | translator share | chronology share | ratio |
|---|---|---|---|
| T4 char/punctuation | **27.0%** | 6.9% | **3.90** |
| T16 citation | 10.1% | 3.0% | 3.37 |
| T1 surface | 1.4% | 17.3% | 0.08 |
| T5 POS/syntax | 5.9% | 12.4% | 0.47 |

The top translator features are `quote_rate` (11.5%), `block_quote_rate`
(10.1%) and `dash_rate` (9.1%) — 31% in three punctuation measures. The top
chronology features are `lexical_chain_density`, `semantic_field_dispersion`,
`sentence_opener_variety`, `function_word_ratio` and the POS entropies.
Translator separation lives in punctuation; chronological separation lives in
lexis and syntax.

Direct measurement confirms the cause. Cary uses straight quotes at 34.1 per
1k words and Gutenberg `_italic_` markers at 3.9 per 1k; Jowett uses neither.
Jowett's own files are internally inconsistent — the Apology transcription uses
curly quotes and em-dashes, the Crito uses double-hyphens and 40 double-spaces
per 1k words. Different volunteers, same translator.

**Critically, that convention noise is not confounded with chronology.** Mean
per-group rates are flat (curly quotes early 0.5 / middle 0.5 / late 0.0;
em-dashes 1.1 / 1.0 / 0.4), and the five odd-convention files are scattered
across all three groups. So it inflates variance for the gate but does not bias
Arm B.

`normalise.py` therefore unifies rendering — speaker-label form, italic markup,
dash and quote glyphs, footnote markers, intra-line whitespace — while
deliberately leaving punctuation *density*, vocabulary, syntax and paragraph
structure untouched. The rule is: unify how a mark is drawn, never how often the
prose reaches for it. Turn counts, word counts and paragraph breaks are verified
preserved. The gate is reported both raw and normalised.

### Negative control — Eryxias

Near-universally judged spurious; Gutenberg's own title page for PG 1681 reads
"By a Platonic Imitator". Never ranked. Tests a second, independent axis —
authorship rather than chronology.

### Ground truth

`chronology.py` encodes the standard grouping (Cooper, *Plato: Complete Works*,
Hackett 1997; resting on Campbell → Lutosławski → Ritter → Brandwood) as ordinal
ranks with a `high_confidence` flag. 16 of 26 ranked dialogues are
high-confidence (early 9, middle 3, late 4). The primary metric uses that subset;
the full corpus is reported secondary. Contested placements (Timaeus — Owen's
challenge; Phaedrus, Parmenides, Theaetetus, Cratylus, Meno, Gorgias,
Euthydemus, Menexenus, Critias) are flagged, not silently ranked.

**Circularity disclosure, required in any writeup:** the scholarly chronology
was itself partly derived from stylometry — Campbell from Greek vocabulary,
Lutosławski from Greek particles, Brandwood from Greek clausulae. None of those
markers survive translation into Jowett's English, so a correlation found here
is not straightforwardly circular. But the ground truth is not *independent* of
the method the way a documented publication date would be.

## Files

New, under `validation/plato/`, following the `validation/public_authors/`
layout: `chronology.py` (ground truth, pure data), `build_corpus.py` (fetch,
strip, chunk, manifest), `features.py` (cached 103-dim matrix), `gate.py`,
`run.py` (orchestrator), `analysis.py` (MDS, Spearman, ablation), plus
`corpus/` and `manifest.json`.

Reused unchanged: `validation/benchmark/reproducibility.py` — `lock_environment()`
must be called before any `original.*` import; `validation/benchmark/report.py`
for the report shape.

`validation/manifest_schema.py:CorpusEntry` has no date field and is **not**
modified. The Plato manifest carries `chronology_group`, `chron_rank`,
`high_confidence`, `translator` and `direct_speech_ratio` in its own local
schema, leaving the shared 807-entry manifest untouched.

## Phasing — each phase is a stop point

- **Phase 1** — corpus + gate. If the gate fails, stop; the
  translator-sensitivity result is itself worth documenting.
- **Phase 2** — Arms A and B + report, with an explicit "this did not
  reproduce" branch written before the numbers are known.
- **Phase 3** — credibility artifact, gated on Phase 2 being positive.
- **Phase 4** — drift fixes, split by dependence on the finding:
  - *Outcome-independent:* parse and sort `submitted_at` in
    `_compute_trajectory`; add a "style has legitimately evolved" hypothesis to
    `professor_narrative`.
  - *Outcome-gated:* `RECENCY_DECAY` and the ×0.75 growth dampening.
  - ⚠️ The `submitted_at` sort **changes scores** for any profile whose samples
    were not inserted in chronological order. Per `CLAUDE.md` that needs its own
    decision and likely an env flag; it must not be folded in silently.

## Verification

```bash
.venv/bin/python -m validation.plato.build_corpus --verify-strip
.venv/bin/python -m validation.plato.gate
.venv/bin/python -m validation.plato.run --report-dir /tmp/plato_run
.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q
```

Phases 1–3 touch no `original/` code, so any test failure there is a real
regression.
