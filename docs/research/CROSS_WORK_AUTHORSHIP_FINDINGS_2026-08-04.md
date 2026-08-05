# Six-author cross-work authorship findings

This benchmark tests whether Original recognizes an author in a different
work, rather than memorizing one book or topic. It uses six authors, two
disjoint Project Gutenberg works per author, and three fixed 2,500-word
windows per work. Baselines and probes never share a work.

## Corpus

The 36-document corpus includes:

- Charles Dickens: *Great Expectations* → *A Tale of Two Cities*;
- Agatha Christie: *The Mysterious Affair at Styles* → *The Secret
  Adversary*;
- G.K. Chesterton: *Orthodoxy* → *Heretics*;
- Ralph Waldo Emerson: *Essays — First Series* → *Essays — Second Series*;
- John Stuart Mill: *On Liberty* → *Utilitarianism*;
- Henry David Thoreau: *Walden* → *Cape Cod*.

The manifest records Project Gutenberg identifiers, source URLs, public-domain
notes, source-body hashes, window hashes, work IDs, genre, language, and split
role. The Gutenberg title pages state that every included work is public
domain in the United States.

## Locked attribution result

Each of 18 held-out probes was scored against all six frozen author baselines.
No thresholds or weights were fitted during this run.

- Top-1 attribution: **17/18 (94.44%)**.
- Mean true-author rank: **1.17**.
- Dickens, Christie, Chesterton, Mill, and Thoreau: 3/3 each.
- Emerson: 2/3. The final *Second Series* window was assigned to Mill, with
  Emerson ranked fourth.

The failure is retained as counterevidence. It occurs in the hardest slice:
same language, century, essay register, and partially overlapping philosophical
subject matter.

## Binary verification

The 18 genuine and 90 impostor trials expose a distinction between
author-relative discrimination and globally portable probabilities.

| Metric | Raw production deviation | Peer-relative impostor LR |
|---|---:|---:|
| Median per-author AUC | 0.9889 | 1.0000 |
| Per-author AUC IQR | 0.8778–1.0000 | 0.9667–1.0000 |
| Pooled uncalibrated AUC | 0.7691 | 0.9519 |
| Pooled Brier | 0.6221 | 0.1268 |
| TPR at pooled 1% FPR | 0.1111 | 0.6111 |
| TPR at pooled 5% FPR | 0.2778 | 0.6667 |
| TPR at pooled 10% FPR | 0.5000 | 0.7778 |

Emerson is the clearest diagnosis: its raw per-author AUC is 0.3556, while the
peer-relative likelihood-ratio channel reaches 0.9556. The main problem is not
that every stylometric feature lacks signal; it is that raw deviation scales
are not comparable across authors. Population-relative normalization repairs
much of that mismatch without changing the fixed feature schema or global
normalization bounds.

## Product consequence

The peer-relative score is the strongest human-impostor channel and should be
the principal input to a future calibrated stack. It remains attach-only:
there are only six historical authors and three genuine probes per author,
and the 1% FPR operating point still detects only 61.1% of genuine-author
mismatches. A universal misconduct threshold is not supported.

Generated reports are under
`validation/benchmarks/2026-08-04/verify_cross_work_six_authors_*` and are
ignored by Git. This tracked note preserves the locked results; the manifest
and corpus preserve the exact inputs.

## Modern cross-topic PAN stress test

The historical result does not transfer unchanged to modern cross-topic
writing. A second corpus was built from the official PAN 2020 authorship-
verification test release (Zenodo DOI `10.5281/zenodo.5106099`; archive MD5
`655f365ab7b736036bbbee717168012b`). The repository's previous PAN downloader
metadata was unusable: its configured 2021 and 2022 Zenodo IDs resolve to
unrelated genomics and terrain-software records. This benchmark uses the
author IDs in PAN's released truth file rather than inventing pseudo-authors
from pair-local nodes.

From 496 eligible real authors, 12 were selected by a predeclared SHA-256
ordering. Each author contributes three baseline documents from one fandom and
three probes from a different fandom. Every source text is unique by SHA-256;
fixed deterministic windows cap each document at 2,500 words. This produces 36
genuine and 396 human-impostor trials.

| Metric | Frozen raw score | Peer-relative impostor LR |
|---|---:|---:|
| Median per-author AUC | 0.6869 | 0.7778 |
| Per-author AUC IQR | 0.5531–0.8687 | 0.6212–0.9697 |
| Pooled uncalibrated AUC | 0.7063 | 0.7334 |
| Pooled Brier | 0.7302 | 0.1584 |
| TPR at pooled 1% FPR | 0.1111 | 0.3056 |
| TPR at pooled 5% FPR | 0.3611 | 0.3611 |
| TPR at pooled 10% FPR | 0.4722 | 0.4722 |

The direct null-model runner's internal raw comparator was slightly higher
(median AUC 0.6970, pooled AUC 0.7106) than the HTTP report. This approximately
one-point discrepancy is retained as a validator-parity issue; it does not
change the conclusion. Peer normalization helps, especially calibration, but
30.6% recall at 1% FPR is not sufficient for authentication or misconduct
claims. Modern topic variation is the missing stressor that the historical
corpus concealed.

**Decision:** do not fuse or promote the current human-impostor channel into a
live action. The next model must learn content-reduced style on author-disjoint
development data and pass a separate author- and topic-disjoint locked test.
Until then, Original can surface inconsistency for review but cannot reliably
authenticate authorship across topic shifts.

## Author-disjoint content-reduced expert

The next model was implemented under `validation/verify/pan_style_expert.py`.
It uses three disjoint real-author partitions:

- 120 development authors fit the representations and equal-prior logistic
  calibration;
- 40 different calibration authors select the 1%, 5%, and 10% impostor-accept
  operating thresholds;
- the original 12 authors remain locked until final evaluation.

No author, probe, or fandom crosses those partitions. The two base signals are:

1. TF-IDF character 3–5-gram cosine similarity, with the 30,000-term
   vocabulary fitted on development baselines only;
2. a content-reduced Burrows-style distance using fixed function-word rates,
   punctuation, word-length histograms, capitalization, and sentence rhythm.

The regularized logistic model learned standardized coefficients 0.853 for
character similarity and 0.725 for content-reduced similarity. On the locked
authors:

| Signal | Pooled AUC | TPR at 1% ROC FPR |
|---|---:|---:|
| Frozen Original | 0.703 | 5.6% |
| Peer-relative Original | 0.731 | 30.6% |
| Character similarity | 0.856 | 25.0% |
| Content-reduced similarity | 0.883 | 30.6% |
| Two-style-signal calibrated fusion | **0.890** | **47.2%** |

The two-signal fusion has Cllr 0.642, Brier 0.166, median per-author AUC 1.000,
and per-author AUC IQR 0.881–1.000. At the threshold selected on all 40
calibration authors, it accepts 17/36 genuine claims and 4/396 impostor claims:
47.2% TPR (Wilson 95% CI 32.0–63.0%) and 1.01% FPR (95% CI 0.39–2.57%).

A second group-aware fusion test added frozen Original and peer-relative
probabilities. It used 20 separate authors for author-grouped fusion fitting,
20 for thresholds, and the same locked 12. Despite positive development
weights for all four channels, locked AUC fell to 0.845 and strict-point TPR
to 38.9%. This is negative evidence against indiscriminately stacking every
available score: the older channels are unstable under the modern topic shift
and degrade the stronger expert.

**Promotion gate: failed.** Only 12 locked authors and 36 genuine trials are
available, the observed strict FPR is just above 1%, and its upper confidence
bound is 2.57%. This initial expert was the best modern human-authorship
candidate but was not promoted on that evidence. The four-channel stack is
rejected rather than shipped. Reports are `pan_style_expert.json` and
`pan_stacked_fusion.json` under
the ignored `validation/benchmarks/2026-08-04/` directory.

## Peer alignment and two fresh 40-author locks

The follow-up style expert was then extended with two label-free cohort-normalized
signals: each probe's character and content-reduced similarities to the claimed
author are standardized against its similarities to the other authors in the
same evaluation cohort. The calibrator uses raw character similarity, raw
content-reduced similarity, peer-z character similarity, and peer-z
content-reduced similarity. It was fitted on the same 120 development authors;
the strict threshold, 0.852247, was selected once on the same 40 calibration
authors. Neither fresh lock influenced representations, weights, or threshold.

| Locked partition | Authors | Genuine / impostor trials | AUC | Cllr | ROC TPR at 1% FPR | TPR at frozen threshold | FPR at frozen threshold |
|---|---:|---:|---:|---:|---:|---:|---:|
| Fresh lock A | 40 | 120 / 4,680 | 0.8784 | 0.6254 | 40.0% | 40.8% | 1.154% |
| Fresh lock B | 40 | 120 / 4,680 | 0.9331 | 0.5229 | 54.2% | 51.7% | 0.748% |
| A + B, frozen threshold | 80 | 240 / 9,360 | — | — | — | 46.3% | 0.951% |

Fresh lock A failed the predeclared 1% point-FPR gate; fresh lock B passed it
with 62/120 accepted genuine trials and 35/4,680 accepted impostor trials. The
latter FPR has a Wilson 95% interval of 0.538–1.038%. Across both untouched
locks the point estimate is just under 1%, but the between-lock variation is
material. This supports cautious report-only review evidence, not an automated
authorship verdict.

The resulting artifact is committed as
`original/data/style_authorship_v1.joblib` and is exposed only when
`STYLE_AUTHORSHIP_ENABLED=1`. It requires a probe of at least 300 words, three
retained authenticated baseline texts for the claimed student, and ten
same-tenant peer profiles with three retained baselines each. Unsupported cases
return `null`. A score below the strict threshold is labeled `inconclusive`,
never `impostor`; the field cannot change Original's score, recommendation, or
action. Artifact schema, signal order, vocabulary checksum, reference
predictions, and threshold are validated before use, with failure closed.

This channel answers only whether a document is stylistically consistent with
the claimed writer under the evaluated conditions. It does not identify an
alternative writer and does not distinguish a human ghostwriter, direct AI, or
humanized AI. Those cause-attribution gates remain separate and unpassed.
