# Length-stability re-run on the decontaminated corpus — comparison vs 2026-06-30

_Generated 2026-08-01. Companion to `report.md` in this directory._

## Why this re-run exists

The 2026-06-30 study ran against a contaminated public-author corpus
(found by inspection 2026-08-01, fixed in commit `7c902de8` on
`claude/compassionate-perlman-cfcd63`):

- `edwards/_full_work_cache.txt` was a **French science-fiction novel**
  (PG 24962, Le Faure & Graffigny), not Jonathan Edwards.
- `james/_full_work_cache.txt` ended with **~32k words of INDEX +
  FOOTNOTES back-matter** from The Varieties of Religious Experience.

The stability study reads `_full_work_cache.txt` directly, so both
contamination modes flowed straight into the Fisher ratios.

## Inputs to this run (provenance)

- Caches from commit `7c902de8` (edwards replaced with PG 34632
  *Selected Sermons of Jonathan Edwards*, 71,356 words raw).
- `build_corpus.py::_truncate_back_matter` (verbatim from `7c902de8`)
  applied to every cache, because the rebuild truncates back-matter
  before *chunking* but leaves the raw caches intact — james still
  ended in footnotes. Effect: james 186,374 → 154,568 words; edwards
  71,356 → 61,448; douglass 134,381 → 133,506; newman 159,383 → 157,478.
- **Same 8 authors as the 2026-06-30 run** (`--only augustine,boethius,
  chesterton,edwards,james,kempis,mill,newman`; the newly-added douglass
  was deliberately excluded) so every difference below is attributable
  to the cleaned edwards/james texts, not a changed author pool.
- Same defaults otherwise: lengths 250/500/1000/2000/5000, 12 windows
  per (author, length), `lock_environment()` reproducibility lock.

## Headline: yes, the contamination changed the conclusions

### The old report's marquee findings were artifacts

| feature | old claim | old F(500)→F(5000) | clean F(500)→F(5000) | what actually happened |
|---|---|---|---|---|
| `adversative_ratio` | **#1 most length-robust** (ratio 12.9) | 0.680 → 0.053 | 0.033 → 0.209 | English adversative markers trivially separated the French text in short windows. Clean: nearly **no** short-window signal — it lands in the bottom-20 *fragile* list now. |
| `article_omission_rate` | #3 most robust (ratio 3.17) | 1.495 → 0.471 | 0.309 → 0.428 | French article/idiom patterns read as "article omission." Clean: unremarkable at every length. |
| `chiasmus_rate` | #2 most *fragile* (ratio 0.045) | 0.681 → 15.058 | 0.040 → 0.045 | The huge F(5000) was contamination; feature is simply near-zero signal at all lengths. |
| `noun_verb_ratio` | #6 most fragile | 2.016 → 28.451 | 0.269 → 0.372 | French POS distribution inflated long-window F ~75×. |
| `function_word_ratio` | top-tier discriminator | 4.110 → 33.536 | 0.215 → 2.219 | English function-word ratios against a French text ≈ language ID, not stylometry. Same story for `stop_word_ratio` (5.78/37.5 → 0.28/1.55). |

Set stability of the reported lists: **top-30 robust overlap 19/30**
(11 features left, 11 entered), **bottom-20 fragile overlap 11/20**.
Both reports' #1 "robust" entries (old `adversative_ratio` 12.9, new
`additive_ratio` 14.4) are ratio-denominator artifacts — F(5000) ≈ 0
makes the ratio blow up. Treat extreme ratios with near-zero
denominators as noise in both reports.

### Per-tier flags: 7 of 14 measurable tiers changed

| tier | old flag | clean flag |
|---|---|---|
| 1 (surface stylometrics) | DEGRADES (0.66) | **HOLDS** (1.31) |
| 5 (POS/syntax) | COLLAPSES (0.25) | **DEGRADES** (0.36) |
| 6 (idiosyncratic) | DEGRADES (0.36) | **COLLAPSES** (0.24) |
| 9 (argument) | DEGRADES (0.40) | **COLLAPSES** (0.23) |
| 10 (semantic gravity) | DEGRADES (0.34) | **HOLDS** (0.84) |
| 14 (error topology) | HOLDS (0.95) | **DEGRADES** (0.45) |
| 15 (lexical architecture) | COLLAPSES (0.26) | **DEGRADES** (0.50) |

Tiers 2, 3, 4, 7, 8, 13, 16 kept their flags (11/12 have no measurable
features on text-only input, as before).

### Downstream: the Phase-2 `LENGTH_WEIGHT_SCHEDULE` amplifies the wrong tiers

`original/constants.py::LENGTH_WEIGHT_SCHEDULE` ("short" bucket) was
derived from the contaminated per-tier F(500) values. On clean data the
tiers it amplifies hardest are among the weakest at 500 words:

| tier | old mean F(500) | clean mean F(500) | schedule factor (short) |
|---|---|---|---|
| 7 (AI/burstiness) | **6.215** (highest → amplified) | **0.228** | 1.56 |
| 5 (POS/syntax) | 2.810 (amplified) | 0.288 | 1.56 |
| 4 (char/punct) | 1.696 (amplified) | 0.558 | 1.56 |
| 1 (surface) | 1.690 (amplified) | 0.600 | 1.56 |
| 8 (prosodic rhythm) | 0.983 | **1.067** (now the strongest) | 1.26 |

On the clean corpus the short-window ranking is tier 8 > 1 > 4 > 15,
with tiers 5 and 7 near the bottom. The 10–27× collapse of tiers 5/7 is
far beyond window-sampling noise and has a clear mechanism (function
words, POS, burstiness, and repetition statistics all trivially
separate a French novel / index back-matter from English prose).
**The schedule needs to be re-derived from this report before
`LENGTH_ADAPTIVE_WEIGHTS=1` is trusted anywhere**, and the
`lift_*_2026-06-30.json` lift measurements should be re-run too, since
they scored against the same contaminated corpus.

## Caveats

- 8 authors × 12 windows is a small sample; individual Fisher ratios
  are noisy and single-feature rank moves of a few places are not
  meaningful. The tier-level and marquee-feature reversals above are
  orders of magnitude and directionally consistent with the known
  contamination mechanism, which is why they are treated as real.
- The clean caches are not on this branch — they live in `7c902de8`
  plus the back-matter truncation described above. Reproduce with:
  extract `validation/public_authors/corpus` from `7c902de8`, apply
  `_truncate_back_matter` to each `_full_work_cache.txt`, then
  `python -m validation.stability.run --only augustine,boethius,chesterton,edwards,james,kempis,mill,newman`.
