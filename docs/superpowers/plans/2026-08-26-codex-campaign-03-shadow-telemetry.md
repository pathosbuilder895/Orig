# Plan 03 — Shadow Telemetry: make the pilot soak turn-key before the pilot exists

> **For agentic workers (Codex):** Goal-oriented brief. Everything here is buildable
> and testable **now**, against synthetic local data; nothing waits on the pilot. The
> one thing Codex cannot do is flip flags on the Render deployment or read its
> Postgres — those are the human steps this plan reduces to a one-page checklist.

**Goal:** When the Postgres cutover (ops item O4) lands and real submissions start
flowing, the entire shadow-evidence program — genre abstention, topic-distance
distribution, characteristic-weight dispersion, fused-score confound regression,
AI-likelihood FPR — is one flag-set change and one report command, with every reader
script already proven against synthetic data.

**Why now:** Five separate mechanisms are blocked on "run shadow first," and each
currently has its own ad-hoc reader (or none). The measured history says the soak is
where mechanisms die: `GENRE_INVARIANT_WEIGHTS_ENABLED` was built, tested, and turned
out to fire on 1-of-6 folds of noise; the Bayesian prior regressed AUC by 0.25 on the
only cold-start segment available. The soak is not a formality — it is the experiment.

**Architecture:** One new aggregator script + small fixes to existing readers; a soak
runbook doc; a latency guard. No scoring behavior changes. Everything reads logs or
the `fused_scores` table; nothing writes to production state.

## Global constraints

Same as Plan 01 (venv path, suite duration, postgres marker tests, coverage margin,
commit style, no pushes to main). Plus:

- **No real student data exists locally and none may be created.** All local testing
  uses synthetic fixtures. Real pilot data is Postgres on Render; no DSN is available
  from this checkout, by design.
- **No PII in any report output.** Existing log lines already omit student ids
  (`bayesian_prior`, `characteristic_weights` INFO lines); every new reader must
  aggregate before printing. Treat this as a hard review gate on your own output.
- **Do not enable score-changing flags to collect telemetry.** Specifically:
  `BAYESIAN_PRIOR_ENABLED` changes scores — its coverage question is answered offline
  by `scripts/measure_genre_prior_scope.py`, never by enabling it.

---

## S1. One aggregator: `scripts/shadow_soak_report.py`

Build a single command that turns a log dump + a DB connection into the complete soak
picture. Interface:

```bash
render logs --tail 200000 > /tmp/pilot.log        # human runs this
.venv/bin/python scripts/shadow_soak_report.py --log /tmp/pilot.log --db "$DATABASE_URL"
```

Sections (each degrades gracefully to "signal absent — flag was not on" rather than a
misleading zero; follow `validation/genre_2026-08/read_shadow_log.py`'s pattern, which
already distinguishes "shadow ran and never abstained" from "shadow was never on"):

1. **Genre resolver v2** — parse `genre_shadow v1=… v2=…` lines: abstention rate,
   label distribution, v1-vs-v2 disagreement matrix. Call
   `validation/genre_2026-08/read_shadow_log.py` as a library if practical rather than
   duplicating its parsing. Surface the sermon question explicitly: rate of
   `scholarly_essay`/`narrative_prose` labels on documents whose v1 label or metadata
   suggests homiletic content, cross-referenced against Plan 02 C6's corpus findings.
2. **Topic distance** — distribution of `topic_distance` from the
   `TOPIC_VARIANCE_INFLATION=shadow` diagnostics: histogram, share above the 0.25
   fire threshold, share of `degraded=True` resolutions. The single decision number:
   **if mass above 0.25 is ~zero, the mechanism is a production no-op regardless of
   G7** — print that sentence when it holds.
3. **Characteristic weights** — parse `characteristic_weights mode=… outcome=…
   dispersion=…` lines: applied-vs-abstain rate, dispersion distribution (this is
   mean(|factor−1|) over **active** features). Print the inertness verdict when
   dispersion is near zero or abstain dominates.
4. **Fused score** — read the `fused_scores` table: row counts, abstain reasons,
   score distribution, and the C1 confound regression (S2's module, imported).
5. **AI likelihood** — delegate to / import `scripts/shadow_report.py`'s logic:
   band distribution, and the go/no-go counters (instructor-confirmed authentic FPR,
   labeled-join count vs the ≥30 bar).
6. **Bayesian prior scope (offline)** — run the coverage measurement
   `scripts/measure_genre_prior_scope.py` provides, against the same DB, reporting
   per-(tenant, genre) pool sizes vs the 5-vector/3-student floors. (The 2026-07-29
   attempt found no genre-labelled data; once the genre shadow has run for a while,
   labels exist — this is the retry it was waiting for.)

Test with committed synthetic fixtures: a fabricated log file and a SQLite/Postgres
fixture DB exercised in `tests/` (postgres-marked variant included). The report must
run green against fixtures on a fresh checkout.

**Acceptance:** one command produces all six sections against fixtures; each section's
"flag was never on" state is visually distinct from "flag on, nothing found"; tests
committed; no student identifier appears in any output path.

## S2. The fused-score C1 confound analysis

The compression channel's distance falls monotonically as the claimed student's
baseline concatenation grows (measured 0.799 at 3 baselines → 0.730 at 48): a genuine
student drifts toward "different author" (or away — direction matters, verify it)
purely by accumulating baselines. `fused_scores` rows persist `baseline_samples` and
`reference_profiles` precisely so this can be regressed out. Build the analysis now,
run it on synthetic data now, run it on real rows when they exist:

1. `validation/fusion_confound/analyze.py`: regression of the peer-centered
   compression channel (and the fused score) on `baseline_samples`, controlling for
   `reference_profiles`; report slope, CI, and the score shift implied across the
   realistic 3→30 baseline range vs the `threshold_fa5`/`threshold_fa1` gaps.
2. Propose (in the report, not in code yet) the normalization fix candidates and what
   each would do to the artifact: cap the baseline concatenation at a fixed byte
   budget; use mean per-baseline-doc distance instead of concatenated distance; or add
   `baseline_samples` as a fusion input and refit. Note that any of these obsoletes
   the shipped thresholds and means a `train_fused_score.py` refit + new artifact.
3. Synthetic validation: generate profiles with 3→48 baselines from committed PD
   corpora, confirm the analysis recovers the known 0.799→0.730 shape.

**Acceptance:** analysis module + tests committed; synthetic run reproduces the known
drift; a written recommendation exists; **`FUSED_SCORE_ENABLED` stays 0** — the
CLAUDE.md row already says enablement waits on this analysis *against real rows*.

## S3. The soak's own cost: latency guard for `CHARACTERISTIC_WEIGHTS=shadow`

Any non-`off` value makes `students_scoring.py` build the impostor pool via
`_repo().all_states()` — a full state scan on **every** scoring request, including on
`NULL_MODEL=none` deployments that never scanned before. Before the soak playbook
tells an operator to turn it on:

1. Measure it: benchmark `/students/{id}/score` latency at realistic state counts
   (50, 500, 5000 profiles) with the flag `off` vs `shadow`, on both SQLite and
   Postgres backends (the postgres path is the one production runs).
2. If the delta at pilot scale (~hundreds of students) is material (>100 ms p50 or
   >2× p95 — judge against the measured baseline), add a cheap mitigation: a
   time-bounded cache of impostor stats per tenant (invalidated on baseline writes,
   mirroring `_GENRE_STATS_CACHE`'s bust-on-put pattern in `store.py`), applied to the
   shadow path only. Do not change `on`-mode semantics.
3. Either way, print the measured numbers into the runbook (S4) so the operator knows
   what they're buying.

**Acceptance:** committed benchmark numbers; mitigation landed or a measured
justification for skipping it; runbook carries the figure.

## S4. The soak runbook: `docs/SHADOW_SOAK_RUNBOOK.md`

One page a human operator executes the day the pilot DB exists. Contents:

- **Flag set for the soak**, exact env lines:
  `GENRE_RESOLVER_V2=shadow`, `TOPIC_VARIANCE_INFLATION=shadow`,
  `CHARACTERISTIC_WEIGHTS=shadow`, `FUSED_SCORE_SHADOW=1`, `AI_LIKELIHOOD_SHADOW=1`
  (all inert w.r.t. scores and actions — cite the byte-identical tests for each), and
  the explicit **do-not-set** list: `BAYESIAN_PRIOR_ENABLED`, `FUSED_SCORE_ENABLED`,
  `TOPIC_VARIANCE_INFLATION=on`, `LLR_ACTION_MODE=blend`.
- Read cadence: weekly `shadow_soak_report.py` run; what each section's decision
  number is and the threshold at which it triggers a decision (topic mass above 0.25;
  dispersion ≈ 0; abstention rate vs the 50% G8 ceiling; sermon-mislabel sightings).
- Exit criteria per mechanism: what evidence ends its soak, and where the verdict gets
  recorded (CLAUDE.md flag row + MODEL_CARD).
- The teardown: `CHARACTERISTIC_WEIGHTS` back to `off` when its soak ends (the scan
  cost is real); which flags stay on indefinitely (fused shadow persistence is cheap
  and builds the C1 dataset).
- Pointer to the two commands that need Postgres and are otherwise ready today:
  `scripts/tier17_report.py --db "$DATABASE_URL"` (Tier-17 readiness) and the
  drift-gate re-check against real uploads.

**Acceptance:** doc committed; every command in it has been executed against fixtures
in this checkout (put the transcript in the PR description, not the doc).

## S5. Window-level AI shadow: document the calibration boundary

`AI_LIKELIHOOD_SHADOW=1` also attaches per-window probabilities on the blend endpoint.
No window-level calibration exists — the detector was trained and thresholded on whole
documents; a 300-token window is outside its evaluated regime, and every blend window
is already labeled `confidence="low"` (300 < the 500-token reliability floor). Add one
paragraph to MODEL_CARD.md's AI-likelihood section and to the runbook: per-window
values are **ordering hints for human review within a document**, never comparable to
the document-level bands, never aggregable across documents. If any consumer surfaces
them today, verify it respects that (grep `ai_window_max` / `ai_probability` consumers;
the report says nothing reads them back — confirm and cite the test).

**Acceptance:** MODEL_CARD paragraph committed; consumer grep documented in the PR.

---

## Human-only steps this plan deliberately leaves behind

(Referenced here so nobody assigns them to an agent; details in the overview's ops
track.) Provision pilot Postgres (O4) and run the cutover; set the soak flag set on
Render; run `render logs` dumps on the cadence; make the enablement decisions the
reports recommend. The DPA (O6) gates all of it — no real student data flows anywhere
before it is signed.
