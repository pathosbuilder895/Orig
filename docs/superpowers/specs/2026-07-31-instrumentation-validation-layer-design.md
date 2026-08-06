# Instrumentation & Validation Layer — Design

**Date:** 2026-07-31
**Status:** Draft for review
**Branch:** `claude/instrumentation-validation-layer-4e9d29`
**Prerequisite:** the instrument-report work on `claude/plato-works-dating-analysis-b05b1a`
(33 commits: conformal typicality axis, `validation/calibration_gate.py` G1–G6,
`scripts/derive_measured_weights.py`, public_authors chunker/attribution fixes, Tier 18)

## 1. Problem

The 2026-07-30 Instrument Report ("The instruments were broken, not the math",
artifact `298bab63`) established that every recent failure lived in the
*measurement* layer, not the scoring engine:

- a verification metric was bookkept as an attribution result;
- structurally-blank feature columns were read as "measured zero" and nearly
  drove wrong re-weighting;
- gate G1 passes by arithmetic (conformal p-values cannot go below 1/(N+1);
  the largest G1 entity has 12 docs, so min p ≈ 0.077 while the action band
  needs ≤ 0.03) — a pass that proves nothing;
- G5's first design could not fail by construction;
- the derivation corpus is 21 parts Plato to 2 parts student-like prose.

The individual defects are fixed on the plato branch, but each fix is local
knowledge embedded in one script. Nothing *structural* prevents the same class
of failure from recurring as gates and tiers keep being added. The external
review (the advisory this design responds to) frames the remedy correctly: an
instrumentation and validation layer — measurability as data, statistical
power as a first-class output, experiment config as data, gates that provably
can fail, and at least one independent attribution engine as a cross-check.

## 2. Goals / non-goals

**Goals**

1. One source of truth for what each feature column and each gate can, in
   principle, measure — and hard refusal to aggregate over anything else.
2. Every reported number carries its statistical floor/ceiling given N, and a
   gate whose pass is unreachable-by-arithmetic reports **uninformative**, not
   **pass**.
3. Every validation run embeds a machine-readable experiment spec (corpus
   composition, windowing, inclusion/exclusion, aggregation, thresholds, task
   type) so a number can never again detach from what it measured.
4. Corpus manifests enforce: minimum window length per task, genre/register
   metadata, provenance flags (real-historical / synthetic-AI / student-pilot),
   and conformal-informativeness given entity doc counts.
5. At least one alternative attribution engine (Burrows'-Delta-family distance
   on the existing 109-feature vectors, plus a classic MFW Delta baseline)
   benchmarked side by side with the impostor-calibrated deviation engine on
   the same held-out essays, with an agreement/ensemble report.
6. A falsifiability test suite: for every gate, a registered failure witness
   and label-destruction properties (Hypothesis), so no gate can be merged
   that cannot fail.

**Non-goals**

- **No product-code changes.** `original/constants.py` tier weights stay held;
  the scoring path is untouched. Everything lands in `validation/`, `scripts/`,
  and `tests/`.
- **No separate API endpoints** for verification/attribution/drift. That is a
  product change; the misuse the advisory worries about happened inside the
  validation layer and is addressed here by the experiment spec's mandatory
  `task` label. Revisit after pilot.
- **No consented student-essay corpus in this plan.** That is
  process/legal work, not code. The corpus module's provenance and genre
  fields are designed so that corpus drops in without schema changes.
- **No Lean/Coq.** The falsifiability registry + property tests deliver the
  advisory's "formal-ish spec" goal at proportionate cost.
- **No new runtime dependencies.** hypothesis 6.112.2, scikit-learn 1.6.1,
  and numpy 1.26.4 are already in the venv.

## 3. Approaches considered

**A. Bolt-on annotations** — extend each existing script in place (power
lines in `calibration_gate.py`, genre in the manifest, Delta inside
`public_authors/run.py`). Fastest, but leaves measurability/power knowledge
scattered per-script — the exact drift pattern that produced the original
failures.

**B. Thin shared layer (chosen)** — five small modules under `validation/`
that the existing runners import; no framework, no new deps. Each module is
independently unit-testable and consumed by ≥ 2 runners, which is what makes
the knowledge structural instead of local.

**C. Full experiment framework** (Sacred/MLflow + formal verification) —
disproportionate: new deps, new operational surface, and the repo's
validation culture (pure functions + JSON reports + CI exit codes) already
provides the skeleton.

## 4. Architecture

```
validation/
  measurability.py      ← C1: feature/gate measurability registry
  power.py              ← C2: statistical floors/ceilings, verdict logic
  experiment.py         ← C3: ExperimentSpec embedded in every report
  manifest_schema.py    ← C4: extended to v2 (genre, provenance, floors)
  attribution/
    __init__.py
    delta.py            ← C5: Burrows' Delta (MFW) + cosine-delta on features
    ensemble.py         ← C5: agreement matrix + 2-of-3 rule
  synthetic/            ← C7 (phase 2): parametric synthetic authors
tests/
  test_measurability.py
  test_power.py
  test_experiment.py
  test_attribution_delta.py
  test_gate_falsifiability.py   ← C6: witnesses + Hypothesis properties
```

Existing consumers changed: `validation/calibration_gate.py`,
`scripts/derive_measured_weights.py`, `validation/public_authors/run.py`,
`validation/stability/stability.py` (exclusion source only).

### C1 — Measurability registry (`validation/measurability.py`)

A single declaration mapping every feature code in `ALL_FEATURE_CODES` to a
status:

- `MEASURABLE` — varies in a corpus sweep; eligible for aggregation.
- `SCORING_ONLY` — comparison-shaped; computed only against a baseline at
  scoring time, hardwired 0.5 in `feature_vector()` (T0 comparison meta,
  T11 error ecology).
- `STRUCTURALLY_BLANK` — constant via a fallback path regardless of corpus
  (T12 `catastrophe_index`).
- `DISABLED` — in `DISABLED_FEATURE_GROUPS` (T17 behavioral, T18 uniformity);
  derived from constants at import time, never hand-listed.
- `CORPUS_LIMITED` — measurable in principle but known-blank on named corpora
  (T16 citation fingerprint on non-academic prose). Carries the corpus names
  it is limited on; treated as MEASURABLE elsewhere.

API sketch:

```python
status(code: str) -> MeasurabilityStatus
measurable_codes(corpus: str | None = None) -> list[str]
assert_aggregatable(codes: Sequence[str], corpus: str | None = None) -> None
    # raises MeasurabilityError listing offending codes + statuses
```

`derive_measured_weights.structurally_excluded_codes()` and stability's
`_FEATURE_INDICES_SKIPPED` become thin delegations to this module
(behavior-preserving refactor — same exclusion sets, one source).

**Self-consistency guard:** a test extracts features over a small fixture
corpus and asserts (a) every non-MEASURABLE code is in fact constant, and
(b) every MEASURABLE code actually varies. The registry cannot silently
drift from pipeline reality — which is precisely how "blank read as zero"
happened the first time.

### C2 — Statistical power (`validation/power.py`) + three-valued verdicts

Pure functions:

```python
conformal_p_floor(n: int) -> float                 # 1/(n+1)
band_reachable(n: int, threshold: float) -> bool   # floor <= threshold
min_docs_for_band(threshold: float) -> int         # ceil(1/t) - 1  (→ ~199 for 0.005)
rule_of_three_upper(n: int) -> float               # 3/n upper 95% CI for 0 observed
wilson_interval(successes: int, n: int) -> tuple   # 95% CI on a proportion
bar_decidable(successes, n, bar) -> str            # "above" | "below" | "undecided"
```

**Two mechanisms, one failure class.** G1 cannot flag because of an
arithmetic floor. G3 cannot demonstrate a *pass* because its interval is
wider than the distance to its bar: on 22 held-out essays the measured 0.455
has a 95% Wilson CI of [0.269, 0.653] — so that **failure is real** — but
the 0.818 diagnostic gives [0.615, 0.927], straddling the 0.7 bar, and even
0.727 gives [0.518, 0.868]. Roughly 306 essays would be needed for a 0.75
result to sit entirely above the bar. Both mechanisms resolve to the same
`uninformative` verdict, and every accuracy the attribution benchmark prints
carries its interval so the three-engine table is never read as a ranking it
cannot support.

`GateResult` gains `verdict: "pass" | "fail" | "uninformative"` (the existing
`passed: bool` field stays, `passed = (verdict == "pass")`, so downstream
readers don't break) and a `power: dict` detail block.

G1 becomes informativeness-aware: it computes, per entity, whether the
typicality band is reachable given that entity's loo-distance count. If no
entity can reach the flagging band, the observed 0.0% is arithmetic and the
verdict is `uninformative` — rendered as, e.g.:

> G1: UNINFORMATIVE — largest entity has N=12 baseline docs; min conformal
> p = 0.077 > no-action threshold 0.03. Escalation requires N ≥ 199. The
> observed 0/216 flagged rate cannot demonstrate an FPR below 1.4%
> (rule of three) and the band cannot flag at all at this N.

**Exit-code semantics:** `uninformative` does not fail CI by default (a small
corpus is a fact, not a regression) but is printed loudly and counted in the
report summary. A `--strict` flag treats it as failure for runs that intend
to *claim* evidence (e.g. before quoting numbers in a report).

### C3 — Experiment spec (`validation/experiment.py`)

A frozen dataclass serialized into every report JSON:

```python
@dataclass(frozen=True)
class ExperimentSpec:
    task: Literal["verification", "attribution", "drift",
                  "weight_derivation", "calibration_suite"]
    # "calibration_suite" labels the mixed G1–G6 battery, which spans tasks
    # in one run; single-question runners must use the specific label.
    git_sha: str
    seed: int
    env_lock: dict[str, str]          # from reproducibility.lock_environment()
    corpora: dict[str, CorpusSummary] # authors, docs, windows, word-count stats,
                                      # provenance, genre histogram
    windowing: dict                   # length, overlap, floors
    features: dict                    # measurable/excluded counts + statuses hash
    aggregation: dict                 # e.g. tier rule = median, variance floor pct
    thresholds: dict                  # gate bars, band constants
```

The mandatory `task` field is the structural fix for "a verification number
wore an attribution label": a report cannot exist without declaring which
question it answers, and comparisons across specs with different `task`
values are refused by the loader. `diff_specs(a, b)` returns a human-readable
list of every field that differs — the first tool to reach for when two runs
disagree. JSON, not YAML: no new dependency, and every existing report is
already JSON.

Runners changed: `calibration_gate.py`, `derive_measured_weights.py`,
`public_authors/run.py` each build a spec at startup and embed it under a
top-level `"experiment"` key.

### C4 — Corpus manifest v2 (`validation/manifest_schema.py` + loaders)

Schema additions (v2, backward-readable from v1):

- per-document: `word_count`, `genre` (e.g. `philosophy`, `essay`,
  `theology`, `student_essay`), `register` (optional), and per-author/corpus
  `provenance: "real_historical" | "synthetic_ai" | "student_pilot"`.
- corpus-level: `min_window_words` actually used, plus computed
  `conformal_informative: bool` per author (from C2's `band_reachable`
  against that author's doc count).

Balance is checked, not merely recorded: `check_genre_balance()` flags any
single genre exceeding 60% of a derivation corpus's words. The advisory's
lead complaint (21:2 Plato-to-student-prose) currently lives as a
hand-written CAUTION string in `derive_measured_weights.py`'s docstring,
which cannot go stale loudly; the check makes the skew a computed warning
carried in the ExperimentSpec alongside every number derived from it.

Enforcement at load time (extending the existing refuse-to-write stub
guard):

- documents under the task's window floor are rejected or routed to a
  verification-only pool — **policy: short texts are verification-only,
  never attribution candidates**. Floors live in the experiment spec, not as
  code defaults (attribution floor stricter than verification's 300-word
  floor; proposed 500 to start, tunable in one place).
- an attribution run refuses a candidate pool where any candidate author's
  profile is built from < 3 baseline docs (the current 3-baseline split
  becomes an enforced invariant instead of a convention).

### C5 — Alternative attribution engines (`validation/attribution/`)

Three engines over the *same* held-out essays and split (from the
public_authors manifest):

1. **Deviation engine** (existing): impostor-calibrated cross-author
   comparison from the plato branch — unchanged, now labeled engine
   `"deviation_calibrated"`.
2. **Cosine-delta on feature vectors** (`delta.py`): per-candidate centroid
   of the 109-feature vectors restricted to `measurable_codes(corpus)`,
   z-scored across the candidate pool (pool-level scale, which is exactly
   what the raw argmin lacked), nearest-centroid by cosine distance.
   Numpy only.
3. **Classic Burrows' Delta on MFW** (`delta.py`): top-150 most-frequent
   words from the pooled baseline docs, per-author mean z-scored frequency
   profile, mean-|Δz| distance. This is the advisory's "cheap but robust"
   baseline and is deliberately independent of the feature pipeline.

Optional fourth (flagged `--engine sklearn`, off by default): multinomial
logistic regression on measurable features (sklearn is already in the venv).
Not part of the headline table until it has its own gate evidence.

`ensemble.py` computes the agreement matrix and applies the routing rule:
**2-of-3 agree → attributed with named engines; otherwise → "unknown —
manual review"**. The benchmark report shows per-engine top-1/top-2 accuracy,
the ensemble's coverage/accuracy trade-off, and never collapses to a single
forced top-1. All of it runs under `task="attribution"` specs with the C4
floors enforced.

### C6 — Gate falsifiability suite (`tests/test_gate_falsifiability.py`)

The "formal-ish spec" as data plus tests:

```python
GATE_CONTRACTS = {
    "G1": Contract(
        claims="pooled same-author flagged rate <= 5%",
        must_fail_on=lambda: evaluate_g1_fpr(["monitor"] * 20, {...}),
        label_destruction=...,   # how shuffling authorship must change the verdict
    ),
    ...
}
```

Three layers, all over the *pure* `evaluate_*` functions (the
`tests/test_calibration_gate.py` precedent):

1. **Failure witness:** for every gate, a registered input on which the gate
   fails. A meta-test iterates `GATE_CONTRACTS`, asserts every gate exported
   by `calibration_gate` has a contract, and executes every witness. A new
   gate cannot merge without a demonstrated failure mode — pass-by-
   construction becomes unmergeable, not just discouraged.
2. **Label-destruction properties:** where the gate's meaning implies it
   (G2: swapping impostor and holdout distributions must fail; G3: accuracy
   at the 1/n_authors chance level must fail; G4: reversed ordering must
   fail; G5's legs already encode this — the suite pins that behavior).
3. **Hypothesis properties:** invariants over generated inputs — G1 verdict
   monotone in flagged count; conformal p-values always in
   [1/(N+1), 1]; verdict never `pass` when `band_reachable` is false for all
   entities; `evaluate_*` functions total (no crash) on degenerate inputs.

### C7 — Synthetic-author E2E harness (`validation/synthetic/`) — phase 2

Deterministic parametric authors: seeded Zipf vocabulary with per-author
preferred-word tilts, sentence-length mean/variance, punctuation-rate and
function-word profile knobs. Generate K authors × M docs; run the *real*
feature pipeline → StudentState → scoring; assert verification separates
self from other and the C5 engines recover identity; then a corruption
ladder (character noise, the G2b mechanical paraphrase proxy re-used, vocab
topic-shift) yields labeled recovery curves. Perfectly-labeled data sits
between unit tests and real benchmarks. Slow-marked; excluded from the fast
suite; run in the validation CI job or on demand.

## 5. Sequencing & dependencies

- **Phase 0 (prerequisite):** merge `claude/plato-works-dating-analysis-b05b1a`
  into this branch. `git merge-tree` reports zero textual conflicts (the two
  branches overlap only in `original/quantum/scoring.py` and
  `original/store.py`, cleanly); full suite must be green after the merge —
  semantic conflicts (genre-prior work vs typicality wiring in scoring.py)
  are the thing to check, not textual ones.
- **Phase 1:** C1 measurability (unblocks honest aggregation everywhere).
- **Phase 2:** C2 power/verdicts, C3 experiment spec (independent of each
  other; both consumed by every later phase).
- **Phase 3:** C4 corpus v2 (uses C2's reachability; feeds C5's floors).
- **Phase 4:** C5 attribution engines + ensemble benchmark.
- **Phase 5:** C6 falsifiability suite (pins everything above; last so it
  covers the final gate shapes).
- **Phase 6 (optional, separable):** C7 synthetic authors.

Each phase is a small number of focused commits, TDD, full suite green
before moving on. If the session ends early, every completed phase stands
alone.

## 6. Testing

- Every new module ships with unit tests in the fast suite
  (`.venv/bin/python -m pytest tests/ -q`; venv lives at
  `~/Desktop/Original/.venv/`).
- The measurability self-consistency test doubles as a canary: it fails if a
  pipeline change makes a "blank" feature start varying (good news that must
  be acted on, not silently absorbed).
- C6 *is* a test deliverable; it also back-tests G1–G6 as they exist today.
- Corpus-driven runners stay out of the fast suite (existing convention);
  their JSON outputs now carry specs + power blocks, verified by unit tests
  on the report-assembly functions.

## 7. Open decisions for review

1. **Merge direction (Phase 0):** merge plato branch into this branch and
   continue here (recommended), vs. rebasing this work onto that branch.
2. **Attribution window floor:** proposed 500 words to start (spec-level
   config, easily changed). The advisory suggests up to 2,000-word windows —
   defensible for public authors, but it would shrink the seminary corpus to
   near-nothing.
3. **`--strict` default for CI:** default lenient (uninformative ≠ red) as
   designed, or strict from day one for `calibration_gate`?
4. **sklearn engine:** include behind a flag now (designed above) or defer
   entirely to keep C5 numpy-only.
5. **CI coverage for the gate battery:** `.github/workflows/test.yml` runs
   only lint (scoped to `original/`) and the fast pytest suite, so the
   corpus-driven G1–G6 run is manual-only and nothing invokes `--strict`.
   The falsifiability and property tests (C6) *do* run per-push, which is
   what stops a can't-fail gate from merging. Recommendation: leave the
   battery manual rather than spend a 20-minute CI budget on it; add a
   nightly job only if gate drift becomes a real problem.
