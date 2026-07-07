# ADR-007: AI-likelihood detector — report-only contract and enablement gating

**Status:** Accepted — implemented 2026-07-01
**Date:** 2026-07-07 (recorded retroactively — see "Why this ADR is late" below)
**Deciders:** Product owner (Andrew)
**Relates to:** `original/ai_likelihood.py`, `original/api.py` (score_submission),
`MODEL_CARD.md` §"AI-Likelihood Detector", ADR-003 (the demo-must-keep-working
constraint that motivates default-OFF flags generally)

## Context

The product's core claim is per-student authorship *verification*: does this
submission match the writing style this specific student has already
established? That is a relative question, answered by the Born-rule/quantum
scoring path (`original/quantum/scoring.py`) and it never involves a labeled
"AI vs. human" example.

A different, absolute question — "does this text look like AI-generated text
at all, independent of whose baseline it's compared to?" — is answered by a
separate supervised classifier (`original/ai_likelihood.py`), motivated by a
diagnostic finding (PR #21) that the product's own 103 features plus a plain
classifier reached AUC 0.7402 on AuTexTification, well above the per-student
path's 0.6091 on the same benchmark (as recorded in `MODEL_CARD.md`).

Shipping a second, statistically different scoring signal into a product
whose core positioning is "explainable, pastoral, not an AI-accusation
machine" (per `CLAUDE.md`'s project framing) creates real risk if it's wired
in carelessly: a false positive from a corpus-level classifier reads very
differently to a professor than "this doesn't match the student's own past
writing," and the feature carries known failure modes (the AuTexT-only v1
model flagged 40% of authentic seminary essays and 76–91% of archaic
historical prose as AI-like — formal register misread by a tweet-heavy
training corpus, per `MODEL_CARD.md`). The detector needed a contract that
made it safe to ship *before* it was fully trusted, not after.

### Why this ADR is late

The detector shipped 2026-07-01 (`MODEL_CARD.md` version history, 1.2.0) with
its contract already implemented and documented in `MODEL_CARD.md`. This ADR
is written after the fact, per `docs/AUDIT_2026-07-06.md` D13 ("three shipped
decisions are unrecorded" — default-OFF env-flag strategy, peer-pool null
model, AI-likelihood detector) — it records a decision already made and
shipped, not a new one. The "Decision" section below describes the mechanism
as implemented, verified against the code, not a design intent that may have
drifted.

## Decision

**Ship the AI-likelihood detector as an attach-only, report-only second
signal, gated behind two independent env flags with different visibility
semantics, defaulting OFF everywhere including demo mode.**

### The gating mechanism (as implemented)

Two flags control the detector, checked at the top of `score_submission` in
`original/api.py`:

```python
_ai_enabled = os.environ.get("AI_LIKELIHOOD_ENABLED") == "1"
_ai_shadow  = os.environ.get("AI_LIKELIHOOD_SHADOW") == "1"
if _ai_enabled or _ai_shadow:
    _ai_res = predict_ai_likelihood(vec)
    if _ai_enabled:
        result.ai_likelihood = _ai_res       # surfaced in the API response
    if _ai_res is not None:
        store.put_ai_likelihood_score(...)   # persisted regardless of enabled/shadow
```

- **`AI_LIKELIHOOD_SHADOW=1`** — computes and **persists** the prediction
  (`store.put_ai_likelihood_score`), but never sets `result.ai_likelihood`.
  Because the field stays `None`, no downstream layer — the API response
  schema, `professor_narrative.py`, the explainer — can see it. This is
  silent, real-world false-positive-rate measurement
  (`scripts/shadow_report.py` reads the persisted rows) with zero product
  surface. Shadow mode is how the detector was evaluated against live pilot
  traffic before anyone decided to show it to a professor.
- **`AI_LIKELIHOOD_ENABLED=1`** — a strict superset of shadow: attaches the
  result to the response **and** persists it, so flipping shadow → enabled
  is one env change with unbroken data continuity (no gap in the persisted
  history, since shadow was already writing the same rows).
- **Both default OFF**, including in demo mode — unlike `CONTEXT_MANIFEST_ENABLED`,
  `ADAPTIVE_WEIGHTS_ENABLED`, and `NULL_MODEL=impostor`, which `run.py` force-enables
  for the demo, `AI_LIKELIHOOD_ENABLED`/`AI_LIKELIHOOD_SHADOW` are not in that
  force-enable list. `MODEL_CARD.md` states this explicitly: "default OFF
  everywhere, including demo mode and both Render services." This is a
  deliberate asymmetry — the other flags reflect scoring-math refinements
  already validated on benchmark data; this flag exposes a categorically
  different kind of claim ("this looks AI-written") that needs its own
  enablement bar (see below) before it's shown to anyone, even in a sales
  demo.
- **`AI_LIKELIHOOD_MODEL_PATH`** — optional override of the committed
  classifier artifact path (`original/data/ai_detector_v1.joblib` by
  default); used for the version-skew runbook and for testing/retraining
  workflows without touching the committed artifact.

### The report-only contract

"Report-only" means precisely: **the signal never feeds `deviation_score` or
the recommended `action`.** Looking at `score_submission`, the AI-likelihood
block runs entirely after `result` (the Layer-7 output containing the
authorship deviation score and recommendation) is already assembled — it can
only *attach* a field, never influence the computation that produced
`result.recommendation.action`. This is structural, not a convention: nothing
in `original/quantum/scoring.py` reads `ai_likelihood` at all. The
professor-facing narrative surfaces it as band-only prose (`low`/`elevated`/
`strong`), "frequency-framed," and explicitly "never contains a number" per
`MODEL_CARD.md` — the same instinct as the peer-pool null model's
attach-only design (`docs/adr/` should record that one too — see D13's
remaining item, out of scope here) and consistent with the product's
pastoral-explainability positioning.

### Fail-closed runtime

`original/ai_likelihood.py` never raises into the request path: `predict_ai_likelihood`
returns `None` on any load or predict failure, logs one warning, and disables
itself rather than repeat the warning or 500 the caller. A load-time smoke
check against 8 stored reference vectors also doubles as a sklearn
version-skew gate — if a dependency bump changes what the deserialized model
predicts by more than 0.02 on those reference vectors, the detector disables
itself rather than silently serve different probabilities under the same
flag value.

### The enablement gate (not yet exercised in production)

Per `MODEL_CARD.md`, flipping `AI_LIKELIHOOD_ENABLED=1` anywhere pilot-facing
is gated on a criterion independent of the env-var mechanism itself:
**seminary AUC ≥ 0.85 AND false-positive rate ≤ 5% at the elevated threshold
on authentic seminary essays**, checked by
`scripts/train_ai_detector.py eval-seminary`. The shipped model passes this
bar on a small (45-essay, single-generator) in-domain sample, but
`MODEL_CARD.md` is explicit that a larger multi-generator eval and an
institutional decision should precede actually flipping the flag on a real
pilot. As of this writing the flag remains off on both Render services — the
gate exists, the criterion is met on the available evidence, but the decision
to enable has not been made for any live institution.

## Options considered

### Option A: Two flags, shadow-then-enabled, report-only, default-OFF — CHOSEN
Lets the detector be validated against real traffic (shadow) before it's ever
shown to a human, with a one-flag graduation path and a hard structural
guarantee that it cannot change what action a student sees, even if the
underlying classifier is later found to be miscalibrated in some subgroup.

### Option B: Single flag, straight to enabled
Simpler, but collapses "we're measuring this" and "we're showing this to
professors" into one decision — no way to gather real-world FPR evidence
without simultaneously exposing a possibly-miscalibrated signal. **Rejected**
— the seminary-essay false-positive story (40% flagged by the AuTexT-only v1
model) is exactly the failure mode shadow mode exists to catch before
exposure.

### Option C: Couple the signal to the recommended action directly
Would let a strong AI-likelihood reading raise the deviation action tier
(e.g., push `monitor` to `schedule_conversation`). **Rejected for now** —
`MODEL_CARD.md` names this as a deliberately deferred "Future path," gated on
its own separate flag (`AI_LIKELIHOOD_ACTION_NUDGE_ENABLED`, not yet
implemented) and a pilot semester of in-domain false-positive data, following
the same raise-only, corroborating-evidence pattern already used for the
conformal p-value nudge. Coupling two independently-calibrated signals
without recalibrating the combined threshold would risk compounding false
positives from two models that were never jointly validated.

## Consequences

**Now (as shipped):**
- The detector can be evaluated against real pilot traffic (shadow mode)
  with zero product-surface risk.
- Turning the signal on for a professor is one env flip, with continuous
  persisted history from whatever point shadow mode was already running.
- A student or professor can never be pushed to a worse recommended action
  by this signal alone, structurally (not just by policy) — `action` is
  computed before the AI-likelihood block runs.
- The version-skew and fail-closed design means a dependency bump or a
  corrupted artifact degrades to "field absent," never a 500 or a silently
  wrong probability.

**Trade-offs accepted:**
- The enablement gate is a documented threshold, not an automated CI check —
  someone has to run `eval-seminary` and read the result before flipping the
  flag; there's no code that prevents enabling below the bar.
- Report-only means the detector currently provides no product value beyond
  professor-facing prose — the "Future path" (action coupling) is where the
  signal would actually change outcomes, and that's explicitly not built yet.

## Action items

1. [x] Implement `AI_LIKELIHOOD_ENABLED`/`AI_LIKELIHOOD_SHADOW` gating in
   `score_submission` (`original/api.py`).
2. [x] Fail-closed runtime + sklearn version-skew smoke check
   (`original/ai_likelihood.py`).
3. [x] Document the contract in `MODEL_CARD.md` (version 1.2.0 entry).
4. [x] Record this decision as an ADR (this document — D13).
5. [ ] Run a larger multi-generator in-domain eval before enabling the flag
   for any live pilot institution (per `MODEL_CARD.md` caveats).
6. [ ] If action-coupling is pursued later, record it as its own ADR rather
   than amending this one — the report-only contract recorded here should
   stay a clean historical record of what shipped 2026-07-01.

## Related documents

- [`MODEL_CARD.md`](../../MODEL_CARD.md) §"AI-Likelihood Detector" — the
  fuller technical writeup (training data, thresholds, evaluation evidence)
  this ADR does not duplicate.
- [`CLAUDE.md`](../../CLAUDE.md) — env-flag table (`AI_LIKELIHOOD_ENABLED`,
  `AI_LIKELIHOOD_SHADOW`, `AI_LIKELIHOOD_MODEL_PATH` rows).
- [ADR-003](003-multi-tenant-auth-without-losing-demo.md) — the demo-must-
  keep-working constraint underlying why this flag (unlike the three
  demo-forced flags) stays off in demo mode.
