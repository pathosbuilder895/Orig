# Fitting the comparison to the new paper: why honest papers are flagged, and what fixes it

| | |
|---|---|
| **Tool** | Claude Code; `validation/scholarly/diagnose.py` and `validation/scholarly/adjust.py` on the scholarly corpus (`validation/scholarly/manifest/`) |
| **Date** | 2026-11-12 |
| **Question** | When a short new paper is compared with long past papers, why are honest writers flagged, and which comparison adjustment (length, topic, section, house style, per-author stability, peer-relative decision) recovers the most other-writer catches at a fixed 5% honest flag rate? |
| **Decision it informs** | Whether to propose a change to how Original builds the baseline for a short submission (`original/quantum/`), and which flag would be worth a shadow soak. Follows `docs/research/2026-11-12-scholarly-intended-use-evaluation.md`. Nothing in the product was changed or enabled. |

**Academics are not students**, and formal academic prose is the register where published
stylometric methods are weakest. Everything here was done in `validation/` with the scorer
called directly; no file under `original/` changed and no product flag was enabled.
`locked_test` was not opened.

## Protocol

* Development partition only for Steps 1 to 3 (humanities 157 authors, science 61);
  calibration (112 and 36) only in Step 4. Collections never pooled.
* Per author: 4 past papers, 2 held-out new papers, 5 other authors' new papers as probes;
  seeds 7, 11, 23 pooled by author; 95% intervals are author-level bootstraps.
* Main measure: **catch rate at a fixed 5% honest flag rate** (threshold set on the same
  data's honest scores, re-set inside each bootstrap resample). Also the product's own flag
  rates (`schedule_conversation` or `escalate`) and AUC.
* Selection rule written and committed before the humanities Step 3 results existed
  (`validation/scholarly/adjust_selection_rule.json`): eligible only if not clearly worse at
  matched lengths in either collection; rank by mean catch@5% in the 1200-past/300-new setup;
  pick the top two. Step 4 fixed thresholds on calibration and reported once.
* Check: the flags-off candidate reproduces PR 336's development numbers exactly.
* Skipped: no author and no paper in any configuration or seed (all 4,222 manifest papers
  verified against their hashes).

## Step 1: why honest papers are flagged (1200-past / 300-new, shipped scorer)

Eight development authors per collection: the 4 with the highest honest false-flag rate
(all 100%) and the 4 closest to the median (83% humanities, 67% science). For every honest
paper of theirs that was flagged, the 5 features with the largest |tier weight x z| were
labelled:

* **length** if the feature's |z| at least halves when the same past papers are cut into
  300-word pieces (only length changes);
* otherwise **topic**, **section** or **house style** if the feature is in the top 20% of
  active features for that sensitivity, measured on all development authors (topic:
  correlation of |z| with TF-IDF topic distance; section: opening versus middle of the same
  paper; house style: within-author venue effect beyond a shuffled baseline);
* otherwise **genuine**.

| collection | flagged honest papers | length | genuine | topic | house style | section |
|---|---|---|---|---|---|---|
| humanities | 44 | **155 (70%)** | 34 (15%) | 14 (6%) | 11 (5%) | 6 (3%) |
| science | 40 | **135 (68%)** | 39 (20%) | 10 (5%) | 10 (5%) | 6 (3%) |

The same picture holds in both the highest and the typical groups. The most frequent drivers
are vocabulary-rate features that depend on text length (`filler_hedge_cluster_rate`,
`type_token_ratio`, `hapax_legomena_rate`, `structural_centrist_penalty`, `that_which_ratio`).
The mechanism is mostly spread, not mean: a baseline built from 1200-word cuts has a far
narrower spread than any 300-word text can, so z-scores inflate. Full rows:
`validation/scholarly/diagnosis_{humanities,science}_2026-11-12.json`.

## Step 2: candidates and the reason for each (stated before testing)

| candidate | what it does | motivated by the diagnosis? |
|---|---|---|
| (a) length-matched baseline | cut each past paper into pieces the size of the new paper | yes: length is about 70% of drivers |
| (b) `LENGTH_ADAPTIVE_WEIGHTS` | rescale feature weights by submission length | yes, partly: a second length response |
| (c) `TOPIC_VARIANCE_INFLATION` | widen spread with topic distance | weakly: topic is 5-6%; tested because requested; `TOPIC_SENSITIVITY` ships empty (uniform widening) |
| (d) `CHARACTERISTIC_WEIGHTS` | weight features by this author's stability against peers | weakly: aims at the "genuine" share |
| (e) impostor / LLR | decide on how much more like the author than like peers | yes: length inflation is shared by honest papers and probes, and a peer-relative decision can cancel it |
| (f) a + e | both | yes: the only combination both diagnoses support |

Not added: topic- or section-specific combinations (each under 7% of drivers) and a + b (two
responses to the same cause).

## Step 3: development results (all authors)

Catch at 5% honest flags, 1200-past / 300-new (95% interval):

| candidate | humanities | AUC | science | AUC |
|---|---|---|---|---|
| flags-off | 25.8% [21.0, 29.1] | 0.745 | 38.8% [30.8, 49.4] | 0.814 |
| (a) length-matched | 29.7% [24.0, 35.1] | 0.775 | 53.7% [40.4, 60.4] | 0.862 |
| (b) length-adaptive | 22.5% [18.3, 28.8] | 0.744 | 36.7% [27.5, 49.8] | 0.813 |
| (c) topic inflation | 25.7% [21.0, 29.2] | 0.745 | 37.9% [30.3, 48.9] | 0.812 |
| (d) characteristic | 26.2% [20.2, 30.0] | 0.752 | 34.8% [27.4, 41.6] | 0.809 |
| (e) impostor / LLR | 30.9% [24.8, 36.5] | 0.785 | 39.3% [33.3, 48.1] | 0.839 |
| **(f) a + e** | **52.0% [46.7, 58.2]** | **0.863** | **58.8% [40.2, 69.0]** | **0.906** |

Honest flag rate under the shipped bands, same setup: flags-off 73.5% (humanities) and 64.2%
(science); with the length-matched baseline (a or f) 3.9% and 1.4%. At matched lengths
(a) is identical to flags-off by construction; (e) and (f) raise catch@5% (humanities 1200/1200:
41.0% to 60.9%; science 300/300: 34.9% to 42.1%). Full tables:
`validation/scholarly/adjust_{humanities,science}_development_2026-11-12.json`.

**Chosen by the rule:** (f) length-matched + LLR (mean catch@5% 55.4%) and (a)
length-matched (41.7%). All candidates were eligible.

## Step 4: calibration, reported once

Thresholds fixed on calibration for a 5% honest flag rate, 1200-past / 300-new; the same
thresholds applied to development as a transfer check. Flags-off on calibration at its own
5% threshold (PR 336) is the reference.

| collection | candidate | calibration catch @ ~5% honest | AUC | development at that threshold: honest / catch |
|---|---|---|---|---|
| humanities (112) | flags-off (PR 336) | 18.8% [16.3, 21.2] | 0.738 | 4.1% / 22.4% |
| | (a) length-matched | 27.1% [23.7, 30.9] | 0.785 | 3.9% / 25.8% |
| | **(f) a + e** | **42.0% [37.8, 46.7]** | **0.846** | 3.4% / 43.1% |
| science (36) | flags-off (PR 336) | 35.4% [28.1, 43.9] | 0.754 | 6.6% / 44.0% |
| | (a) length-matched | 25.4% [18.5, 33.3] | 0.791 | 2.5% / 39.9% |
| | **(f) a + e** | **44.8% [37.2, 53.0]** | **0.874** | 5.5% / 58.9% |

All configurations and intervals: `validation/scholarly/adjust_{humanities,science}_calibration_2026-11-12.json`.

## What it shows

1. **Most honest false flags in the long-past / short-new setup are a length artefact.** About
   70% of the features driving them lose at least half of their deviation when the baseline
   is cut to the new paper's length, in both collections.
2. **Cutting the past papers to the new paper's length removes the false-alarm flood.** Under
   the shipped bands the honest flag rate falls from 74% to 4% (humanities) and from 64% to 1%
   (science) on development, with no threshold change.
3. **Length matching plus the peer-relative LLR decision catches the most other writers.** At
   a fixed 5% honest rate it roughly doubles humanities catch (18.8% to 42.0% on calibration)
   and lifts science (35.4% to 44.8%), with AUC 0.85 and 0.87. Length matching alone is not
   enough in science calibration (25.4%, below flags-off), so the LLR step is doing real work.
4. **Topic, section, house-style and per-author stability adjustments did not help** here,
   matching their small share in the diagnosis.

## Limits

* Academics are not students; none of this is validated on student writing. `locked_test`
  remains unopened and is the place to confirm (f) under a pre-registration.
* Science calibration has 36 authors; its intervals are wide.
* The LLR peer pool is the other authors of the same partition and trial set, which mirrors
  the product's same-tenant pool but includes the probe authors themselves, as a real class
  would.
* `TOPIC_SENSITIVITY` ships empty, so (c) widened every feature equally; a populated table
  might behave differently. No sentence-transformers in this run (Tier 10 TF-IDF fallback).
* The diagnosis labels rest on stated cut-offs (a 50% drop for length, the 80th percentile
  for the other sensitivities); different cut-offs move the minor categories but not the
  length majority.
* Adopting (a) or (f) in the product would change how `original/` builds baselines and which
  flags are on. That needs your approval and its own validation gate, and the CLAUDE.md flag
  table's shadow-first rule applies to `NULL_MODEL=impostor`.
