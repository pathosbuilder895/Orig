# Stacked Authorship Verification Plan

Status: implementation contract (research-only until the promotion gates pass)

## Objective

Improve Original's ability to distinguish a claimed author's natural style,
gradual stylometric drift, a human impostor/ghostwriter, direct AI generation,
humanized AI, and locally mixed authorship. The system must abstain when the
evidence cannot support that distinction. No research output may alter the
existing `deviation_score`, action, or professor-facing decision by default.

## Why the current score is insufficient

The per-student score estimates distance from the claimed writer. It does not,
by itself, estimate how likely the text is under a relevant population of other
writers, identify the cause of a mismatch, or account for a student's gradual
change through time. Topic, genre, work, translation, text length, and prompt
can all create distance that is not an authorship change.

The current public-author benchmark also permits same-work leakage for several
authors: chunks of one book occur on both sides of the baseline/probe split.
That measures continuation within a work more than cross-work authorship.

## Hypotheses and independent evidence channels

The primary verification question is binary:

- `H_claimed`: the claimed author wrote the text.
- `H_other`: the claimed author did not write the text.

Evidence channels are kept separate until calibration:

1. Claimed-author distance: existing deviation/fidelity/conformal evidence.
2. Population evidence: score relative to a tenant- and genre-matched impostor
   cohort, not merely distance from the claimed author.
3. Longitudinal evidence: deviation from the predicted current style after a
   gradual model is selected using history only. It can explain a mismatch but
   cannot establish authorship on its own.
4. Content-reduced style evidence: an independently trained representation or
   function-word signal that is tested cross-topic and cross-work.
5. AI evidence: the existing corpus-level AI likelihood, explicitly not an
   identity score.
6. Humanization evidence: an adversarially trained detector evaluated on held-
   out generators and held-out humanizers.
7. Local mixture evidence: window-level discontinuity/segmentation for texts
   assembled from multiple sources.
8. Process evidence: keystroke/paste/revision telemetry when genuinely
   available. Missing telemetry is missing, never neutral evidence.

## Calibration and fusion

Each channel first emits a score plus an availability flag. Scores are mapped
to log-likelihood-ratio space using held-out calibration data. A regularized
logistic fusion model consumes only out-of-fold base-model predictions and
availability flags. Missing channels are median-imputed after fold-local
standardization and accompanied by their flags, so absence cannot look like a
negative result.

No likelihood ratios are multiplied under an independence assumption. The
fusion model learns dependence among channels. The artifact records feature
order, folds, corpus hashes, model versions, calibration authors, and reference
predictions; mismatches disable it rather than silently changing results.

The second-stage cause classifier runs only when `H_other` has adequate
evidence. Its mutually exclusive labels are:

- `human_impostor`
- `direct_ai`
- `humanized_ai`
- `mixed_authorship`
- `unknown_other`

If the best class is below its calibrated precision requirement or too close
to the runner-up, return `unknown_other`. Natural drift remains an explanation
attached to `H_claimed`, not a fifth impostor class.

## Non-leaky evaluation splits

Three partitions are mandatory: development, calibration, and a locked test.

- Fusion splits are author-disjoint. No author used to fit a base expert or
  meta-learner appears in the locked test.
- Claimed-author trials are cross-work and preferably cross-topic. Chunks from
  one work must stay in a single partition and may not form both baseline and
  probe evidence.
- Generator families and humanizer/attack families are grouped: at least one
  generator and one attack family are held out entirely.
- Longitudinal trials are chronological. A disputed probe never enters its own
  historical fit; shuffled chronology is a required negative control.
- Threshold selection uses calibration only. The locked test is evaluated once
  per version and its corpus hashes are stored with the report.

## Required corpora

1. PAN authorship-verification corpora for open-set, author-disjoint trials.
2. Public-domain cross-work authors: at minimum Dickens and Chesterton, plus
   multiple essayists already present. Agatha Christie is included only for
   works whose distribution is lawful in the evaluation jurisdiction and whose
   source records that status.
3. RAID and M4/AuTexTification for direct-AI generalization.
4. DAMAGE-style humanizer attacks and local perturbation suites for humanized
   AI. Synthetic attack generation must never be mixed into the locked human
   evaluation set.
5. Constructed mixed-authorship texts with known boundaries, generated only
   from already licensed corpus texts and recorded in a reproducible manifest.

Every entry records `author_id`, `work_id`, title, source URL, source/license
note, language/translation, genre, date when known, word count, and partition.

## Metrics and promotion gates

Report per-author and macro distributions, never only pooled accuracy:

- verification: `Cllr`, `Cllr_min`, Brier, ECE, AUC, and TPR at 1%, 5%, and
  10% FPR;
- attribution of alternatives: macro-F1, per-class precision/recall, confusion
  matrix, coverage, and selective risk under abstention;
- robustness slices: author, work, topic, genre, length, native-language status,
  generator, attack/humanizer, and mixed-text boundary distance;
- drift: genuine-probe false-flag rate before/after drift relief, impostor escape
  rate, model-selection frequency under shuffled chronology, and change-point
  false alarms.

Promotion requires all of the following on the locked test:

1. No regression in macro claimed-author AUC or `Cllr` versus the best current
   production signal, with bootstrap confidence intervals reported.
2. Lower or equal false-positive rate for genuine cross-work probes at the
   chosen operating point.
3. Drift relief lowers genuine longitudinal false flags without a material
   increase in impostor acceptance.
4. Cause labels meet predeclared precision thresholds; otherwise the system
   abstains.
5. No evaluated demographic/language slice shows a material unexplained
   degradation; any underpowered slice is labeled inconclusive.
6. Default-off and report-only integration is byte-compatible with existing
   score/action behavior and the full test suite passes.

## Implementation sequence

1. Repair corpus metadata and add cross-work sources without changing the
   production feature schema.
2. Implement a validation-only, group-aware out-of-fold fusion and abstention
   harness with synthetic unit tests.
3. Produce base-expert trial tables from existing validation adapters.
4. Run author/work/generator/attack-disjoint ablations and calibration.
5. Package a versioned artifact only if promotion gates pass.
6. Add an opt-in, report-only API field with fail-closed loading.
7. Consider action changes only in a later ADR backed by locked-test evidence.

## Safety boundary

These scores are triage evidence, not proof of misconduct. Professor-facing
language must describe observed inconsistency and uncertainty, preserve the
student's opportunity to explain, and never claim that stylometry alone proves
who or what wrote a document.

## Research basis

- PAN/open-set experimental design: _Rethinking the Authorship Verification
  Experimental Setups_ (EMNLP 2022), https://aclanthology.org/2022.emnlp-main.380/
- Cross-domain author representations: _Learning Universal Authorship
  Representations_ (EMNLP 2021), https://aclanthology.org/2021.emnlp-main.70/
- Content-independent style: _Same Author or Just Same Topic?_ (2022),
  https://aclanthology.org/2022.repl4nlp-1.26/
- Robust AI-detector evaluation: RAID (ACL 2024),
  https://aclanthology.org/2024.acl-long.674/
- Humanizer/adversarial evaluation: DAMAGE (GenAIDetect 2025),
  https://aclanthology.org/2025.genaidetect-1.9/
- Likelihood-ratio evaluation and logistic fusion for text evidence:
  https://pubmed.ncbi.nlm.nih.gov/35334288/

## 2026-08-04 implementation evidence

The group-aware fusion and abstention harness is implemented under
`validation/stacked/`; PADBen direct/humanized adapters are under
`validation/cause/padben.py`; and DAMASHA mixed-boundary evaluation is under
`validation/cause/damasha.py`. Results are recorded in
`docs/research/CAUSE_ATTRIBUTION_FINDINGS_2026-08-04.md`.

The evidence supports selective positive humanization detection and a learned
mixed-window expert, but does not support reliable direct-vs-humanized negative
inference. Consequently, the planned production artifact/API promotion gate is
not met. The production score and action remain unchanged.

The subsequent RAID external test confirms why. A PADBen-trained subtype
ranking reverses on RAID paraphrasing (AUC 0.063), even though a RAID-local,
source-disjoint leave-one-generator-out expert reaches AUC 0.985. The
remaining promotion requirement is therefore attack/humanizer-family-disjoint
validation, not further tuning on the same paraphrase family.

The implemented attack-family evaluator uses a stable source-level
development/locked split, discards held-family rows from development sources,
excludes every locked source prompt from fitting, calibrates selective
thresholds on generator-held development predictions, and applies explicit
per-family gates. On PADBen first-versus-third paraphrase depth, AUC remained
0.944 but the direct-AI branch made no selections and coverage stayed below
40%; the promotion gate correctly failed.

The PAN requirement has now been exercised on a deterministic 12-author,
cross-fandom corpus recovered from the official PAN 2020 truth author IDs.
The frozen raw score fell to median per-author AUC 0.687 and 11.1% TPR at 1%
FPR. Peer-relative impostor evidence improved those figures to 0.778 and
30.6%, respectively, but still failed a safe authentication gate. This is the
strongest evidence that the remaining authorship problem is cross-topic
generalization, not merely threshold tuning. No fusion artifact or API action
change is authorized by these results.

A content-reduced follow-up now improves locked pooled AUC to 0.890 and TPR at
1% FPR to 47.2% by fusing character 3–5-gram similarity with function-word,
punctuation, word-length, and sentence-rhythm distance. Representation fitting
(120 authors), threshold calibration (40 authors), and locked testing (12
authors) are author-disjoint and cross-fandom. Adding raw Original and
peer-relative signals in a separately grouped four-channel stack regressed
locked AUC to 0.845 and strict TPR to 38.9%, so those weights are rejected.
The initial style expert was not promoted because locked genuine support was 36
and the 1.01% observed impostor-accept rate had a 2.57% upper Wilson bound.

A subsequent peer-aligned version was frozen on the same 120 development and
40 calibration authors, then evaluated on two new, disjoint 40-author locks.
Fresh lock A reached AUC 0.878 with 40.8% TPR and 1.154% FPR at the frozen
threshold; fresh lock B reached AUC 0.933 with 51.7% TPR and 0.748% FPR. Across
both locks the frozen threshold accepted 111/240 genuine and 89/9,360 impostor
trials (46.25% TPR, 0.951% point FPR). The cross-lock variation precludes action
coupling, but the sample now supports a default-off, report-only API field for
review. The production adapter abstains unless raw text is retained for three
claimed-author baselines and ten same-tenant peer profiles. Below-threshold
evidence is explicitly `inconclusive`, not evidence that an impostor wrote the
text. The existing deviation score, recommendation, and action remain
unchanged.

The cause audit now also contains an exact-source 1,080-document RAID study
with clean/synonym/paraphrase triplets for two AI generators and attacked human
controls. Holding out both generator and attack yields AUC 0.973–1.000 and
69.6–92.0% recall for unseen synonym rewriting at zero observed human FPR, but
only 12–13% recall for unseen paraphrasing. RAID-to-PADBen external transfer
then collapses to AUC 0.544, 2.7% human FPR, and 0.45% humanized-AI recall.
Consequently the next step is not subtype threshold tuning: it requires
multi-domain, multi-humanizer invariant training and another untouched
humanizer family. No cause artifact or API label is authorized.

A subsequent direction-stable, non-negative fusion confirms that preventing
weight reversals alone is insufficient: domain-held AUC spans 0.641–0.903 and
strict recall 2.4–27.5%. The joint identity/cause hierarchy reaches 99.55%
precision and 92.08% recall for merged AI-origin evidence on a Mistral/
paraphrase RAID lock, but its exact frozen threshold falls to 60.21% precision
on external PADBen because 189/222 human controls are selected as AI-origin.
Human-impostor precision is 77.78% on the PAN/RAID lock and 32.65% externally.
This locks in the remaining requirements: positive alternative-author evidence
for human ghostwriters and a genuinely cross-domain invariant representation
for AI origin. Low claimed-author similarity and a corpus AI score cannot be
treated as sufficient cause evidence.

Positive alternative-author scoring plus 64 deterministic General Impostors
subspace/peer trials improves known-peer human-impostor precision to 91.84%,
but recall is 37.5%. Against a fourth unseen 40-author cohort it falls to
80.95% precision / 14.17% recall. This establishes a closed-set/open-set
boundary: the signal can corroborate an enrolled peer, but it cannot identify
an arbitrary outside ghostwriter.

A separate GPT-2 same-model Fast-DetectGPT analytic diagnostic reaches AUC
0.9143 on a generator-held RAID lock (0.6% human FPR), yet paraphrased-AI recall
is 42.08%; on external PADBen its AUC reverses to 0.3121 and the frozen
threshold selects no AI. The experiment is explicitly a small-model
approximation, not the published configuration. It fails promotion and leaves
the required next step unchanged: validate a properly sized probability-
geometry model on multiple untouched human and humanizer domains.

The full-corpus follow-up uses the official codebase's same-model
GPT-Neo-2.7B pair (with a locally documented 256-token truncation). It also
fails: RAID AUC is 0.9013, direct-AI recall is 90.0%, paraphrased-AI recall is
32.08%, and external PADBen reverses to AUC 0.3879 with zero selections at the
frozen threshold. Consequently no curvature weight is added to the joint
stack. The failure is cross-domain orientation/calibration, not merely an
undersized GPT-2 observer.

A third external lock now uses 960 checksum-pinned English FAIDSet test texts,
balanced among genuine human, direct AI, and human--LLM collaborative writing
across four generator families. The transported frozen detector reaches AUC
0.748 but 57.5% human FPR; GPT-Neo curvature reaches AUC 0.757 but 0%
collaborative recall. Even hash-disjoint local-human calibration fails: the
best curvature anomaly has 62.19% direct recall, 0% collaborative recall, and
1.25% human FPR. This falsifies the hypothesis that local threshold
normalization alone will recover collaboration/humanization. The next model
must learn a collaboration representation from development corpora while
keeping FAID test, RAID attack families, and PADBen domains locked.

A final validation-only adversarial axis evaluates the released RADAR
RoBERTa detector, pinned to revision
`4ff1f23a69a36aa1df47b0933be6279f1b896c9b`. Its checkpoint is explicitly
non-commercial and therefore can never be a production dependency. Class
orientation is chosen on RAID development sources and the 1% threshold is
frozen on disjoint RAID human sources. On the untouched 960-document FAID lock,
RADAR reaches 50.31% merged recall including 53.13% collaboration recall, but
only 77.78% precision and 28.75% human FPR. Local authenticated-human
calibration lowers FPR to zero while collapsing direct/collaborative recall to
0%/0.63%. On a second external PADBen Task-5 deep-paraphrase stress lock, it
selects every AI and every human bundle (50% precision, 100% human FPR, AUC
0.582). Adversarial training supplies humanization recall, but the learned
boundary is not domain invariant; no RADAR score or weight is integrated.

The updated product contract was also applied to a new 100-author PAN lock,
with three authenticated baselines per author and 120 additional authors
excluded between calibration and lock. This revealed that the earlier
authorship promotion gate was incomplete: AUC/FPR could pass while the frozen
threshold selected no genuine authors. The gate now jointly requires ≥90%
precision, ≥50% recall, ≤1% FPR, and 100 locked authors. Peer alignment fails
with 0% recall; adding best-enrolled-alternative margins reaches AUC 0.880 but
only 82.35% precision / 9.33% recall at the frozen joint threshold.

Under the separately revised closed-set ghostwriter rule, the known-peer branch
passes: 90.20% precision / 38.33% recall on 120 held authors. The implementation
contract treats this only as broad human-impostor evidence. Exact source naming
was then tested explicitly: top-one identity accuracy is 47.5%; a calibrated
winner-over-runner-up margin reaches only 83.33% exact-name precision / 12.5%
recall and incorrectly names 1.67% of outside-pool writers. Because this fails
the 90%/30% identity gate and the ≤1% outside-naming guard, no peer-name expert
is packaged. The product must return `unknown_writer`.

Binary authentication is now evaluated separately from 100-way attribution
using one deterministic source-matched impostor for each genuine probe (300 +
300 locked trials across 100 authors). This resolves the prevalence mismatch
without weakening the explicit FPR gate. Claimed-minus-best-peer style margins
transport well at 98.90% precision and 0.333% FPR, but recall is only 30.0%.
A new topic-masked sequence axis retains function words, punctuation, and word-
length shapes while replacing content vocabulary. It improves ranking AUC to
0.890 but not the frozen operating point; the stable three-margin model reaches
97.20% precision / 34.67% recall / 1.0% FPR. A 100k character vocabulary also
fails to improve recall. Authentication therefore remains below the 50% gate.

A pinned LUAR-MUD universal authorship representation was then evaluated as an
independent pretrained expert. Each claimed author is represented by one LUAR
episode containing the same three authenticated baselines; each probe is a
one-document episode. The Apache-2.0 model is pinned to Hugging Face revision
`1c11d29789851d629e42455570780ec3cec89e6a`, and embeddings are cached by model
revision plus ordered document hashes. LUAR alone reaches locked AUC 0.867,
94.90% precision, 31.0% recall, and 1.667% FPR. Calibration-only variant
selection chooses LUAR cosine fused with the two existing style margins. On the
100-author lock that fusion reaches AUC 0.922, 100% precision, 39.33% recall,
and 0% observed FPR. The fusion improves the low-FPR result, but recall still
falls short of 50%; it therefore remains validation-only. The frozen report is
`pan_auth_luar_matched_cal100_lock100.json`.

Individual-baseline LUAR signals were then added without changing the fitting
partitions: probe-to-baseline mean/minimum/dispersion, baseline-pair cohesion,
and probe-versus-cohesion gap. Calibration selects those consistency signals
with LUAR cosine and the existing style margins. The existing 100-author lock
improves to 98.56% precision / 45.67% recall / 0.667% FPR (AUC 0.927).

To avoid further selection on that lock, the frozen model and threshold were
transported to a new 100-author open-set lock: 99 eligible PAN 2021 authors,
whose authors and topics are officially unseen relative to PAN 2020, plus one
previously unused PAN 2020 tail author after all 452 allocated authors. Every
author has three authenticated cross-topic baselines and contributes one
probe. This lock reaches AUC 0.941, 97.83% precision, 45.0% recall, and exactly
1.0% FPR. The result independently confirms the gain but still misses the 50%
recall gate. The report is `pan_auth_luar_pan21_open_lock100.json`; no live
authentication behavior is changed.

The final authentication ablation adds a regularized two-covariance PLDA/Bayes-
factor backend over individual LUAR embeddings, following the probabilistic
layer used by PAN's Deep Bayes Factor Scoring work. Development authors alone
fit a 64-dimensional PCA space, within-author covariance, between-author
covariance, and the three-baseline-versus-one-probe uncertainty model. PLDA
alone reaches calibration AUC 0.913 and 35.67% recall at the joint gate;
PLDA/style and PLDA/consistency/style fusions reach only 33.67% and 41.33%
recall. The existing consistency/style fusion remains the calibration-selected
model, and the fresh open-set lock remains unchanged at 45.0% recall. The
probabilistic backend is mathematically valid but adds no promotable separation
to LUAR under this data regime.

Two final fusion/calibration hypotheses are also rejected on calibration before
promotion. A regularized pairwise-interaction model over all 12 LUAR, PLDA,
cohesion, and style channels reaches only 38.67% gated recall versus 49.33% for
the existing linear consistency fusion. A three-stratum uncertainty rule then
allocates the same global 1% false-positive budget according to baseline-pair
cohesion; it reaches 47.33% calibration recall and would reach 44.0% on the
open-set lock. Neither rule is selected. This localizes the remaining 5-point
gap to representation/generalization rather than a missing nonlinear weight or
global-threshold artifact.

A supervised metric-learning ablation next fits shrinkage LDA exclusively on
the individual development-author LUAR embeddings. In the resulting geometry,
the regularized pairwise interaction fusion becomes calibration-selected at
98.05% precision / 50.33% recall / 1.0% FPR. The frozen point clears recall but
transports at 2.0% FPR on both the prior 100-author lock (54.0% recall) and the
fresh PAN 2021 lock (59.0% recall). Calibration thresholds allowing 0, 1, 2,
or 3 false accepts out of 300 show that no stricter global point retains both
50% recall and at most 1% transported FPR.

To test local calibration without touching model weights, 43 unused PAN 2020
tail authors form a separate author-disjoint threshold cohort. Its 1%-budget
threshold reaches 57.36% local recall with 1/129 false accepts, but produces
67.0% recall and 6/100 false accepts on PAN 2021. This rejects the assumption
that author disjointness makes a threshold cohort deployment-representative.
The next valid step is institution-local calibration matched on assignment and
population, followed by a separately reserved institutional lock; the current
public-corpus experiment cannot authorize production promotion.

An additional independent domain uses Project Gutenberg's machine-readable
catalogue (SHA-256
`77090fbe48e36863f9dfcfb1d273d3e8457dafb6ff0d71e736f688bfd31becf2`).
The deterministic builder rejects ambiguous/editor/translator/corporate
records and retains 400 English writers with six distinct, content-hashed works
each. After an initial PAN-transfer failure, the final pre-registered protocol
uses writers 1--50 for local fitting, 51--100 for selection, excludes two
viewed 100-author blocks, and locks writers 301--400. Three works form each
baseline and three further works form probes.

The zero-calibration-false-accept rule selects LUAR cosine plus the two style
margins. On the final untouched 100-author lock it accepts 238/300 genuine
trials and 0/300 deterministic source-matched impostor trials: 100% precision,
79.33% recall, and 0% observed FPR. This passes the numerical public-corpus
gate. It does not satisfy the institutional evidence requirement: historical
edited books are not student assignments, and the 95% Wilson upper FPR bound
is 1.264%. No production action changes until a representative institutional
calibration cohort and separate untouched student lock reproduce the result.

The same Gutenberg blocks were used for a strict enrolled-peer identity audit.
The candidate ranker learns development-only weights over LUAR cosine,
character n-grams, and content-reduced rhythm, while an independent confidence
model sees both known and outside writers. Top-one accuracy improves from 30%
for raw LUAR to 73%. The locked known-peer result is 95.10% precision / 32.33%
recall, but 4/300 outside probes are named (1.333%), one case above the guard.
A zero-outside calibration budget produces 96.81% / 30.33% with the same
outside error. Adding a runner-up-margin conjunction lowers recall to 28.67%
and still does not reject those four cases. The branch therefore remains
validation-only and all outside writers resolve to `unknown_writer`.
