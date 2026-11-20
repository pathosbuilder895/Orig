# ADR-014: Versioned measurements

Status: proposed (PR stacked on #354 → #353). Nothing is switched on.

## Context

`FEATURE_SET=2` (reworked hedging, modal, confident-statement and linking-word
habits, `original/features/lexicon_v2.py`) and `MATTER_SPLITTER_ENABLED=1`
(front/back matter set aside, `original/features/matter.py`) change what is
measured. A past paper's `vector` is measured once, when the paper is added,
and the score compares a freshly measured paper with those stored vectors.
Turning either switch on by itself would compare a paper measured one way
with past papers measured another way.

## Decision

1. **Named measurements.** `features/feature_flags.MEASUREMENTS`:
   `v1` (default: feature set 1, no splitter), `fs2`, `matter`, `fs2+matter`.
   `requested_measurement()` reads the two switches; `measuring(id)` (a
   ContextVar) forces one for a block, overriding the environment, and
   propagates into the scoring thread pools (`context/pipeline.py`,
   `context/resolvers.py` submit through `contextvars.copy_context().run`).
2. **Storage.** `BaselineSample.vector` is always `v1`. Upload routes measure it
   inside `measuring("v1")` whatever the switches say. Other measurements live
   in `BaselineSample.extra_vectors: {id: vector}`, stored in the student
   document as `"extra_vectors"` **only when non-empty** (read back with
   `.get()`), so documents without them are byte-identical to before, on
   SQLite (`store._serialize`) and Postgres (`PostgresRepository._state_to_doc`).
   A vector of the wrong length is dropped on read (that paper counts as not
   measured that way). A swapped "view" state can never be persisted
   (`store._refuse_measurement_view`).
3. **Filling them.** `scripts/backfill_measurements.py` (dry run by default;
   `--apply --confirm <id>` to write; idempotent; one student at a time;
   re-reads each student before writing and skips one whose papers changed;
   never touches `vector`). Optionally `UPLOAD_ALSO_MEASURE=<id>` stores the
   extra measurement on new uploads (one extra extraction per upload, run
   after the first; off by default because of the 512 MB pilot instance).
4. **Like with like.** `original/measurement.plan_for(state)`: the requested
   measurement is used only when **every** past paper of the student has it;
   otherwise `v1` for both the new paper and the past papers. The score route
   (`/students/{id}/score`, and `/score/blend`) runs in its own context with
   `set_measurement(plan.used)`, so the new paper, the evidence pages'
   re-reading of past papers and any peer texts are all measured the same way.
   Peer pools use only peers whose every paper has the measurement
   (`states_measured_as`).
5. **Stamp.** When anything but `v1` was requested, the score response carries
   `measurement: {requested, used, past_papers, past_papers_measured,
   fallback?}` and the staff evidence carries the same under
   `evidence.measurement`; the evidence page states it in plain words. When
   only `v1` was requested the field is left out of the JSON entirely
   (`exclude_if`), so default responses are byte-identical; **absent means
   `v1`**. The OpenAPI schema gains the optional field (additive).

## Seam for other engines (e.g. a future `original/consistency`)

- `original.measurement.measurement_of(score_or_dict) -> str`: the
  measurement a returned or stored score used; `"v1"` when unstamped.
- `original.measurement.vector_for(sample, id) -> ndarray | None`: a past
  paper's vector for a measurement; `None` when not measured that way.
- Compare two results, or a result with a baseline, only when their
  measurement ids agree. Run any fresh extraction inside
  `features.feature_flags.measuring(id)`.

## Consequences

- Off by default; `FEATURE_SET`, `MATTER_SPLITTER_ENABLED`, `UPLOAD_ALSO_MEASURE`
  are in `FLAG_OFF_VALUES` and the API/unit snapshots are unchanged.
- Scores under `fs2+matter` are a different scale; thresholds were calibrated
  on `v1`. Recalibration is required before any switch is turned on for live use.
- Not versioned yet (documented gaps): stored past-score fidelities read by
  `AMPLITUDE_SCORING_ENABLED`, the alpha batch scripts under `scripts/alpha/`,
  and `/admin` playground scoring (which measures both sides fresh, so it is
  consistent but unstamped).
