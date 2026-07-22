# Model Card — Original Stylometric Scorer v1.3.1

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
Motivated by the PR #21 diagnostic: Original's own 103 features + a plain
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
| 1.3.1 | 2026-07-09 | Documentation-only: recorded verdicts for three previously-unbenchmarked scoring flags — `AMPLITUDE_SCORING_ENABLED` (structural no-op on deviation_score/authorship_probability; `quantum_fidelity` alone AUC 0.7633 on a small N=55 sample), `BAYESIAN_PRIOR_ENABLED` (ΔAUC −0.2508 on the cold-start segment — regression), and the previously-unrecorded 2026-06-30 `LENGTH_ADAPTIVE_WEIGHTS` measurement (+0.0035 to +0.0058 ΔAUC — negligible). All three remain default OFF; no scoring behavior changed. |
| 1.3.0 | 2026-07-04 | Peer-pool null model in production: `NULL_MODEL=impostor` builds a per-tenant impostor cohort on the live scoring path and attaches `llr_deviation_score` (attach-only; cold-start abstention; on by default in demo mode only). |
| 1.2.0 | 2026-07-01 | Added the optional AI-likelihood detector (corpus-level second scoring mode): committed calibrated classifier artifact, `AI_LIKELIHOOD_ENABLED` flag, report-only contract, enablement gate, and version-skew runbook. |
| 1.1.0 | 2026-06-09 | Updated model card for 103-dimensional pipeline, Tier 17 behavioral biometrics, comparison dimensions, pilot runtime posture, and explicit human-review policy. |
| 1.0.0 | 2026-03-17 | Initial release — 34-feature pipeline, quantum density matrix scorer. |
