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
- Calibration gate legs (G1p, G2, G4), main vs this branch: see the PR description.

## Re-calibration

NORM_BOUNDS were derived in 2026-03 from a 20-essay set that is not in the repo, so whether the bug skewed them cannot be checked here. The gate corpora (seminary, public_authors) were measured far more completely after this fix. Any threshold or AUC quoted from earlier gate reports (`validation/calibration_report_2026-*.json`) was computed on partially measured texts and should be re-run before it is quoted again. No re-calibration is done in this change.
