# Model Card — Original Stylometric Scorer v1.4.25

This document describes the current feature pipeline, scoring model, output actions, reliability limits, and intended institutional use of Original.

---

## Intended use

Original is designed for higher-education academic integrity review, with a current product focus on theological seminaries and writing-intensive college courses. Given authenticated baseline samples for a student and a new submission, Original outputs a deviation score, supporting explanation, and recommended instructor action.

**Original is a decision-support tool, not a decision-making system.** It does not prove misconduct, assign guilt, or replace institutional process. All non-clear results require human review before any academic or disciplinary action.

Recommended use:

- Build a writing baseline from proctored or instructor-verified work.
- Compare new submissions against that student's established writing profile.
- Use recommendations to decide whether to monitor, schedule a conversation, or begin formal review.
- Record instructor decisions so the institution can audit outcomes and recalibrate over time.

Not recommended:

- Standalone punishment, grading penalties, or misconduct findings based only on a score.
- Cross-domain comparison where baseline and submission genres are materially different.
- High-stakes use with weak baselines, very short texts, or missing institutional review policy.

---

## Inputs

- **Baseline samples** — Authenticated writing samples by the same student. Proctored samples carry the highest authentication weight, instructor-verified samples carry lower weight, and unverified samples are excluded from baseline construction.
- **Submission** — A new text submission. The API accepts short text, but practical reliability begins around 300 words and improves with longer, genre-matched essays.
- **Optional proctored keystroke data** — Used by Tier 17 behavioral biometrics when a Bluebook/proctored writing session supplies timing, deletion, pause, paste, and revision signals. When absent, these dimensions default to neutral values.

Minimum baseline policy (recommended thresholds):

| Condition | Effect |
|-----------|--------|
| < 3 authenticated baselines | Treat as insufficient — read any score as low-confidence enrollment, not a verdict. |
| 3-4 authenticated baselines | Scoring runs at reduced confidence; treat any `escalate` as "review," not "act." |
| >= 5 authenticated baselines | Full action range is available, subject to confidence checks. |
| Low baseline purity | Treat recommendations with caution and consider rebaselining. |

**Enforcement note.** These are *recommended* thresholds. The current pilot scoring
surface (`original/api.py`) enforces only the zero-sample block — scoring is refused
until at least one authenticated sample exists — and expresses thin baselines through
a reduced `baseline_confidence` and a "confidence is limited" note in the rationale,
rather than hard-suppressing `escalate`. The stricter hard gates —
`MIN_BASELINE_SAMPLES = 3` (below which scoring is blocked) and
`MIN_BASELINE_FOR_ESCALATE = 5` (below which `escalate` is downgraded to
`schedule_conversation`) — are enforced on the v1 policy path (`original/api/v1/`).
Until they are enforced on the pilot surface, institutions should apply the
suppression thresholds during human review.

---

## Feature Pipeline

The current engine uses `FEATURE_DIM = 103` from `original/constants.py`.

- **96 base dimensions** are extracted from text, citation behavior, and optional proctored keystroke data.
- **7 comparison/profile dimensions** are computed during scoring when baseline context is available — 2 pure comparison features (Tier 0 below) plus 5 baseline-relative features distributed across Tiers 9–11.
- Legacy profiles with older dimensions are padded on load for backward compatibility.

| Tier | Name | Count | Purpose |
|------|------|-------|---------|
| 1 | Surface stylometrics | 9 | Lexical diversity, sentence length, function words, passive voice, word length. |
| 2 | Discourse and cohesion | 13 | Transitions, lexical chains, thematic progression, paragraph structure. |
| 3 | Rhetorical register | 12 | Hedging, assertion, claims, first person, source integration, theological register. |
| 4 | Character/punctuation fingerprint | 7 | Character trigram entropy, punctuation diversity, comma/semicolon/dash/quote habits. |
| 5 | POS and syntax | 7 | POS entropy, noun-verb balance, adjective/adverb rates, subordination, clause depth. |
| 6 | Idiosyncratic markers | 6 | Contractions, that/which ratio, citation style, list markers, abbreviation tendency. |
| 7 | AI-pattern signals | 6 | Burstiness, perplexity proxy, repetition gaps, transition predictability, hedge clustering. |
| 8 | Prosodic rhythm | 4 | Stress entropy, clausulae consistency, breath-group variance. |
| 9 | Cognitive sequencing | 2 | Argument topology and baseline-relative argument sequence likelihood. |
| 10 | Semantic gravity wells | 2 | Semantic field dispersion and baseline-relative centroid proximity. |
| 11 | Error ecology | 3 | Error-profile divergence, stumble-rate consistency, punctuation-error similarity. |
| 12 | Tension arc | 1 | Structural catastrophe index from sentence-length tension arc. |
| 13 | Prosodic depth | 6 | Clausula type, breath regularity, sonority, arc resolution, metric flatness. |
| 14 | Error topology | 4 | Positional error entropy, article omissions, pronoun ambiguity, comma splices. |
| 15 | Lexical architecture | 5 | Semantic concentration, polysyndeton, chiasmus, Latinate ratio, nominalizations. |
| 16 | Citation fingerprint | 8 | Signal verbs, source loyalty, block quotes, citation clustering, ibid., paraphrase style. |
| 17 | Behavioral biometrics | 6 | Keystroke rhythm, bursts, deletion rate, pauses, paste events, revision depth. |
| 0 | Comparison/profile features | 2 | The two pure baseline-relative comparison dimensions computed at scoring time. (The other 5 of the 7 comparison/profile dims are the baseline-relative features already counted in Tiers 9–11, so this Count column sums to 103.) |

Preprocessing removes bibliography, appendix, notes, parenthetical citation markers, footnote superscripts, and block quotes from prose features while preserving citation behavior for Tier 16.

---

## Scoring Model

Each student's authenticated baseline samples form a density matrix ρ: a weighted sum of outer products of normalized feature vectors.

```
ρ = Σᵢ wᵢ vᵢvᵢᵀ / Σᵢwᵢ
```

Weights combine sample provenance and recency. New submissions are scored with a baseline-relative deviation calculation and a Born-rule-style projection/fidelity signal. The response includes:

- `deviation_score` — distance from the student's established baseline, normalized to 0-1.
- `authorship_probability` / fidelity-style signal — how strongly the submission projects onto the student's baseline state.
- `baseline_confidence` — sample count, purity, and confidence indicators.
- `interference_decomposition` (response key: `interference`) — feature/tier contributions that drove the recommendation.
- `trajectory_conformance` (response key: `trajectory`) — whether observed deviation resembles natural growth.
- `context_manifest` and scoring report when enabled — auditable context and weighting decisions.
- `recommended_action` (response key: `recommendation.action`) — `no_action`, `monitor`, `schedule_conversation`, or `escalate`.

---

## Output Actions

| Action | Typical deviation range | Meaning |
|--------|-------------------------|---------|
| `no_action` | 0.00-0.40 | Submission is consistent with the student's established voice. |
| `monitor` | 0.40-0.60 | Mild deviation; watch future submissions and context. |
| `schedule_conversation` | 0.60-0.75 | Notable deviation; instructor should discuss the submission with the student. |
| `escalate` | 0.75-1.00 | Significant deviation; begin formal institutional review if baseline confidence is adequate. |
| `escalate` override | RMS z ≥ 3.0 | Catastrophic drift; immediate review recommended. |

By policy, escalation is suppressed when fewer than 5 authenticated baselines are available — but see the enforcement note under *Inputs*: on the current pilot surface this is expressed as reduced confidence and a thin-baseline caution rather than a hard downgrade, so a sparse-profile `escalate` can still surface and must be corroborated by human review. A recommendation is never equivalent to a finding of misconduct.

---

## Human Review Policy

Original's intended review flow is:

1. **Inspect the explanation.** Identify which features and context assumptions drove the result.
2. **Check baseline quality.** Confirm the student has enough authenticated, genre-matched baselines.
3. **Talk with the student.** Ask about drafting process, sources, tutoring, accommodations, language support, illness, time pressure, or legitimate style change.
4. **Record the decision.** Keep an audit trail of instructor judgment and any corrected label.
5. **Escalate only through institutional policy.** Original should support, not replace, due process.

This posture is especially important for multilingual writers, students with disabilities, students receiving writing support, and students moving between genres.

---

## Known Limitations

- **Topic and genre dependency** — Results are strongest when baseline and submission are in comparable genres. Cross-domain scoring can be unreliable.
- **Length sensitivity** — Very short texts produce unstable feature estimates; practical reliability begins around 300 words.
- **Baseline dependency** — Weak, inconsistent, stale, or unauthenticated baselines reduce reliability.
- **Calibration** — Thresholds should be recalibrated against each institution's confirmed outcomes before high-stakes use.
- **Bias and accessibility** — The system must be monitored for differential accuracy across multilingual writers, disability accommodations, and writing-support contexts.
- **Adversarial behavior** — Sophisticated users may try to mimic surface features; deeper citation, rhythm, error, and proctored behavioral features are designed to raise the cost of evasion, not make evasion impossible.
- **AI detection scope** — Original is not primarily an "AI detector." It verifies consistency with a student's own writing history, which may catch ghostwriting, AI-assisted writing, or other authorship changes. A dedicated corpus-level AI-likelihood detector exists as an optional second scoring mode — see the section below.

---

## AI-Likelihood Detector (second scoring mode, optional)

A supervised human-vs-AI classifier that runs **alongside** the per-student
identity verification, answering a different question: not "does this match
student X's baseline?" but "does this look like AI-generated text at all?"
Motivated by the PR #21 diagnostic: Original's own then-103 features + a plain
classifier reached AUC 0.7402 on AuTexTification where the per-student
Born-rule path (never trained on a labeled example) scored 0.6091.

**Contract**

- Gated by `AI_LIKELIHOOD_ENABLED=1`; **default OFF everywhere**, including
  demo mode and both Render services. Flag-off responses are byte-identical.
- **Report-only.** The signal never feeds the deviation score or the
  recommended action. The structured API field (`ai_likelihood`) carries the
  calibrated probability, band (`low`/`elevated`/`strong`), and up to three
  plain-language indicators; professor-facing prose is band-only,
  frequency-framed, and never contains a number.
- Fail-closed runtime (`original/ai_likelihood.py`): a missing, schema-
  mismatched, or version-skewed artifact logs one warning and the field is
  null — never an error to the caller.

**Training and artifact**

- Trained by `scripts/train_ai_detector.py` on a register-diverse mix:
  the AuTexTification 2023 English subtask-1 official train split
  (33,845 rows) plus the M4 train side (12,758 rows across
  arxiv/peerread/reddit/wikihow/wikipedia; 20% of pairs hash-held-out
  for evaluation and never trained on). Text columns only.
- The academic mix matters: the AuTexT-only v1 model flagged 40% of
  authentic seminary essays and 76-91% of archaic historical prose —
  formal register read as "AI-like" to a tweet-heavy model. With
  arxiv/peerread human prose in training, both failure modes measured 0-4%.
- Committed artifact: `original/data/ai_detector_v1.joblib` with full
  provenance (git SHA, sklearn/numpy versions, dataset sha256s, metrics).
- Thresholds are Neyman-Pearson operating points from train-out-of-fold
  probabilities of FORMAL-REGISTER humans (legal/arxiv/peerread, n=8,645):
  `t_elevated` at 5% FPR, `t_strong` at 1% FPR. The official AuTexT test
  split is scored exactly once, by the frozen artifact.
- Evaluation evidence lives in `validation/diagnostics/ai_detector_eval_*.json`
  (official test, M4 holdout, RAID cross-dataset, in-domain seminary;
  `*_v2_*` files are the shipped mixed-training model, earlier files
  document the AuTexT-only v1 for comparison).

**sklearn version-skew runbook** — the loader smoke-predicts 8 stored
reference vectors at startup; drift > 0.02 disables the detector with a
logged reason. If that happens after a dependency bump, retrain the artifact
on the deployed sklearn version (`train_ai_detector.py train`) rather than
tightening the requirements pin.

**Demo/pilot enablement gate** — rule: **seminary AUC ≥ 0.85 AND
false-positive rate ≤ 5% at `t_elevated` on authentic seminary essays**
(`train_ai_detector.py eval-seminary` prints the verdict). Status: the
shipped mixed-training model **passes** (AUC 1.0, FPR 4%, TPR 100% on
25 authentic vs 20 Claude essays; archaic-prose flag rates 0%). Caveats
before flipping the flag anywhere pilot-facing: the in-domain sample is
small (45 essays), single-generator (Claude), and corpus-synthesized —
a larger multi-generator in-domain eval and an institutional decision
should precede enablement. Known trade-off: detection of RAID's
adversarially-attacked generations dropped relative to v1; adversarial
robustness remains out of scope for this mode.

**Future path (deliberately deferred)** — coupling the signal to recommended
actions would follow the conformal-nudge pattern (raise-only, never lowers,
requires corroborating deviation evidence) behind a separate
`AI_LIKELIHOOD_ACTION_NUDGE_ENABLED` flag, and is gated on a pilot semester
of in-domain false-positive data.

---

## Modern Authorship Consistency Expert (report-only, optional)

`STYLE_AUTHORSHIP_ENABLED=1` attaches a separate peer-aligned style comparison
to the live response. It is default OFF and cannot modify `deviation_score`,
the recommendation, or the action. The output is either positive consistency
evidence or `inconclusive`; the latter must not be described as proof of an
impostor or misconduct.

The v1 artifact combines character 3–5-gram similarity with a content-reduced
signature (fixed function words, punctuation, word length, capitalization, and
sentence rhythm), then normalizes both against same-tenant peer profiles. It
abstains unless the probe has at least 300 words, the claimed student has three
retained authenticated baseline texts, and at least ten same-tenant peers each
have three eligible baselines. Institutions that do not retain raw baseline
text will therefore receive `null`, by design.

Training used 120 PAN 2020 authors; threshold calibration used 40 different
authors. Two subsequent, author-disjoint 40-author cross-fandom locks produced:

| Lock | AUC | TPR at frozen threshold | FPR at frozen threshold |
|---|---:|---:|---:|
| Fresh A (120 genuine / 4,680 impostor) | 0.878 | 40.8% | 1.154% |
| Fresh B (120 genuine / 4,680 impostor) | 0.933 | 51.7% | 0.748% |
| Combined frozen-threshold counts | — | 46.25% (111/240) | 0.951% (89/9,360) |

The variation between locks is operationally important: this is triage
evidence, not a universal authentication test. The loader fails closed if its
schema, signal order, vocabulary checksum, reference predictions, or strict
threshold do not match the artifact contract. It does not determine whether an
inconsistent document came from a human ghostwriter, direct AI, humanized AI,
editing, accommodation, or a legitimate context shift. Cause attribution and
action coupling remain unpromoted.

Reproduction entry point: `.venv/bin/python scripts/train_style_authorship.py`.
Locked reports are `pan_style_peer_aligned_fresh40a.json` and
`pan_style_peer_aligned_fresh40b.json` under
`validation/benchmarks/2026-08-04/`.

---

## Longitudinal Drift Analysis (report-only, optional)

`LONGITUDINAL_DRIFT_ENABLED=1` attaches a separate chronological analysis to
the live score response. It does **not** replace the density matrix, modify
`deviation_score`, or change `recommended_action`.

The v1 model compares a constant history with a ridge-shrunk per-feature linear
trend using forward-chaining prediction. Only authenticated, ISO-dated samples
of at least 300 words are eligible. The default eligibility floor is six such
samples spanning at least 60 days; the optional one-change-point diagnostic
requires 12. Undated, short, and unverified samples are excluded, and the
submission being evaluated is never fitted into its own trajectory.

The response distinguishes:

- `stable_consistent` — compatible with the historical profile;
- `drift_compatible` — historical distance is reduced by a supported trend;
- `unexplained_change` — neither the constant nor predicted-current profile
  explains the submission;
- `unexplained_discontinuity` — a longer history supports a possible abrupt
  break, whose cause remains unknown;
- `insufficient_history` — the chronological evidence floor is not met.

An abrupt change is not evidence of an impostor: genre, editing, dictation,
accommodation, illness, or a changed writing process can produce the same
pattern. Comparative authorship evidence remains the responsibility of the
peer-pool/null model and human verification. Promotion beyond report-only is
gated on chronological real-student validation showing reduced genuine false
alarms without an unacceptable loss in matched-impostor rejection.

Validation entry point: `python -m validation.longitudinal.run`. It reports
static versus drift-adjusted genuine flag rates and a chronology-permutation
false-selection diagnostic; it never tunes production thresholds.

---

## Peer-Pool Null Model (relative scoring signal, optional)

The primary `deviation_score` answers "how far is this submission from the
claimed student's baseline?" — an absolute distance with no notion of what
*someone else's* writing looks like. The peer-pool null model adds the
missing half of the hypothesis test: a diagonal-Gaussian impostor cohort
fit from the authenticated baseline vectors of the student's **same-tenant
peers** (`original/quantum/null_pool.py`), producing
`authorship.llr_deviation_score` — a bounded log-likelihood-ratio proxy.
0.5 = fits the claimed student and a typical classmate equally; toward 0 =
distinctly this student's voice; toward 1 = fits the peer pool better than
the claimed student's own baseline.

**Measured lift** (binary authorship verification, N=3 baselines,
`validation/benchmarks/2026-07-01/*nullmodel*`): seminary median
per-author AUC 0.8125 → **1.0** (pooled 0.8925 → **0.9325**, Brier 0.51 →
0.17); public authors pooled 0.8551 → **0.8993** (Brier 0.34 → 0.09).
TPR at 5% FPR rose from 0.6 → 0.8. Ledoit-Wolf shrinkage
(`RANK_REMEDIATION=shrinkage`) was A/B'd at the same time and *hurt* —
the null model alone accounts for the entire gain.

**Contract**

- Gated by `NULL_MODEL=impostor` (default OFF; demo mode sets it via
  `setdefault` in `run.py`). Attach-only: `deviation_score`, the
  recommended action, and every other response field are unchanged.
- Cold-start abstention: the pool requires ≥ 3 same-tenant peers with
  authenticated baselines and ≥ 5 pooled vectors, else the field is null.
  Weak evidence abstains; it never widens or blocks a score.
- Tenant isolation: cross-tenant vectors are never pooled — the cohort is
  the student's own school, which also keeps the comparison genre-matched.
- Coupling the relative score to recommended actions is deliberately
  deferred (same posture as the AI-likelihood action nudge): thresholds
  were calibrated for `deviation_score`, so action coupling waits on
  pilot-semester recalibration against the llr distribution.

---

## Length-Adaptive Tier Weighting (evaluated, kept OFF)

`LENGTH_ADAPTIVE_WEIGHTS` rescales the per-feature deviation weight vector by
submission length (`quantum/scoring.py:515`). **Evaluated 2026-06-30** on the
seminary calibration corpus (N=717 scored essays, truncated to 500 words,
`validation/stability/measure_lift_seminary.py`) across three candidate
weight schedules: **+0.0035 to +0.0058 ΔAUC, ΔBrier ≈ 0.0** for all three —
negligible, and the first schedule iteration collapsed `escalate`
true-positives 165→1 before the shipped Σ(w²)-preserved schedule brought
that back to 159→19. **Verdict: kept OFF.** Small, noisy lift does not
justify a scoring-math change; this entry exists so nobody re-runs the
experiment from scratch. Evidence: `validation/stability/lift_seminary_2026-06-30.json`,
`lift_seminary_normalized_2026-06-30.json`, `lift_seminary_sum_w2_preserved_2026-06-30.json`.

---

## Amplitude Scoring / Quantum Fidelity (Phase 6, optional second signal)

`AMPLITUDE_SCORING_ENABLED` turns on the complex-amplitude encoding path
(`_amplitude_score()` in `original/quantum/scoring.py`), which attaches
`authorship.quantum_fidelity` and `authorship.fidelity_conformal_pvalue` to
the response. Structurally — confirmed by reading the scoring code and by
measurement — **this flag cannot change `deviation_score` or
`authorship_probability`.** `rms_z` (and therefore `deviation_score`) and the
Born-rule `authorship_probability` are both computed before the amplitude
branch runs and are never touched by it; the flag only adds the two new
fields above.

**Measured lift** (2026-07-09, ad hoc script mirroring
`validation/verify/run_null_model.py`'s direct-`score()`-call pattern —
see methodology note below): `validation/corpus` + `validation/manifest.json`,
13 eligible authors (≥3 baselines), full-length essays, capped at 5 scoring
entries/author for tractability (N=55 scored, seed 42). Confirmed
max |Δ deviation_score| = max |Δ authorship_probability| = 0.000000 across
every scored essay — the primary-score AUC/Brier is identically 0.6643 /
0.1388 ON and OFF (ΔAUC = ΔBrier = 0.0000), exactly as the code predicts.
The only new information is `quantum_fidelity` itself: taken alone as a
discriminator on the same N=55, it reached **AUC 0.7633 / Brier 0.1828** —
numerically higher AUC than the primary score, but on a small, capped
sample, and not wired into `deviation_score` or `recommended_action` at all.

**Verdict: kept OFF.** The flag is a pure no-op for the scores and action
the product currently makes decisions on, so there is no regression risk
in leaving it off — but there is also no measured lift to justify turning
it on for its stated purpose (report-only fidelity/conformal fields). The
apparent standalone discriminative power of `quantum_fidelity` (AUC 0.7633)
is worth a properly-sized follow-up (full 737-essay corpus, uncapped) before
any product conversation about surfacing or blending it — this measurement
is too small and too capped to act on by itself.

**Methodology caveat.** `validation/calibration.py`'s `run_calibration()`
(used by `measure_lift_seminary.py`) calls `score()` without a
`scoring_config` argument. Since the WS-7 `ScoringConfig` refactor
(`original/quantum/scoring.py`), `score()` reads `scoring_config or
ScoringConfig()` — the all-flags-off default — and **no longer reads
`os.environ` itself**. Confirmed empirically: setting
`AMPLITUDE_SCORING_ENABLED=1` and calling `run_calibration()` produces
byte-identical output to the flag being unset, because the harness never
builds a `ScoringConfig` at all. A naive rerun of `measure_lift_seminary.py`
against this flag today would silently report "no lift" for the wrong
reason. This measurement instead built `ScoringConfig.from_env()` explicitly
and passed it into `score()`, mirroring `original/api.py`'s production
wiring (`api.py:2010-2054`). The same gap likely affects any future flag
benchmarked by pointing `measure_lift_seminary.py`/`run_calibration()` at an
env var without first checking whether `score()` still reads it directly.

---

## Hierarchical Bayesian Cold-Start Prior (optional)

`BAYESIAN_PRIOR_ENABLED` blends a student's personal baseline mean/std with a
cross-student, same-genre prior when `state.sample_count < 10`
(`quantum/scoring.py:532-561`, weighted by `PRIOR_WEIGHT`, default 3.0). Unlike
amplitude scoring, this flag **does** change `deviation_score` (it feeds the
blended mu/sigma into the z-score computation) but does **not** change
`authorship_probability` (the Born-rule projection depends on the density
matrix ρ, not on mu/sigma).

**Measured lift** (2026-07-09, cold-start segment only, per this flag's
stated use case): the only students in `validation/corpus` with fewer than 5
baseline samples are the 5 `seminary_0N` authors (3 baselines each). Cross-scored
each of their scoring essays (2 authentic + 1 ghostwritten per author)
against every one of the 5 authors' baselines (N=75 pairs: 10 positive / 65
negative). Since `validation/manifest.json` carries no `genre` field at all,
this measurement assigned a synthetic `genre="seminary_exegesis"` label to
these 5 authors' baseline samples only — justified because all 5 share an
identical 3-prompt baseline set and identical scoring prompts (a real shared
assignment structure, not an arbitrary grouping) — and fit each target's
genre prior from the other 4 authors' baseline vectors (12 vectors/target,
clearing `get_genre_stats()`'s ≥5 floor).

Result: **AUC 0.8077 → 0.5569 (Δ = −0.2508)** — a large regression, not a
lift. `authorship_probability`-based Brier is flag-blind here (0.5204 both
ways, confirmed max |Δ| = 0, since Born P doesn't depend on mu/sigma); a
supplementary Brier computed on `(1 − deviation_score)` as a proxy
probability — which does reflect the blend — also got worse: **0.1261 →
0.1804 (Δ = +0.0543)**.

**Verdict: kept OFF.** The genre prior actively hurts AUC on the one segment
it exists to help, on the only cold-start population available in this
corpus. Working hypothesis: the cross-student genre pool's mean sits closer
to the *ghostwritten* essays (same theological genre, different real human)
than to any individual target's own 3-sample baseline, so blending toward it
makes ghostwritten submissions look more "authentic," not less — the
opposite of the intended effect. Caveats: N=75 pairs across only 5 real
seminary identities (small, single-corpus), a synthetic (if well-justified)
genre label standing in for real production genre metadata, and a
methodology that (like the amplitude measurement above) had to build
`ScoringConfig.from_env()` explicitly rather than reuse
`run_calibration()`/`measure_lift_seminary.py` directly, since those never
construct a `ScoringConfig` and would silently no-op this flag too. Do not
enable without a larger, multi-institution cold-start sample and an
investigation of the ghostwritten-pulls-prior-toward-it hypothesis above.

---

## Cross-Work Authorship Verification (2026-08-04)

A source-work-disjoint corpus now uses three 2,500-word baseline windows from
one book and three probe windows from another for G.K. Chesterton, Agatha
Christie, Charles Dickens, Ralph Waldo Emerson, John Stuart Mill, and Henry
David Thoreau (36 documents; 108 target/probe verification pairs). No work
appears on both sides of an author's split.

The existing score achieved 17/18 top-1 attribution and median per-author AUC
0.989 (IQR 0.878–1.000), but pooled uncalibrated AUC was only 0.769 (95%
bootstrap CI 0.607–0.897) with Brier 0.622. This confirms that author-relative
ranking and a portable absolute probability are different problems. The
existing population-relative impostor signal increased median per-author AUC
to 1.000 (IQR 0.967–1.000), pooled AUC to 0.952, and improved pooled Brier to
0.127. At 1% pooled FPR its recall was 61.1%.

**Verdict: retain as attach-only evidence; do not promote thresholds.** This is
strong support for using the null score as one calibrated fusion channel, but
not enough evidence for a universal claim: there are only six historical
authors, 18 genuine probes, and substantial era/register mismatch with student
writing. Full details are in
`docs/research/CROSS_WORK_AUTHORSHIP_FINDINGS_2026-08-04.md`.

A harder modern cross-topic test uses 12 real PAN authors, three baseline
documents from one fandom and three probes from another (72 unique texts; 432
verification trials). The frozen raw score achieved only median per-author AUC
0.687 and 11.1% TPR at 1% FPR. Peer-relative impostor evidence improved median
AUC to 0.778 and TPR at 1% FPR to 30.6%, but this remains inadequate for
authentication. Therefore Original must not claim reliable cross-topic
authorship measurement, and the null score remains report-only.

The initial validation-only content-reduced expert trained on 120 disjoint PAN authors
and thresholded on 40 additional authors improved the locked result to pooled
AUC 0.890 and 47.2% TPR at the 1% ROC point. It combines character-pattern
similarity with function-word, punctuation, word-length, and sentence-rhythm
distance. A four-channel stack that also included Original's raw and
peer-relative probabilities regressed AUC to 0.845 and strict TPR to 38.9%, so
that merge was rejected. That initial two-style-signal version was not shipped:
its locked set had only 12 authors/36 genuine trials, and its observed 1.01%
impostor-accept rate had a 2.57% upper 95% confidence bound. The later
peer-aligned, report-only adapter and its larger fresh locks are documented in
the Modern Authorship Consistency Expert section above; no action threshold was
promoted.

### Cause and mixed-authorship stress tests

PADBen source-held-out testing produced 92.1% precision / 58.1% recall for a
positive humanized-AI signal, but the direct-AI subtype failed its precision
gate. DAMASHA train/calibration/locked testing raised short-window AUC from
0.437 for the frozen corpus detector to 0.907 for a locally learned window
expert; its q95 operating point reached 80.0% mixed recall at 8.3% control FPR,
with 32-word median boundary error. On a locked 100-document RAID clean versus
paraphrase test, the PADBen subtype ranking reversed (AUC 0.063), while a
source-disjoint RAID-local leave-one-generator-out expert reached AUC 0.985.
This proves generator transfer within one attack family, not humanizer-family
transfer. A source-disjoint PADBen first-versus-third paraphrase-depth control
retained AUC 0.944, but failed coverage and direct-AI precision/recall gates;
high ranking performance still did not produce a deployable bidirectional
decision. These are validation-only results and do not justify a production
cause artifact. See
`docs/research/CAUSE_ATTRIBUTION_FINDINGS_2026-08-04.md`.

A larger exact-source RAID follow-up keeps human rewrites labeled human and
holds out both an AI generator and a rewrite family. Unseen synonym rewrites
reach 69.6–92.0% TPR at 0% observed human FPR, but unseen paraphrases reach only
12–13% TPR. A RAID-trained model then fails on external PADBen (AUC 0.544,
2.7% human FPR, 0% direct-AI TPR, 0.45% humanized-AI TPR). This confirms that
AI-origin invariance is the appropriate target, while current features do not
generalize across paraphrasers and domains. Direct-versus-humanized provenance
remains unavailable in production.

A two-axis joint cause hierarchy was subsequently tested on three disjoint
fresh 40-author PAN partitions. It combines only peer-aligned claimed-author
probability and frozen AI likelihood. On a generator- and rewrite-held RAID
lock, merged AI-origin evidence reached 99.55% precision / 92.08% recall and
positive claimed-author evidence reached 100% precision / 38.3% recall.
However, the identical frozen hierarchy failed on external PADBen: AI-origin
precision fell to 60.21% because 189/222 human texts were false positives.
Human-impostor precision was only 77.78% on the first lock and 32.65%
externally. No cause output is exposed by the production API. Low style
consistency is not positive evidence of a ghostwriter, and a locally accurate
AI-origin threshold is not a portable detector.

Positive peer alternatives and 64 deterministic General Impostors trials raise
known-peer human-impostor precision to 91.84%, but recall remains 37.5%. With
ghostwriters drawn from an entirely unseen 40-author cohort, precision/recall
fall to 80.95%/14.17%. A separate small-model probability-curvature diagnostic
reaches RAID AUC 0.9143, but misses the paraphrased-AI recall gate and reverses
to AUC 0.3121 on external PADBen. Both additions remain validation-only; no
cause label or production threshold was added.

The probability-curvature experiment was repeated over the complete locks with
the official Fast-DetectGPT implementation's GPT-Neo-2.7B same-model pair and a
documented local 256-token truncation. It reached RAID AUC 0.9013 and 90.0%
direct-AI recall, but only 32.08% paraphrased-AI recall. External PADBen AUC
reversed to 0.3879 with no selections at the frozen threshold. Model scale
therefore did not repair transfer, and the signal was not integrated into the
production stack.

A third independent lock adds 960 checksum-pinned FAIDSet test documents:
human, direct AI, and human--LLM collaborative writing across GPT, Gemini,
Llama, and DeepSeek. The frozen detector has 57.5% human FPR; probability
curvature has 0% collaborative recall. Local-human calibration also fails,
including a two-sided curvature anomaly with 62.19% direct recall, 0%
collaborative recall, and 1.25% locked-human FPR. The collaborative label is
not equated with humanizer-paraphrased AI, and no production output is added.

The authorship promotion gate now requires actual frozen-threshold precision
and recall, not only AUC/FPR. On a newly untouched 100-author PAN lock with
three baselines each, peer alignment selects nobody; a best-alternative-margin
variant reaches 82.35% precision / 9.33% recall and fails the required
90%/50%. Conversely, the separately scoped enrolled-peer ghostwriter branch
passes its revised initial gate at 90.20% precision / 38.33% recall on 120 held
authors. That evidence supports only a closed-pool report with
`unknown_writer` outside the enrolled comparison set.

Exact enrolled-peer identity was subsequently audited rather than inferred
from the broad human-impostor label. Top-one source accuracy is 47.5%; adding a
best-versus-runner-up peer margin yields 83.33% selective identity precision,
12.5% recall, and a 1.67% outside-writer naming rate. These fail the required
90% precision, 30% recall, and ≤1% outside naming guard. No peer identity is
therefore exposed; the supported output remains `unknown_writer`.

Binary authorship authentication is now separated from 100-way identity using
300 genuine and 300 deterministic source-matched impostor trials across the
same 100 untouched authors. Best-peer style margins reach 98.90% precision,
30.0% recall, and 0.333% FPR. Topic-masked function/punctuation/word-shape
sequences and a 100k character vocabulary were also tested; the best stable
variant reaches 97.20% precision / 34.67% recall / 1.0% FPR. All remain below
the required 50% recall, so no authentication action is promoted.

A validation-only LUAR-MUD expert was subsequently pinned and evaluated with
the same three-baseline, cross-topic protocol. LUAR cosine alone reaches 94.90%
precision / 31.0% recall / 1.667% FPR. Calibration-only selection chooses a
fusion of LUAR cosine and the two existing best-peer style margins; the frozen
100-author lock reaches AUC 0.922 and 100% precision / 39.33% recall / 0%
observed FPR. This is the strongest low-FPR authentication result so far, but
it still fails the 50% recall gate and remains outside the live API.

Individual-baseline LUAR cohesion and dispersion signals improve the original
lock to 98.56% precision / 45.67% recall / 0.667% FPR. The frozen fusion and
threshold were then evaluated on a fresh 100-author open-set lock built from 99
PAN 2021 authors and one never-allocated PAN 2020 tail author. Every author has
three cross-topic baselines. The fresh lock reaches AUC 0.9414, 97.83%
precision, 45.0% recall, and 1.0% FPR. The independent result remains below the
50% recall requirement, so the production boundary is unchanged.

A non-commercial, validation-only RADAR adversarial detector was also tested to
measure whether paraphraser-aware training repairs AI-origin transfer. It
recalls 50.31% of merged FAID AI involvement, including 53.13% collaboration,
but flags 28.75% of humans. Local-human calibration collapses recall. On a
second PADBen deep-paraphrase lock it flags every human and AI bundle. RADAR is
therefore neither accurate enough nor legally usable as a production model;
no score or weight was added.

A regularized PLDA/Bayes-factor backend was tested over LUAR embeddings to
model three-baseline versus one-probe uncertainty. PLDA reaches calibration AUC
0.913 but only 35.67% recall at the joint gate; all PLDA fusions underperform
the existing consistency/style fusion. Calibration therefore rejects it before
locked model selection, and the production boundary remains unchanged.

Pairwise cross-channel interactions and baseline-cohesion-stratified thresholds
were also evaluated. They reach only 38.67% and 47.33% calibration recall,
respectively, versus 49.33% for the selected linear fusion. The stratified rule
would reach 44.0% on the open-set lock. Both are rejected before promotion.

A development-only shrinkage-LDA metric over individual LUAR documents changes
that conclusion for recall, but not for false positives. A regularized
cross-channel interaction fusion reaches 98.05% precision / 50.33% recall /
1.0% FPR on calibration. At the frozen threshold it reaches 96.43% / 54.0% /
2.0% on the earlier 100-author lock and 96.72% / 59.0% / 2.0% on the fresh
open-set lock. Tightening the calibration false-positive budget from 3/300 down
to 0/300 does not produce a transported point satisfying both 50% recall and
1% FPR, demonstrating threshold covariate shift rather than a missing global
cutoff.

An author-disjoint 43-author PAN 2020 tail cohort was then used only for local
threshold estimation. Its selected point is 98.67% precision / 57.36% recall /
0.775% FPR locally, but transports to 91.78% / 67.0% / 6.0% on the PAN 2021
lock. Author disjointness alone is therefore insufficient: any institutional
threshold cohort must also represent the target writing context and must be
followed by a separate untouched deployment lock. The LDA metric, interaction
fusion, and local calibration remain validation-only; no live score or action
changed.

An independent cross-work experiment uses a checksum-recorded Project
Gutenberg catalogue and 400 single-author English writers with six distinct
works each. The first 50 authors fit a local LUAR/style calibrator, the next 50
select its variant and a pre-registered zero-false-accept threshold, two
previously inspected 100-author blocks are excluded, and the final 100 authors
form the untouched lock. The selected LUAR-cosine/style-margin model reaches
100% precision, 79.33% recall, and 0/300 observed impostor accepts on that lock.
It passes the stated numerical public-corpus authorship gate with three
baseline works per author.

This does not establish performance on contemporary student assignments: the
historical literary domain differs materially in era, genre, editing, and text
length, and the 0/300 FPR Wilson upper bound is 1.264%. The result is therefore
eligible only for report-only review. Institutional calibration and a separate
untouched student lock are still required before any live authentication action
can be promoted.

Exact enrolled-peer identity was separately re-tested on the Gutenberg domain
with 100 enrolled candidates, three baseline works, three probes, and 100
outside-pool writers. A development-fitted ranker combining LUAR, character
n-grams, and content-reduced rhythm raises top-one identity accuracy from 30%
for LUAR alone to 73%. Calibration-controlled abstention reaches 95.10% exact
identity precision and 32.33% recall, satisfying the known-peer targets, but
names 4/300 outside-pool probes (1.333%) and therefore fails the ≤1% guard by
one case. Requiring zero outside names during calibration improves precision to
96.81% while retaining 30.33% recall, but the same 4/300 outside rate remains.
A two-axis runner-up-margin rule regresses recall to 28.67% without reducing
outside names and is rejected. Exact peer names remain unavailable;
`unknown_writer` is mandatory outside the enrolled pool.

---

## Data Protection and FERPA Posture

Original is designed around data minimization:

- Hashes, extracted feature vectors, baseline state, scoring results, and audit records are the primary retained artifacts.
- Raw text retention is institution-configurable and should default to deletion after feature extraction in FERPA-sensitive deployments.
- Student data is not sold and is not used to train external models.
- Instructor decisions and system actions should be retained in an audit log for institutional review.
- Pilot deployments must use tenant isolation, stable secrets, locked CORS, guarded destructive operations, TLS, and documented backups.

FERPA compliance is ultimately an institutional program: Original supplies technical controls and audit artifacts, while the school owns policy, notices, access rights, retention schedules, appeals, and records governance.

---

## Runtime Status

There are two backend surfaces in the repository:

| Surface | Status | Notes |
|---------|--------|-------|
| Dashboard/pilot app (`original/api.py`, `python run.py --demo --frontend-dir demo/`) | Current pilot-facing surface | Serves the static professor, student, admin, operator, and Bluebook dashboards. Hardened with tenant isolation, staff login, guard token support, audit logs, and SQLite WAL backups. |
| v1 API (`original/main.py`, `python run.py`) | Long-term production surface | Uses JWT auth, SQLAlchemy models, rate limiting, Canvas/LTI routes, and a Postgres-oriented data model. |

The zero-login demo remains intentionally available for sales and evaluation. Real tenants should run in `ORIGINAL_ENV=pilot` or production mode with a stable `SECRET_KEY`, configured `ALLOWED_ORIGINS`, `GUARD_DESTRUCTIVE=1`, a maintenance token, TLS, and backups.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.4.25 | 2026-08-04 | Reproduced RepreGuard-style layerwise PCA activation directions with pinned Phi-2, 512 M4 training pairs, 512 disjoint calibration pairs, and external RAID/FAID diagnostics. RAID AUC was 0.9442, but recall at the ≤1% FPR operating point was 10% overall and 0% for synonym/paraphrase; FAID selected no direct or collaborative AI. The branch was rejected and production remains unchanged. |
| 1.4.24 | 2026-08-04 | Added a validation-only closed-pool Gutenberg identity ranker combining LUAR, character, and content-reduced evidence. Known-peer precision/recall reached 95.10%/32.33%, but outside naming was 1.333%; stricter and runner-up-margin rules did not repair the guard. Exact names remain disabled. |
| 1.4.23 | 2026-08-04 | Added a reproducible 400-author Project Gutenberg cross-work corpus and domain-local LUAR/style calibration. A pre-registered zero-calibration-FP rule passed the final untouched 100-author lock at 100% precision, 79.33% recall, and 0/300 observed FPR; it remains report-only pending a representative institutional student lock. |
| 1.4.22 | 2026-08-04 | Added a validation-only development-fitted shrinkage-LDA LUAR metric, cross-channel fusion, false-positive sensitivity audit, and author-disjoint local-threshold experiment. Recall passed, but both global transport locks reached 2% FPR and the locally fitted threshold reached 6% FPR on PAN 2021. Promotion remains blocked. |
| 1.4.21 | 2026-08-04 | Tested regularized pairwise feature interactions and uncertainty-stratified thresholds over baseline cohesion. Both underperformed the selected linear fusion on calibration (38.67%/47.33% versus 49.33% recall) and were rejected before promotion. |
| 1.4.20 | 2026-08-04 | Added a validation-only regularized PLDA/Bayes-factor scorer over LUAR embeddings. PLDA calibration AUC was 0.913, but its best gated recall and all fusions underperformed the existing consistency/style model. It was rejected before locked selection. |
| 1.4.19 | 2026-08-04 | Added a pinned, validation-only RADAR adversarial detector transfer test. FAID merged recall reached 50.31%, but precision was 77.78% with 28.75% human FPR; PADBen Task-5 produced 50% precision and 100% human FPR. The checkpoint is also non-commercial. No production signal was added. |
| 1.4.18 | 2026-08-04 | Added individual-baseline LUAR consistency/cohesion signals and a checksum-verified PAN 2021 open-set lock. The existing lock improved to 98.56% precision / 45.67% recall / 0.667% FPR; a fresh 100-author lock reached AUC 0.9414 and 97.83% / 45.0% / 1.0%. Recall still fails the 50% gate, so production remains unchanged. |
| 1.4.17 | 2026-08-04 | Added a pinned, cached, validation-only LUAR-MUD author-episode expert. Calibration selected LUAR cosine plus existing style margins; the 100-author lock reached AUC 0.922, 100% precision, 39.33% recall, and 0% observed FPR. Recall remains below the 50% authentication gate, so no production artifact or action changed. |
| 1.4.16 | 2026-08-04 | Separated binary source-matched authentication from exhaustive identity attribution on 100 untouched authors. Best style margins reached 98.90% precision / 30.0% recall / 0.333% FPR. Added topic-masked function/punctuation/word-shape n-grams and a 100k character ablation; best recall was 34.67%, below the 50% gate. |
| 1.4.15 | 2026-08-04 | Distinguished broad human-impostor detection from exact enrolled-peer identification. Although the broad class passed 90.20%/38.33%, exact top-one identity was only 47.5%; calibrated runner-up margins reached 83.33% precision / 12.5% recall and named 1.67% of outside writers. No peer-name artifact was packaged. |
| 1.4.14 | 2026-08-04 | Corrected authorship promotion to require ≥90% precision and ≥50% recall at the frozen threshold on 100 untouched authors with three baselines each. Peer and best-alternative variants failed (best: 82.35% precision / 9.33% recall). The separately scoped enrolled-peer ghostwriter branch passed its revised ≥90%/≥30% gate at 90.20%/38.33%, with mandatory `unknown_writer` outside the pool. |
| 1.4.13 | 2026-08-04 | Added a checksum-pinned 960-document FAIDSet test lock covering genuine human, direct AI, and human--LLM collaboration across four model families. Transported and locally human-calibrated frozen/curvature signals all failed; collaborative recall remained at most 7.19% and no production label was added. |
| 1.4.12 | 2026-08-04 | Repeated the probability-curvature lock with the official implementation's GPT-Neo-2.7B same-model pair over 1,080 RAID documents and 555 PADBen bundles. RAID AUC was 0.9013, but paraphrased-AI recall was 32.08%; PADBen reversed to AUC 0.3879 with no frozen-threshold selections. Added incremental content-addressed checkpoints; no production weight was added. |
| 1.4.11 | 2026-08-04 | Added known-peer and open-set General Impostors evaluation plus an independent GPT-2 probability-curvature diagnostic. Known-peer human-impostor precision reached 91.84% but recall was 37.5%; unseen-cohort precision/recall fell to 80.95%/14.17%. RAID probability-curvature AUC was 0.9143 but external PADBen reversed to 0.3121. Both failed promotion; production remains unchanged. |
| 1.4.10 | 2026-08-04 | Added training-only direction-stable/non-negative AI-origin fusion and a joint claimed-author/human-impostor/direct-AI/humanized-AI hierarchy. RAID-local merged AI-origin reached 99.55% precision/92.08% recall, but external PADBen precision fell to 60.21% with 189/222 human false selections. Human-impostor evidence also failed; no cause label was promoted. |
| 1.4.9 | 2026-08-04 | Added exact-source RAID clean/synonym/paraphrase triplets with attacked human controls, generator- and attack-held AI-origin evaluation, and a locked RAID-to-PADBen external transfer test. Synonym transfer passed locally, but unseen paraphrase recall was 12–13% and external AUC was 0.544; no cause model was promoted. |
| 1.4.8 | 2026-08-04 | Added the default-off, report-only peer-aligned style-authorship API field and fail-closed artifact. Two fresh 40-author locks yielded AUC 0.878/0.933 and frozen-threshold FPR 1.154%/0.748% (combined 0.951%); cross-lock variation keeps the result action-blind and below-threshold cases explicitly inconclusive. |
| 1.4.7 | 2026-08-04 | Added author-disjoint PAN character and content-reduced style experts plus grouped fusion. Two-style-signal locked AUC reached 0.890 and 47.2% TPR at the 1% ROC point; adding raw/peer Original signals regressed to 0.845/38.9%. Both remain validation-only because locked support and strict-FPR confidence fail promotion gates. |
| 1.4.6 | 2026-08-04 | Added a checksum-pinned, real-author PAN 2020 cross-fandom test (12 authors, 72 unique documents). Raw median AUC fell to 0.687; peer-relative AUC reached 0.778 with only 30.6% TPR at 1% FPR. Cross-topic authorship promotion failed; production behavior remains unchanged. |
| 1.4.5 | 2026-08-04 | Added source-disjoint, leave-one-attack-family-out subtype evaluation with generator-held calibration and explicit AUC/precision/recall/coverage/support gates. PADBen depth-held AUC was 0.944, but selective coverage and the direct-AI branch failed; no artifact was promoted. |
| 1.4.4 | 2026-08-04 | Added a pinned, source-disjoint RAID external subtype test. PADBen-to-RAID transfer failed (AUC 0.063 and no correct selective labels), while RAID-local leave-one-generator-out ranking reached AUC 0.985. Production promotion remains blocked on unseen attack-family evidence. |
| 1.4.3 | 2026-08-04 | Expanded the work-disjoint corpus to six authors and 36 hashed documents by adding Emerson, Mill, and Thoreau. Locked attribution reached 17/18; peer-relative impostor evidence improved pooled AUC from 0.769 to 0.952 and Brier from 0.622 to 0.127, while remaining attach-only. |
| 1.4.2 | 2026-08-04 | Added source-held-out PADBen cause attribution and train/calibration/locked DAMASHA mixed-boundary stress tests. The evidence supports selective positive humanization evidence and validation-only mixed-text localization, but fails the direct-AI and production false-positive gates; no live cause model was promoted. |
| 1.4.1 | 2026-08-04 | Added source-work-disjoint Dickens/Christie/Chesterton validation and a validation-only grouped fusion/abstention harness. Results support the attach-only impostor signal but do not promote any production threshold. |
| 1.4.0 | 2026-08-04 | Added default-off, report-only longitudinal drift analysis with chronological eligibility, constant-vs-regularized-trend selection, predictive drift relief, a conservative one-change-point diagnostic, and a separate Dirichlet-multinomial validation implementation. Primary scoring and actions remain unchanged. |
| 1.3.1 | 2026-07-09 | Documentation-only: recorded verdicts for three previously-unbenchmarked scoring flags — `AMPLITUDE_SCORING_ENABLED` (structural no-op on deviation_score/authorship_probability; `quantum_fidelity` alone AUC 0.7633 on a small N=55 sample), `BAYESIAN_PRIOR_ENABLED` (ΔAUC −0.2508 on the cold-start segment — regression), and the previously-unrecorded 2026-06-30 `LENGTH_ADAPTIVE_WEIGHTS` measurement (+0.0035 to +0.0058 ΔAUC — negligible). All three remain default OFF; no scoring behavior changed. |
| 1.3.0 | 2026-07-04 | Peer-pool null model in production: `NULL_MODEL=impostor` builds a per-tenant impostor cohort on the live scoring path and attaches `llr_deviation_score` (attach-only; cold-start abstention; on by default in demo mode only). |
| 1.2.0 | 2026-07-01 | Added the optional AI-likelihood detector (corpus-level second scoring mode): committed calibrated classifier artifact, `AI_LIKELIHOOD_ENABLED` flag, report-only contract, enablement gate, and version-skew runbook. |
| 1.1.0 | 2026-06-09 | Updated model card for 103-dimensional pipeline, Tier 17 behavioral biometrics, comparison dimensions, pilot runtime posture, and explicit human-review policy. |
| 1.0.0 | 2026-03-17 | Initial release — 34-feature pipeline, quantum density matrix scorer. |
