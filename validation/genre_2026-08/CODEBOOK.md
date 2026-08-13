# Genre Labelling Codebook

**Date:** 2026-08-08
**Spec:** `docs/superpowers/specs/2026-08-08-genre-resolution-design.md`
**Status:** frozen. Committed **before** any document was labelled and before
any classifier code existed.

---

## Why this document is committed first

Labels for this corpus are assigned by hand, by the same agent that
implements the classifier. That is a real circularity: labels could be
shaped, consciously or not, to be the ones a particular model would find
easy.

Nothing in a promise fixes that. What fixes it — partially — is ordering that
can be checked afterwards by someone who does not trust the labeller:

1. This codebook is committed **alone**, before `labels.json` exists.
2. `labels.json` is committed before `genre_v2` gains any model code.
3. `labels.json` pins `codebook_sha256`, so the definitions cannot be
   rewritten under labels that were assigned against an earlier version.
4. The train/hold-out split is **author-disjoint** and the hold-out is not
   read during derivation.
5. An author-shuffled control re-fits on permuted labels and must collapse to
   chance, which is the direct test for a classifier that has learned authors
   rather than genres.

The git history is the evidence. If these commits are not in this order, the
guarantee is void.

---

## Label set

Three classes. Not the eight in `GENRE_LABELS`, and not the five the spec
anticipated. Reduced from four on 2026-08-08 — see the redefinition section.

| class | in the class set? | why |
|---|---|---|
| `academic_exegesis` | yes | 5 distinct seminary authors |
| `scholarly_essay` | yes | Mill, James, Newman, Chesterton, Burke, Paine, Federalist |
| `narrative_prose` | yes | Dickens, Christie, Austen, Twain, Doyle (invented); Douglass, Augustine, Thoreau, Franklin, Washington, Keller, Grant, Cellini (recounted) |
| `personal_essay` | **no** | superseded — see "The redefinition of 2026-08-08" |
| `creative_fiction` | **no** | superseded — separated from the above by truth claim, which text cannot carry |
| `sermon` | **no** | **only one author available** |
| `blog_post` | no | no examples in any committed corpus |
| `correspondence` | no | no actual letters in any committed corpus |
| `structured_template` | no | markup, not style — a syntactic rule, not a learned class |

### Why `sermon` was dropped

The spec anticipated five classes including `sermon`. The corpus cannot
support it: the only genuine homiletic texts are Jonathan Edwards'
`selected_sermons_of_jonathan_edwards_part_*.txt` — six documents, **one
author**. Newman is present but as *The Idea of a University*, which is
lectures rather than sermons.

A class evidenced by exactly one author cannot be distinguished from a
detector for that author. Keeping it would mean the model could score well on
`sermon` by recognising Edwards' prose, and no hold-out split could reveal
that, because there is no second sermon author to hold out.

This is precisely what the "no class carried by a single author" rule exists
to catch, and it caught it before anything was trained. `sermon` remains in
`GENRE_LABELS` — stored values stay valid — but v2 will never predict it.

Chance accuracy for the remaining three classes is **0.333**.

---

## The classes

### `academic_exegesis`

Formal written analysis of a text or doctrine, produced for assessment or
scholarly publication, in which the argument is organised around exposition
of sources rather than around the writer's own experience.

**Include when:** the document analyses a specific text, doctrine or passage;
its structure is expository (claim, evidence, qualification) rather than
narrative or hortatory; and it addresses a reader as an assessor rather than
as a congregation or a friend.

**Exclude when:** the primary mode is persuasion of a general public
(→ `scholarly_essay`); the text advances by events (→ `narrative_prose`);
or the text addresses the reader in the second person
to move them to action (would be `sermon`, which is not in the class set —
label such documents `scholarly_essay` only if the expository mode dominates,
otherwise leave them out of the labelled set entirely).

**Worked examples:** `validation/corpus/seminary_04_justification.txt`,
`validation/corpus/seminary_05_ecclesiology.txt`.

**Nearest neighbour:** `scholarly_essay`. **Deciding test:** who is the
addressee? Academic exegesis is written for someone who will evaluate it
against sources; a scholarly essay is written for someone who must be
persuaded. If the document would be graded, it is exegesis.

---

### `scholarly_essay`

Sustained argumentative prose addressed to an educated general reader,
advancing a thesis about ideas, institutions or public questions.

**Include when:** the document argues a position at length; the intended
reader is a public rather than an examiner; and the organising structure is a
chain of argument rather than a narrative or a personal reflection.

**Exclude when:** the text advances by scene and event rather than by claim
(→ `narrative_prose`); or the document is written to be graded
(→ `academic_exegesis`).

**Worked examples:**
`validation/public_authors/corpus/mill/on_liberty_part_01.txt`,
`validation/corpus/fed_hamilton_001.txt`.

**Nearest neighbour:** `narrative_prose`. **Deciding test:** is the first
person doing argumentative work or narrating events? Mill writes "I" while
arguing about liberty in general; Thoreau writes "I" about what he himself did
at Walden. Argument about the world → scholarly. Account of events →
narrative. The pronoun decides nothing.

---

### `narrative_prose`

Prose whose organising structure is a sequence of events and reported
speech — scene, incident, and what people said — whether those events are
invented or recounted as the writer's own.

**Include when:** the text advances by event rather than by claim; character
or participant speech is a substantial part of the prose; and a reader
follows *what happened next* rather than *what follows from this*.

**Exclude when:** the organising thread is a chain of argument, even one
carried in the first person (→ `scholarly_essay`); or the text expounds a
source for an assessor (→ `academic_exegesis`).

**Worked examples:**
`validation/public_authors/cross_work_corpus/dickens/a_tale_of_two_cities_01.txt`
(invented), `validation/genre_2026-08/corpus/washington/up_from_slavery_01.txt`
(recounted).

**Nearest neighbour:** `scholarly_essay`. **Deciding test:** does removing the
events leave an argument standing? Mill's *On Liberty* survives losing its
examples; *Up From Slavery* does not survive losing its events.

---

## The redefinition of 2026-08-08

`narrative_prose` replaces two earlier classes, `creative_fiction` and
`personal_essay`, which were separated by a distinction text cannot carry.

The old codebook's deciding test between them was **the truth claim**:
"fiction does not assert that its events happened." That is a fact about the
world, not a property of the prose. It was measured to be unlearnable exactly
as the definition predicts: with the classifier otherwise scoring 1.000 on
third-person novelists (Austen, Doyle) and 0.947 on scholarly essays, every
single error on the hold-out — five of them — was Mark Twain predicted
`personal_essay` against a `creative_fiction` label. *Huckleberry Finn* and
*Tom Sawyer* are first-person vernacular narratives of a boy recounting his
own experiences; stylometrically they ARE autobiography. No surface signal
separates them from *Up From Slavery*, and none ever will.

The replacement axis is **mode of discourse** — event-and-speech versus
claim-and-warrant — which prose does carry, and which is what the label is
actually used for downstream: `creative_fiction` existed in the first place
to mute tier 16 (citation and signal-verb features), and narrative prose
lacks citations whether it is invented or true. Muting on the wider class is
if anything more correct than muting on the narrower one.

Both old labels remain in `GENRE_LABELS` so stored `sample.genre` values and
`get_genre_stats` pooling keys stay valid. v2 simply never emits them.

### What this gives up

Fiction and autobiography are no longer distinguished. That is a real
reduction in what the taxonomy claims, and it is the honest one: the system
was never able to make that distinction, it was only asserting it. For the
product the cost is small — students submit reflection papers and essays,
not novels — and for the one consumer that reads the label, the merged class
is the better fit.

## Recorded judgement calls

### Plato is excluded from the labelled set

The spec anticipated labelling Plato's dialogues `creative_fiction` under a
dialogue criterion. On reflection while writing these definitions, that is
wrong on both available readings: Socratic dialogue is philosophical argument
in dramatic form, so it satisfies `creative_fiction`'s exclusion clause
("dialogue used as a vehicle for philosophical argument") and equally fails
`scholarly_essay`'s requirement that the structure be a chain of argument
rather than a scene.

Two further reasons not to force it into either class. Plato is 263 of the
available documents, so a single labelling decision would dominate class
balance outright. And the corpus holds two different translations (Cary,
Jowett) of the same source, so the "author" of the English prose is a
translator — which makes the author-disjointness of any split ambiguous in a
way no other group has.

Plato is therefore **not labelled and not used**. This is a deliberate
reduction in corpus size in exchange for not resting a class on a
contestable call.

### Chesterton appears in two classes

*Orthodoxy* and *Heretics* are labelled `scholarly_essay`. Chesterton also
wrote fiction, but the committed corpus contains only his essays, so he
contributes to one class. He is nonetheless valuable: he is the one author
present in both `public_authors/corpus` and `cross_work_corpus`, which makes
him a useful check that document-level duplication across those two trees
does not leak between splits.

### Documents that fit no class are omitted, not forced

Any document that does not clearly satisfy one class's inclusion criteria is
left out of `labels.json` entirely. A forced label is worse than a missing
one: it teaches the model a boundary the codebook does not actually draw, and
it inflates apparent coverage. Notably this omits the `ai_*.txt` corpus (the
genre of generated text is whatever it was prompted to imitate) and the
devotional works (Kempis, Boethius, Augustine's more meditative books) where
the line between `personal_essay` and a homiletic mode we cannot label is
genuinely unclear.
