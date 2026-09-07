# Consent Records and Retention Enforcement — Design

**Date:** 2026-08-17 · **Status:** specified · **Posture:** authorization records live; retention sweep shadow-only (user-selected)

## Problem

Two gaps, related by the same governance documents.

**No record of the legal basis.** Original is positioned as FERPA-compliant and
`docs/dpa_template.md` implements the school-official framework, but nothing in the
data model records that any institution ever executed that agreement. `grep -rni
"consent" original/` returns nothing. The authorization exists as a PDF in someone's
filing cabinet and as prose in a template; the running system cannot answer "under
whose authorization are we processing this tenant's student work?"

**Retention is written but not computed.** `docs/data_inventory.md` §1 states
retention periods for every data category, and §10.1 writes out the deletion order
step by step — then marks the whole section **"Planned — not implemented in the pilot
stack (no retention scheduler runs)."** Every period in that document is a policy
target with no code behind it. `store.delete_student()` (`original/store.py:1634`) is
real and does the work; what is missing is anything that decides *when*.

## Enabling facts

- `store.delete_student()` already purges profiles, fidelity scores, AI-likelihood
  rows, fused scores, manifests, and corrections. The deletion primitive exists and is
  tested; this design adds a trigger, not an eraser.
- `backup.py` establishes the in-app scheduler idiom: an `asyncio.create_task` started
  from the API lifespan (`original/api.py:104,166-168`) on an env-configured interval.
  A retention sweep has a home that needs no new infrastructure and no Celery/Redis.
- `GUARD_DESTRUCTIVE` + `MAINTENANCE_TOKEN` already gate high-risk endpoints
  (`original/api.py:395`), so an admin-facing retention surface inherits an existing
  authorization mechanism.
- The repository-contract suite (`tests/test_repository_contract.py`) parametrizes
  SQLite and Postgres, so new tables get both backends tested by construction.

## Framing decision — this is not student consent

FERPA's school-official exception makes the **institution** the authorizing party. The
student is not the consenting party and has no opt-out from a required course's
integrity tooling. `docs/STUDENT_DISCLOSURE.md` is written correctly against this: it
is a notice document, and the rights it enumerates are inspection, correction, and
deletion-via-registrar — the last explicitly flagged as "beyond what FERPA requires —
it is this institution's commitment, not a FERPA right." It never asks the student to
agree to anything.

A literal student-consent gate would therefore be **worse than absent**. It implies an
opt-out that does not exist, and forces a branch with no good arm: a decline either
blocks required coursework or is recorded and ignored. The second is consent theater
and reads badly in exactly the audit this feature exists to survive.

So the model records two different things, with different subjects and different
weight:

| Record | Subject | What it is | Legal weight |
|---|---|---|---|
| `tenant_authorizations` | Institution | A DPA / school-official designation was executed | **The basis for processing** |
| `disclosure_acknowledgments` | Student | This student was shown disclosure version X on date Y | Evidentiary only — proof of notice |

## §1 — Data model

Two tables, following `store.py`'s `CREATE TABLE IF NOT EXISTS` idiom and its
convention of ISO-8601 `TEXT` timestamps.

### 1.1 `tenant_authorizations`

```sql
CREATE TABLE IF NOT EXISTS tenant_authorizations (
    id             TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL,
    document_type  TEXT NOT NULL,   -- 'dpa' | 'school_official_designation'
    document_version TEXT NOT NULL, -- e.g. 'dpa_template.md@2026-07-07'
    executed_at    TEXT NOT NULL,   -- when the institution signed (out-of-band)
    officer_name   TEXT NOT NULL DEFAULT '',
    officer_title  TEXT NOT NULL DEFAULT '',
    recorded_by    TEXT NOT NULL DEFAULT '',  -- operator user id who entered it
    recorded_at    TEXT NOT NULL,
    notes          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tenant_auth ON tenant_authorizations(tenant_id, executed_at);
```

This records an **out-of-band legal event**, entered by an operator. Deliberately not
a click-through: nobody executes a data-processing agreement by clicking a checkbox in
a student-facing tool, and modelling it that way would misrepresent what happened.

`executed_at` and `recorded_at` are distinct on purpose — the signature date and the
data-entry date are different facts, and conflating them destroys the audit trail.

Multiple rows per tenant are expected and allowed: agreements get renewed, and the
history is the point. "Current authorization" is the row with the greatest
`executed_at`, computed at read time; no `is_current` column to drift.

### 1.2 `disclosure_acknowledgments`

```sql
CREATE TABLE IF NOT EXISTS disclosure_acknowledgments (
    id                 TEXT PRIMARY KEY,
    student_id         TEXT NOT NULL,
    tenant_id          TEXT NOT NULL,
    disclosure_version TEXT NOT NULL,
    acknowledged_at    TEXT NOT NULL,
    context            TEXT NOT NULL   -- 'bluebook_briefing' | 'lti_launch' | 'manual'
);
CREATE INDEX IF NOT EXISTS idx_disclosure_student
    ON disclosure_acknowledgments(student_id, acknowledged_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_disclosure_unique
    ON disclosure_acknowledgments(student_id, disclosure_version);
```

`student_id` is the existing opaque tenant-scoped code — this table adds no new PII.

**No `declined` column, deliberately.** Per the framing decision this is proof of
notice, not a gate. A decline field would invite a later contributor to build
enforcement on a basis that does not hold, which is the specific failure this design
is shaped to prevent.

One row per (student, disclosure_version), enforced by the UNIQUE index above rather
than by write-path convention — re-acknowledging the same version is an upsert that
leaves the original `acknowledged_at` intact, since the first notice is the one with
evidentiary value.

## §2 — Retention computation

New module `original/retention.py`. Pure functions over repository data, no scheduler
dependency, so the date arithmetic is testable in isolation.

### 2.1 Deriving last activity

`student_profiles` has **no timestamp column** — it is `(student_id TEXT PRIMARY KEY,
data TEXT NOT NULL)` and nothing more. Last activity must therefore be derived:

```
last_activity(student) = MAX(
    max(BaselineSample.submitted_at for samples in state),   # may be ""
    MAX(submission_manifests.created_at)  WHERE student_id = ?,
    MAX(fidelity_scores.created_at)       WHERE student_id = ?,
    student_names.updated_at,
)
```

### 2.2 The undated rule — load-bearing

`BaselineSample.submitted_at` defaults to `""` (`original/quantum/state.py:49`). A
student whose baselines were ingested without dates and who has no manifests or
fidelity rows has **no derivable activity date at all**.

The naive implementation coerces missing to epoch and therefore deletes exactly the
oldest, most-established, least-recoverable records first — the worst possible failure
ordering, executed silently.

**Rule: a student with no derivable date is `undated` and is NEVER eligible.** They are
reported as a separate count requiring human resolution. This is asserted by a
dedicated test (§6) rather than left as an implementation detail, because it is the
one rule whose violation is unrecoverable.

### 2.3 Categories and periods

Taken verbatim from `data_inventory.md` §1 — this design implements the written
schedule and does not invent one:

| Category | Period | Measured from |
|---|---|---|
| PII (display name) | 1 year | last activity |
| Submissions / manifests | 1 year | row `created_at` |
| Baselines | duration + 1 year | last activity |
| Results (fidelity, AI, fused) | 1 year | row `created_at` |
| Audit log | 2 years | row `created_at` |

`STUDENT_DISCLOSURE.md` promises students "enrollment plus one academic year, unless
your institution sets a shorter period." The per-tenant shorter-period override is
**out of scope here** and noted as deferred (§8) — the sweep computes against the
1-year default only, and the report states which period it used so a shorter
institutional policy is visible as a discrepancy rather than silently unmet.

## §3 — Sweeper wiring

`asyncio.create_task` from the API lifespan, mirroring `backup.py`.

| Flag | Default | Effect |
|---|---|---|
| `RETENTION_SWEEP_ENABLED` | `0` | Runs the sweep; logs one INFO summary plus per-category counts. **Deletes nothing.** |
| `RETENTION_SWEEP_INTERVAL_HOURS` | `24` | Sweep cadence |

Log line shape (no student ids):

```
retention_sweep tenant=<t> eligible_pii=<n> eligible_submissions=<n> \
  eligible_results=<n> eligible_audit=<n> undated=<n> period_days=365
```

**There is no enforcement flag in this change — not even a disabled one.** The code
that calls `store.delete_student()` from a sweep does not exist. A flag that cannot be
flipped is safer than a flag that can be flipped by mistake, and enforcement should be
a separate reviewed change made against real soak data.

Flag-off is byte-identical: the task is not created, the module is not imported.

## §4 — API and CLI surface

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/admin/retention/candidates` | GET | admin; `X-Guard-Token` when `GUARD_DESTRUCTIVE=1` | Read-only candidate report incl. `undated` count |
| `/admin/tenants/{id}/authorization` | POST | admin | Record a DPA execution |
| `/admin/tenants/{id}/authorization` | GET | admin | Current + historical authorizations |
| `/students/{id}/disclosure-ack` | POST | student or staff | Record notice |
| `/students/{id}/disclosure-ack` | GET | student or staff | Acknowledgment history |

`GET /admin/retention/candidates` is read-only but sits behind the destructive guard
anyway: it enumerates which students are closest to deletion, which is exactly the
reconnaissance an attacker would want.

`original.cli.delete_student` is extended to purge both new tables, so FERPA deletion
stays complete. `store.student_data_inventory()` gains both record types, so a
"what do you hold on me?" request returns them.

## §5 — Documentation changes

- `data_inventory.md` §10.1: "Planned — not implemented" → "computed and reported, not
  enforcing", with the undated caveat stated plainly. The gap between policy and
  reality should be visible in the document, not resolved by optimistic wording.
- `data_inventory.md` §1: note that periods are now *computed* but still not
  *enforced*.
- `CLAUDE.md`: two new env flags in the flag table, matching the existing style
  (default, effect, and what a shadow soak is meant to measure).
- A new §on authorization records in `data_inventory.md`, since they are themselves
  data held about the institution.

## §6 — Test plan

| Area | Tests |
|---|---|
| Date arithmetic | Boundary at exactly 365 days (eligible vs not); mixed sources where the max comes from each of the four in turn; future-dated rows treated as recent, never as stale |
| **Undated rule** | A student with `submitted_at=""`, no manifests, no fidelity rows is **never** returned as eligible and **is** counted as `undated`. Asserted directly. |
| Both tables | Repository-contract tests across SQLite and Postgres (suite already parametrizes both) |
| Idempotence | Re-acknowledging the same disclosure version does not duplicate |
| Authorization history | Multiple rows per tenant; "current" = greatest `executed_at`, not insertion order |
| Deletion completeness | `delete_student` purges both new tables; `student_data_inventory` reports them |
| Flag-off | Sweep task not created, module not imported, output byte-identical |
| Guard | `/admin/retention/candidates` rejects without the guard token when `GUARD_DESTRUCTIVE=1` |

## §7 — Scope boundary

The `disclosure_ack` write is cheap; nothing currently *shows* students the
disclosure. Bluebook's briefing screen would need a line of copy and an ack call for
the record to carry meaning.

That frontend work is **deliberately excluded** from this change. Including it pulls in
a `bluebook.bundle.js` rebuild and the Playwright e2e specs, which triples the review
surface for a text change. This change lands the backend plus the manual and LTI ack
paths; the briefing-screen call is a follow-up.

Consequence, stated honestly: until that follow-up ships, `disclosure_acknowledgments`
will be sparse or empty in production. It is a capability, not yet a practice.

## Open questions deferred to evidence

- **Per-tenant retention override.** `STUDENT_DISCLOSURE.md` promises institutions may
  set shorter periods. Deferred until a tenant actually asks; the sweep reports the
  period it used so the gap is visible meanwhile.
- **Enforcement.** Whether the sweep ever deletes automatically is a separate decision
  requiring real soak data. The undated count is the number that decides it: a
  meaningful `undated` population means the date coverage is too poor to enforce
  against at all.
- **Audit-log retention (2 years).** Purging the audit log is in the written policy but
  interacts with the deletion audit trail — deleting the record of a deletion. Reported
  by the sweep, deliberately not actioned.
- **Polarity.** Decided 2026-08-17: `deviation_score` stays 0–1 internally (high =
  deviant) and inverts to a 0–100 consistency score at the presentation edge. No
  retention or authorization surface exposes a score, so this design is unaffected —
  recorded here because the decision was made in the same session.
