# WS-1 — Security & data-integrity hotfixes

> Part of the [Master Implementation Plan](../AUDIT_2026-07-06.md) (Audit §9). Refs are a 2026-07-07 snapshot — resolve each cited `path:line` by its **named symbol** via [ANCHORS.md](ANCHORS.md); the tree is under active edit and line numbers drift.
> **Findings:** B10, A1, B16, F3 (MAINTENANCE_TOKEN/GUARD_DESTRUCTIVE doc subset) · **Effort:** 1–2 days · **Depends on:** — · **Unblocks:** WS-2 (pip-audit gate has a clean baseline to enforce), WS-6 (a store that surfaces write failures is a precondition for the Postgres repository seam).

## Objective
Close the four items that can silently lose FERPA-protected data or ship a known-CVE'd auth dependency, with no change to scoring output. "Done" means: the pilot deploy can no longer install a vulnerable `python-jose`, a failed SQLite write reaches the API caller instead of vanishing, `python run.py --demo` cannot pollute or clear a persistent pilot DB, and the two undocumented privileged env vars (`MAINTENANCE_TOKEN`, `GUARD_DESTRUCTIVE`) are fully described in the ops runbook. All four are independently shippable; none touch `original/quantum/`.

## Prerequisites & dependencies
- Working `.venv` (`.venv/bin/python`, `.venv/bin/pytest`) per CLAUDE.md. `.venv` is Python 3.9.6 today (B7, WS-2) — irrelevant to these edits but note "passes locally" is on 3.9 until WS-2 rebuilds it.
- No other WS output required. WS-1/2/3 run in parallel.
- **Shared-finding boundary:** F3 is split. WS-1 owns *only* the `MAINTENANCE_TOKEN` + `GUARD_DESTRUCTIVE` runbook documentation (the operational, security-relevant subset). The rest of F3 — the scoring-affecting flags (`LENGTH_ADAPTIVE_WEIGHTS`, `RANK_REMEDIATION`), the CLAUDE.md flag-table expansion, `ORIGINAL_ENV`/`ENVIRONMENT` merge, and the AI-likelihood flags — belongs to **WS-3** (trust surface). Do not document scoring flags here.
- B16's stale-banner sub-item (`run.py:162–165`) overlaps F5's banner note; WS-1 owns the fix (one edit site).

## Tasks

### 1. python-jose pin — B10
- **Current state:** `requirements-pilot.txt:17` pins `python-jose[cryptography]>=3.3,<4.0` — the file `render.yaml:57` installs on the real pilot. `requirements.txt:11–13` already documents PYSEC-2024-232/233 (algorithm confusion + JWT decode bypass, fixed 3.4.0) and pins `>=3.4.0`. `python-jose` verifies Canvas LTI id_tokens in `original/lti.py`. The `<3.4` range is reachable via a stale wheel cache or resolver backtrack even though pip picks ≥3.4 today.
- **Change:** one line.
  - before: `python-jose[cryptography]>=3.3,<4.0`
  - after: `python-jose[cryptography]>=3.4.0,<4.0`
  Keep the existing two comment lines above it (they explain the jose/cryptography split).
- **Files touched:** `requirements-pilot.txt`.
- **Verify:** `.venv/bin/pip install -r requirements-pilot.txt` resolves; then `pip-audit -r requirements-pilot.txt` reports no PYSEC-2024-232/233 (this becomes the permanent gate in WS-2 §4). Grep guard: `grep python-jose requirements*.txt` shows both files at `>=3.4.0`.

### 2. store.py — stop swallowing write/load failures — A1
- **Current state:** `original/store.py:485–494` `_persist` wraps the upsert in `except Exception: pass` ("Non-fatal — data is still live in memory"); `_load_all` (`store.py:470–482`) does the same ("Fresh DB or filesystem error — start empty"). (Audit cited `_persist` 485-495 / `_load_all` 470-483; actual is 485-494 / 470-482.) `_persist` has exactly one caller, `put()` (`store.py:511–515`), which does `_STORE[...] = state` *before* `_persist(state)` — so on failure, memory and disk diverge and today nobody is told. There is **no** existing 503 mapping for a persistence failure (the two `503`s in `api.py` are the guard-token check at `:327` and the Bbook path at `:1478`); the audit's "API can return 503" is net-new wiring, not a reconnect.
- **Change:**
  - `_persist`: re-raise `sqlite3.Error` after logging. Add a module logger (`log = logging.getLogger(__name__)`) if absent. Do **not** broaden to bare `Exception`; a serialization bug should still crash loudly, only I/O-class `sqlite3.Error` is the "surface it" path.
    ```python
    # before (store.py:487-494)
    try:
        with _get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO student_profiles ...", (...))
    except Exception:
        pass  # Non-fatal — data is still live in memory
    # after
    try:
        with _get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO student_profiles ...", (...))
    except sqlite3.Error as e:
        log.error("persist failed for student %s: %s", state.student_id, e)
        raise
    ```
  - `_load_all`: distinguish the two cases the current comment conflates. A missing DB file (first boot) is normal → start empty. An *existing but unreadable/corrupt* DB must fail startup. `_DB_PATH` is defined `store.py:41`.
    ```python
    # after (store.py:475-482)
    db_missing = not _DB_PATH.exists()
    try:
        with _get_conn() as conn:
            for row in conn.execute("SELECT student_id, data FROM student_profiles"):
                _STORE[_deserialize(row[1]).student_id] = _deserialize(row[1])
    except sqlite3.Error as e:
        if db_missing:
            pass          # first boot — no DB yet, start empty
        else:
            log.error("profile DB exists but is unreadable: %s", e)
            raise         # corrupt/locked DB must fail startup, not present as empty
    ```
  - API seam: at the write endpoints that call `store.put(...)` (the baseline-ingest and `score_submission` persistence paths), let the now-raising `sqlite3.Error` map to `HTTPException(503, "storage temporarily unavailable")`. Prefer one small wrapper or a narrow `try/except sqlite3.Error` at the call sites over a global handler, so the 503 is scoped to writes and reads stay unaffected.
- **Files touched:** `original/store.py` (`_persist`, `_load_all`, logger); `original/api.py` (503 mapping at the `store.put` write sites).
- **Verify:** new test in `tests/test_store_persistence.py` — monkeypatch `store._get_conn` (or the connection's `execute`) to raise `sqlite3.OperationalError("disk I/O error")`, assert `store.put(state)` raises (not silently returns), and assert an ERROR record is emitted (`caplog`). Second test: point `ORIGINAL_DB` at a non-DB junk file, assert `_load_all()` raises rather than yielding an empty `_STORE`. Full suite stays green: `.venv/bin/python -m pytest tests/ -q` (0 failed).

### 3. run.py — port default + seed-by-default footgun + stale banner — B16
- **Current state:**
  - `run.py:113` `--port` defaults to **8000**; CLAUDE.md, `start.sh`, Playwright, and CI all assume **8001**. CI already passes `--port 8001` explicitly with `--skip-seed` and `ORIGINAL_ENV=pilot`, so the default only bites humans running the documented bare command.
  - `run.py:157–158`: `if not args.skip_seed: seed_demo_store()` — seeding is **on by default** under `--demo`. `seed_demo_store()` (`run.py:52–73`) hard-refuses only when `ORIGINAL_ENV in (pilot, staging, production)` (`:59–65`), then calls `store.clear()` (`:70`) and `seed(verbose=True)`. Note: `store.clear()` (`store.py:537`) clears the **in-memory cache only, not SQLite** — but the subsequent `seed()` writes synthetic students that persist via `put()→_persist()`, so a dev with `ORIGINAL_DB` pointed at a valuable local file who runs the documented `python run.py --demo` **pollutes/overwrites** it (audit said "wipe"; precise mechanism is pollution-via-reseed, and the on-disk rows the synthetic ids collide with are overwritten). A `--seed` flag already exists as a deprecated no-op (`run.py:129–133`, `:169–172`).
  - `run.py:163–164` banner prints `original.html` / `original-review.html`, which existed only in the dead `frontend/` tree (removed 2026-07-07, ADR-006), not `demo/`.
- **Change:**
  - Port: `run.py:113` `default=8000` → `default=8001`.
  - Seeding: invert the default so `--demo` alone does **not** clear/reseed a store that already has rows. Repurpose the deprecated `--seed` (`run.py:130`) into the real opt-in. Keep the existing `ORIGINAL_ENV` hard-refusal in `seed_demo_store()` untouched (belt-and-suspenders). Drop the now-obsolete `--seed`-is-a-no-op notice at `:169–172`.
    ```python
    # before (run.py:157-158)
    if not args.skip_seed:
        seed_demo_store()
    # after — explicit --seed, or auto-seed ONLY an empty store (keeps zero-config sales demo)
    if args.seed:
        seed_demo_store()
    elif not args.skip_seed:
        from original import store
        if store.count() == 0:
            print("WARNING: empty store, auto-seeding synthetic demo data. "
                  "Pass --seed to silence, --skip-seed to disable.")
            seed_demo_store()
        else:
            print(f"Store has {store.count()} profiles; not reseeding "
                  "(pass --seed to force, which CLEARS synthetic data first).")
    ```
  - Banner: `run.py:163–164` → advertise pages that actually exist in `demo/` (`professor.html` — the `/` redirect target at `run.py:88` — and `/bluebook/`), or drop the two stale lines. Keep the `Health:` line.
- **Files touched:** `run.py`.
- **Verify:** `python run.py --demo` (no `--seed`) against an `ORIGINAL_DB` containing a known student → that student still present afterward (store not cleared/overwritten); `--help` shows `--port` default 8001; `grep -n "8000" run.py` returns nothing in the arg default; banner lines resolve to files under `demo/`. CI is unaffected (already explicit `--port 8001 --skip-seed`).

### 4. Document MAINTENANCE_TOKEN + GUARD_DESTRUCTIVE — F3 (subset)
- **Current state:** `docs/OPS_RUNBOOK.md:22` has a single table row for `MAINTENANCE_TOKEN` describing only its `X-Guard-Token` role. **`GUARD_DESTRUCTIVE` is not documented anywhere in the runbook** (the only "maintenance" hit is the `## Routine maintenance` heading at `:78`). Two real semantics are undocumented:
  1. **Destructive-endpoint guard** — `GUARD_DESTRUCTIVE=1` (`api.py:305`) makes `_require_guard` (`api.py:313–337`) require an `X-Guard-Token` header equal to `MAINTENANCE_TOKEN` on the guarded endpoints (student deletion, tenant writes, calibration-threshold apply, baseline-request list, admin corrections — call sites at `api.py:937, 982, 1062, 1548, 2596`). If `GUARD_DESTRUCTIVE=1` but the token is empty, those endpoints return **503** (`api.py:325–332`).
  2. **Admin-granting login backdoor** — the *same* `MAINTENANCE_TOKEN` (`api.py:2642`), when presented as the password to `POST /api/v1/auth/login` (`demo_login`, `api.py:2657`), grants the **admin** role and writes a WARNING audit log (`_audit_maintenance_access`, `api.py:2645`). This path 404s on real deploys (`_IS_REAL_DEPLOY`, `api.py:114`, checked at `:2674`), so on the pilot the token's *only* live effect is guard #1 — but an operator reading the runbook has no way to know the value doubles as a break-glass admin password in demo/dev.
- **Change:** in `docs/OPS_RUNBOOK.md` expand the `MAINTENANCE_TOKEN` coverage and add `GUARD_DESTRUCTIVE`:
  - State that `MAINTENANCE_TOKEN` + `GUARD_DESTRUCTIVE=1` together are what protect destructive endpoints in pilot; list the guarded operations; note the empty-token 503.
  - Note the demo-only admin-login backdoor use of the same value and that it is 404'd on real deploys (so operators understand *why* the value is sensitive and must live only in the Render env, never in code or a demo config).
  - Rotation: env-var change + restart (no code deploy); rotating logs no one out (unlike `SECRET_KEY`).
  - Action item: **rotate the pilot's `MAINTENANCE_TOKEN` if it predates this documentation** (per §9.4) — it may have been set before its dual role was understood.
- **Files touched:** `docs/OPS_RUNBOOK.md`.
- **Verify:** `grep -n "GUARD_DESTRUCTIVE" docs/OPS_RUNBOOK.md` returns the new coverage; runbook names both semantics of `MAINTENANCE_TOKEN`. Doc-only; no test.

## Acceptance criteria
- [ ] `pip-audit -r requirements-pilot.txt` is clean for python-jose (no PYSEC-2024-232/233); both requirements files pin `>=3.4.0` (B10).
- [ ] An injected `sqlite3.Error` on write makes `store.put()` raise and log ERROR; the API returns 503 for that write instead of a silent success (A1).
- [ ] `_load_all` fails startup on an existing-but-unreadable DB and starts empty only when the DB file is genuinely absent (A1).
- [ ] `python run.py --demo` against an existing non-seed `ORIGINAL_DB` cannot clear or reseed it; `--port` default is 8001; banner advertises only pages that exist under `demo/` (B16).
- [ ] `docs/OPS_RUNBOOK.md` documents both `MAINTENANCE_TOKEN` semantics and `GUARD_DESTRUCTIVE`; pilot token rotated if it predates the doc (F3 subset).
- [ ] `.venv/bin/python -m pytest tests/ -q` → 0 failed (5 rate-limit tests XFAIL/XPASS as usual).

## Risks & watch-outs
- **Byte-identical invariant:** untouched. None of these edits enter `original/quantum/` or the flag-gated scoring branches; flags-OFF output is unchanged. The A1 API seam only converts a swallowed write failure into a 503 — it never alters a *successful* score's bytes.
- **memory/disk divergence (A1):** `put()` mutates `_STORE` *before* `_persist`. Re-raising from `_persist` means the caller sees 503 while the in-memory cache already holds the new state — acceptable (single-worker process; next restart reloads from disk), but do not "roll back" the `_STORE` write in a way that could mask a partial success. Document the 503 as "not persisted; retry."
- **Secondary swallowers (A1 scope creep — note only):** many `put_*` writers (`put_manifest` `store.py:544`, `put_fidelity_score` `:781`, `put_ai_likelihood_score` `:854`, correction/threshold/bluebook writers) have their own best-effort `try/except`. The §9.2 fix is deliberately scoped to the **core `_persist`/`_load_all`** (baseline + score persistence). Broadening to audit-log writers is out of scope for WS-1 — flag for WS-6, do not expand here.
- **Seed-default change is behavior-visible:** the sales `original-demo` service relies on zero-config seeding. The "auto-seed only when the store is empty, with a warning" compromise keeps that UX; verify the free demo still boots seeded before shipping. Do not remove the `ORIGINAL_ENV` hard-refusal — it is the last line of defense.
- **Do not restart the pilot to rotate the token without operator sign-off** (CLAUDE.md: server restarts require explicit permission). Runbook should state rotation is a scheduled action.

## Sequencing within the workstream
1. **B10** (§1) — one line, zero risk, unblocks the WS-2 pip-audit gate. Ship first, standalone.
2. **F3 doc** (§4) — doc-only, no code risk; can land in parallel with B10. Token rotation is an ops action tracked separately.
3. **B16** (§3) — port + seed + banner in `run.py`; standalone, but verify the free demo still seeds when empty.
4. **A1** (§2) — the only multi-file change (store + api). Land last so the persistence-failure test and the 503 seam ride on an otherwise-green tree. Independently shippable but highest blast radius; keep it its own commit.
