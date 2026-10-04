# ADR-010: Keystroke capture is macro-only

Status: Accepted — decided with the user 2026-09-20

## Context

Bluebook's exam client (`demo/bluebook/Exam.jsx`) captures raw per-key
timing — an array of `{key, elapsed_ms}` entries, capped at 8000 — plus
pause gaps, and POSTs the whole blob as `keystroke_data` with
`provenance: 'proctored'`. The backend stores that blob verbatim at rest
inside the `student_profiles.data` JSON document (`store.py:693`,
`postgres_repository.py:157`); `docs/data_inventory.md` does not list it and
no retention rule runs. The blob was collected to seed Tier 17 (behavioural
biometrics), but Tier 17 is in `DISABLED_FEATURE_GROUPS` and its six vector
dimensions are neutral 0.5 placeholders — the raw keystrokes reach no score
today (`docs/TIER17_ENABLEMENT_RUNBOOK.md` documents an enablement ritual
that has never run).

The programme brief is explicit: no keystroke biometrics or invasive
surveillance; text-level and *macro* timing only; FERPA and pedagogy first.
Storing per-key timing that nothing scores is pure liability — a biometric
identifier retained without inventory, disclosure, or purpose.

## Decision

Capture and retain **macro** composition timing only, never per-key data.

- Bluebook emits a `composition_summary` object (`session_seconds`,
  `word_count`, `paste_attempts`, `focus_losses`, `revision_count`,
  `started_at`, `ended_at`, `exam_config`) instead of the per-key
  `keystrokes`/`pauses` arrays. The shape is frozen in the threat-model spec
  §5.3.
- The server accepts `composition_summary` on `AddSampleRequest` /
  `ScoreSubmissionRequest`, stops persisting raw `keystroke_data` arrays on
  ingest (the field is accepted-but-stripped for one release for backward
  compatibility, then removed), and a one-off `scripts/purge_keystroke_blobs.py`
  redacts `keystrokes`/`pauses` from existing stored profiles (dry-run
  default, SQLite and Postgres).
- `resolve_composition_mode` (`context/resolvers.py:538-566`) is rewired to
  read `composition_summary` with an **unchanged output vocabulary**
  (`natural_drafted | tool_cleaned | structured`, `edit_signature`,
  `software_mediated`).
- `docs/TIER17_ENABLEMENT_RUNBOOK.md` is retired and the data inventory and
  student-disclosure docs are corrected to match reality.

Tier 17 is **not** removed from the feature vector. `ALL_FEATURE_CODES`
ordering is frozen (removing the tier would renumber every downstream
vector); its six dimensions stay as 0.5 placeholders exactly as today. Only
the *collection and storage* of the raw signal that would have fed them is
withdrawn.

## Consequences

- No keystroke biometrics are collected or stored. The macro summary carries
  the same information `resolve_composition_mode` actually used (paste
  presence, edit heaviness) without per-key timing, so the resolver's output
  is unchanged.
- `resolve_composition_mode` feeds the context manifest, which affects the
  score under `CONTEXT_MANIFEST_ENABLED`. The rewiring is therefore the one
  score-touching change in this sub-project and must be proven byte-identical
  on the flag-on path (a TermSim `baseline`-cell diff) before it ships, held
  to the same standard as any flag-off byte-identity requirement.
- `composition_summary` is a JSON-document additive field: no SQLite
  migration and no Alembic migration, only coordinated `_serialize` /
  `_deserialize` edits (finding B of the programme plan).
- The purge is one-way. Existing per-key data is destroyed, not archived —
  that is the intended FERPA-minimising outcome, but it means any future
  Tier 17 work would start collection afresh under its own consent and
  disclosure design.
- Gap-register row T-74 tracks the storage-and-purge obligation.
