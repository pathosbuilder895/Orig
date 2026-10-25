# Quote-block and indent-block stripping fix: measurement impact

**Date:** 2026-10-25 · **Branch:** `fix/quote-block-strip` · **Approved by:** Andrew (2026-10-25)
**Code:** `original/features/preprocess.py` (`_DOUBLE_QUOTE_BLOCK`, `_INDENT_BLOCK`, `_indent_is_paragraph_style`)
**NORM_BOUNDS / constants:** unchanged.

## What was wrong

1. `_DOUBLE_QUOTE_BLOCK = '"[^"]{200,}"'` also matched from a short quotation's closing mark to the next short quotation's opening mark. Everything the writer wrote between two short quotes more than 200 characters apart was dropped before any feature was measured.
2. `_INDENT_BLOCK = '(?m)^(?:    |\t).+(?:\n(?:    |\t).+)*'` treated any indented line as a block quote. It dropped the first line of every paragraph with a first-line indent (hard-wrapped text). It also dropped every one-line paragraph that starts with a typed tab, so an essay whose paragraphs all start with a tab lost almost everything.
3. Curly quotes (“ ”) were never recognised, so a genuine long quotation in curly quotes was measured as the writer's own prose.

## What it does now

- **Quotations:** a quotation is stripped only from a real opening mark to its real closing mark, with 200+ characters and more than 40 words, and no double-quote character inside. Straight quotes get their role from context; curly quotes are explicit. Nested or unbalanced quotes are kept, never dropped.
- **Indented blocks:** only a whole paragraph (blank line before and after) of two or more indented lines is stripped. If every paragraph is indented, indentation is paragraph style and nothing is stripped.
- Single quotes were never stripped, so there was no single-quote variant to fix.

## Measured words, before → after (all committed .txt corpora, 1,691 files)

Words are the engine's alphabetic tokens after back-matter removal. "Quote fix only" applies change 1 and 3 without change 2.

| Corpus | Files changed | Measured before | Quote fix only | After | Files under 80% measured |
|---|---:|---:|---:|---:|---:|
| **All corpora** | 659 / 1,691 | 82.8% | 93.2% | 93.3% | 272 → 148 |
| validation/corpus seminary_* (student pilot) | 65 / 139 | 84% | 96% | 96% | 46 → 12 |
| public_authors/corpus (calibration gate) | 52 / 61 | 16–51% for most authors | | 94–99% | most → 0 |
| pan20_cross_fandom | 72 / 72 | 56–86% | | 95–100% | 61 → 0 |
| genre_2026-08 austen / doyle / twain (fiction) | 75 / 84 | 100% | | 71–85% | 0 → 48 |
| public_authors cross_work christie / dickens | 51 / 64 | 100% | | 84–92% | 0 → 15 |
| validation/corpus paine_* | 77 / 125 | 97% | | 88% | 8 → 30 |

Examples: Mill *On Liberty* part 2, 2% → 99%. Chesterton *Orthodoxy* part 3, 7% → 96%. The 1,444-word Chesterton slice used in the evidence run, 125 → 1,444.

**Where measured words go down (333 files):** these texts have genuine long quotations in curly quotes. In novels, that is long dialogue speeches (Austen, Doyle, Christie, the "paine" files, which are fiction), and they were never recognised before. That is the rule doing what it says, a long direct quotation is not measured. But in fiction the dialogue is the author's own prose, so fiction-heavy corpora now measure less of the author. Student essays quote other people, so the rule fits them.

## Score impact

- Committed scoring snapshots (`tests/snapshots/score_default*.json`): unchanged, because the fixed profile has no quotes or indents.
- Toy alpha fixture (3 Mill baselines; a Mill paper and a Chesterton paper): Mill paper 0.557 monitor → 0.550 monitor. Chesterton paper 0.789 escalate → 0.597 monitor. That paper was 9% measured before and 100% after, so its old "escalate" came from measuring only 125 words. With the whole text it sits closer to Mill on this tiny two-paper fixture.

**Calibration gate (G1p, G2, G4) not run to completion.** On this box, `python -m validation.calibration_gate --only G1p,G2,G4` was still building the G1p Plato reference pools after about 95 minutes, on both main and this branch, so I stopped both runs. No gate numbers exist for either side. Re-run it on a faster machine before quoting gate results.

**Proxy measured instead: seminary corpus through the alpha batch scorer, main vs this branch.** The 139 seminary essays were grouped the way the gate groups them (5 sequential files per "student", 27 students; 4 baselines plus 1 held-out paper). Each student was scored on their own held-out paper ("self") and on the next group's held-out paper ("other"). 26 of 27 scored on both sides; one group had too little baseline on both sides.

| | main | this branch |
|---|---|---|
| self papers flagged (schedule_conversation / escalate) | 2 / 26 (7.7%) | 1 / 26 (3.8%) |
| other papers flagged | 8 / 26 (31%) | 4 / 26 (15%) |
| mean deviation, self | 0.509 | 0.490 |
| mean deviation, other | 0.568 | 0.539 |
| self actions changed | | 3 (median shift 0.013, max 0.146) |
| other actions changed | | 4 (median shift 0.058, max 0.268) |

Both sides fail the alpha's pre-registered bar (≤5% false flags and ≥75% caught) on this proxy, as before. With the full text measured, false flags go down. But the gap between self and other papers also narrows (0.059 → 0.049), and fewer other papers are flagged.

**Concern:** the thresholds were tuned while much of the text was not measured. These numbers suggest the action thresholds, and possibly NORM_BOUNDS, should be re-derived on the corrected measurement. That is a separate, approved re-calibration. It is not done here, and NORM_BOUNDS and constants are untouched. Caveat: the seminary "students" are sequential 5-file groups, not verified single authors, so this proxy is only directional.

## Re-calibration

NORM_BOUNDS were derived in 2026-03 from a 20-essay set that is not in the repo, so whether the bug skewed them cannot be checked here. The gate corpora (seminary, public_authors) were measured far more completely after this fix. Any threshold or AUC quoted from earlier gate reports (`validation/calibration_report_2026-*.json`) was computed on partially measured texts and should be re-run before it is quoted again. No re-calibration is done in this change.
