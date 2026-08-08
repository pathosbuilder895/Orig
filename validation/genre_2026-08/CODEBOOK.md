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

Four classes. Not the eight in `GENRE_LABELS`, and not the five the spec
anticipated.

| class | in the class set? | why |
|---|---|---|
| `academic_exegesis` | yes | 5 distinct seminary authors |
| `scholarly_essay` | yes | Mill, James, Newman, Chesterton, Burke, Paine, Federalist |
| `personal_essay` | yes | Thoreau, Emerson, Douglass, Augustine |
| `creative_fiction` | yes | Dickens, Christie |
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

Chance accuracy for the remaining four classes is **0.25**.

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
(→ `scholarly_essay`); the writer's own life is the subject matter
(→ `personal_essay`); or the text addresses the reader in the second person
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

**Exclude when:** the argument is carried by narrative or scene
(→ `creative_fiction`); the subject is the writer's own experience
(→ `personal_essay`); or the document is written to be graded
(→ `academic_exegesis`).

**Worked examples:**
`validation/public_authors/corpus/mill/on_liberty_part_01.txt`,
`validation/corpus/fed_hamilton_001.txt`.

**Nearest neighbour:** `personal_essay`. **Deciding test:** is the first
person doing argumentative work or autobiographical work? Mill writes "I" while
arguing about liberty in general; Thoreau writes "I" about what he himself did
at Walden. Argument about the world → scholarly. Account of a life →
personal.

---

### `personal_essay`

First-person reflective prose in which the writer's own experience,
observation or interior life is the subject rather than the illustration.

**Include when:** the writer is the subject; the organising thread is
experience or reflection rather than argument; and removing the first person
would destroy the piece.

**Exclude when:** the first person is incidental to an argument about
something else (→ `scholarly_essay`); the narrative is invented
(→ `creative_fiction`); or the reflection is structured as exposition of a
source (→ `academic_exegesis`).

**Worked examples:**
`validation/public_authors/corpus/thoreau/civil_disobedience.txt`,
`validation/public_authors/corpus/douglass/my_bondage_and_my_freedom_part_01.txt`.

**Nearest neighbour:** `creative_fiction`. **Deciding test:** is the narrative
asserted as true of the writer? Douglass's account of his own enslavement is
autobiography; Dickens's account of Pip's childhood is not.

---

### `creative_fiction`

Invented narrative: characters, scene and dialogue presented as story rather
than as argument or record.

**Include when:** events and persons are invented; the text advances by scene
and incident; and reported speech between characters is a substantial part of
the prose.

**Exclude when:** the narrative is asserted as the writer's own experience
(→ `personal_essay`); dialogue is used as a vehicle for philosophical
argument (see the Plato note below); or quotation is of sources rather than
of characters (→ `academic_exegesis` / `scholarly_essay`).

**Worked examples:**
`validation/public_authors/cross_work_corpus/dickens/a_tale_of_two_cities_01.txt`,
`validation/public_authors/cross_work_corpus/christie/the_mysterious_affair_at_styles_01.txt`.

**Nearest neighbour:** `personal_essay`. **Deciding test:** the truth claim.
Fiction does not assert that its events happened.

---

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
