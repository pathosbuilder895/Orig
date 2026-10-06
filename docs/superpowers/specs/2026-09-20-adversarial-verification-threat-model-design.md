# Adversarial-Verification Threat Model — SP1 design

**Status:** Approved design, pre-implementation
**Date:** 2026-09-20
**Prior work:** the 2026-09-20 programme plan ("Adversarially aware
authorship consistency for Original + modular Bluebook"), reviewed and
decided with the user the same day (see "Decisions taken with the user"
below). This spec is Sub-project 1, deliverable group A of that programme.
It is the source of truth for the gate names (`G-A1`…`G-A6`) and field
contracts that Sub-projects 2–5 (`style_authorship` v2, macro-context
features, Bluebook standalone, the instructor dashboard) build against.

---

## 1. Problem

**No threat-model document exists for Original today.**
`docs/testing/04-security-adversarial.md` covers application security
(injection, auth, SSRF) but has no entry for obfuscation, imitation,
paraphrase laundering, baseline poisoning, or σ-inflation — the attacks
specific to a one-class stylometric *verifier*, as opposed to a web
application. The gap register (`docs/testing/10-gap-register.md`, T-01
through T-66) has no row naming any of them either. This spec is that
document, and it converts the taxonomy below into gap-register rows
(T-67…T-75) and a set of gates (`G-A1`…`G-A6`) a later cycle must build and
measure against.

### Why this is a verification problem, not an attribution problem

The academic literature this taxonomy draws on (Brennan, Afroz & Greenstadt
2012, and the replications/extensions below) studies closed-set
*attribution*: an attacker with a document tries to evade being matched to
their true identity among several candidates. Original does one-class
*verification*: the question is whether a submission is consistent with one
specific claimed author's own baseline. The threat surface inverts:

- Obfuscating a **submission** helps Original, not the attacker — a
  submission written to not-sound-like-oneself is exactly what the scoring
  path is built to flag.
- The live threat is obfuscating, padding, or outsourcing the **baselines**,
  so the profile itself becomes wide, wrong, or someone else's — attacks
  1–3 and 7 below.
- **Imitation** is the direct threat: a ghostwriter, or an LLM prompted with
  the student's own essays ("write in the style of these three") — attack 4.
- **Paraphrase/translation laundering** of a purchased or AI-written paper
  toward the student's own style is the modern, LLM-era version of the
  study's weakest 2012-era attack (machine translation), and is
  substantially stronger now — attack 6.

### The attacker taxonomy

Transcribed verbatim from the programme plan's "Sub-project 1 (detailed) →
A. Threat-model spec":

| # | Attack | Academic-integrity realisation | Motivating evidence | Existing control (file:line) | Gap | Severity | SP1 gate |
|---|---|---|---|---|---|---|---|
| 1 | Obfuscated / "dumbed-down" own baselines | Student writes baselines unlike their real voice so a later AI/ghostwritten paper matches | Study §4.5; R1 (contested magnitude); R9 (self-poison looks atypical) | `check_drift` catches 6.7% (`state.py:346-500`) | No baseline-consistency surfacing | P1 | G-A6 (integrity) |
| 2 | Outsourced baselines | Someone else writes the baselines | R9 (UPTON) | provenance ladder only (`constants.py:688`) | provenance is a label, not evidence | P1 | G-A6 |
| 3 | σ-inflation | Deliberately inconsistent baselines widen `baseline_std`, shrinking every later z | `baseline_std` floor but **no ceiling** (`state.py:248-272`) | none | nothing flags a too-wide baseline | P1 | G-A5 (σ-inflation curve) |
| 4 | Imitation of own baselines | Ghostwriter/LLM told "write like these three essays" | R3 (~50% ASR, 3 samples enough); R4 (detectable "too-diverse") | too-central band, **off** (`typicality.py`) | off + paraphrase-defeatable | P0 | G-A2 (imitation) |
| 5 | Imitation of a peer / collusion | Submit in a specific classmate's style; two students swap | R4 | null pool is aggregate (`null_pool.py:69`) | no nearest-peer attribution | P2 | G-A4 (peer) |
| 6 | Paraphrase / round-trip laundering | Launder AI/purchased text toward own style | R3 (83–92% flip); R1 (MT halves attribution) | 32% paraphrased-AI recall (`CAUSE_…`) | the dominant modern hole | P0 | G-A3 (paraphrase/MT) |
| 7 | Provenance forgery / replay | Reuse a proctor attestation; batch-upload as `verified`; fire request-baseline as a student | survey §E findings | attestation binds student+expiry only (`student_auth.py:145`); upload-batch skips `_authorize_provenance` (`students_baseline.py:358`) | replay + unauthorised trust | P0 | covered by C-i tests |
| 8 | "Too-perfect" submission | Near-duplicate of a baseline submitted as new work | R4 | none; `1.0=authentic` (`schemas.py:576`) | no near-duplicate / too-central check live | P2 | G-A2 shares metric |
| 9 | Cold-start N=1 | Score fires on one baseline; FPR ~0.9 at N=3 | T-01 (red); R7 | adaptive σ floor only | no minimum-baseline policy | P0 | G-A1 (cold-start FPR) |

### What this product will not claim

The literature is unambiguous on one point that must be stated as an
explicit product limit, not left implicit:

- **R1** (Wang, Juola & Riddell 2022, reproducing Brennan 2012): manual
  obfuscation and imitation each roughly halve closed-set attribution
  accuracy under a proper no-instruction control — a real, not
  chance-level, effect, even though the original 2012 magnitude was
  overstated.
- **R2** (PAN-2016 automatic obfuscators vs. PAN 2013-2015 verifiers):
  against a one-class verifier specifically, light rewriting is a *modest*
  threat to the final accept/reject decision, but it reliably shifts the
  calibrated score toward the threshold before it flips the decision — the
  direct argument for an abstention/inconclusive band rather than a binary
  call.
- **R7** (PAN 2022 cross-discourse-type): top verifiers fall from >0.93 to
  ~0.31 overall (AUROC ~0.5) purely from a genre/register shift between
  same-author documents — an in-class proctored essay baseline scored
  against a take-home submission in a different register looks different
  for entirely benign reasons.

Taken together: **verification is unreliable wherever a plausible
register/genre shift or a deliberate stylistic modification could explain
the same numbers as a different-author submission.** Original does not, and
after this work still will not, claim to reliably detect a submission that
has been deliberately rewritten to pass, nor to distinguish that from
honest stylistic growth or a change in assignment genre. Every signal this
programme adds is report-only evidence for a human conversation, not an
automated determination.

This is not a new posture invented for this document — it is already the
product's architecture, in two places:

1. **`professor_narrative.py:11-18`**, the tone rules governing every
   professor-facing explanation: never say "cheating", "fraud", or
   "plagiarism"; never present output as a verdict, only as "observations
   that may warrant a conversation"; acknowledge innocent explanations
   first; never show raw numbers (z-scores, deviation scores) to a
   professor.
2. **The report-only posture** already used for `AI_LIKELIHOOD_ENABLED`,
   `FUSED_SCORE_ENABLED`, `STYLE_AUTHORSHIP_ENABLED`, and
   `LONGITUDINAL_DRIFT_ENABLED`: each of these attaches evidence to the
   response without ever moving `deviation_score` or `recommendation` on
   its own initiative.

Every mechanism this taxonomy motivates — `baseline_integrity`, the
`G-A1`…`G-A6` gates, and the composite consistency work in later
sub-projects — must be built to the same standard: additional evidence
surfaced for a human, never a new automated verdict.

---

## 2. Goals and non-goals

**Goals**

1. Name every attack against the verification path in one document, so
   later work has a fixed taxonomy to cite instead of re-deriving it.
2. Freeze the field contracts (band vocabulary, reason codes,
   `composition_summary`, `baseline_integrity`, the signed-webhook
   contract) that Sub-projects 2–5 build against, so they do not each
   invent an incompatible shape.
3. Define the harness and gates (`G-A1`…`G-A6`) that will produce the first
   honest numbers for impostor catch rate, same-author FPR, imitation
   success, paraphrase-laundering success, peer-collusion detectability,
   and σ-inflation — replacing "no measurement exists" with a committed
   baseline every later sub-project must report against and try to beat.
4. Close the three cheap, already-identified security holes in the
   provenance/attestation path (attack 7) — these are unauthorised-caller
   bugs, not accuracy questions, and need no new gate.
5. Record the keystroke-capture decision (ADR-010) and its consequences for
   the feature vector and stored data.

**Non-goals**

- This document does not implement the harness, the security fixes, or the
  `baseline_integrity` diagnostic. Those are later tasks in the same
  sub-project (see "Architecture" below) and ship as their own commits with
  their own tests.
- No change to `deviation_score`, `recommendation`, or any existing
  production scoring path. Nothing in this spec is a scoring change; the
  one score-touching item in Sub-project 1 (the keystroke macro-only
  rewiring of `resolve_composition_mode`) is scoped in ADR-010, not here,
  and is required to be proven byte-identical before it ships.
- No new machine-learning model. `style_authorship` v2, the macro-context
  composite score, and the instructor dashboard are separate sub-projects
  (SP2, SP3, SP5) that consume this spec's contracts; they are not designed
  here.
- No claim that any gate below, once green, "solves" adversarial
  robustness. R5 (adversarial training) found training on synthetic
  attacks improved only 11 of 80 configurations and *worsened* 22 of them —
  this program's value is honest measurement and an abstention band, not a
  promise of robustness.
- Not a redesign of `check_drift`, `typicality.py`, or `null_pool.py`.
  Those remain as-is; this spec measures their current adversarial
  behaviour and defines what a future fix must beat.

---

## 3. Architecture

```
                    ┌─ A. Threat-model spec (this document) ─────────┐
                    │ taxonomy, frozen contracts, gate definitions    │
                    └───────────────────┬──────────────────────────--┘
                                         │ defines what B measures,
                                         │ what C fixes
                    ┌────────────────────▼───────────────────────────┐
                    │ B. Red-team harness — validation/adversarial/   │
                    │ victim-profile construction, attack generators, │
                    │ two scoring paths (fast + real-API), G-A1…G-A6  │
                    └────────────────────┬───────────────────────────┘
                                         │ interleaves once the harness
                                         │ can measure byte-identity
                    ┌────────────────────▼───────────────────────────┐
                    │ C. Baseline-hygiene fixes (product code)        │
                    │ (i) provenance/replay security fixes            │
                    │ (ii) baseline_integrity report-only diagnostic  │
                    │ (iii) keystroke macro-only capture (ADR-010)    │
                    └──────────────────────────────────────────────--┘
```

Build order, per the programme plan: **(A) this spec first** — it defines
what B measures and what C fixes — **then (C-i)** the cheap security fixes
(independent, unblock nothing but reduce live risk today), **then (B)** the
harness and gates (the largest piece), **interleaving (C-iii)** the
macro-only capture change once the harness can measure that scores stay
byte-identical on the flag-on path.

### B. Red-team harness — `validation/adversarial/` (future task)

- **Victim-profile construction** from committed public-domain material
  (`validation/public_authors/`, `validation/pan20_cross_fandom/`,
  `validation/corpus/`) into `{victim: N baselines, genuine_holdout: [...],
  impostor_docs: [...]}` at N ∈ {3, 5, 10}, reusing
  `validation/verify/pan_corpus.py`'s loaders and its deterministic
  SHA-256 selection convention.
- **Attack generators**, each implementing the existing `Generator` ABC
  (`validation/diagnostics/generators.py:49-73`: `configured`,
  `skip_reason()`, `load_samples()`, must raise rather than fabricate):
  - `MechanicalObfuscation` — deterministic "dumbing down" per the 2012
    study's §4.5 (split at coordinating conjunctions, thin
    adjectives/adverbs, swap high-syllable words); no randomness. Expected
    weak against a one-class verifier per R2 — that is the point, it
    calibrates the floor.
  - `LLMImitation`, `LLMParaphrase`, `LLMRoundTrip` (EN→DE→EN,
    EN→JA→EN) — offline validation only, cached outputs with a manifest
    (model id, prompt SHA, per-doc SHA) so CI replays hermetically, the
    `ClaudeStaticGenerator` pattern. This is where the R3/R6 modern threat
    is measured.
  - `BaselinePoisoning` scenarios — obfuscated baselines, σ-inflation by
    register-mixing, outsourced baselines. Measures attacks 1/2/3.
  - The CC0 Riddell-Juola replication corpus (R10) as a real, non-synthetic
    obfuscation/imitation set.
- **Runner:** two paths — a fast path driving `quantum.score()` directly
  (calibration-gate style, for sweeps and the σ-inflation curve) and a
  real-API path (a TermSim-style runner, deployment-shaped: real
  `ACTION_THRESHOLDS`, not the typicality path) for the *reported* number.
  The adversarial leg is its own `--only` CI leg with a tight corpus, kept
  under 30 minutes.
- **Metrics:** impostor catch rate at each action bar
  (`no_action|monitor|schedule_conversation|escalate`); same-author FPR on
  genuine hold-out at each bar, at N ∈ {3, 5, 10}; imitation success
  (fraction of imitated docs landing at `no_action`); poisoning success
  (fraction of poisoned profiles whose later impostor submission lands at
  `no_action`); the σ-inflation curve (mean `baseline_std` vs. catch rate).

### C. Baseline-hygiene fixes (future tasks)

Security fixes (C-i), the `baseline_integrity` diagnostic (C-ii), and the
keystroke macro-only capture change (C-iii, recorded in ADR-010) are scoped
in the programme plan and land as their own tasks with their own tests;
this spec defines the contracts and gates they are built and measured
against, not their implementation.

---

## 4. Phase 0 — Gates (built first, in the harness)

Six gates, `G-A1`…`G-A6`, three-valued (`pass` / `fail` / `uninformative`,
matching `validation/calibration_gate.py`'s existing `GateResult`
convention — a criterion unreachable at the current corpus size downgrades
a would-be pass to `uninformative`, never a pass). Each needs a failure
witness registered in `validation/gate_contracts.py`
(`GATE_CONTRACTS`) before it may be wired into `run_all()` /
`GATE_LEGS`, per the existing falsifiability enforcement
(`tests/test_gate_falsifiability.py`). Each gate is **uninformative when
its cached attack corpus is absent** — it must never report a pass on a
fresh checkout that has not fetched or generated the corpus, mirroring how
G7 already handles an uncommitted corpus.

| Gate | Measures | Attacks covered | Corpus need |
|---|---|---|---|
| `G-A1` | Cold-start same-author FPR at N ∈ {3, 5, 10} through the real scoring path | 9 (cold start) | committed public-author / seminary corpora (already present) |
| `G-A2` | Imitation success rate (fraction of `LLMImitation` outputs landing at `no_action`); shares its "too-perfect" metric with near-duplicate submissions | 4 (imitation), 8 (too-perfect) | cached `LLMImitation` outputs |
| `G-A3` | Paraphrase / round-trip laundering success rate | 6 (paraphrase/MT) | cached `LLMParaphrase` / `LLMRoundTrip` outputs |
| `G-A4` | Peer-imitation / collusion detectability against the aggregate null pool | 5 (peer imitation) | `BaselinePoisoning` / peer-swap scenarios |
| `G-A5` | σ-inflation curve — mean `baseline_std` vs. catch rate as baselines are made more internally inconsistent | 3 (σ-inflation) | `BaselinePoisoning` register-mixing scenarios |
| `G-A6` | Baseline-integrity signal quality against obfuscated / outsourced baselines | 1 (obfuscated own baselines), 2 (outsourced baselines) | `MechanicalObfuscation` + Riddell-Juola corpus, outsourced-author swaps |

Attack 7 (provenance forgery/replay) is **not** gated numerically — it is
covered by the security fixes' own regression tests
(`tests/security/test_unauthenticated_writes.py` and new attestation
tests), because it is an authorisation bug, not an accuracy question.

The first full run of `G-A1`…`G-A6` is recorded in
`docs/research/ADVERSARIAL_BASELINE_FINDINGS_2026-09-20.md` (future task) —
the numbers every later sub-project (style_authorship v2, the composite
score) must report against and try to beat, per the programme plan's
"Number it must report on the SP1 harness" column.

---

## 5. Frozen contracts

These five shapes are frozen here so Sub-projects 2–5 build against stable
contracts instead of each inventing their own. Nothing in this section
changes any existing schema, route, or scoring behaviour by itself — these
are the shapes a future implementation task must produce.

### 5.1 Band vocabulary

Three-valued, shared by SP2 (`style_authorship` v2), SP3 (composite
consistency score), and SP5 (the dashboard):

```
consistent | inconclusive | divergent
```

This matches `FusedScoreOut`'s existing three-value band
(`schemas.py:836`), **not** `style_authorship` v1's two-value
(`consistent`/`inconclusive`) set. `inconclusive` is the abstention band —
it is the direct expression of R2 (a verifier under light rewriting should
move toward the threshold, not flip a hard decision) and R7 (a
cross-genre-shifted submission should abstain, not be scored as divergent).

### 5.2 Reason-code vocabulary

For any signal that abstains rather than producing a band, following
`original/fusion/expert.py`'s `predict_fused_score_with_reason` pattern
(the reason-code precedent `style_authorship` v1 lacks — v1 abstains
silently at three call sites with no log and no reason code):

```
probe_too_short | artifact_unavailable | baseline_below_min |
insufficient_peers | cross_genre_incomparable | channel_error
```

### 5.3 `composition_summary` shape

A macro-timing object on `AddSampleRequest` / `ScoreSubmissionRequest` /
`BaselineSample` (this spec defines it; SP3 consumes it; ADR-010 records
why it replaces raw keystroke capture):

```json
{
  "session_seconds": 0,
  "word_count": 0,
  "paste_attempts": 0,
  "focus_losses": 0,
  "revision_count": 0,
  "started_at": "",
  "ended_at": "",
  "exam_config": {
    "block_copy": false,
    "min_words": 0,
    "duration_min": 0
  }
}
```

All fields optional, `.get()`-defaulted on read. This is a JSON-document
additive field on the existing `student_profiles.data` document store —
per finding B in the programme plan's deep-exploration notes, adding it
requires no SQLite migration and no Alembic migration, only coordinated
edits to `_serialize`/`_deserialize` (`store.py:673-765`,
`postgres_repository.py:145-210`) and the ingest path.

### 5.4 `baseline_integrity` shape

A report-only block (this spec defines it; SP1's own C-ii task attaches
it; SP5 renders it):

```json
{
  "n_baselines": 0,
  "min_required": 0,
  "readiness": "ready",
  "provenance_mix": {},
  "span_days": 0,
  "loo_outlier_samples": [
    {"index": 0, "z": 0.0}
  ],
  "sigma_inflation": null,
  "notes": []
}
```

`readiness` is one of `"ready" | "thin" | "absent"`. `sigma_inflation` is
`float | null`. This block changes no score by itself — it is computed from
`StudentState` (per-sample LOO-outlier z reusing `loo_distances`,
`state.py:559-596`; a σ-inflation indicator from the share of features
whose `baseline_std` exceeds `null_pool`'s σ_null when a peer pool exists;
provenance mix; span in days; N vs. `MIN_BASELINES` readiness) and attached
alongside the existing score response, never folded into
`deviation_score`.

### 5.5 Signed-webhook contract (for SP4)

SP1 defines the contract; SP4 (Bluebook standalone) implements the sender;
Original implements the receiver. It replaces today's send-only
`BBOOK_EXTERNAL_SECRET` (outbound only, no inbound verification anywhere,
per the deep-exploration findings) with two-sided verification:

- **HMAC-SHA256** over a canonical request body.
- A **nonce** and an **issued-at** timestamp carried in the signed payload.
- A **replay window**: a receiver rejects any request whose issued-at falls
  outside a bounded window, even with a valid signature.
- An **idempotency key**: a receiver deduplicates by this key, independent
  of the replay window, so a legitimate retry inside the window is not
  double-applied.

No transport, header names, or key-rotation mechanism are specified here —
those are SP4 implementation detail. This section freezes only the four
required properties (signed, nonced, time-windowed, idempotent) so SP4's
design does not have to re-derive them from first principles.

---

## 6. Phase 1 — Provenance / replay security fixes (`C-i`, no flag; future task)

Behaviour changes for **unauthorised callers only** — no environment flag,
because these are authorisation bugs, not accuracy trade-offs, and every
legitimate caller's behaviour is unchanged:

- `upload-batch` (`students_baseline.py:358`) must call
  `_authorize_provenance` the same way `add_baseline` already does; an
  unauthorised caller is downgraded to `unverified`, never rejected outright
  (matching the existing downgrade-not-reject policy). Closes attack 7's
  batch-upload leg; test:
  `tests/security/test_unauthenticated_writes.py:127,290`.
- `request-baseline` (`students_baseline.py:246`) requires staff
  (`_require_staff` plus a `Request` parameter it currently lacks).
- The proctor attestation binds and checks `exam` (currently accepted but
  never verified, `student_auth.py:145-151`) and becomes single-use per
  exam, closing the 6-hour any-text replay window.

## Phase 2 — `baseline_integrity` diagnostic (`C-ii`, no flag; future task)

Attach-only, byte-identical when the block is absent, no environment flag —
it changes no score, only what is reported alongside one. Tests follow the
existing cross-flag-invariant pattern
(`tests/fusion/test_wiring.py:193-210`): the block's presence or absence
must never move `deviation_score`, `quantum_fidelity`, or
`recommendation.action`.

## Phase 3 — Keystroke macro-only capture (`C-iii`; future task, see ADR-010)

The one item in Sub-project 1 that can move a score, because
`resolve_composition_mode` (`context/resolvers.py:538-566`) feeds the
context manifest under `CONTEXT_MANIFEST_ENABLED`. Full decision record and
consequences are in `docs/adr/ADR-010-keystroke-macro-only.md`; this spec
only states the acceptance bar: the rewiring must be proven byte-identical
on the flag-on path (a TermSim `baseline` cell diff against
`python -m validation.termsim run --matrix standard`) before it ships,
using the same discipline as any other flag-off byte-identity requirement
in this repository.

---

## 7. Rollout

1. This spec merges first (Phase 0's gate definitions and the frozen
   contracts) — nothing downstream can be built against a moving target.
2. Phase 1 (C-i security fixes) ships next, independently — it fixes live
   authorisation bugs and depends on nothing else in this programme.
3. Phase 0's harness (`validation/adversarial/`) and gates `G-A1`…`G-A6`
   are built third, interleaving Phase 3 (macro-only capture) once the
   harness can measure byte-identity on that change.
4. The first `G-A1`…`G-A6` run is recorded in
   `docs/research/ADVERSARIAL_BASELINE_FINDINGS_2026-09-20.md` before any
   later sub-project (SP2's `style_authorship` v2, SP3's composite score)
   is allowed to claim an improvement over it.
5. No gate in this document authorises turning on any existing flag
   (`TYPICALITY_SCORING`, `IDENTITY_AXIS`, `GENRE_INVARIANT_WEIGHTS_ENABLED`,
   etc.) — that remains governed by each flag's own row in CLAUDE.md and
   `.claude/agents/flag-rollout-auditor.md`'s "a passing gate does not
   authorise on" rule.

---

## 8. Risks and open questions

- **R5 (adversarial training is not a reliable defense).** Training a
  verifier on synthetic attack samples improved only 11 of 80
  method-dataset configurations in the literature and worsened 22 of them.
  This programme's harness measures degradation honestly; it does not
  promise that any later sub-project's mechanism closes these gaps, only
  that it reports its number against this baseline.
- **Corpora are public-domain and synthetic, not pilot data.** Every
  `G-A1`…`G-A6` number is measured against `validation/public_authors/`,
  `validation/pan20_cross_fandom/`, `validation/corpus/`, and cached LLM
  attack outputs — none of it is real student writing. Numbers are
  directional until real pilot data replicates them, the same caveat
  already carried by G1/G2/G4 in the two-axis verification design.
- **LLM attack generation needs an API key in the validation environment
  only** (never the product path), per the programme plan's open question
  1 — outputs are cached and committed so CI never calls out.
- **Committing the Riddell-Juola CC0 corpus** (2.4 MB) into
  `validation/adversarial/corpus/` is the programme plan's open question
  2 — it is CC0-licensed, so this is a repo-size question, not a licensing
  one.
- **`G-A4` (peer imitation) has no live mechanism to detect its own
  target.** `null_pool.py`'s aggregate Gaussian null model cannot say
  "closer to peer B than to claimed student A" today; a closed-set
  enrolled-peer branch was tried and not promoted (per the deep-exploration
  findings). `G-A4` measures the current, structural blind spot — it does
  not assume a fix exists yet.
- **Severity ≠ gate value.** A gate reading `uninformative` because its
  corpus is absent is not evidence the underlying attack is safe; it is
  evidence the measurement has not been taken yet. Treat an uninformative
  `G-A` gate the same way `G7` is already treated elsewhere in this
  repository: not a pass, not a crash, a missing measurement.

---

## 9. Deliverables

| Path | Content |
|---|---|
| `docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md` | This document |
| `docs/adr/ADR-010-keystroke-macro-only.md` | The keystroke macro-only decision record |
| `docs/testing/10-gap-register.md` | Rows T-67…T-75 |
| `validation/adversarial/` (future task) | Victim-profile construction, attack generators, the two-path runner, `G-A1`…`G-A6` |
| `validation/gate_contracts.py` (future task) | Failure witnesses for `G-A1`…`G-A6` |
| `docs/research/ADVERSARIAL_BASELINE_FINDINGS_2026-09-20.md` (future task) | First recorded `G-A1`…`G-A6` run |
| `students_baseline.py`, `student_auth.py` (future task) | Phase 1 security fixes (C-i) |
| `original/quantum/state.py`, response schemas, `professor_narrative.py` (future task) | `baseline_integrity` diagnostic (C-ii) |
| `demo/bluebook/Exam.jsx`, `context/resolvers.py` (future task) | Keystroke macro-only capture (C-iii, ADR-010) |
