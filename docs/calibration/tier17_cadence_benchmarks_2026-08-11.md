# Tier 17 recalibration against published keystroke benchmarks — 2026-08-11

Tier 17 (behavioral biometrics) is in `DISABLED_FEATURE_GROUPS` pending live
keystroke data from Bbook. This pass reconciled its six estimators and their
`NORM_BOUNDS` against the published typing-cadence literature *before* any
baseline is collected — once students have baselines, changing what a feature
means invalidates them.

Nothing here changes production scores: the tier is disabled, and the pipeline
writes the `NORM_BOUNDS` midpoint for every Tier 17 code when it is.

## 1. What the anchors are, and what they are not

The primary reference is Dhakal et al. (2018), 136.9M keystrokes from 168,960
volunteers doing short English sentence transcription
(<https://userinterfaces.aalto.fi/136Mkeystrokes/resources/chi-18-analysis.pdf>):

| Quantity | Value |
|---|---|
| Inter-key interval (IKI) | mean 238.7 ms, SD 111.6 |
| Observed physical floor | ~60 ms |
| Backspace/Delete share of keypresses | 6.31%, SD 4.48 |
| Final uncorrected errors | 1.17%, SD 1.43 |
| Gross speed | 51.6 WPM, SD 20.2 |

Three caveats govern how these are used here:

1. **Transcription is not composition.** Pauses in prose generation mix lexical
   retrieval, planning, rereading, revision and distraction. Pause rates will be
   higher than in copied sentences and are not intrinsically anomalous.
2. **The sample skews young and typing-interested** (mean age 24.5, 75% aged
   11–30). This is a high-coverage modern-keyboard benchmark, not a
   population-standard adult reference interval.
3. **The dispersion figures are between-person.** The 111.6 ms SD describes the
   spread of *participant-average* IKIs across a heterogeneous sample. It is not
   a within-writer variability target, and the 12 ms / 123 ms fast-vs-slow figures
   are likewise between-person dispersion within speed strata.

So these are **guardrails for rejecting instrument artifacts and for sizing
bounds** — not denominators. Per-writer normalisation against the student's own
baseline remains the scoring path.

## 2. Estimator changes

### `typing_speed_cv` — raw CV → interquartile robust CV

Was `stdev/mean` over IKIs. The IKI distribution is strongly right-skewed, so a
plain CV is dominated by whichever planning pauses happen to fall inside the 30 s
cadence window rather than by typing rhythm.

Now `(Q75 − Q25) / (1.349 × median)`. The 1.349 divisor is the normal
IQR-to-sigma factor, which keeps the output on ordinary-CV scale.

**MAD/median was tried first and rejected.** Burst-and-hesitate typing is
strongly bimodal; whenever the split is uneven enough for the median to land on
the fast mode, over half the intervals sit at distance zero from it, MAD reads 0,
and the most diagnostic composition rhythm in the tier scores as perfectly
metronomic. This was not hypothetical — it made `typing_speed_cv` degenerate on
the existing `tier17_report` "composer" fixture and flipped its READY verdict.

Measured properties of the shipped estimator (synthetic composition traces,
lognormal bursts punctuated by ~4 s pauses):

| Trace | Result |
|---|---|
| median IKI 120 / 216 / 480 ms, fluent | 0.469 / 0.467 / 0.466 — speed-invariant across 4× |
| same, halting | 0.629 / 0.626 / 0.620 |
| σ_log 0.25 / 0.50 / 0.75 / 1.00 | 0.251 / 0.507 / 0.774 / 1.072 — recovers σ_log |
| Published moments (lognormal fit, σ_log 0.4446) | 0.451 (vs raw CV 0.468) |

### `burst_ratio` — absolute 150 ms threshold → pause-delimited production bursts

Was "fraction of IKIs under 150 ms". Against a 238.7 ms population mean — fast
typists at 121.7 ms, slow at 481.0 ms — that is a gross-speed proxy: fast typists
saturate near 1.0 and slow typists near 0 regardless of how they phrase.

Now the standard writing-research construct: the fraction of keystrokes produced
inside pause-delimited production bursts of ≥10 keystrokes, where any pause ≥2 s
breaks a burst. Long interruptions are deliberately *kept* for segmentation (an
interruption does end a burst) even though they are excluded from cadence.

Simulated across a 4× speed range:

| | fast (120 ms) | avg (216 ms) | slow (480 ms) |
|---|---|---|---|
| fluent | 0.999 | 0.999 | 0.998 |
| halting | 0.147 | 0.154 | 0.148 |

Speed-invariant, and it separates fluency by ~0.85.

An earlier attempt — run structure relative to the writer's own median — was
rejected: the self-median threshold falls *inside* the fast mode, shredding the
run structure it was meant to measure (bursty 0.274 vs iid null 0.249).

### `deletion_rate` — unit validation

Bbook's precomputed `deletionRate` was passed through as a float with no range
check. Fractional and percentage forms differ by 100× against a 0.20 bound, so a
percentage read as a fraction saturates every sample. Values in `(1, 100]` are
now treated as percentages; anything outside `[0, 100]` returns neutral rather
than a confident wrong number. Exactly `1.0` is ambiguous and is read as a
fraction.

### `pause_density` — 3 s → 2 s, interruptions excluded

3 s was nonstandard; keystroke-logging analysis conventionally uses 1 s or 2 s
(<https://aclanthology.org/W16-4111.pdf>). Now counts pauses in `[2 s, 20 s)`.
Intervals ≥20 s are look-ups, interruptions or task switches, not composition
planning, and are counted nowhere.

Ideally these would be *binned* (1–2 s, 2–5 s, 5–20 s, >20 s) with a separate
long-interruption share, and pause topology (fraction following spaces,
punctuation, backspaces, word-initial keystrokes) is usually more discriminative
and less task-confounded than a single count. Both are deferred: Tier 17 is a
fixed six-feature block inside `BASE_FEATURE_DIM`, so adding features is a
dimension change, not a calibration change.

### Missing data is no longer zero

`pause_density`, `paste_event_rate` and `revision_depth` returned `0.0` when the
instrument gave them nothing. For all three, `0.0` is also a *real reading*
("never pauses", "never pasted", "only single-character corrections"). They now
return the feature's `NORM_BOUNDS` midpoint, which `pipeline._normalise` maps to
exactly 0.5 — the same value the disabled-group path writes.

`paste_event_rate` additionally returned a raw event *count* when no word count
was available — a different unit silently scored on the same scale.

The two cadence features previously returned a bare `0.5` for "too few
keystrokes". Against bounds `(0.0, 1.5)` that normalises to 0.33 — a confident
low reading, not "no measurement".

### Instrumentation hygiene

- A median IKI below the ~60 ms physical floor now returns neutral for cadence:
  that is timestamp quantisation or a clock bug, not fast typing.
- `_iki_deltas` used `ks.get("elapsed") or ks.get("timestamp")`. The first
  keystroke of every session legitimately has `elapsed == 0.0`, which is falsy,
  so the truthiness form either mixed session-relative ms with epoch ms or
  dropped the first real interval outright. The presence check is now explicit.
- `_is_paste()` counted any literal `v` keypress as a paste event. It was dead
  code — `paste_event_rate` reads revision records — and has been removed rather
  than left as a trap for whoever wires up key-level paste detection.

## 3. Bounds

| Feature | Was | Now | Basis |
|---|---|---|---|
| `typing_speed_cv` | (0, 2.0) | (0, 1.5) | **Derived.** Covers σ_log to ~1.4; typical composition 0.47–0.63 |
| `deletion_rate` | (0, 0.5) | (0, 0.20) | **Derived.** 6.31% ± 4.48 → 0.20 is mean+3SD |
| `burst_ratio` | (0, 1.0) | (0, 1.0) | Unchanged; genuinely spans [0, 1] now |
| `pause_density` | (0, 20.0) | (0, 40.0) | **Guardrail.** 2 s admits materially more than 3 s |
| `paste_event_rate` | (0, 5.0) | (0, 5.0) | Unchanged |
| `revision_depth` | (0, 50.0) | (0, 50.0) | Unchanged |

The old `deletion_rate` bound was the most consequential: against a 1.83–10.79%
mean ±1 SD band, `(0, 0.5)` compressed all genuine between-writer variance into
`[0.036, 0.216]` of the normalised range, leaving the feature near-constant
before the density matrix ever saw it.

`pause_density` at 40.0 is explicitly **not** derived — there is no published
composition-pause anchor to derive it from. It is a plausibility ceiling chosen
so that halting composition does not saturate.

## 4. What is still open

- **The bounds are pre-pilot.** Re-run `scripts/tier17_report.py` against real
  proctored keystroke data before the tier leaves `DISABLED_FEATURE_GROUPS`, and
  re-derive the two guardrail bounds from observed distributions. The READY rule
  (≥20 samples, ≥5 students, ≥4 of 6 features non-degenerate) is unchanged.
- **`TOPIC_SENSITIVITY`-style per-feature weighting does not exist for Tier 17.**
  All six features are treated as equally informative.
- **No device/layout stratification.** Gross speed, raw dispersion and deletion
  rate all co-vary with typing skill, hardware and task difficulty. Per-writer
  baselining absorbs some of this; a writer who switches keyboards mid-term will
  not be absorbed.
- **`paste_event_rate` is degenerate on any locked-down corpus** (it should be ~0
  everywhere), and will likely stay one of the two features the readiness rule
  permits to be degenerate.
