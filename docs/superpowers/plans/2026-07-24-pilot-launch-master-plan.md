# Pilot Launch Master Plan (code waves + operational track)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. **Dispatch rule: a task may run concurrently with
> another ONLY if they are in the same wave (waves are built from file-disjointness — see the
> dependency graph). Each concurrent task gets its own git worktree/clone and its own branch,
> and lands as its own PR.**

**Goal:** Take Original from code-complete-but-undeployed to a running, monitored,
Canvas-integrated pilot with hardened tests, keyboard-accessible exams, a maintainable router
layout, and Bluebook's phone-deterrence layer — with maximum safe parallelism across subagents.

**Architecture:** Three tracks. (1) An **operational track** (human + assistant, not subagent
work): deploy → monitor → pre-launch Postgres cutover → Canvas → provisioning. (2) **Code wave
1**: five file-disjoint tasks that can all dispatch simultaneously. (3) **Code waves 2–3**:
tasks serialized only where they contend on `original/api.py` (the router split owns it
exclusively) or on the committed `demo/bluebook/bluebook.bundle.js` build artifact (any two
frontend tasks conflict on it).

**Tech Stack:** FastAPI + SQLite/Postgres repository seam, React (esbuild bundle, committed),
pytest (+ `postgres:16` CI service container), ruff, Render (blueprint deploy).

## Global Constraints

Copied from CLAUDE.md / CI — binding on every task:

- Python: always `.venv/bin/python` and `.venv/bin/pytest` — never system python3.
- Full-suite command (CI-exact): `.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q` — a clean run is **0 failed**; treat any failure as real.
- Lint gates (CI runs both, on `original/` scope): `ruff check original/` AND `ruff format --check original/`. `tests/` has pre-existing lint debt outside CI scope — do not run `ruff --fix` across `tests/`; fix only lines you author.
- After editing any `demo/bluebook/*.jsx`: `cd demo/bluebook && npm run build` and **commit the regenerated `bluebook.bundle.js`** (Render has no Node).
- Never reorder `ALL_FEATURE_CODES` in `original/constants.py`; any change to feature ordering or `NORM_BOUNDS` requires explicit human permission.
- Deleting files: use `git rm`, never bare `rm`.
- Never run `git add -A` in a clone containing a virtualenv; add files explicitly.
- Commit style: `Fix ...`/`Add ...`/`Refactor ...`, co-author line `Co-Authored-By: Claude <model name> <noreply@anthropic.com>`.
- Default behavior (SQLite, all flags off) must remain byte-identical unless the task says otherwise; `requirements-pilot.txt` environments must stay sqlalchemy-free on the default path (`import original.api` must not pull sqlalchemy).
- Feature dimensionality: `FEATURE_DIM = 109`, 97 active by default; Tier 17 (6 behavioral features) and Tier 18 (6 uniformity features) are both in `DISABLED_FEATURE_GROUPS` — tasks below collect/report Tier 17 data but MUST NOT enable the group.

---

## Dependency graph (what runs when)

```
OPERATIONAL TRACK (human-gated, runs alongside ALL code waves)
  O1 deploy → O2 canvas email ─────────────────────────────→ O7 LTI bind → O8 sandbox verify
  O1 → O3 monitoring                                              ↑ (admin reply, days–weeks)
  O1 → O4 postgres + cutover (pre-launch) → O5 restore drill
  O6 DPA signature ──────────────────────────────────────────→ O9 real students (hard gate)

CODE WAVE 1 — all five dispatch IN PARALLEL (file-disjoint)
  T1 flag-matrix scoring tests      (creates tests/test_flag_matrix.py only)
  T2 Bluebook CRUD API tests        (creates tests/test_bluebook_crud.py only)
  T3 db/core v1 pruning             (original/db/*, original/core/*, pyproject.toml)
  T4 docs bundle                    (docs/* only: proctor script, disclosure, release tags)
  T5 Tier 17 shadow report script   (creates scripts/tier17_report.py + its test)

CODE WAVE 2 — starts after T1+T2 MERGE (their tests are the split's safety net);
              the two lanes below are mutually disjoint and run IN PARALLEL
  T6 WS-7.3 router split            (owns original/api.py + new original/routers/ EXCLUSIVELY)
  T7 WS-4 keyboard accessibility    (owns demo/bluebook/*.jsx + bundle EXCLUSIVELY)

CODE WAVE 3 — after T6 merges (backend) and T7 merges (frontend/bundle)
  T8 QR phone-park backend          (new original/routers/proctor.py + store table; needs T6's layout)
  T9 QR phone-park frontend         (bluebook JSX + parked page + bundle; needs T7 merged to avoid
                                     bundle conflict, and T8's endpoints)  [T8 → T9 serialized]
```

**Why these edges (contention analysis, not vibes):**
- `original/api.py` is one 3,265-line file with 64 `@app.` endpoints and zero `APIRouter` usage. T6 rewrites all of it. Nothing else may touch `api.py` while T6 is in flight — T1/T2/T5 only *read* it; T8 waits for the new layout so its endpoints land as a router, not as more `api.py` growth.
- `demo/bluebook/bluebook.bundle.js` is a committed build artifact — two branches that both rebuild it always conflict. So all Bluebook-frontend tasks (T7, T9) serialize with each other, but T7 is disjoint from T6 and runs alongside it.
- T1+T2 before T6 is a safety edge, not a file edge: the router split is a mass mechanical move, and the CRUD/flag-matrix tests are precisely the net that catches a dropped route or a broken flag path.
- The operational track shares no files with any code task — it runs whenever you have minutes, and O2 (Canvas email) is the schedule's long pole: send it the day O1 completes.

---

## OPERATIONAL TRACK (not subagent work — human + assistant checklist)

- [ ] **O1. Deploy** — Render dashboard: delete the failed Docker-runtime service → New → Blueprint → repo `pathosbuilder895/Orig`, branch `main` → paste `SECRET_KEY`, `MAINTENANCE_TOKEN`, `LTI_PRIVATE_KEY` from `~/Desktop/Original-secrets/render-env-sheet.txt` (leave `LTI_PLATFORMS`, `DATABASE_URL`, `REPO_*`, `MAINTENANCE_MODE` unset) → Apply. Then verify with `python -m scripts.o1_golive_check --base-url https://original-pilot.onrender.com --expect-kid 7939c6c8a6f9a736 --expect-commit <deployed-sha>`, which asserts all of: `/health` returns `ok`/`pilot`/`sqlite`; `/lti/jwks` non-empty with that kid; the anonymous lockdown spot-checks from `docs/PROVISIONING_CHECKLIST.md` §4; HSTS present and CORS closed. **Not** `scripts/pilot_smoke_test.py` — that one asserts `backend == "postgres"` and fails by design until O4. Secrets were rotated 2026-08-07; the kid above is the current key's, and the old `b4c53c942c470222` is retired.
- [ ] **O2. Canvas ask — same day as O1** — send `~/Desktop/Original-secrets/canvas-admin-email.md` + `docs/canvas_developer_key.md` (as PDF) + `docs/dpa_template.md`. Need back: Client ID + Deployment ID.
- [ ] **O3. Monitoring** — UptimeRobot/BetterStack on `https://original-pilot.onrender.com/health`, 1–5 min, alert → your email.
- [ ] **O4. Pre-launch Postgres cutover** — New → Postgres (smallest tier, same region) → set `DATABASE_URL` → `render ssh original-pilot -- python -m alembic upgrade head` → brief `REPO_SHADOW=postgres` exercise → flip `REPO_BACKEND=postgres` → `python -m scripts.pilot_smoke_test --base-url https://original-pilot.onrender.com` must print PASS. (Full ceremony in `docs/OPS_RUNBOOK.md`; with zero users, no freeze window is needed.)
- [ ] **O5. Restore drill** — one `pg_dump` → restore to scratch → boot against it. Log in `docs/PILOT_LOG.md`.
- [ ] **O6. DPA signed** — hard gate before any real student data.
- [ ] **O7. LTI bind** — on admin reply: fill `~/Desktop/Original-secrets/LTI_PLATFORMS.template.json`, paste as `LTI_PLATFORMS`, redeploy.
- [ ] **O8. Sandbox-course verification** — the 5 checks in `docs/CANVAS_RUNBOOK.md` §3 before any professor.
- [ ] **O9. Tenant + professors** — `docs/PROVISIONING_CHECKLIST.md` §1–4 (guarded curls), watch-them-login ritual, then real students only after O6+O8.

---

## CODE WAVE 1 (dispatch T1–T5 in parallel, one worktree + branch + PR each)

### Task T1: Flag-matrix scoring tests

**Files:**
- Create: `tests/test_flag_matrix.py`
- Test: itself (`.venv/bin/python -m pytest tests/test_flag_matrix.py -v`)

**Interfaces:**
- Consumes: `original.store` (put/get), `original.quantum.state.StudentState`/`BaselineSample`, `original.quantum.scoring.score`, `original.constants.FEATURE_DIM`. No production file changes.
- Produces: the pilot-flag regression net later tasks (esp. T6) rely on.

**Why:** the pilot runs `CONTEXT_MANIFEST_ENABLED=1 ADAPTIVE_WEIGHTS_ENABLED=1 NULL_MODEL=impostor`, but no test proves score behavior across flag combinations (WS-5's named gap).

- [ ] **Step 1: Write the failing/parametrized test file**

```python
"""Flag-matrix regression: scoring must be stable and sane under every
pilot-relevant env-flag combination. Guards the WS-5 gap: the pilot runs
with flags ON, but the suite only exercised defaults."""
from __future__ import annotations

import itertools

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState

FLAGS = ["CONTEXT_MANIFEST_ENABLED", "ADAPTIVE_WEIGHTS_ENABLED", "AMPLITUDE_SCORING_ENABLED"]
MATRIX = list(itertools.product("01", repeat=len(FLAGS)))  # 8 combos
NULLS = ["none", "impostor"]


def _student(seed: int = 7, n: int = 6) -> StudentState:
    rng = np.random.default_rng(seed)
    st = StudentState(student_id="matrix:stu")
    base = rng.random(FEATURE_DIM)
    for i in range(n):
        vec = np.clip(base + rng.normal(0, 0.02, FEATURE_DIM), 0, 1)
        st.add_sample(BaselineSample(text=f"baseline {i}", vector=vec,
                                     provenance="instructor_verified", auth_weight=1.0))
    return st


def _score(monkeypatch, combo, null):
    for flag, val in zip(FLAGS, combo):
        monkeypatch.setenv(flag, val)
    monkeypatch.setenv("NULL_MODEL", null)
    # scoring reads flags at call time via ScoringConfig.from_env()
    from original.quantum.scoring import ScoringConfig, score
    st = _student()
    probe = np.clip(st.baseline_mean + 0.01, 0, 1)
    return score(st, probe, text="a probe submission", config=ScoringConfig.from_env())


@pytest.mark.parametrize("combo", MATRIX, ids=["".join(c) for c in MATRIX])
@pytest.mark.parametrize("null", NULLS)
def test_every_combo_scores_in_range_with_action(monkeypatch, combo, null):
    out = _score(monkeypatch, combo, null)
    assert 0.0 <= out.deviation_score <= 1.0
    assert out.recommendation.action in {
        "no_action", "monitor", "schedule_conversation", "escalate"}


def test_default_flags_match_all_off_exactly(monkeypatch):
    """Flags unset must behave byte-identically to explicitly '0' (Phase-1 guarantee)."""
    for f in FLAGS + ["NULL_MODEL"]:
        monkeypatch.delenv(f, raising=False)
    from original.quantum.scoring import ScoringConfig, score
    st = _student()
    probe = np.clip(st.baseline_mean + 0.01, 0, 1)
    unset = score(st, probe, text="a probe submission", config=ScoringConfig.from_env())
    explicit = _score(monkeypatch, ("0", "0", "0"), "none")
    assert unset.deviation_score == pytest.approx(explicit.deviation_score, abs=1e-12)


def test_null_model_is_attach_only(monkeypatch):
    """NULL_MODEL=impostor may attach llr_deviation_score but must never
    change deviation_score or the action (documented attach-only contract)."""
    off = _score(monkeypatch, ("1", "1", "0"), "none")
    on = _score(monkeypatch, ("1", "1", "0"), "impostor")
    assert on.deviation_score == pytest.approx(off.deviation_score, abs=1e-12)
    assert on.recommendation.action == off.recommendation.action
```

- [ ] **Step 2: Run, expect import/signature failures first** — `.venv/bin/python -m pytest tests/test_flag_matrix.py -x -q`. Adapt ONLY the test to the real signatures (`score()`'s true parameters, the real output attribute names — check `original/quantum/scoring.py` and `original/schemas.py`); production code must not change. If a combo genuinely fails (not a test bug), STOP and report BLOCKED with the failing combo — that is a real pilot bug, not something to paper over.
- [ ] **Step 3: All 19 tests green** — `.venv/bin/python -m pytest tests/test_flag_matrix.py -v` → 19 passed (8×2 matrix + 2 + 1).
- [ ] **Step 4: Full suite** — CI-exact command, 0 failed.
- [ ] **Step 5: Commit** — `git add tests/test_flag_matrix.py && git commit -m "Add flag-matrix scoring regression tests (WS-5 gap)"`.

### Task T2: Bluebook CRUD API tests

**Files:**
- Create: `tests/test_bluebook_crud.py`
- Test: itself

**Interfaces:**
- Consumes: `live_client`/`store_reset` fixtures from `tests/conftest.py`; the `/bb/*` endpoints in `original/api.py` (read-only — find the exact paths with `grep -n '@app\.\(get\|post\|put\|delete\)("/bb' original/api.py`).
- Produces: the endpoint-inventory safety net T6 (router split) relies on to prove no route was dropped.

**Why:** WS-5's second named gap; also the direct protection for the router split.

- [ ] **Step 1: Inventory the Bluebook surface** — run the grep above; enumerate every `/bb/...` route and method into a module-level `EXPECTED_ROUTES` list in the test file.
- [ ] **Step 2: Write the tests** — for each of: examinations, courses, students-roster, results (the four Bluebook nouns): create → list → get → update → delete via `live_client` with a professor principal (mint via `/auth/register` + `/auth/login` exactly as `tests/test_staff_auth.py` does — copy its `provision` pattern, tenant `bbcrud`), asserting status codes, tenant scoping (a second tenant's professor gets 403/404 on the first's objects), and unauthenticated 401s. Plus one route-inventory test:

```python
def test_bluebook_route_inventory_is_complete(live_app):
    """Every /bb route present — the router-split (T6) safety net. If this
    fails after a refactor, a route was dropped or renamed."""
    live = {(r.path, m) for r in live_app.routes for m in (r.methods or ())}
    for path, method in EXPECTED_ROUTES:
        assert (path, method) in live, f"missing {method} {path}"
```

- [ ] **Step 3: Run to green** — `.venv/bin/python -m pytest tests/test_bluebook_crud.py -v`; adapt tests to real request/response shapes (read the handlers), never the handlers to the tests. Report any genuine 500 as BLOCKED with the traceback.
- [ ] **Step 4: Full suite, 0 failed. Commit** — `git add tests/test_bluebook_crud.py && git commit -m "Add Bluebook CRUD + route-inventory tests (WS-5 gap)"`.

### Task T3: Prune v1 leftovers from original/db + original/core; bring both into lint scope

**Files:**
- Delete (git rm): `original/db/base.py`, `original/db/session.py`, v1 model modules in `original/db/models/` (`baseline.py`, `canvas.py`, `course.py`, `institution.py`, `student.py`, `submission.py`, `user.py` — verify list with `ls`), `original/core/config.py` (verify no live importer first — see step 1).
- Modify: `original/db/models/__init__.py` (drop v1 re-exports), `pyproject.toml` (remove `original/db`, `original/core` from ruff `extend-exclude`), any test that imports the deleted modules.
- Test: full suite.

**Interfaces:**
- Consumes: nothing from other tasks. Produces: a fully-linted `original/` tree.

**Why:** the named WS-6 follow-up: these dirs mix live modules (`db/models/live.py`, `db/postgres_session.py`, `db/tenancy_shim.py`, `core/logging.py`) with dormant v1 leftovers excluded from lint.

- [ ] **Step 1: Verify each candidate is import-dead** — `grep -rn "from original.core.config\|from original.db.base\|from original.db.session\|from original.db.models import" original/ tests/ scripts/ run.py alembic/ --include="*.py"` . Anything still imported by LIVE code stays and gets reported. (Known: `alembic/env.py` must keep working — it uses `LiveBase` only; `tests/test_db_models.py` may import v1 models — update or delete those tests accordingly.)
- [ ] **Step 2: `git rm` the dead modules; fix `db/models/__init__.py`** to export only live names.
- [ ] **Step 3: Un-exclude in pyproject; fix what lint finds** — `ruff check original/db original/core` then `ruff format` those dirs. Fix violations in LIVE files properly (no blanket noqa).
- [ ] **Step 4: Verify** — full suite 0 failed; `ruff check original/` + `ruff format --check original/` clean; sqlalchemy-free check: create a venv from `requirements-pilot.txt`, `python -c "import sys, original.api; assert 'sqlalchemy' not in sys.modules"`; `alembic upgrade head` against a scratch Postgres (docker `postgres:16-alpine`) still works.
- [ ] **Step 5: Commit** — `Refactor: prune v1 leftovers from db/ and core/, bring both into lint scope`.

### Task T4: Docs bundle — proctor script, disclosure update, release-tag convention

**Files:**
- Create: `docs/PROCTOR_SCRIPT.md`
- Modify: `docs/STUDENT_DISCLOSURE.md` (add phone-park beacon paragraph), `docs/OPS_RUNBOOK.md` (add release-tag convention under "Deploys")
- Test: none (docs); `python -c "import pathlib; [pathlib.Path(p).read_text() for p in [...]]"` sanity only.

**Interfaces:** none — pure docs. Content requirements (write these, not placeholders):
- `PROCTOR_SCRIPT.md`: a one-page, read-aloud-able script: before (seat map note, phones face-down + QR park ritual once T9 ships — write the ritual now, marked "(available from Bluebook vX)", laptop on exam page), during (what the proctor tile colors mean: parked=green / dropped=amber → walk over; one warning per event; never accuse from a tile alone — tiles are signals, the authorship analysis is the evidence), after (collect submissions confirmation, note incidents in PILOT_LOG).
- `STUDENT_DISCLOSURE.md` addition: one paragraph, same plain-language register as the existing text: during proctored examinations students may be asked to scan a QR code that opens a "parked" page on their phone; the page reports only presence (foreground/heartbeat), collects no content, no location, no identifiers beyond the exam session, and is discarded after the session.
- `OPS_RUNBOOK.md` deploys section: tag each production deploy `pilot-YYYY-MM-DD` (`git tag pilot-2026-07-24 <sha> && git push origin --tags`); the tag is what "roll back to last Friday" resolves to.

- [ ] **Step 1: Write all three.** **Step 2: Self-check** each against its named register (proctor: imperative, non-technical; disclosure: plain-language, no jargon). **Step 3: Commit** — `Add proctor script; document phone-park disclosure + release-tag convention`.

### Task T5: Tier 17 shadow report script

**Files:**
- Create: `scripts/tier17_report.py`, `tests/test_tier17_report.py`
- Modify: nothing in the pipeline. **MUST NOT touch `original/constants.py`.**

**Interfaces:**
- Consumes: stored proctored samples' `keystroke_data` (see how `demo/bluebook/Exam.jsx` `buildKeystrokeData()` shapes it and how the baseline endpoint persists it — grep `keystroke_data` in `original/`).
- Produces: `python -m scripts.tier17_report [--db PATH]` → per-student and cohort table: sample count with keystroke data, distributions (p10/p50/p90) of the six behavioral inputs (typing_speed_cv, burst_ratio, deletion_rate, pause_density, paste_event_rate, revision_depth), and a `READY/NOT READY` verdict per the rule: ≥20 proctored samples across ≥5 students with non-degenerate distributions (p10 ≠ p90 for at least 4 of 6 features).

**Why:** the phone-cheating detection layer is Tier 17; it stays disabled until live pilot data validates the distributions. This script is the validation gate — during the pilot's shadow weeks you run it weekly, and its READY verdict is the trigger for the (separate, human-approved) enable decision.

- [ ] **Step 1: TDD the report core** — test feeds a synthetic store (via `original.store` put of StudentStates whose samples carry keystroke_data fixtures: one "composer" profile with pauses+revisions, one "transcriber" profile with long pauses + clean bursts + zero deletions) and asserts the table math and the READY rule on both a ready and a not-ready corpus.
- [ ] **Step 2: Implement; run script against the demo seed DB** (expect NOT READY — no keystroke data in synthetic seeds; that's the correct output, print it, don't fake it).
- [ ] **Step 3: Full suite 0 failed; ruff clean on the new files. Commit** — `Add Tier 17 shadow-readiness report script`.

---

## CODE WAVE 2 (dispatch T6 and T7 in parallel — disjoint; both AFTER T1+T2 merge)

### Task T6: WS-7.3 router split (EXCLUSIVE owner of original/api.py)

**Files:**
- Create: `original/routers/__init__.py`, and one module per domain: `original/routers/{health,auth,students,scoring,tenants,bluebook,lti_routes,admin,lab}.py` (final grouping from the inventory in step 1; aim 6–9 routers, none over ~600 lines)
- Modify: `original/api.py` (shrinks to: app construction, middleware, lifespan, shared helpers, `include_router` calls), `pyproject.toml` (per-file-ignores: move `original/api.py`'s E501/E402 entries to the routers that inherit the long professor-narrative strings, if any)
- Test: the whole existing suite IS the test — plus T2's route-inventory test as the explicit net.

**Interfaces:**
- Consumes: T2's `test_bluebook_route_inventory_is_complete` (merged before this starts).
- Produces: `original/routers/` layout that T8 adds `proctor.py` to; `original.api.app` unchanged as the import surface (`run.load_legacy_demo_app()` and every test keep working untouched).

**Method — mechanical, verbatim, no improvements:**
- [ ] **Step 1: Inventory** — `grep -n "^@app\." original/api.py` (64 endpoints). Write the grouping table (route → target router) into the PR description. Snapshot the route set before touching anything: `.venv/bin/python -c "import original.api as a; print(sorted((r.path, tuple(sorted(r.methods or ()))) for r in a.app.routes))" > /tmp/routes_before.txt`.
- [ ] **Step 2: One router at a time** — create `original/routers/<name>.py` with `router = APIRouter()`; MOVE each handler verbatim (decorator `@app.get` → `@router.get`, path unchanged); move only the imports that handler needs; in `api.py` add `from original.routers import <name>` + `app.include_router(<name>.router)`. Shared helpers (`_repo()`, principal deps, `_login_attempts`, rate-limit state) STAY in `api.py` (or move to `original/routers/_shared.py` if importing from `api` would be circular) — routers import them; behavior identical. **No handler body edits. No renames. No "while I'm here."**
- [ ] **Step 3: After EACH router move** — routes diff empty (`routes_after` vs `routes_before`), full suite 0 failed, then commit that router (`Refactor: extract <name> router (no behavior change)`). Nine small commits, each independently revertible.
- [ ] **Step 4: Final** — `api.py` under ~700 lines; suite 0 failed; `ruff check`/`format --check original/` clean; boot check `ORIGINAL_ENV=demo SECRET_KEY=t python run.py --demo --skip-seed --port 8099` + `/health` 200; sqlalchemy-free import check (as in T3 step 4).

### Task T7: WS-4 keyboard accessibility for Bluebook (EXCLUSIVE owner of bluebook JSX + bundle)

**Files:**
- Modify: the Bluebook JSX files containing click-only rows — find them with `grep -n "onClick" demo/bluebook/*.jsx | grep -v "button\|Button\|<a "` then confirm each is a `<div>`/`<tr>` acting as a button (known: list rows in the dashboard views; the WS-4 doc names them — read `docs/implementation/WS-4-accessibility-hotfix.md` §open items)
- Modify: `demo/bluebook/bluebook.bundle.js` (rebuild, commit)
- Test: `cd demo/bluebook && npm test` (vitest) + new keyboard tests; e2e specs must stay green

**Interfaces:** none consumed; produces the accessible row pattern T9 must reuse for any new interactive element.

**Per-row fix pattern (apply uniformly, no variants):**
```jsx
// was: <div className="row" onClick={() => open(item)}>
<div
  className="row"
  role="button"
  tabIndex={0}
  onClick={() => open(item)}
  onKeyDown={(e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(item); }
  }}
  aria-label={`Open ${item.title}`}
>
```
- [ ] **Step 1: Inventory every click-only interactive element** (grep above + the WS-4 doc list); table into the PR description.
- [ ] **Step 2: Write failing vitest keyboard tests** for two representative rows (render, `fireEvent.keyDown(row, {key: 'Enter'})`, assert the open handler fired; same for Space; assert `tabIndex`/`role`).
- [ ] **Step 3: Apply the pattern to every inventoried element; tests green.** Also ensure visible `:focus-visible` outline on `.row` in the stylesheet if absent (`outline: 2px solid var(--focus, #4c9ffe); outline-offset: 2px`).
- [ ] **Step 4: Rebuild + verify** — `npm run build`, commit bundle; run the axe/e2e suites (`npx playwright test` per repo config) — 0 new violations on touched pages; flip the axe CI job from advisory to blocking ONLY if it's already clean repo-wide, else leave and note.
- [ ] **Step 5: Commit** — JSX + tests + bundle together: `Fix: make Bluebook rows keyboard-operable (WS-4)`.

---

## CODE WAVE 3 (after T6 AND T7 merge; T8 then T9, serialized)

### Task T8: QR phone-park backend

**Files:**
- Create: `original/routers/proctor.py`, `tests/test_phone_park.py`
- Modify: `original/api.py` (one `include_router` line), `original/store.py` (+`phone_park_*` functions + `CREATE TABLE IF NOT EXISTS phone_park_sessions` in the `_get_conn` ladder), `original/repository.py` + `original/postgres_repository.py` + `original/db/models/live.py` (+ alembic revision) — the Repository seam rule: every new store surface lands on BOTH backends + the Protocol.

**Interfaces:**
- Consumes: T6's `original/routers/` layout and `_shared` helpers (guard-token dep, principal dep).
- Produces (exact contract T9 codes against):
  - `POST /proctor/park/open` (professor principal required) `{exam_session_id: str}` → `{park_token: str, qr_url: str}` — `qr_url` = `<base>/bluebook/parked.html?t=<park_token>`; token = 16-byte urlsafe, stored with exam_session_id + created_at, TTL 6h.
  - `POST /proctor/park/beat` (anonymous — the phone has no login) `{park_token: str, student_hint: str, state: "parked"|"foreground_lost"|"resumed"}` → `{ok: true}`; 404 unknown/expired token; rate-limited per token (≥1s spacing enforced server-side); each beat upserts `last_seen_at`, appends state transitions (not every heartbeat) to an events list.
  - `GET /proctor/park/status?exam_session_id=` (professor principal) → `{tiles: [{student_hint, state, last_seen_seconds_ago, transitions: [...]}]}`; a tile whose `last_seen_seconds_ago > 30` reports state `"dropped"` regardless of last reported state.
- Privacy constraints (bake into code + docstrings, they mirror the T4 disclosure): store ONLY park_token, student_hint (free-text name/initials the student types — never an id from our roster), timestamps, state transitions. No IP, no user-agent, no location. Rows deleted by a `DELETE /proctor/park/{exam_session_id}` (professor) and auto-purged after 24h (purge on any `/park/open` call — no scheduler needed).

- [ ] **Step 1: TDD the store layer** (open/beat/status/purge functions, both backends via the contract-test pattern in `tests/test_repository_contract.py` — add a `TestPhonePark` class there OR in the new test file with the same dual-backend fixture).
- [ ] **Step 2: TDD the endpoints** via `live_client`: professor auth enforced on open/status, anonymous beat works, dropped-detection at >30s (monkeypatch time), tenant isolation (professor B cannot read A's session), TTL expiry 404.
- [ ] **Step 3: Full suite 0 failed; ruff clean; alembic revision applies on scratch Postgres. Commit** — `Add phone-park proctoring endpoints (QR deterrence layer)`.

### Task T9: QR phone-park frontend (needs T8 merged)

**Files:**
- Create: `demo/bluebook/parked.html` (standalone, NOT bundled — plain JS, must load instantly on any phone), `demo/bluebook/ProctorTiles.jsx`
- Modify: `demo/bluebook/Exam.jsx` or the briefing component (QR display on the professor/projector side), professor dashboard JSX (mount ProctorTiles), rebuild + commit bundle
- Test: vitest for ProctorTiles (mock fetch of `/proctor/park/status`, assert green/amber tile render + transition list); manual phone walkthrough documented in PR

**Interfaces:**
- Consumes: T8's three endpoints exactly as specified; T7's accessible-element pattern for the tiles (role/tabIndex/keydown).
- Produces: the ritual T4's proctor script references.

**`parked.html` behavior (complete spec):** reads `?t=` token; asks for a name/initials (student_hint) once; requests a screen wake-lock (`navigator.wakeLock?.request('screen')` in try/catch — degrade silently); POSTs `/proctor/park/beat` every 10s with state `parked`; on `visibilitychange` hidden → immediate beat `foreground_lost`; visible again → `resumed`; page shows only a full-screen calm state ("Phone parked for: <exam title fetched? NO — keep zero-fetch: show generic 'Examination in progress'"), a big timer, and "keep this page open, screen may dim". No cookies, no storage beyond the in-memory token.
**QR display:** professor clicks "Start phone park" on the exam briefing → calls `/proctor/park/open` → renders the QR client-side (vendor a tiny MIT qr encoder into `demo/bluebook/vendor/` — it is ruff/lint-exempt there — or generate `<img>` via a data-URI QR lib already in node_modules if present; NO external CDN, page must work offline-ish).

- [ ] **Step 1: parked.html + manual curl-driven test against a local server** (open a park via curl with a professor token, load the page with the token, watch status flip parked/dropped in a second curl).
- [ ] **Step 2: TDD ProctorTiles (vitest, mocked fetch, 5s poll), wire into dashboard + briefing QR button.**
- [ ] **Step 3: `npm run build`, commit bundle; vitest + playwright green; full backend suite untouched-green. Commit** — `Add QR phone-park: parked page, briefing QR, proctor tiles`.

---

## Standing rules for every dispatched task

1. Isolated worktree/clone per task; branch names `t<N>-<slug>`; one PR per task; PR body lists the verification evidence (suite count, lint, boot checks).
2. Never modify files owned by a concurrently-running task (ownership is listed per task above). If you discover you need to, STOP and report BLOCKED — the wave assignment is wrong, don't improvise.
3. Full-suite + `ruff check original/` + `ruff format --check original/` before every PR; CI must be green before merge; merges are human-gated.
4. Any genuine product bug you uncover (not caused by your change): report it in the PR, do not fix it in-scope unless it blocks your task.

## Merge order & rollback

- Wave 1 PRs merge in any order (disjoint). Wave 2: T7 may merge before or after T6 (disjoint). T8 requires T6 merged; T9 requires T7+T8 merged.
- Every task is one PR = one revert. T6's nine per-router commits make partial revert possible even within its PR.
