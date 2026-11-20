# Provenance: LLM attack corpus (gates G-A2 and G-A3)

## What this is

AI-written and AI-laundered documents for the published-author victims in
`validation/public_authors/`, used by `validation/adversarial/report.py` to
measure whether the live scoring path notices them:

- **imitation** (G-A2): the model is shown a victim's baseline papers and
  asked for about 600 new words "a reader would mistake for more work by
  the same author". One per victim per baseline size N.
- **paraphrase** (G-A3): the model rewrites one of the victim's own
  genuine held-out documents, same meaning, new wording.
- **roundtrip_de / roundtrip_ja** (G-A3): the same held-out document
  translated into German or Japanese and back into English.

The victims are 19th- and early 20th-century published authors, not
students. No student writing and no study participant's writing was sent
to a model.

## How it was made

- **Date:** 2026-11-19.
- **Model:** `claude-opus-5-5` (Claude Opus 5.5), the `model_id` on every
  manifest entry.
- **Route:** Claude Code subagents (`route: claude-code-subagent` on every
  entry), not the Anthropic API. No API key was available, and the owner
  approved generating the corpus with Claude itself (2026-11-19).
  `validation/adversarial/llm_attack_jobs.py` built the jobs and assembled
  this directory; `gen_llm_attacks.py` remains the API route.
- **Prompts:** built by `gen_llm_attacks.py`'s own prompt builders
  (`_imitation_prompt`, `_paraphrase_prompt`, `_translate_prompt`) from the
  same victim profiles, so each `prompt_sha` is the sha256 of exactly the
  text the API route would send (for a round trip, the two hop prompts
  joined by `\n<<ROUNDTRIP>>\n`, as there). `assemble` rebuilds every
  prompt from the profiles and refuses a doc whose prompt file differs.
- **Agents:** each agent read its prompt from a file, was told to treat
  the file as the whole request and answer it as it would a user, and
  wrote only its answer to an output file. The brief said the output was
  a test document for an authorship-consistency tool and asked for a
  genuine, best response regardless of that framing. Agents were told not
  to run commands, open other files, or use the web.
  - One fresh agent per imitation, so no imitation was written by an agent
    that had read a different N's baselines or written another imitation.
  - Paraphrases: one agent per victim, its two held-out documents in turn.
  - Round trips: the first hop (English to German or Japanese) by one
    agent per victim; the second hop (back to English) by a **different,
    fresh agent per document**, which never saw the English source, so the
    back-translation is a translation and not a recollection. This mirrors
    the API route's two independent calls. Every first-hop translation is
    kept in `_intermediate/<attack>/<victim>/<doc_sha>.<lang>.txt`, and each
    round-trip entry records its `intermediate_sha`.

## Where delivery differs from the API route

1. **Agent context.** A subagent answers inside Claude Code, with its
   system prompt and the brief above, not as a bare API call.
2. **Display wrapping.** Some source documents are one line of 14,000
   characters. Agents read a copy in which spaces on lines over 1,000
   characters were replaced by line breaks (Japanese lines with no space
   break after a full stop instead); `prompt_sha` is of the unwrapped
   prompt. Same words and punctuation.
3. **Dash markers.** The workspace this ran in has a hook that rewrites
   em dashes (U+2014) and horizontal bars (U+2015) in every file a tool
   writes, subagents' included, to commas. Several victims use em dashes
   heavily and the feature pipeline measures punctuation, so a stripped
   attack would be easier to catch than a real one. Agents wrote
   `[[EMDASH]]` / `[[HBAR]]` where the character goes and `assemble` put
   the character back (owner decision, 2026-11-19). The count restored in
   each doc is in `generation_log.json`.
4. **No length cap.** `gen_llm_attacks._complete` sends `max_tokens=4096`
   and does not check `stop_reason`, which would cut a 2,500-word
   Japanese translation short without saying so. The subagent route has
   no such cap, and `assemble` rejects any paraphrase or back-translation
   outside 0.6-1.5 times its source's length.

## Checks applied before a doc was accepted

`llm_attack_jobs.assemble` rejects a doc, and writes nothing at all while
any finished doc is rejected, when it is empty, opens with an assistant
preamble, still contains a marker, is outside its length bounds, is not in
the expected language (first hops: Japanese characters or German function
words; everything else: English), or, for an imitation, shares more than
5% of its word 8-grams with its own baselines (a copy, not an imitation).
Per-doc statistics (word count, length ratio, 8-gram overlap with the
source or baselines, markers restored) are in `generation_log.json`.

## What it covers, and what it does not

| Attack | Victims | Docs | Scored at N |
|---|---|---|---|
| imitation | all 13 at N=3; the 6 cross-work victims at N=5 and N=10 | 25 (13 + 6 + 6) | the N it was written from |
| paraphrase | chesterton, christie, dickens, emerson, mill, thoreau | 12 (2 each) | 3, 5 and 10 |
| roundtrip_de | the same 6 | 12 | 3, 5 and 10 |
| roundtrip_ja | the same 6 | 12 | 3, 5 and 10 |

61 documents. Imitations run 583-722 words; every paraphrase and
back-translation is 0.97-1.11 times its source's length (about 2,500
words). Paraphrases and round trips rewrite the victim's genuine
held-out documents, which do not depend on N, so the same 36 documents
are scored against the 3-, 5- and 10-paper baselines.

The seven plain-manifest victims (augustine, boethius, douglass, edwards,
james, kempis, newman), whose held-out documents run 2,800-19,400 words
(12 of the 14 over 7,500), have imitations only. Rewording and
round-tripping those 14 documents is about five times the generation work
of everything else here; the owner deferred it (2026-11-19). Those victims
exist only at N=3, so G-A3 at N=3 covers 6 of 13 victims. The gate's
coverage rule withholds a would-be pass on that population until they are
generated; it does not soften a fail, and G-A3 fails on its point
estimates regardless. G-A3 at N=5 and N=10, and G-A2 at every N, are fully
covered.

## Limits that go with any result read from this corpus

- **One generator.** Every doc comes from one model. A student can use
  any model, and a detector that separates this one's output is not shown
  to separate another's.
- **Published authors, not students.** Long, distinctive, edited prose;
  pilot students write shorter and more alike.
- **The model knew.** The brief told agents the output was a test
  document. It asked for a genuine best response, but a model that knows
  it is being tested is not a student trying not to be caught.
- **Strong prompts.** The imitation prompt hands the model every baseline
  in full (up to 58,000 words); a student would paste less.
- **Imitations are short.** The imitation prompt asks for about 600
  words, while the genuine documents G-A2 compares them with run
  2,500-19,400 words, and a short paper scored against long past papers
  reads as unlike them whoever wrote it. Measured
  (`validation/adversarial/imitation_controls.py`): against the authors'
  own excerpts cut to the imitations' length, the separation does not
  survive (AUROC 0.27 to 0.43). Do not read G-A2's AUROC as style; see the
  findings addendum.
- **Layout differs, but the score does not see it.** For the six
  cross-work victims every baseline and held-out document is one unbroken
  paragraph, while every imitation has paragraphs (3 to 27). Their
  paragraph length is the same in every baseline, so the score leaves that
  feature out (`StudentState.active_feature_mask`); removing the
  imitations' paragraph breaks moved their scores by at most 0.025.
- **Paraphrases added paragraphs too.** For single-paragraph sources the
  paraphrases of chesterton (about 55 paragraphs), dickens (about 30),
  emerson (about 15) and thoreau (3) split the text up; christie's and
  mill's, and every round trip but three (at most 4 paragraphs), stayed one
  paragraph. For the reason above this likely matters little to G-A3.
- **Famous originals can be recalled.** These are well-known published
  texts, and a model translating a German or Japanese version of, say,
  Mill back into English can land on Mill's own sentences from memory.
  Share of word 8-grams a doc has in common with its source
  (`overlap_with_source` in `generation_log.json`): paraphrases 2-17%,
  back-translations via Japanese 7-18%, via German 16-54%, with Mill
  (54%) and Emerson (47%) highest. A student's unpublished essay cannot be
  recalled that way, so on this corpus a round trip may look more like
  its author than it would for a student, which makes it harder to catch,
  not easier.

## Regenerating or extending

```
.venv/bin/python -m validation.adversarial.llm_attack_jobs jobs --jobs-dir <dir> \
    --attacks imitation
.venv/bin/python -m validation.adversarial.llm_attack_jobs jobs --jobs-dir <dir> \
    --attacks paraphrase,roundtrip_de,roundtrip_ja --victims <victims>
# give each J/view/<job>.txt to a fresh agent, which writes J/out/<job>.txt
.venv/bin/python -m validation.adversarial.llm_attack_jobs hop2 --jobs-dir <dir>
# second hops, each to an agent that has not seen that document's English
.venv/bin/python -m validation.adversarial.llm_attack_jobs assemble --jobs-dir <dir> \
    --model <exact model id>
```

`assemble` merges into the existing manifest, so a later batch (the seven
plain-manifest victims, or a second model) adds to this corpus without
touching what is here.
