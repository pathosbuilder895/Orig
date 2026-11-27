# Why the SP1 harness's honest-paper scores moved between `4bab200` and `216c3e2d`

| | |
|---|---|
| **Tool** | Claude Code, local re-scoring of committed data at several commits |
| **Date** | 2026-11-20 |
| **Question** | Re-scored on 2026-11-19 (PR #367), the public-author "clean" cells of the SP1 adversarial harness gave different scores than the first run of 2026-10-21, with no flag change between them. Which change on main moved them, was it intended, and did it break a flag-off byte-identity promise? |
| **Decision it informs** | How to read the drift caveat in the 2026-11-19 addendum of `docs/research/ADVERSARIAL_BASELINE_FINDINGS_2026-09-20.md`, and whether the first run's numbers can still be quoted. |

Investigation only: no score, constant or flag was changed.

## Answer

**All of the drift is [PR #316](https://github.com/pathosbuilder895/Orig/pull/316)**
(merge `827f8ab9`, 2026-10-25), "fix(preprocess): strip only genuine long
quotations and indented block quotes (changes scores)". It changed which part
of each document the engine measures. It was intended, declared as a score
change in its title, and approved by Andrew. It is not behind a flag, so no
flag-off byte-identity promise covers it and none was broken.

The other 85 commits touching `original/` left these scores where they were.
Scored at `827f8ab9`, every value in the 25 clean cells (50 genuine held-out and 125
peer-swap scores) is identical to the 2026-11-19 run; scored at its parent,
every value is identical to the 2026-10-21 run.

The first run was scored at `4bab200`, whose `original/` is main's `5942bbd2`
(2026-10-21), four days before #316 merged. So the first run measured the
partly stripped text: 68% of the words in the public-author harness documents
and 70% in the Riddell-Juola baselines (98% after). #316's own calibration
note (`docs/calibration/quote_block_fix_2026-10-25.md`) says gate reports from
before the fix were computed on partially measured texts and should be re-run
before they are quoted again. The SP1 first-run report is one of them.

## What #316 changed

Before #316, `original/features/preprocess.py` removed:

1. Everything between a short quotation's closing mark and the next short
   quotation's opening mark, if they were more than 200 characters apart
   (`'"[^"]{200,}"'` matched close-to-open as well as open-to-close).
2. The first line of every indented paragraph, and every one-line paragraph
   starting with a tab (`_INDENT_BLOCK` took any indented line).

It did not recognise curly quotes at all. After #316, only a real quotation of
more than 40 words (straight quotes read by position, curly quotes by side) and
only a whole indented paragraph of two or more lines are removed.

Measured share of words (alphabetic tokens in the text `preprocess()` returns,
over the raw text), every baseline and held-out document of each public-author
victim across N = 3, 5, 10:

| Victim | Docs | Before #316 | After | Held-out docs before → after | Mean change in held-out score |
|---|---:|---:|---:|---|---:|
| augustine | 5 | 23% | 97% | 18%, 44% → 92%, 99% | 0.099 |
| boethius | 5 | 31% | 81% | 8%, 34% → 81%, 87% | 0.181 |
| chesterton | 12 | 63% | 98% | 100%, 100% → 92%, 84% | 0.168 |
| christie | 12 | 100% | 78% | 100%, 100% → 87%, 68% | 0.027 |
| dickens | 12 | 100% | 97% | unchanged | 0.011 |
| douglass | 5 | 100% | 99% | unchanged | 0.010 |
| edwards | 5 | 32% | 97% | 25%, 37% → 96%, 98% | 0.042 |
| emerson | 12 | 72% | 98% | 47%, 18% → 98%, 100% | 0.181 |
| james | 5 | 69% | 68% | 80%, 80% → 78%, 78% | 0.013 |
| kempis | 5 | 100% | 92% | 100%, 100% → 85%, 99% | 0.035 |
| mill | 12 | 88% | 99% | 100%, 50% → 100%, 83% | 0.032 |
| newman | 5 | 100% | 97% | 100%, 100% → 96%, 96% | 0.011 |
| thoreau | 12 | 100% | 99% | 100%, 100% → 100%, 98% | 0.009 |
| **all** | | **68.4%** | **89.7%** | | |

The authors whose scores moved most are the ones whose measured text changed
most. Two mechanisms, one in each direction:

- **Straight-quote texts gained prose** (augustine, edwards, emerson, mill,
  boethius, and some chesterton): the close-to-open bug had removed most of
  them. Emerson's second held-out document was 18% measured before; its score
  fell 0.26 to 0.28 at every N. Boethius's first held-out document was 8%
  measured (its verse is indented, and it quotes); 0.743 → 0.457.
- **Curly-quote texts lost their long quotations** (christie, kempis,
  chesterton's two held-out documents): these were never recognised before.

**Chesterton rose (0.494 → 0.699 at N=3) for a different reason: his baseline
was repaired, not his held-out papers.** One of his baseline documents was 4%
measured before (the first run flagged it as the baseline's outlier, LOO z
4.86; the re-run flags nothing). That document widened his spread: mean
baseline std 0.067 → 0.039 at N=3 and 0.122 → 0.056 at N=10. Measured whole,
his past papers agree more closely, and his held-out papers (another work,
now also missing 8% and 16% of their words as quotations) sit further outside
them.

Sixteen of the 50 held-out actions changed. At `schedule_conversation`+
(4% / 8% / 8% → 8% / 17% / 25% at N=3/5/10), all six chesterton held-out
readings moved up from `monitor`, while boethius at N=3 and emerson at N=5
moved down from it. At `monitor`+ (73% / 83% / 92% → 62% / 83% / 75%),
emerson, augustine and boethius fell to `no_action` (seven readings), against
kempis at N=3 and mill at N=5 rising to `monitor`. Peer-swap AUROC moved for
the same reason: the peer-swap documents are other victims' baseline
documents, re-measured by the same fix, and every one of those scores is
reproduced too.

On chesterton's first baseline document, 71 of 109 features changed, among
them character-level ones (`char_trigram_entropy`, `avg_word_length`): the
change is in the text measured, not in any one feature's formula.

## Intended, and declared

- PR #316's title says "(changes scores)", its body "Changes scores. Do not
  merge without Andrew", and it records Andrew's approval ("fix the quote
  stripping bug as well"). Its calibration note reports public_authors going
  from "16-51% for most authors" to 94-99% measured, the same corpus the SP1
  harness draws its victims from.
- It is a fix to the default measurement, not a new mechanism, so it has no
  flag and the flag byte-identity matrix does not apply to it. The committed
  flag-off snapshots (`tests/snapshots/score_default*.json`) were unchanged by
  it, as its PR states, because the snapshot fixture
  (`tests/config/_flag_corpus.py`) has no double quotes and no indented lines
  in its baseline or submission texts. That is a coverage gap in the snapshot,
  not a broken promise: the snapshot cannot see a change to quote or indent
  handling.

## The other commits: flag-off byte-identical on these documents

Every later flag-gated change in the range left these 25 cells bit-identical
at its flag's default (the harness pins only the flags in
`report.LIVE_SCORING_ENV`; the newer ones ran at their defaults, none set in
the environment): `OPPORTUNITY_MASK` (#334), `LENGTH_MATCHED_BASELINE`
(#334, #358), `FEATURE_SET` and `MATTER_SPLITTER_ENABLED` (#354), versioned
measurements (#355), `RULE_D_OBSERVATION` (#338, on by default but
report-only), the evidence and preliminary-score defaults (#314, #318, #346),
the shared spaCy model (#353), and #320 (comparison measurements left out of
the comparison, unflagged, declared score-neutral on its proxies). The feature
vectors of chesterton's and boethius's ten N=3 documents are bit-identical
after each of the seven main merges that touched `original/features/` from
#316 on.

## Method

1. **Both runs reproduce exactly in today's venv.** Chesterton and boethius
   at N=3, scored with the harness at `4bab200` and at `216c3e2d`, give the
   first run's and the re-run's values to every printed digit (chesterton
   0.4940, 0.5396 → 0.6992, 0.7057; boethius 0.7426, 0.4420 → 0.4570,
   0.3658). So the environment (package versions, spaCy model) is not the
   cause, and both reports hold what a cold extraction gives at their
   commit.
2. **The harness did not change.** `validation/adversarial/runner.py` and
   `profiles.py` are identical at the two commits, the held-out and baseline
   selections match row for row, and `validation/public_authors/` did not
   change. `original/` at `4bab200` equals main's `5942bbd2`, and at
   `216c3e2d` equals main's `d62562fe`.
3. **Feature-vector timeline.** Ten documents' live feature vectors
   (`original.features.pipeline.feature_vector`) were computed before and
   after each of the seven first-parent main merges between those two commits
   that touch `original/features/`. They equal the first run's vectors before
   #316 and the re-run's at and after it, with no other change point.
4. **Scores at the change point.** All 25 public-author clean cells were
   scored at `827f8ab9^1` and `827f8ab9`.

The harness exists only on the SP1 branch, so at main commits it was run from
a `216c3e2d` checkout with `original` imported from the commit under test. The
scripts are in the session's scratchpad, not committed; the core of each run
is `report._worker_init()` followed by
`runner.run_attack(profile, "none", path="api")` over
`profiles.build_victim_profiles(n, report.HARNESS_SEED)`.

## What this means for the SP1 findings

- **Every first-run number was measured on partly stripped text.** That
  includes G-A1 to G-A6 and the Riddell-Juola cells: the Riddell-Juola
  baseline files in the harness corpus were 70.4% measured before #316 and
  97.9% after (410 of 856 files changed; 325 of those have indented lines,
  295 have double quotes). The classroom peer-swap result (AUROC 0.46 to
  0.51) is one of them. None of these was re-run here; they should be before
  they are quoted again.
- **The 2026-11-19 re-run is on the corrected measurement.** Its public-author
  clean cells are the numbers as of `216c3e2d`, and they are what a re-run of
  the first run's gates should be compared against. Main has moved since;
  nothing here checks merges after `d62562fe`.
- **The curly-quote rule now removes long quotations from published prose.**
  For christie (dialogue) it removes 13% and 32% of the two held-out
  documents, and as much as half of one baseline document. #316 raised this
  for fiction; it applies to these harness victims too.
