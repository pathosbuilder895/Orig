# 03 — API, persistence, and migration tests

Scope: `original/api.py`, `original/routers/*` (12 routers, spliced at root
with no prefixes), `original/store.py` (SQLite), `original/postgres_repository.py`,
`original/repository.py` (`Repository` protocol + `ShadowRepository`),
`original/db/models/live.py`, `alembic/`, `scripts/migrate_sqlite_to_pg.py`.

What is strong here: the 2,504-line repository contract suite runs every
public method on both backends and is Hypothesis-backed for the density-matrix
round trip; the Bluebook seal-race tests force the idempotency lookup to miss
and assert the `IntegrityError` recovery path; `test_migration.py` derives its
expected table set from `LiveBase.metadata` so a new table without a migrator
fails loudly. Reuse these patterns.

What is missing: Alembic entirely, migration-vs-model drift, value-level shadow
divergence, and the lockset boot path (§08 owns that one).

---

## 1. Alembic (zero tests today)

The four-revision chain (`20128da16c79 → 3f695550f43e → 7c4d1e88a3b5 →
9f2c7a1b4d63`) has `downgrade()` bodies that have never been executed by a
test. Every test and `postgres_session.init_live_schema()` build the schema
with `create_all`, so the chain can silently disagree with the models.

New file `tests/test_alembic.py`, all `@pytest.mark.postgres` (Alembic on
SQLite hides DDL differences that matter on Postgres):

| Test | Assertion |
|---|---|
| `test_upgrade_head_matches_models` | fresh DB → `alembic upgrade head` → `alembic.autogenerate.compare_metadata(ctx, LiveBase.metadata)` returns `[]` |
| `test_round_trip_upgrade_downgrade_upgrade` | `upgrade head`, `downgrade base`, `upgrade head`; table set and column set identical to the first upgrade |
| `test_single_head` | `ScriptDirectory.get_heads()` has length 1 — catches a merge that forks the chain |
| `test_every_revision_downgrades_one_step` | walk head→base one revision at a time; no step raises |
| `test_migrated_schema_accepts_contract_suite` | run a representative slice of `test_repository_contract.py` against a DB built by `upgrade head` instead of `create_all` — proves the two schemas are interchangeable for real traffic |

Use a per-test database (`CREATE DATABASE` from a maintenance connection, drop
on teardown) so Alembic's own `alembic_version` table does not collide with the
contract suite's truncate-everything fixture. The contract suite already knows
the reverse-dependency table order; import it, do not copy it.

Also record the deploy fact: Alembic runs only under `deploy/legacy-v1/`
(dormant). `render.yaml` and `start.sh` for the live pilot never invoke it. A
test cannot fix that, but `08-config-deploy-readiness.md` §4 adds a check that
whatever provisions the pilot schema is the same thing this test exercises.

## 2. Repository contract suite — extend, do not fork

Keep the public-interface-only rule. Add these behaviours as new classes in
the same file, parametrised over `BACKENDS`:

- **Tenant-scoped listing under adversarial ids.** Ids containing `%`, `_`,
  `:`, and unicode; a student in tenant A named to collide lexically with
  tenant B's prefix. The SQLite LIKE-escaping test exists in
  `test_store_tenants.py`; it must hold on Postgres too, and the contract suite
  is where that is proved.
- **Delete completeness.** `delete_student` must leave zero rows referencing
  the student in *every* table that carries a student key. Derive the table
  list from `LiveBase.metadata` by walking foreign keys and column names, the
  way `test_migration.py` derives its table set. The architecture review found
  four tables missed (`bluebook_submissions`, `baseline_requests`,
  `bluebook_sessions`, `formation_pathways`); this test fails until they are
  covered and cannot go stale when a fifth table is added.
- **Audit-log immutability.** No public method can update or delete an audit
  row except the FERPA purge, and the purge writes its own terminal row.
- **Cache coherence across instances.** Two `PostgresRepository` instances
  over the same DB: a write through one is visible through the other on the
  next read. This is the multi-worker scenario §07 §4 cares about; today the
  instance-scoped `_genre_stats_cache` makes it fail, which is the point.

## 3. ShadowRepository — value-level divergence

Today the shadow wrapper logs `REPO_SHADOW divergence` only when the shadow
write *raises*. Add an opt-in read-comparison mode for the cutover window:

```python
def test_shadow_read_compare_flags_value_drift(shadow_repo, primary, shadow):
    primary.add_baseline(sid, sample_a)
    shadow.add_baseline(sid, sample_b)          # deliberately different
    with caplog.at_level("WARNING"):
        shadow_repo.get(sid)
    assert "REPO_SHADOW value-divergence" in caplog.text
```

If the product decision is *not* to compare values, keep this as a documented
non-goal in the shadow tests (the negative-space pattern from
`test_email_notification_noop.py`) so the next reader does not assume it does.

## 4. Router tests — from arm coverage to behaviour

Routers are 98.8 % branch-covered. The remaining work is behavioural and lives
mostly in `04-security-adversarial.md`. Two non-security items belong here:

**4.1 Response-shape contract.** `test_openapi_stability.py` proves the schema
is deterministic, not that it is unchanged. Add a committed snapshot
`tests/snapshots/openapi.json` and a test that diffs `app.openapi()` against it
with `sort_keys=True`. A change is allowed but must be *deliberate*: the test
message says "run `scripts/update_openapi_snapshot.py` and review the diff".
Pair it with the TypeScript client generator already in `app/package.json`
(`gen:client`) so the frontend's types cannot drift from the backend silently.
**Implemented** (T-34): `tests/snapshots/openapi.json`, `tests/test_openapi_snapshot.py`,
`scripts/update_openapi_snapshot.py`, and `make openapi-snapshot` now exist as
described above.

**4.2 Error-envelope consistency.** Every non-2xx from every route returns
`{"detail": ...}` and never a stack trace or a raw SQL string. Route-table
driven, like `test_no_admin_route_answers_a_student_principal`: iterate
`app.routes`, send a malformed body to each POST/PUT, assert 4xx with the
envelope. Catches the raw-`sqlite3.OperationalError` leak class.

## 5. Persistence error arms — keep, but make them backend-honest

`test_persistence_error_arms.py` (1,428 lines) forces SQLAlchemy and sqlite3
failures. The coverage effort found its Postgres arms once tested reachability
rather than schema existence because an earlier test's `drop_all` teardown ran
first. The fix centralised `create_all` in the availability helper. Lock that
in: a test that runs *last* alphabetically (`tests/test_zz_schema_present.py`)
and asserts every live table exists on the Postgres service — a canary for
teardown-ordering regressions.

## 6. Data-integrity invariants worth one test each

| Invariant | Where it would break |
|---|---|
| A submission's `text_hash` is persisted, not derived on read | the `upload_baseline_batch` dedup bug the coverage effort fixed; pin it |
| `sample_count` on `/readiness` equals `len(baseline_samples)` after any sequence of add/delete | drift between the counter and the rows |
| Calibration-run timestamps are microsecond-resolution on both backends | the SQLite whole-second bug, fixed; pin it |
| `submission_uuid` partial unique index exists after `upgrade head` | Alembic must carry the index the seal-race tests depend on |
| Legacy 74/89/102-wide vectors are padded to `FEATURE_DIM` on load and a warning is emitted exactly once per profile | the padding contract in CLAUDE.md |

## 7. Migration script (`scripts/migrate_sqlite_to_pg.py`)

Already well tested. Two additions: a test that the migration refuses to run
when `REPO_BACKEND` on the target already reports `postgres` (guard against
double-migrating a live pilot), and one that the checksum parity check is
order-invariant for every composite-PK table, not just the one currently
asserted.

## 8. Acceptance for this slice

- `tests/test_alembic.py` passes on the Postgres service; `compare_metadata`
  returns empty.
- Delete-completeness test is red until the four tables are handled, then
  green.
- OpenAPI snapshot committed; CI fails on undeclared schema change.
- Cross-instance cache-coherence test exists and its status (red/green) is
  recorded in `10-gap-register.md`.
