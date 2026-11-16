# Design: does rule D catch AI-written papers? (20-paper screen)

*2026-11-16. Owner: Andrew Clark. Builds on PR #336 (scholarly evaluation, rule D locked test).*

## Question and the decision it informs

Rule D caught 94.8% of other scholars' papers at a 4.7% honest flag rate (humanities,
1200-word past papers vs a 1200-word new paper, `locked_test`). It has never been shown an
AI-written paper. This study asks one thing: **when an AI tool writes a paper on the same
topic, for the same journal, as one of an author's own papers, does rule D flag it against
that author's past papers?**

Twenty papers is a **screen**, not proof of any catch rate. It decides between two outcomes:

* **Clearly short of 95%** (the top of the 95% interval is below 95%): rule D needs work
  before AI catch rates are worth measuring at scale. With 20 papers this means 17 or fewer
  caught.
* **95% not ruled out** (18 or more caught): scale up to about 130 AI papers, the number
  needed before any 95% claim, as a separate pre-registered study.

Nothing here enables anything in the product. Results are reported as measured on published
humanities scholarship, not student writing (NORTH_STAR rule 2).

## Design

* **Authors.** 20 humanities authors from `locked_test` (116 authors), picked by a seeded
  hash from the manifest alone, before any AI paper exists. An author whose papers cannot be
  rebuilt at the opening is reported as missing (n drops below 20), never replaced. `locked_test` may be opened once per pre-registered study;
  rule D, its thresholds and its vectorizers are unchanged since the first opening, which is
  the condition the locked-test write-up sets for reusing these authors. Humanities only: it
  has 116 locked authors against science's 33, and its journals (mostly theology) are the
  closest register in the corpus to seminary writing.
* **The paper being mirrored.** For each author, the first new (held-out) paper of the seed-7
  trial, so it is never one of that trial's past papers. Its title and journal name come
  from the committed candidate list; no text of the author's goes to any AI tool.
* **Prompt (fixed, identical for every tool):**
  > Write an original scholarly journal article of about 1,600 words titled "{title}",
  > suitable for publication in {venue}. Write continuous academic prose in paragraphs. Do
  > not use headings, bullet points, numbered lists, tables, footnotes or a reference list.

  If the cleaned reply is under 1,300 words, one follow-up is sent, once:
  > Please continue the article from where it stopped, in the same style, for about 600
  > more words.
* **Tools.** Three consumer chat apps, assigned by rank: Claude (claude.ai) 7, ChatGPT 7,
  Gemini 6. Andrew pastes the prompts in his own accounts (free tiers are enough). If he
  prefers, the Claude share may instead be written by a fresh Claude Code subagent given
  only the prompt; the route used is recorded in the pre-registration before generation.
  Only published titles and journal names leave the machine; no student writing does
  (NORTH_STAR rule 7).
* **Cleaning.** Each reply goes through the corpus's own inline cleaner (citations, footnote
  markers, URLs removed) plus removal of markdown, headings and any reference list, and
  paragraphs under 12 words are dropped, as the corpus cleaner does for papers.
* **Scoring.** Rule D exactly as pre-registered on 2026-11-12, with the committed thresholds,
  in the seed-7 trial of each configuration. The AI paper is cut at a seeded paragraph start
  to the configuration's new-paper length (1200 or 300 words), and is compared against all
  other authors in the trial set, like a probe. A paper under 1,200 words after one
  continuation enters only the 300-word configurations and is reported as missing from the
  1200 one.
* **Reported, per configuration:** caught out of n, with a Wilson 95% interval; the
  outcome above; a per-tool breakdown (descriptive only, about 7 per tool); and, beside it,
  how many of the same 20 authors' own new papers were flagged in the same trials.
  * **Primary:** 1200 past vs 1200 new.
  * **Secondary:** 1200 past vs 300 new, the short-paper case where rule D was weakest.
  * **Reported only:** 300 vs 300.

## The environment gate (before anything else)

The texts and the frozen vectorizers from the 2026-11-12 run are not on this machine, so the
setup has to be rebuilt and shown to be the same before its numbers mean anything. A cloud
session's disk does not outlast it, so steps 1 to 4 run in one session, after the AI papers
are committed:

1. **Restore with the right cleaner.** 3,185 of the 3,190 humanities papers were recorded
   with cleaner v1. v2 stopped stripping digits glued to letters, which is also how
   footnote markers sit in many theology PDFs, so a v2 restore would likely fail the hash
   check for many papers. The restore must clean each paper with the version it was
   recorded with. It runs on Linux with `poppler-utils`, as the corpus was built (the
   README's `apt-get` line; the branch name is a Claude Code cloud session's), because a
   different PDF extractor build can change the text and fail the hash check. A Claude Code
   cloud session is the default place; a local Mac run is acceptable only if the gate below
   passes there.
2. **Refit the vectorizers** on development texts (the same procedure).
3. **Recompute the calibration thresholds** in memory. The gate passes only if all three
   equal the committed thresholds to 6 decimals. If it fails, stop and report to Andrew;
   do not open `locked_test`.
4. **Reproduction check at the opening.** The locked run recomputes every published cell of
   the 2026-11-12 result; any difference is reported next to the AI result.

## What this cannot show

* Anything about student writing, or about a catch rate at 95% (20 papers cannot).
* A determined cheater who feeds the AI samples of their own writing to copy. That is a
  harder second round, designed only if this one says "95% not ruled out".
* Science papers, and AI tools beyond the three named.

## Andrew's yes needed for

1. Running the restore, the gate and the opening in a Claude Code cloud session, which
   downloads the 3,190 openly licensed humanities papers (about 15.7 million words) again
   from the publishers' sites into that session's git-ignored cache.
2. Pasting 20 prompts (plus any continuations) into claude.ai, ChatGPT and Gemini, or
   choosing the subagent route for the Claude share.
3. Opening `locked_test` a second time, under the new study id `scholarly-ai-mirror-2026-11-16`.
