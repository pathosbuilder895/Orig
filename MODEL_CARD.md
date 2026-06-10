# Model Card — Original Stylometric Scorer v1.1.0

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

Minimum baseline policy:

| Condition | Effect |
|-----------|--------|
| < 3 authenticated baselines | Scoring is blocked or should be treated as insufficient. |
| 3-4 authenticated baselines | Scoring can run, but `escalate` is suppressed. |
| >= 5 authenticated baselines | Full action range is available, subject to confidence checks. |
| Low baseline purity | Treat recommendations with caution and consider rebaselining. |

---

## Feature Pipeline

The current engine uses `FEATURE_DIM = 103` from `original/constants.py`.

- **96 base dimensions** are extracted from text, citation behavior, and optional proctored keystroke data.
- **7 comparison/profile dimensions** are computed during scoring when baseline context is available.
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
| 0 | Comparison/profile features | 7 | Baseline-relative divergence dimensions computed during scoring. |

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
- `interference_decomposition` — feature/tier contributions that drove the recommendation.
- `trajectory_conformance` — whether observed deviation resembles natural growth.
- `context_manifest` and scoring report when enabled — auditable context and weighting decisions.
- `recommended_action` — `no_action`, `monitor`, `schedule_conversation`, or `escalate`.

---

## Output Actions

| Action | Typical deviation range | Meaning |
|--------|-------------------------|---------|
| `no_action` | 0.00-0.40 | Submission is consistent with the student's established voice. |
| `monitor` | 0.40-0.55 | Mild deviation; watch future submissions and context. |
| `schedule_conversation` | 0.55-0.75 | Notable deviation; instructor should discuss the submission with the student. |
| `escalate` | 0.75-1.00 | Significant deviation; begin formal institutional review if baseline confidence is adequate. |
| `escalate` override | RMS z > 3.0 | Catastrophic drift; immediate review recommended. |

Escalation is suppressed when fewer than 5 authenticated baselines are available. A recommendation is never equivalent to a finding of misconduct.

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
- **AI detection scope** — Original is not primarily an "AI detector." It verifies consistency with a student's own writing history, which may catch ghostwriting, AI-assisted writing, or other authorship changes.

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
| 1.1.0 | 2026-06-09 | Updated model card for 103-dimensional pipeline, Tier 17 behavioral biometrics, comparison dimensions, pilot runtime posture, and explicit human-review policy. |
| 1.0.0 | 2026-03-17 | Initial release — 34-feature pipeline, quantum density matrix scorer. |
