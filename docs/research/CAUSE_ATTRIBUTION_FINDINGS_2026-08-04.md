# Cause-attribution and mixed-authorship findings

These experiments test whether Original can explain a strong claimed-author
mismatch. They do not change the live score or action path. Generated JSON and
feature caches remain under `validation/benchmarks/2026-08-04/` and are ignored
by Git; the adapters record source URLs, licenses, parameters, and input hashes
so the measurements can be reproduced from the same corpus snapshots.

## PADBen paraphrase stress test

Dataset: PADBen (MIT), 555 bundled sentence-level trials from MRPC, PAWS, and
HLPC. Each outer fold holds out one source corpus. Inner source-held-out
predictions select per-class thresholds targeting 90% precision; the outer
source is never used for fitting or threshold selection.

The input is Original's 103-feature vector plus the frozen AI-likelihood
probability. Bundling twelve same-source sentences stabilizes document
features, but does not turn PADBen into natural essays.

- Coverage: 40.5%; selective accuracy: 81.8%.
- Humanized-AI precision: 92.1%; recall: 58.1%.
- Human and direct-AI branches did not retain adequate cross-source precision
  and therefore mostly or entirely abstained.
- In the separate direct-vs-humanized experiment, humanized precision was
  90.6% at 60.8% recall, but direct-AI precision was only 69.2%.

Verdict: a positive humanization signal is useful research evidence. Absence
of that signal is **not** evidence of direct AI. No production subtype artifact
is promoted.

## DAMASHA mixed-authorship stress test

Dataset: 60 clean Human-to-AI records from DAMASHA/MAS (CC-BY-4.0), split into
16 training, 14 calibration, and 30 locked rows. The training partition fits a
regularized window expert over Original's features plus the frozen AI signal.
The calibration partition chooses mixture-range operating points; locked rows
measure performance.

- Frozen AI detector pure-window AUC: 0.437 (failure under short windows).
- Learned window expert locked AUC: 0.907.
- At the calibration q95 threshold: mixed recall 80.0%; control FPR 8.3%.
- At the conservative max-control threshold: mixed recall 16.7%; control FPR
  1.7%.
- Boundary median absolute error: 32 words; p90: 59 words.

Verdict: local window learning repairs much of the distribution mismatch, but
the operating point is not suitable for high-stakes use. The batch
AI-likelihood path added during this study is safe infrastructure; the learned
mixture model remains validation-only.

## RAID external subtype transfer

Dataset: a deterministic HTTP Range sample from RAID's pinned MIT-licensed
training CSV (revision `865cac74188466cb0c3b7574a10204007b57a459`). The
locked set contains 100 `books` documents: 25 clean and 25 paraphrase-attacked
generations from each of `llama-chat` and `mistral-chat`. Median length is 267
words. The sample has 94 source prompts; overlapping prompts are removed from
held-out folds. Its local JSON SHA-256 is
`fe3f10342bd94ed2eba4d1a0580b0f81b899694039f6fcde64f00ae6b52a6832`.

The external test exposes two different generalization questions:

- The PADBen-trained three-way model fails: 12% coverage, 0% selective
  accuracy, and no direct-AI or humanized-AI decisions. The other 88% abstain.
- Its continuous direct-versus-humanized ranking is worse than chance (AUC
  0.063), showing that PADBen-specific paraphrase cues reverse on RAID.
- The frozen AI detector, interpreted as humanization lowering its AI score,
  reaches only 0.712 AUC.
- A RAID-local leave-one-generator-out model reaches pooled AUC 0.985 after
  removing shared source prompts. Per fold, train-Mistral/test-Llama AUC is
  1.000 and train-Llama/test-Mistral AUC is 0.993.

Verdict: generator transfer within one domain and one paraphrase mechanism is
strong, but attack-family transfer is unproven. The next locked gate must train
without a second RAID attack/humanizer family and test on it. No subtype model
or threshold is promoted.

### PADBen paraphrase-depth negative control

The attack-family protocol was also applied locally to PADBen's first- and
third-pass paraphrases. Each fold holds out one depth, uses a stable source-row
development/locked split, removes every locked source group from development,
and calibrates thresholds on generator/source-domain-held predictions.

- Hold out first pass: AUC 0.9435, coverage 4.9%, humanized precision 100%,
  humanized recall 9.8%, and no direct-AI selections.
- Hold out third pass: AUC 0.9444, coverage 30.2%, humanized precision 91.4%,
  humanized recall 55.2%, and no direct-AI selections.
- The predeclared subtype gate requires AUC >= 0.80, precision >= 90%, recall
  >= 50%, coverage >= 40%, and support >= 20 for every held family and class.
  It fails both folds.

This separates discrimination from deployment: the feature stack ranks the
held paraphrase depth well, but the calibrated two-sided operating point cannot
identify direct AI and abstains too often. A high AUC alone is not grounds for
a cause label.

## Matched multi-attack AI-origin invariance

The RAID follow-up now uses exact-source triplets rather than independently
sampled documents. For each of 120 roots per model, `adv_source_id` links the
clean, synonym-rewritten, and paraphrase-rewritten versions of the same text.
The corpus contains two AI generators (`llama-chat`, `mistral-chat`) plus human
controls subjected to the same rewrites: 1,080 documents total. Rewritten human
text remains human, following DAMAGE's invariance formulation.

Each fold holds out both one generator and one attack family. Root sources use
a fixed 60/20/20 development/calibration/locked split. The model sees the other
generator and the other attack only; thresholds use calibration human controls
at a target 1% FPR. Locked slices contain 23–25 direct and attacked AI examples
per generator and 38 human controls.

| Held attack | Held generator | AUC | Human FPR | Direct-AI TPR | Attacked-AI TPR |
|---|---|---:|---:|---:|---:|
| Paraphrase | Llama-chat | 0.9595 | 2.63% | 96.0% | 12.0% |
| Paraphrase | Mistral-chat | 0.9594 | 0.00% | 78.3% | 13.0% |
| Synonym | Llama-chat | 1.0000 | 0.00% | 80.0% | 92.0% |
| Synonym | Mistral-chat | 0.9731 | 0.00% | 60.9% | 69.6% |

Thus, training on RAID paraphrasing transfers to unseen synonym rewriting, but
training on synonym substitutions does not recover unseen paraphrasing at the
strict operating point. The overall AUC for paraphrase folds is high because
the ranking remains useful, yet the calibrated high-specificity tail misses
most attacked AI. The promotion gate fails both paraphrase folds.

An additional external test fits and calibrates only on the matched RAID
corpus, then evaluates once on PADBen bundles from MRPC, PAWS, and HLPC. PADBen
comes from commit `2bdc624b6536f63dbf90a10486aa6dc0b554d135`; input SHA-256 is
`bd221a8669c7b804e77fa85a17b3ec3e4e834faf8c3342a1d8c575db8f8a6484`.
Transfer fails: AUC 0.5440, human FPR 2.70%, direct-AI TPR 0%, humanized-AI TPR
0.45%, and AI precision 14.29% among seven selections.

**Decision:** no AI-origin or direct-versus-humanized artifact is promoted.
The evidence supports treating humanization robustness as learned invariance,
not claiming the rewrite method from final text. It also shows that even the
invariant detector remains domain/paraphraser-specific. Reports are
`raid_ai_origin_invariance_120.json` and
`raid_external_origin_padben.json`; exact byte ranges and content hashes are
recorded in their source manifests.

## Direction-stable fusion and local calibration

A post-hoc feature audit found that 35/104 production signals reverse their
AI-vs-human direction between RAID and PADBen; the cross-corpus AUC-order
Spearman correlation is only 0.298. Strong reversals include function-word and
stop-word ratios, perplexity proxy, paragraph length, and noun/verb ratio.
More stable signals include frozen AI likelihood, sentence-length variance,
Latinate ratio, nominalization density, adjective rate, passive voice, and
burstiness.

`validation/cause/invariant_origin.py` therefore selects features using
development domains only, retains a feature only when its AUC direction agrees
in every development domain, orients it consistently, and fits an L2 logistic
model with non-negative weights. Entire RAID/PADBen domains are held out; all
selection, imputation, scaling, weights, and thresholds exclude the held
domain. The constrained model is precise but not useful enough: held-domain
AUC ranges 0.641–0.903 and strict recall ranges 2.4–27.5%. A disjoint local
human calibration subset does not repair this; PADBen calibration support is
only 18–30 independent human groups, far below what is required to resolve a
1% tail, and locked FPR remains unstable. Roughly 100 independent authenticated
human controls are needed even to obtain 1%-granularity empirical calibration.

## Joint identity/cause stack

`validation/cause/joint_stack.py` tests the intended decision hierarchy with
only two auditable axes: the frozen peer-aligned claimed-author probability and
the frozen AI-likelihood probability. Cause development, calibration, and
locked testing use three fresh, mutually disjoint 40-author PAN partitions.
RAID development/calibration uses Llama-chat clean/synonym roots; the lock
changes both generator and rewrite family to Mistral-chat clean/paraphrase.

The unconstrained four-way stack fails:

| Cause | Locked precision | Locked recall |
|---|---:|---:|
| Claimed author | 86.0% | 66.7% |
| Human impostor | 81.8% | 52.5% |
| Direct AI | 75.0% | 27.5% |
| Humanized AI | no selections | 0% |

A conservative hierarchy applies the independent frozen authorship threshold
first, then merges direct and humanized AI as `ai_origin_unknown_subtype` unless
subtype evidence exists. On the RAID/PAN lock it reaches 100% precision / 38.3%
recall for positive claimed-author evidence and 99.55% precision / 92.08%
recall for merged AI-origin evidence. Human-impostor evidence reaches only
77.78% precision / 58.33% recall because genuine cross-topic authors occupy the
same low-style tail.

Those promising RAID-local AI-origin numbers do **not** transfer. Applying the
exact frozen hierarchy to external PADBen yields 60.21% AI-origin precision at
85.89% recall: 189/222 human texts are false AI-origin selections. Human-
impostor precision falls to 32.65%. Therefore neither the merged AI-origin
label nor any finer subtype is promoted. The report is `joint_cause_stack.json`.

### Positive alternative-author and General Impostors evidence

The human-impostor branch was extended to score every enrolled peer and to use
64 deterministic General-Impostors-style trials (30% random character-feature
subspaces and 50% random peer subsets). This is positive evidence for a known
alternative author, not merely evidence against the claim. On the known-peer
lock the selective four-way branch reaches 91.84% precision but only 37.5%
recall. When the ghostwriter comes from a fourth, entirely unseen 40-author PAN
cohort, precision/recall fall to 80.95%/14.17% (75.38%/40.83% in the merged
hierarchy). It therefore corroborates an enrolled peer but does not solve
open-set ghostwriter detection.

### Probability-curvature negative control

`validation/cause/zero_shot_origin.py` implements the analytic same-model
Fast-DetectGPT statistic as a validation-only, small-model diagnostic. Its
threshold is calibrated on RAID Llama-chat plus disjoint human roots; Mistral
and PADBen remain untouched locks. The GPT-2 approximation reaches AUC 0.9143
on the generator-held RAID lock, with 0.6% human FPR, 80.83% direct-AI recall,
and 42.08% paraphrased-AI recall. On external PADBen it reverses to AUC 0.3121
and selects no AI at the frozen threshold. This is not the published
multi-billion-parameter configuration and is not a production detector. It
shows that likelihood geometry is a useful independent axis but, at this
scale, remains domain/model dependent. The locked report is
`zero_shot_origin_gpt2.json`.

The experiment was then repeated with the official implementation's
GPT-Neo-2.7B/GPT-Neo-2.7B model pair over the full 1,080 RAID documents and all
555 PADBen bundles. The local protocol truncates to 256 tokens, so it is a
published-model-pair replication rather than the paper's exact configuration.
The larger model does not repair transfer: held-generator RAID AUC is 0.9013,
with 0.6% human FPR, 90.0% direct-AI recall, and only 32.08% paraphrased-AI
recall. External PADBen AUC is 0.3879 and the frozen threshold again selects no
AI. The result rules out model size as the explanation for the GPT-2 failure
under this protocol. The content-addressed, incrementally checkpointed report
is `zero_shot_origin_gptneo27b.json`.

### FAIDSet human--LLM collaboration lock

An additional untouched external lock uses the MIT-licensed FAIDSet test split
at revision `e2927dd1218b32767b212f822366c01bd406f5b3`. The adapter verifies nine
source-file checksums, filters English academic documents with at least 80
words, removes duplicate text hashes, and deterministically balances 960
trials: 320 human, 320 direct AI, and 320 human--LLM collaborative across GPT,
Gemini, Llama, and DeepSeek. Collaborative writing is kept distinct from
humanizer-paraphrased AI.

The frozen AI-likelihood score reaches AUC 0.748 but its transported threshold
flags 57.5% of genuine humans. GPT-Neo probability curvature reaches AUC 0.757;
its transported threshold has 0% human FPR but recalls only 30.0% of direct AI
and 0% of collaborative writing. A hash-disjoint local-human calibration (160
calibration / 160 locked humans) repairs neither signal: AI-likelihood recall
falls to 19.69% direct / 7.19% collaborative at 0% observed FPR; a two-sided
curvature anomaly reaches 62.19% direct recall but 0% collaborative recall and
1.25% locked-human FPR. No signal passes. The report is
`faid_external_lock.json` and the adapter is `validation/cause/faid.py`.

### RADAR adversarial detector transfer

The released RADAR-Vicuna-7B detector tests a genuinely independent hypothesis:
joint adversarial training against a paraphraser. The 355M-parameter RoBERTa
checkpoint is pinned to revision
`4ff1f23a69a36aa1df47b0933be6279f1b896c9b` and weights SHA-256
`4ea32c4a31b7004364df4fe672c5c763f3d5f32b7514aaeb2b5e47653bc89792`.
Its Vicuna-derived license is non-commercial, so it is validation-only even if
metrics pass.

RAID development sources determine class orientation (AUC 0.984), and disjoint
RAID human sources freeze the 1% threshold. Transport to FAID reaches 50.31%
merged AI-involvement recall and 53.13% collaborative recall, but 28.75% human
FPR and 77.78% precision. Hash-disjoint local-human calibration produces 0%
human FPR but only 0% direct and 0.63% collaborative recall. A second external
PADBen Task-5 lock bundles checksum-pinned human originals and third-iteration
paraphrases; RADAR selects all 320 bundles, yielding AUC 0.582, 50% precision,
and 100% human FPR. The experiment shows adversarial training can recover
humanization recall, but not a transferable low-FPR boundary. The report is
`radar_origin_faid.json`; no production signal is added.

The supported mathematical architecture is now empirically clear:

1. claimed-author consistency is a peer-aligned, independently calibrated
   channel;
2. AI-origin evidence needs its own cross-domain invariant representation and
   local human calibration support;
3. human-impostor evidence requires positive population-relative alternative-
   author evidence, not merely low claimed-author similarity;
4. direct-versus-humanized provenance must remain unknown without a separate
   humanizer-family expert.

## Revised product-gate audit on 100 untouched authors

The authentication gate was corrected to require the actual frozen operating
point—not merely AUC and FPR—to achieve at least 90% precision and 50% recall
on at least 100 out-of-training authors, each with three authenticated
cross-topic baselines. A new 100-author PAN lock, placed after the original
lock, development, calibration, and 120 additional excluded authors, exposes a
previous false-positive promotion condition. The peer-aligned model has AUC
0.866 but its calibration threshold selects nobody (0% recall). Increasing
calibration from 40 to 100 authors does not repair it.

Adding claimed-minus-best-enrolled-peer margins improves AUC to 0.880. Under a
calibration-only joint ≥90%-precision/≤1%-FPR threshold, however, the untouched
lock reaches 82.35% precision and 9.33% recall (28/300 genuine selections and
6/29,700 impostor selections). It therefore remains report-only and cannot be
called authenticated authorship. The corrected reports are
`pan_style_peer_product_gate_cal100_lock100.json` and
`pan_style_margin_product_gate_cal100_lock100.json`.

The separate closed-set enrolled-peer ghostwriter branch does clear the revised
initial gate. On 120 held authors it reaches 90.20% precision and 38.33% recall
(51 selections), exceeding ≥90%/≥30%. Its scope is explicitly limited to the
enrolled comparison pool; an author outside that pool must return
`unknown_writer`. This validates the broad **class** signal, not peer naming and
not authorship authentication.

A subsequent exact-identity audit carries the true source and predicted
best-peer ID through every trial. The actual enrolled source is the top-ranked
alternative only 47.5% of the time; among the 51 broad human-impostor
selections, exact-name precision is 62.75%. Adding the best peer's margin over
the second-best peer and calibrating only on enrolled identities improves the
locked selective result to 83.33% exact-name precision / 12.5% recall, while
still naming 1.67% of outside-pool writers incorrectly. It fails all three
identity gates (90% precision, 30% recall, and ≤1% outside naming). Therefore
no peer-name artifact is packaged; outside and ambiguous cases remain
`unknown_writer`.

### Binary source-matched authentication protocol

The 100-way exhaustive target matrix is appropriate for identity attribution
but gives 99 impostor claims for every genuine claim. A separate binary
verification lock now pairs every genuine probe with one deterministic
different-author probe at the same probe offset: 300 genuine and 300 impostor
trials over the same 100 untouched authors. Fitting still uses all development
pairs; only calibration and locked operating-point evaluation are matched.

Peer-aligned probability again fails threshold transfer. Claimed-minus-best-
peer character/content margins are stable and reach 98.90% precision, 30.0%
recall, and 0.333% FPR. Adding topic-masked function-word/punctuation/word-shape
1--4-grams reaches AUC 0.890 and a theoretical 49% TPR at the locked 1% ROC
point, but its frozen calibration threshold recalls only 7.33%. A margin-only
version is stable at 97.20% precision / 34.67% recall / 1.0% FPR. Expanding
character vocabulary from 30,000 to 100,000 does not help (97.80% / 29.67% /
0.667%). Thus the content-reduced margin family satisfies precision and FPR
but not the required 50% recall. No authentication artifact is promoted.

### Pretrained LUAR authorship representation

The next validation-only expert uses the externally pretrained LUAR-MUD model
to encode the three authenticated baselines jointly and every probe
individually. The model and tokenizer are pinned to revision
`1c11d29789851d629e42455570780ec3cec89e6a`; the adapter is isolated from the
live API and uses content-addressed, incrementally written embeddings. Variant
and operating-threshold selection use only the 100 calibration authors.

LUAR cosine alone transports to the 100-author lock at AUC 0.867, 94.90%
precision, 31.0% recall, and 1.667% FPR. Fusing LUAR cosine with character and
content-reduced claimed-minus-best-peer margins improves locked AUC to 0.922
and the calibration-frozen operating point to 100% precision / 39.33% recall /
0% observed FPR (118/300 genuine and 0/300 impostor selections). The locked
ROC contains a 50.33% TPR point at 1% FPR, but changing the threshold after
viewing the lock would invalidate the protocol; the frozen threshold remains
at 39.33% recall. The 50% authentication-recall gate therefore still fails and
no production artifact is added.

Adding individual-baseline consistency (probe-to-each-baseline similarity,
dispersion, baseline-pair cohesion, and a cohesion-relative gap) improves the
same locked operating point to 98.56% precision / 45.67% recall / 0.667% FPR.
The calibration-selected model and threshold were then transported unchanged
to a fresh 100-author lock. It contains 99 PAN 2021 open-set authors—officially
unseen authors and topics relative to PAN 2020—and one never-allocated PAN 2020
tail author. With three cross-topic baselines per author and one probe each,
the fresh lock reaches AUC 0.9414, 97.83% precision, 45.0% recall, and 1.0% FPR.
The independent lock confirms the improvement but not the required recall, so
authentication remains report-only.

A regularized PLDA log Bayes factor was also evaluated over LUAR document
embeddings. Development authors fit PCA plus within- and between-author
covariance; the scorer explicitly models the lower uncertainty of a
three-document baseline mean relative to a one-document probe. PLDA ranks well
(calibration AUC 0.913) but reaches only 35.67% recall at the joint operating
gate. Its best fusion with consistency and style margins reaches 41.33%, below
the already selected 49.33% calibration recall. It is therefore rejected before
locked selection and does not change the 45.0% fresh-lock result.

Explicit cross-channel pairwise interactions and uncertainty-stratified
thresholding were tested next. The interaction-only logistic fusion is strongly
regularized but falls to 38.67% calibration recall. The uncertainty rule uses
baseline cohesion to allocate one shared 1% false-positive budget across three
cohorts; it reaches 47.33% calibration recall and 44.0% on the open-set lock.
Both underperform the existing global linear fusion and are rejected. The
remaining authentication error is not repaired by nonlinear weights or
cohesion-conditioned thresholds.

Shrinkage LDA fitted only on development-author LUAR documents was then tested
as a supervised metric. It makes a regularized cross-channel interaction model
the calibration winner at 98.05% precision / 50.33% recall / 1.0% FPR. The
frozen threshold reaches 96.43% / 54.0% / 2.0% on the prior lock and 96.72% /
59.0% / 2.0% on the PAN 2021 lock. A complete 0--3 calibration-false-positive
sensitivity audit finds no global cutoff that preserves both target recall and
transported FPR.

A separate 43-author, author-disjoint PAN 2020 tail cohort was used only to
estimate a local threshold. Although it meets its local false-positive budget
(1/129) with 57.36% recall, it yields 6/100 false accepts on PAN 2021. This is
evidence of domain-dependent calibration: local thresholding requires a cohort
representative of the actual institution and a later untouched institutional
lock. The experiment remains validation-only and supplies no production cause
or authentication decision.

### Independent Gutenberg cross-work lock

A deterministic Project Gutenberg builder supplies a separate literary domain
of 400 writers and six content-hashed English works per writer. Following an
exploratory PAN-transfer failure, a pre-registered local protocol fits on 50
authors, selects on 50, excludes both viewed 100-author blocks, and evaluates
the final untouched 100. The selected LUAR-cosine/style-margin model reaches
238/300 genuine accepts and 0/300 impostor accepts: 100% precision, 79.33%
recall, and 0% observed FPR.

This is strong cross-work authentication evidence but not student or cause
evidence. The corpus differs from academic submissions, its zero-FP upper 95%
bound is 1.264%, and it neither identifies enrolled ghostwriters nor separates
human writing from AI involvement. It therefore remains report-only pending
the institutional lock and the independent cause gates.

The corresponding closed-pool identity experiment combines LUAR, character,
and content-reduced candidate scores. It reaches 95.10% exact-name precision
and 32.33% recall for known peers, but names 4/300 outside writers (1.333%). A
zero-outside calibration budget retains 96.81% precision and 30.33% recall yet
does not reduce the transported outside count; a runner-up-margin rule instead
drops recall below 30%. Because the outside guard fails, no exact identity is
exposed and the required result remains `unknown_writer`.

### RepreGuard-style activation directions

A validation-only reproduction of RepreGuard's central mechanism uses the
immutable MIT-licensed `microsoft/phi-2` revision
`810d367871c1d460086d9f82db8696f2e0a0fcd0`. For each transformer layer it
fits the first PCA direction of paired M4 machine-minus-human mean-token hidden
states, then averages layer projections. M4 alone supplies 512 training pairs
and 512 disjoint threshold-calibration pairs; RAID and FAID are external
transport diagnostics.

At the permitted 1% empirical human calibration budget, M4 calibration reaches
only 73.33% precision and 2.15% recall. RAID ranking remains strong (AUC
0.9442), but the operating point reaches 100% precision, 10% merged recall,
and 0% human FPR: clean generation recall is 30%, while synonym and paraphrase
recall are both 0%. FAID reaches AUC 0.8138 but selects no direct or
human--LLM collaborative examples. The smaller 64-pair diagnostic showed the
same structural failure (90% direct RAID recall and 70% direct FAID recall,
but 0% transformed/collaborative recall).

The experiment therefore confirms that source-model activation evidence does
not survive the transformations Original must detect. It fails the merged AI
involvement gate and is rejected; no Phi-2 dependency, activation feature, or
production score is added.

## Product consequence

The supported decision hierarchy is:

1. Measure claimed-author versus other-author evidence.
2. If other-author evidence is strong, evaluate independent human-versus-AI,
   humanization, and mixture signals.
3. Emit a specific cause only when that cause's held-out precision gate passes.
4. Otherwise return `unknown_other`.

Current evidence supports population-relative human-impostor evidence on the
six-author cross-work corpus. Humanized AI can be surfaced only as experimental
positive evidence, and direct-versus-humanized subtyping must abstain unless a
locally validated attack-family expert is available. This is an intentional
result, not a missing default.

## Research sources

- PADBen dataset and benchmark: <https://huggingface.co/datasets/JonathanZha/PADBen>
- DAMASHA/MAS model and data card: <https://huggingface.co/saiteja33/DAMASHA-RMC>
- DAMASHA paper: <https://aclanthology.org/2026.findings-eacl.326/>
- DAMAGE humanizer evaluation: <https://aclanthology.org/2025.genaidetect-1.9/>
- RAID robust detector benchmark: <https://aclanthology.org/2024.acl-long.674/>
- Koppel and Winter, *Determining if Two Documents Are Written by the Same
  Author*: <https://doi.org/10.1002/asi.22954>
- Potha and Stamatatos, *An Improved Impostors Method for Authorship
  Verification*: <https://aclanthology.org/W17-4902/>
- Fast-DetectGPT: <https://arxiv.org/abs/2310.05130>
- Binoculars: <https://arxiv.org/abs/2401.12070>
- LUAR: <https://aclanthology.org/2021.emnlp-main.70/>
- Official LUAR repository: <https://github.com/LLNL/LUAR>
- Deep Bayes Factor Scoring: <https://arxiv.org/abs/2008.10105>
- RADAR: <https://arxiv.org/abs/2307.03838>
- RepreGuard: <https://aclanthology.org/2025.tacl-1.81/>
