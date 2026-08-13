# Fused Stylometric Score — Design

**Date:** 2026-08-11 · **Status:** specified · **Posture:** report-only + shadow persist (user-selected)

## Problem

Original's primary `deviation_score` asks one question — "how far is this submission
from the claimed student's own baseline?" — and answers it per-feature, against that
student's own three-or-so samples, in absolute terms. Three measured studies now agree
that this is the weakest available formulation when the submission's topic or genre
shifts:

- `validation/genre_crossgenre_2026-08/` — raw `deviation_score` AUC **0.387** on a
  leave-one-genre-out C.S. Lewis corpus. Below 0.5 means *inverted*: genuine
  cross-genre work scores more anomalous than a different author's writing.
- Paths experiment (2026-08-07, 172 PAN cross-fandom authors, 52 held out):
  production-proxy diagonal z caught **2%** of impostors at a 1% false-alarm budget.
  Peer-centering the same score took it to 24%; conditional compression alone to 33%;
  a calibrated fusion of peer-centered z + compression + a function-word adjacency
  network reached AUC **0.881**, 56% catch at 5% FA, Cllr **0.625** — best on every
  metric measured.
- Gate audit (2026-08-10, same corpus, real `original.quantum.scoring.score()`):
  the fused score reached AUC **0.889** vs **0.798** for the production score, lifting
  catch-at-conversation from 91.7% → 99.4% and catch-at-escalate from 51.3% → 70.5%.

The fusion exists only as a scratchpad experiment. This spec makes it a real,
report-only component of the live stack so it can be measured on pilot traffic —
which every one of those studies names as the missing ingredient.

**Non-goal:** changing any score or action. The fused score does not touch
`deviation_score`, `quantum_fidelity`, or `recommendation`. Whether it should
eventually drive actions — and whether `LLR_ACTION_MODE=gate` should be retired when
it does — is a separate decision that this spec exists to gather evidence for.

## Enabling facts

- **Raw baseline text is retained** in serialized profiles (`store.py` student_profiles
  JSON blob carries `samples[].text`; verified against a real row). The compression and
  function-word channels need it and can therefore run on live data.
- Two mature patterns to copy: `original/style_authorship.py` (peer-aligned,
  report-only, abstains with `None` on every insufficiency) and
  `original/quantum/null_pool.py` (tenant-scoped peer pooling with cold-start floors).
  Both wire in at `original/routers/students_scoring.py`.
- Inference is a dot product. Unlike `ai_likelihood` and `style_authorship`, this
  component needs no sklearn at runtime — which matters, because the AI-likelihood
  detector is *currently inert* precisely from artifact/version drift.

## §1 — Architecture

New package `original/fusion/`, four files, each with one job:

| File | Responsibility | Tested against |
|---|---|---|
| `channels.py` | Three pure distance functions. No state, no I/O. | Fixed strings → known values |
| `peers.py` | Deterministic same-tenant reference selection + profile cache | Synthetic `StudentState`s |
| `artifact.py` | Load and validate the committed weights JSON; fail closed | Corrupt fixtures |
| `expert.py` | Orchestrate profile → center → fuse → abstain | Mocked channels |

Flow:

```
students_scoring.py
  └─ FUSED_SCORE_ENABLED or FUSED_SCORE_SHADOW?
       └─ fusion.expert.predict_fused_score(text, state, all_states)
            ├─ peers.select_references(state, all_states)   → exactly 8 stable same-tenant peers
            ├─ channels.*                                    → 3 raw distances, self + each peer
            ├─ centering: self − mean(peer values)           → 3 peer-centered channel values
            ├─ artifact: (x − mu)/sd · w + b                 → fused log-odds
            └─ FusedScoreResult | None
```

Peer-centering is **one generic function applied to all three channels**, not three
bespoke code paths. This is the property that makes the package decompose cleanly
where `style_authorship.predict_style_authorship` (a single 65-line function doing
peer selection, profiling, centering, and calibration at once) did not.

### The three channels

1. **`peer_centered_z`** — the existing diagonal RMS-z formulation (winsorized |z| ≤ 4,
   sigma floor `max(0.005, 0.15/√N)`, `tanh(rms/1.5)`), computed against the claimed
   baseline and against each reference, then centered. Operates on the 109-dim feature
   vectors already extracted for the primary score — **no second extraction**.
2. **`compression_distance`** — conditional compression:
   `(C(base + probe) − C(base)) / C(probe)` using `lzma` `FORMAT_RAW`, `FILTER_LZMA2`,
   `preset=1`. Reads raw text; no features, no vocabulary, no training.
3. **`function_word_network_distance`** — cosine distance between row-normalized
   function-word transition matrices (100 function-word states + `OTHER`, gap ≤ 3
   intervening tokens, additive smoothing 0.05). Reads raw text.

**The third channel must earn its place.** In the gate audit the fusion assigned it a
weight of **−0.127** (near zero, and negative) against 1.560 for compression and 0.915
for peer-centered z. The training script runs a per-channel ablation on held-out
development authors and the artifact's `channel_order` is data-driven: if the network's
contribution falls inside noise, the artifact ships with two channels and `channels.py`
retains the third as dead-but-tested code for a future refit. Shipping two measured
channels is preferable to three that merely look thorough.

### Determinism

The experiment shuffled references with a seed. Production sorts eligible peers by
`sha256(student_id)` and takes the first 8. The same student scored twice gets the same
references, so the value is reproducible and explainable. Peer profiles (compressed
baseline size, function-word matrix, baseline vector stack) are cached keyed by a
content fingerprint of the peer's authenticated samples; otherwise every submission
re-compresses nine baselines.

## §2 — Contract, floors, and output

```python
predict_fused_score(text, claimed_state, states) -> FusedScoreResult | None
```

Signature-identical to `predict_style_authorship` so the wiring is familiar.

```python
@dataclass(frozen=True)
class FusedScoreResult:
    fused_log_odds: float                 # w·x + b, the raw evidence weight
    probability_different_author: float   # sigmoid(fused_log_odds)
    band: str                             # "consistent" | "inconclusive" | "divergent"
    channels: dict[str, float]            # peer-centered per-channel values
    reference_profiles: int
    baseline_samples: int
    model_version: str
    trained_on: str
```

**Abstain floors.** Any one failing returns `None`. No partial answers.

| Condition | Floor | Rationale |
|---|---|---|
| Probe words | ≥ 300 | Matches `style_authorship.MIN_WORDS` |
| Claimed baselines carrying retained text | ≥ 3 | Matches the corpus the weights were fit on |
| Eligible same-tenant peers | ≥ 8, and **exactly 8 used** | The artifact is calibrated at 8 references; fewer is off-calibration |

The fixed reference count is deliberate. `style_authorship` requires 10 peers and uses
*all* of them, so its inference runs at a reference count it was never calibrated at.
This component abstains below its calibrated count rather than extrapolate.

Legacy flat student IDs (`tenant_of → None`) form their own cohort, exactly as
`null_pool` treats them. Cross-tenant vectors and texts are never pooled.

**Direction:** higher `fused_log_odds` means *more impostor-like* (less consistent with
the claimed author), matching the sign convention of `deviation_score` and
`llr_deviation_score`. `probability_different_author` is therefore
`sigmoid(fused_log_odds)`, and both thresholds are lower bounds.

**Bands come from the artifact, not from module constants.** `threshold_fa5` and
`threshold_fa1` are the development-author operating points at 5% and 1% false alarms:

| Band | Condition |
|---|---|
| `consistent` | `fused_log_odds < threshold_fa5` |
| `inconclusive` | `threshold_fa5 ≤ fused_log_odds < threshold_fa1` |
| `divergent` | `fused_log_odds ≥ threshold_fa1` |

So "divergent" means literally "past the bar where 1 in 100 genuine submissions land" —
a sentence a professor can be told.

**Attachment point:** `Layer7Output` gains
`fused_score: FusedScoreResult | None = field(default=None)`, additive and defaulting to
`None`, exactly like the existing `style_authorship` and `ai_likelihood` fields. It is
set at the `students_scoring.py` call site, never inside `quantum/scoring.py` — that
module must stay unaware this component exists.

## §3 — Persistence

New table `fused_scores`, mirroring `ai_likelihood_scores` (SQLite DDL in `store.py`,
a `PostgresRepository` method, and an alembic migration):

```sql
CREATE TABLE IF NOT EXISTS fused_scores (
    submission_id   TEXT PRIMARY KEY,
    student_id      TEXT NOT NULL,
    fused_log_odds  REAL NOT NULL,
    probability     REAL NOT NULL,
    band            TEXT NOT NULL,
    channels_json   TEXT NOT NULL DEFAULT '{}',
    model_version   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fused_scores_student
    ON fused_scores(student_id, created_at);
```

`channels_json` is what makes shadow mode worth running: storing the three per-channel
values means the fusion weights can be **re-fit on real student data later without
re-extracting anything**. Storing only the fused number would discard exactly the
information a refit needs.

## §4 — Wiring and flags

In `students_scoring.py`, immediately after the `style_authorship` block, same shape as
the AI-likelihood two-mode call site:

- `FUSED_SCORE_SHADOW=1` → compute + persist only; `result.fused_score` stays `None`,
  so narrative, explainer, and API response can never see it.
- `FUSED_SCORE_ENABLED=1` → compute + persist **and** attach (strict superset:
  enablement is one env flip with unbroken data continuity).
- Both off → the module is never imported.

| Flag | Default | Effect |
|---|---|---|
| `FUSED_SCORE_ENABLED` | `0` | Attach `FusedScoreResult` to the scoring result |
| `FUSED_SCORE_SHADOW` | `0` | Compute + persist without attaching |
| `FUSED_SCORE_MODEL_PATH` | unset | Override path to the committed artifact |

CLAUDE.md's environment-flag table gains these three rows.

## §5 — Artifact and reproducibility

`original/data/fused_score_v1.json` — committed, human-readable. Every numeric value
below is **written by the training script**, not chosen by hand; the shape is the
contract, the numbers are output:

```jsonc
{
  "schema_version": 1,
  "channel_order": ["peer_centered_z", "compression", "function_word_network"],
  "mu":      [<float per channel>],   // standardizer, fit on development authors
  "sd":      [<float per channel>],
  "weights": [<float per channel>],   // logistic coefficients
  "intercept":     <float>,
  "threshold_fa5": <float>,           // dev operating point, 5% false alarms
  "threshold_fa1": <float>,           // dev operating point, 1% false alarms
  "reference_inputs":  [[<float per channel>], ...],  // loader self-check
  "reference_outputs": [<float>, ...],
  "provenance": {
    "dataset": "PAN 2020 cross-fandom authorship verification",
    "n_development_authors": 120, "n_references": 8, "trained": "<ISO date>"
  }
}
```

`channel_order` is authoritative: it may legitimately contain two entries rather than
three if the ablation drops the function-word network, and `mu`/`sd`/`weights` must
match its length.

The loader validates `schema_version`, `channel_order` against the module's known
channels, `len(weights) == len(mu) == len(sd) == len(channel_order)`, and recomputes
`reference_inputs → reference_outputs` (tolerance 1e-9). Any mismatch logs one WARNING
and fails closed to `None` — never a partially-trusted model.

`scripts/train_fused_score.py` regenerates the artifact from the 120 PAN development
authors: fits the standardizer and logistic, runs the per-channel ablation that decides
whether the function-word network ships, selects both thresholds, writes the JSON, and
prints held-out metrics on the 52 locked authors for the record. Deterministic seed
(20260807). Without this script the artifact rots into an unexplainable blob within a
quarter.

## §6 — Error handling

Every failure path returns `None` and never raises into the scoring path: missing or
corrupt artifact, too few peers, missing or short text, any inference error. One
WARNING log per distinct cause. The result is indistinguishable from flag-off, which is
the property that makes enabling this safe. Persistence failures are logged and never
block scoring, matching the `ai_likelihood` call site.

## §7 — Performance

Per submission: 9 LZMA compressions (claimed baseline + 8 references, each concatenated
with the probe) plus 9 function-word matrix builds. The peer profile cache holds the
expensive half — each reference's compressed baseline size and transition matrix are
computed once per profile fingerprint, not once per submission.

**Budget: < 250 ms added p95 latency.** A test asserts the cache prevents
recomputation (score twice, assert peer profiles built once).

## §8 — Test plan

The load-bearing test is the invariant: **for a fixed submission, `deviation_score`,
`quantum_fidelity`, and `recommendation.action` are byte-identical with the flag off,
in shadow, and enabled.** If that test cannot fail, none of the rest matters.

1. **Channels** — fixed strings → known values; determinism across calls; identity
   property (text against its own baseline is minimally distant); empty/degenerate input.
2. **Peer selection** — deterministic ordering; tenant isolation (never crosses tenant);
   self-exclusion; floor enforcement at 7 vs 8 eligible peers; legacy `None` tenant
   cohort behaviour.
3. **Artifact loader, fail-closed** — missing file; `schema_version` drift;
   `channel_order` mismatch; weight/mu/sd length mismatch; reference-prediction drift.
4. **Abstain paths** — short probe; fewer than 3 text-carrying baselines; fewer than 8
   peers; artifact unavailable.
5. **Invariant** — the byte-identity test above, across all three flag states.
6. **Persistence** — shadow persists without attaching; enabled persists and attaches;
   a persistence exception does not break scoring.
7. **Repository parity** — SQLite and `PostgresRepository` round-trip identically
   (mirroring existing repo parity tests); alembic migration up/down.
8. **Performance** — peer profile cache prevents recomputation.

Estimated shape: 4 source files, 1 training script, 1 migration, 1 artifact, ~35–40
tests, plus the three CLAUDE.md flag rows.

## Open questions deferred to evidence

- Whether the function-word network survives ablation (decided by the training script,
  not by this spec).
- Whether the fused score should eventually drive actions, and whether
  `LLR_ACTION_MODE=gate` is retired when it does. The 2026-08-10 gate audit measured
  the gate's contribution on the fused score at **zero** at every consequential severity
  bar, but on corpus data only. Shadow-mode pilot data is the evidence that decides it.
- Whether the weights refit meaningfully on real student traffic — which is why
  `channels_json` is persisted.
