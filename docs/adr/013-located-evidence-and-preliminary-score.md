# ADR-013: Located evidence passages and an optional preliminary score (staff only)

**Status:** Accepted (#314, merged); all-measurements extension (items 9–14) proposed on `feat/evidence-all-features`, awaiting Andrew
**Date:** 2026-10-24
**Deciders:** Andrew
**Relates to:** `docs/NORTH_STAR.md`; ADR-012 rows "Evidence quotes" and "My Work highlights" (this ADR supersedes the "no text positions exist" reason for staff views only); ADR-011 claim-table rules.

## Context

Andrew, 2026-10-24: "our greatest strength is to not be a black box. We also need preliminary optional scores according to our math". ADR-012 removed quotes because a score response carried no text positions. This ADR adds positions for the features where Original's own count can be reproduced exactly, and a preliminary score that is nothing more than the existing math restated.

## Decision

1. **New module `original/evidence.py`.** It rebuilds the engine's `preprocess()` and `TextDoc` strings with a character map back to the stored text, and refuses (fails closed) if the rebuilt strings differ from the engine's own. For each feature it re-counts using the extractor's exact rule and refuses if its count differs from the extractor's. Only then does it return quotes, and each quote is `text[start:end]` of the stored text, with its offsets.
2. **Ordering is the engine's**: `interference.destructive_features` (|delta| x tier weight, top 5). No new ranking. Up to 3 sentences from the new paper and 3 from past papers (round-robin across papers, document order), deterministic.
3. **Locatable features (23):** `mean_sentence_length`, `sentence_length_variance` (shown as the shortest/longest sentences), `passive_voice_ratio` (approximate pattern, max one per sentence, as the engine), `modal_verb_ratio`, `discourse_marker_density`, `additive_ratio`, `adversative_ratio`, `causal_ratio`, `temporal_ratio` (the four marker ratios count the first use of each marker, as the engine), `transition_density`, `hedging_density`, `assertion_density`, `claim_density`, `question_ratio`, `first_person_ratio`, `appeal_to_authority_density`, `comma_rate`, `semicolon_colon_rate`, `parenthetical_rate`, `dash_rate`, `quote_rate`, `contraction_rate`, `sentence_initial_conjunction_rate`. They are locatable because each is a count of specific characters, words or sentences that can be pointed at.
4. **Every other feature is numbers-only** and labelled so: entropy, distributional, embedding, syntactic-parse, error-topology and similar features are properties of the whole text, and pointing at a sentence would invent a reason.
5. **"What Original measured"**: every evidence payload says how many stored words were measured and shows (verbatim) up to five ranges the preprocessor set aside, with a warning below 80%.
6. **Preliminary score**: `score = round(deviation_score, 2)`, band words from `ACTION_THRESHOLDS` ("Within the writer's usual range" ... "Far outside the usual range"), label "Preliminary · unvalidated · not a judgment". Inconclusive (no score) below the readiness minimum (5 counted, 3 effective). No accuracy claim; none of "AI detection", "cheating" or "authorship verification" in any wording (tested).
7. **Gating**: `EVIDENCE_PASSAGES_ENABLED` and `PRELIMINARY_SCORE_ENABLED`, both default `0`. When off, `POST /students/{id}/score` is byte-identical (fields are `null`; snapshot regenerated only to add the two null keys). When on, they attach only for non-student principals on HTTP requests; `/me/work` (request=None) and student principals never get them. Neither changes `deviation_score`, the recommendation or anything persisted.
8. **Alpha batch** (`scripts/alpha/batch_score_alpha.py`): writes `out/evidence/<id>.md/.html/.json` and `preliminary_score` / `preliminary_band` CSV columns (staff tool, on by default, `--no-evidence` to skip). report.md accuracy numbers, CSV semantics and calibration are unchanged; labels are never read into evidence.

## Extension: every measurement (2026-10-25, branch `feat/evidence-all-features`)

Andrew approved extending the evidence pages from the top 5 to the whole feature vector.

9. **One section per measurement.** `evidence.build_all_features` returns one entry for every code in `constants.ALL_FEATURE_CODES` (`FEATURE_DIM` entries, read from the registry, never hard-coded); `build_evidence(..., all_features=True)` adds it as `all_features` plus `feature_count` and `all_features_ordering`. The batch scorer and the flag-gated staff API field both pass `all_features=True`.
10. **Values.** The 0–1 values are the engine's: in the API, `result.feature_vector`, each contributing `BaselineSample.vector` and `StudentState.baseline_mean`; in the batch, `extract_features` on the same texts, with the past-paper average taken the way `baseline_mean` takes it (`RECENCY_DECAY` weights, newest 1.0; the batch uploads every past paper as `verified`). Plain units come from `features.pipeline.extract_raw_features`, a behaviour-preserving split of `extract_features` (it returns the dict that `extract_features` normalises; scores are unchanged, guarded by the byte-identity snapshots). For the 23 locatable measurements the plain value is the evidence layer's own located count, as before. If the API cannot show every contributing past paper (a sample without stored text), the full list falls back to the recency-weighted mean of the papers it can show. `past_average_matches_top_list` is false, and the pages say so, when the top list's averages differ from the full list's (for example when the score blended in a population prior for a short baseline).
11. **Order (documented in every page).** Descending `|this paper − past-paper average| × TIER_WEIGHTS[tier]`, the same size measure `_decompose` uses for `destructive_features`, applied to every measurement; ties (including every measurement that does not differ) keep `ALL_FEATURE_CODES` order. The engine's top list additionally requires |z| > 1, so a measurement can rank high in the full list and still be absent from the top list; pages say so, and mark top-list entries with ★. The top-5 "biggest differences" summary stays first, in the engine's order.
12. **Kinds.** `located` (the 23 locatable measurements, with up to 3 verbatim, offset-checked sentences per side in two columns, failing closed exactly as before), `whole_text` ("Whole-text measurement, no single sentence to point to."), `off` (tiers 17 and 18 while in `DISABLED_FEATURE_GROUPS`: every paper gets the fixed middle value) and `placeholder` (the 7 comparison codes, which default scoring sets to 0.5 for every paper). Each entry shows each past paper's value, the range, the average, the signed difference, the weighted size and whether the paper is outside every past paper's range.
13. **Descriptions** live in `original/evidence_features.py`, written from the extractor code (tiers 1–16, `prosodic.py`, `tension_arc.py`), with units for the raw value. Heuristics are called heuristics; where a measurement cannot be put in everyday words (the catastrophe index) the entry says what is computed. A test fails if the table and `ALL_FEATURE_CODES` disagree or any description uses a banned word. The top-5 sections now use these descriptions too.
14. **Rendering.** Markdown: summary, then a table of all measurements, then one section each (this replaces the old "Every countable habit" table when the full list is present). HTML: a table of contents linking to every measurement and one collapsible `<details>` per measurement.

## Finding (not fixed here; changes scores, needs Andrew)

`features/preprocess._DOUBLE_QUOTE_BLOCK` (`"[^"]{200,}"`) is meant to drop long block quotes but matches from one short quotation's closing mark to the next one's opening mark. Any paper with two short quotes more than 200 characters apart loses all the prose between them from measurement (demo: 121 words -> 7 measured; the Chesterton fixture: 125 of 1,441 words measured). This likely affects alpha calibration. The evidence layer now exposes it ("What Original measured"), but the fix belongs in a separate, approved, re-calibrated change.

## Deferred

- Teacher UI rendering in `demo/original/writing-state.html` / packet (API field is ready; no JSX touched).
- Per-teacher/per-tenant toggle instead of env flags.
- Locating more features (e.g., function-word or POS features) only where an exact count match can be proved.
- Showing the engine's per-feature z-scores (the API does not return `sigma`), which would let the full list mark the |z| > 1 cut-off directly.
