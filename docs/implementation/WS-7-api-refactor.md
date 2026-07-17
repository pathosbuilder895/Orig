# WS-7 — API-layer refactor

> Part of the [Master Implementation Plan](../AUDIT_2026-07-06.md) (Audit §9). Refs are a 2026-07-07 snapshot — resolve each cited `path:line` by its **named symbol** via [ANCHORS.md](ANCHORS.md); the tree is under active edit and line numbers drift.
> **Findings:** A2, A6, A7, A10, S1, S4, S5, S7, S8, S9, F2, F5 · **Effort:** 2–3 weeks · **Depends on:** interleaves with WS-6 (Postgres) · **Unblocks:** WS-6 P0 (step 1 `ScoringConfig` removes the scoring→store edge the `PostgresRepository` would otherwise have to port); a testable, router-split `api.py` that WS-5/WS-9 can target.

## Objective
Turn the 2,714-line `original/api.py` god module (60 routes, 11 `async` handlers, mid-file pydantic models, a 195-line flagship handler and a 116-line untyped mapper) into a router-split app with a scoring service, typed request/response contracts, and config read once at the boundary. Every step is independently shippable and **behavior-preserving**: the WS-5 test net (flag-matrix scoring + Bluebook API + shared live-app fixture) is the guard, and the flags-OFF byte-identical-to-Phase-1 invariant holds at every commit.

## Prerequisites & dependencies
- **`.venv`** active (`.venv/bin/python`, `.venv/bin/pytest`); full suite green as the pre-refactor baseline (`~497 tests`, `0 failed`).
- **WS-5 lands first, or in lockstep.** Its `tests/conftest.py` live-app fixture and flag-matrix `score()` tests (§9 WS-5 items 1, 3) are the regression net for the router split (step 3) and the `ScoringConfig` change (step 1). Do **not** do step 3 before that net exists.
- **CRITICAL ORDERING — step 1 (`ScoringConfig`) is a WS-6 prerequisite.** `score()` reaching back into `store` (`scoring.py:310` inside `_amplitude_score`, `:478` inside `score`) is the A5 cycle. WS-6's `PostgresRepository` cannot be the sole data path while the math layer imports `store` directly at call time. **Do step 1 before WS-6 starts porting reads.** Say so in the WS-6 kickoff.
- **Cross-workstream shared findings — which slice is ours:**
  - **S4** is split with WS-6: **we own** the `ScoringConfig` injection + passing genre stats as a parameter + collapsing the always-on flag branches (F2). WS-6 owns the store-side aggregate split (S2).
  - **A7 / F3** ORIGINAL_ENV vs ENVIRONMENT merge is **ours** (step 4) — but it consumes the promoted pydantic `Settings` object that **WS-6 P0 produces** (`core/config.py` pattern → live stack). Sequence step 4 after that promotion.
  - **F5** static-gating is **ours** (step 5). The *durable* a11y rebuild of those pages is WS-8; we only gate/501/delete.
  - **D14** docstring pass on `scoring.py` folds into step 1 (WS-3 defers it here to avoid documenting `score()` twice).

## Tasks

### 7.1 `ScoringConfig` frozen dataclass — S4, A5, A7 (partial), F3 (partial)
- **Current state:** `quantum/scoring.py` `score()` spans **lines 386–714** (~329 lines; audit "~325"). Six `os.environ.get()` reads sit *in the function body*: `BAYESIAN_PRIOR_ENABLED` (`:475`), `PRIOR_WEIGHT` (`:486`), `LENGTH_ADAPTIVE_WEIGHTS` (`:515`), `NULL_MODEL` (`:548`), `AMPLITUDE_SCORING_ENABLED` (`:559`), `SECRET_KEY` (`:564`) — all six lines exactly as the audit cites. Two call-time store imports form the A5 cycle: `from ..store import get_genre_stats` inside `score()` (`:478`) and `from ..store import get_authentic_fidelities` inside the `_amplitude_score` helper (`:310`, which `score()` calls). The model to copy is `amplitude.py`: **0 env reads**, `secret_key` is a parameter (`amplitude.py:213`, `:264`). `score()` already takes `impostor_stats` as a parameter (`scoring.py:394`) — the same shape the flags should take.
- **Change:**
  1. Add a frozen dataclass in `quantum/scoring.py` (or a new `quantum/config.py`), e.g.:
     ```python
     @dataclass(frozen=True)
     class ScoringConfig:
         bayesian_prior_enabled: bool = False
         prior_weight: float = 3.0
         length_adaptive_weights: bool = False
         null_model: str = "none"
         amplitude_scoring_enabled: bool = False
         secret_key: str = ""
         @classmethod
         def from_env(cls) -> "ScoringConfig": ...  # the ONE place the 6 vars are read
     ```
  2. `def score(..., config: ScoringConfig | None = None, genre_stats=None, authentic_fidelities=None)`. Default `config = config or ScoringConfig()` so a no-arg call is byte-identical to today's flags-OFF path. Replace each in-body `os.environ.get(...)` with the matching `config.*` field.
  3. Delete the two call-time store imports: `genre_stats` (was `get_genre_stats(_genre)` at `:478`) and `authentic_fidelities` (was `get_authentic_fidelities(student_id)` at `:310`, inside `_amplitude_score`) become parameters the caller supplies. Thread `authentic_fidelities` through `_amplitude_score`'s signature.
  4. At the API boundary (`api.py` `score_submission`, ~`:1721` `quantum_score(...)` call), build `ScoringConfig.from_env()` once and fetch `store.get_genre_stats(...)` / `store.get_authentic_fidelities(...)` there, passing both in. `NULL_MODEL` stays read at the boundary too (already is, `api.py:1713`).
  5. Fold the WS-3 **D14** docstring pass into this edit (document each `config` field + the two new params).
- **Files touched:** `original/quantum/scoring.py`, `original/api.py` (call site ~1721), optionally new `original/quantum/config.py`.
- **Verify:** `.venv/bin/python -m pytest tests/quantum/ -v` green; WS-5 flags-OFF byte-identical assertion passes; `grep -n "os.environ\|from ..store" original/quantum/scoring.py` returns **zero** hits.

### 7.2 Pydantic request models + response_model + typed seams — A10, S7, S8, S9
- **Current state:** exactly **8** `body: dict` endpoints (grep `body: dict` in `api.py`): `auth_login` (`:460`), `auth_register` (`:500`), `bluebook_create_exam` (`:624`), `bluebook_record_submission` (`:674`), `bluebook_create_course` (`:715`), `create_tenant` (`:969`), `student_login` (`:1088`), `demo_login` (`:2658`, async, demo-only). `schemas.py` exists (**650 lines**) and is the home for these. `_to_response(r, arc=None, report=None)` (`api.py:1842`, ~116 lines, **untyped**) is the load-bearing dataclass→pydantic mapper; called at `:1663`, `:1837`, `:2452`. `RequestBaselineRequest` is defined mid-`api.py` (audit `:1450`).
- **Change:**
  - Add a request model per dict-body endpoint to `schemas.py`; replace the hand-rolled 422 checks (e.g. `auth_register`'s three manual checks, `:500–516`) with the model. `demo_login` is demo-only — model it too for consistency but it is gated off real deploys anyway.
  - Add `response_model=` to routes still missing it (~half of 60; audit: ~30 already declare it).
  - Annotate handler return types and, first, the two highest-value untyped seams: `_to_response(...) -> Layer7OutputResponse` and `run_adaptive_pipeline` (S7).
  - **S9:** replace the manual `_to_response` field-copying with `Layer7OutputResponse.model_validate(asdict(result))` (dataclasses in the math core stay pydantic-free — correct per S9). Guard the `report=None` / `arc=None` defaulting path (where a drift bug would hide) with a **round-trip test**: `Layer7Output → asdict → model_validate → response`.
  - Move `RequestBaselineRequest` (and any other mid-file models) into `schemas.py`.
- **Files touched:** `original/schemas.py`, `original/api.py`.
- **Verify:** `/docs` OpenAPI shows request schemas for all 8 endpoints; round-trip test green; `grep -n "body: dict" original/api.py` returns **zero**; malformed-body request returns 422 (was hand-rolled 400/dict-KeyError).

### 7.3 APIRouter split by domain + scoring_service extraction — A2, S1
- **Current state:** `api.py` has **zero `APIRouter`s** — one flat file with 60 routes across ~12 product areas, two middleware (`security_headers` `:214`, `tenant_isolation` `:262`), the lifespan/backup scheduler (`:117`), and 79 `HTTPException` sites. The flagship `score_submission` (`api.py:1643–1837`, ~195 lines) inlines: existing-result cache check, adaptive pipeline call, impostor-pool build, `quantum_score`, three persistence writes, report + tension-arc assembly, email notification, audit logging.
- **Change:**
  - Introduce `original/routers/{auth,lti,bluebook,students,scoring,tenants,admin,lab}.py`, each an `APIRouter` mounted on the same `app` (`app.include_router(...)`). Move handlers verbatim — **mechanical, behavior-preserving**. Keep the two middleware + lifespan on the root app in `api.py` (or a thin `app.py`). Shared deps (principal resolver, `store`/`_repo`, `_IS_REAL_DEPLOY`) move to a `routers/deps.py` or stay importable from the app module.
  - Extract `score_submission`'s orchestration into `original/services/scoring_service.py` as `score_and_persist(...)` (S1). The router handler becomes a thin adapter: parse request → call service → `_to_response`. The service composes: build `ScoringConfig` (from step 1), fetch genre stats/fidelities, run adaptive pipeline, build impostor stats, call `quantum_score`, persist, assemble report/arc, notify, audit.
  - Preserve route paths, methods, status codes, and response bodies exactly. The A9 importlib load path (`run.load_legacy_demo_app()` / `spec_from_file_location`) must still resolve — keep the app object where `run.py` expects it.
- **Files touched:** new `original/routers/*.py`, new `original/services/scoring_service.py`, `original/api.py` (shrinks to app assembly + middleware + lifespan).
- **Verify:** full suite `.venv/bin/python -m pytest tests/ -q` **0 failed** (WS-5 net is the guard); route inventory unchanged — diff `sorted((r.methods, r.path) for r in app.routes)` before/after must be identical; `python run.py --demo` boots and serves.
- **Deferred, not forgotten — `lab/` module extraction:** audit §2 (F7) recommends revisiting extraction of `original/lab/` (862 lines, staff-gated calibration ops, 22 tests) into its own package post-pilot; it's "acceptable at pilot stage" as-is and this is explicitly not urgent. This step's `routers/lab.py` is the natural landing spot for that extraction once it's revisited — do it here, as part of the router split, rather than as a separate untracked effort. Owner: whoever executes 7.3; trigger: post-pilot, opportunistically alongside this step.

### 7.4 De-async blocking handlers + flag GA collapse + env merge — A6, F2, A7, F3
- **Current state — A6:** `async def` handlers doing sync/CPU-bound work on the event loop: `upload_file` (`:1605`), `upload_baseline_batch` (`:2011`), `import_turnitin_csv` (`:2133`), `list_canvas_submissions` (`:2205`), `import_canvas_baseline` (`:2222`), `demo_login` (`:2658`). (The other `async` handlers — `lifespan`, the two middleware, `lti_login` `:534`, `lti_launch` `:548` — are legitimately async and stay. Audit "7 blocking" counts the 6 here plus treats the Canvas pair as two; step 5 turns the Canvas stubs into 501s so those two disappear as a concern.)
- **Current state — F2:** `render.yaml:62` runs `--demo`; `run.py:149–155` setdefaults `CONTEXT_MANIFEST_ENABLED=1`, `ADAPTIVE_WEIGHTS_ENABLED=1`, `NULL_MODEL=impostor` — so production is always-on for these three. The dual-path branch in `score_submission` reads them at `api.py:1669` (`CONTEXT_MANIFEST_ENABLED`), `:1670` (`ADAPTIVE_WEIGHTS_ENABLED`), `:1713` (`NULL_MODEL`).
- **Current state — A7/F3:** two vars, both default `"demo"`: `ORIGINAL_ENV` (deploy gate, `api.py:113`, drives `_IS_REAL_DEPLOY` `:114`) and `ENVIRONMENT` (repository seam, `api.py:310`, `:1561`, `:1574`, `:1592` → `get_repository(...)`). Genuinely confusing dual.
- **Change:**
  - **A6:** drop `async` from the 4 kept file/CSV handlers (`upload_file`, `upload_baseline_batch`, `import_turnitin_csv`, and any residual), so FastAPI runs them in its threadpool; or wrap the heavy loop in `run_in_threadpool`. One line per endpoint. `demo_login` is demo-only — de-async or leave, low priority.
  - **F2:** declare `CONTEXT_MANIFEST_ENABLED`, `ADAPTIVE_WEIGHTS_ENABLED`, `NULL_MODEL=impostor` **GA**; collapse the off-branches in the (now-extracted) scoring service so the adaptive pipeline + impostor pool are the single path. **Reserve flags for genuinely unproven features only** (`AMPLITUDE_SCORING_ENABLED`, `BAYESIAN_PRIOR_ENABLED`, `AI_LIKELIHOOD_*`). Remove the corresponding `setdefault`s from `run.py:149–155` since they become the default. **Invariant guard:** the flags-OFF *scoring math* (Bayesian/amplitude/length-adaptive) stays byte-identical — only the three now-GA pipeline flags lose their off-branch. Confirm no WS-5 flags-OFF assertion covers manifest/adaptive/null (those are attach-only / weight-vector, not the byte-identical deviation_score core).
  - **A7/F3:** collapse `ORIGINAL_ENV`/`ENVIRONMENT` into **one** setting on the promoted pydantic `Settings` (from WS-6 P0). Pick one name (recommend keeping `ORIGINAL_ENV` semantics: deploy tier drives both the real-deploy gate and repository selection), map the other for one release with a deprecation warning. Document every behavior-affecting flag in CLAUDE.md (F3): `LENGTH_ADAPTIVE_WEIGHTS`, `RANK_REMEDIATION`, `AI_LIKELIHOOD_*`, `GUARD_DESTRUCTIVE`/`MAINTENANCE_TOKEN`, `ENABLE_HSTS`, `ALLOWED_ORIGINS`, `BACKUP_*`, `BBOOK_*`, `LTI_*`.
- **Files touched:** `original/api.py` (or the split routers), `original/services/scoring_service.py`, `run.py`, `render.yaml` (drop redundant flag setdefaults), `CLAUDE.md` (flag table).
- **Verify:** `/health` stays responsive during a multi-PDF `upload_baseline_batch` (manual or a threadpool-assert test); flag-matrix suite still green with off-branches removed; `grep -c "os.environ" original/api.py` drops materially; one env var governs deploy tier.

### 7.5 Static gating + Canvas stub 501 + tier registry — F5, S5
- **Current state — F5:** `_DEMO_ONLY_STATICS` (`api.py:249`) currently 404s only `/seed.db`, `/lab.html`, `/playground.html`, and three validation JSONs on real deploys (`_IS_REAL_DEPLOY and path in _DEMO_ONLY_STATICS`, `:265`). The whole `demo/` dir is static-mounted (`run.py:107`), so **`operator.html`, `admin-context.html`, `student-coach.html`, `onboard.html`, `landing.html` are served on real deploys**. Confirmed present in `demo/`; `landing.html` has **zero inbound links** (grep across `demo/` returns nothing — orphaned). Canvas stubs `list_canvas_submissions`/`import_canvas_baseline` (`:2205`, `:2222`) return demo placeholder JSON permanently.
- **Current state — S5:** adding a tier touches ≥5 places: new tier module + `TIERN_CODES` in `constants.py` + hand-composed `ALL_FEATURE_CODES` tuple (`constants.py:197–204`, verified) + `NORM_BOUNDS` + hardcoded import/call in `features/pipeline.py` (imports `:25–39`, calls `:112–124`, verified). Special cases already accreting (tier 12 bespoke wrapper, tier 17 inline `DISABLED_FEATURE_GROUPS` branch).
- **Change:**
  - **F5:** add `operator.html`, `admin-context.html` to `_DEMO_ONLY_STATICS` (or staff-gate them via `_is_staff_only_path`). Note operator/admin-context are the two NOT already gated that must be. `student-coach.html`/`onboard.html` per product call (gate unless the pilot links them). **Delete `landing.html`** via `git rm` (orphaned). Turn the two Canvas stubs into **HTTP 501** (`raise HTTPException(501, "Canvas import not available in the pilot server")`) instead of misleading success JSON. Fix the `run.py:164–165` banner that advertises pages living only in dead `frontend/`.
  - **S5:** lightweight declarative registry — each tier module exports `(CODES, BOUNDS, extractor, kind)`; `constants.py` composes `ALL_FEATURE_CODES` and `NORM_BOUNDS` by iterating one ordered `TIERS` tuple; `pipeline.py` iterates the same tuple to run extractors. **Ordering stays explicit** (the tuple order is the serialization contract) — no plugin dynamism. ⚠ This edits `constants.py` feature ordering, which **requires explicit permission** (CLAUDE.md); the refactor must produce a byte-identical `ALL_FEATURE_CODES` — assert equality against the pre-refactor list.
- **Files touched:** `original/api.py` (`_DEMO_ONLY_STATICS`, Canvas handlers), `run.py` (banner, `git rm demo/landing.html`), `original/constants.py`, `original/features/pipeline.py`, tier modules.
- **Verify:** on `ORIGINAL_ENV=pilot`, `GET /operator.html` and `/admin-context.html` return 404 (or 403); `/landing.html` 404; Canvas endpoints return 501; `python -c "from original.constants import ALL_FEATURE_CODES; assert len(ALL_FEATURE_CODES)==103"` and an equality assert vs the frozen pre-refactor tuple; full suite green.

## Acceptance criteria
> Verified against the working tree 2026-07-09. Only step 1 (`ScoringConfig`) has landed; steps 2–5 have not started.
- [x] `grep -n "os.environ" original/quantum/scoring.py` → **0**; `score()` takes `config`, `genre_stats`, `authentic_fidelities`; no call-time `from ..store` import remains (A5 edge deleted). — DONE: step 1 landed. `ScoringConfig` dataclass + `from_env()` exist; `score()` takes a `scoring_config` param; no `store` import remains in the module.
- [x] WS-5 flags-OFF byte-identical `score()` assertion passes at every WS-7 commit (Phase-1 scoring math unchanged). — DONE currently: `tests/test_scoring_flags.py` (WS-5) covers this and passes.
- [ ] `grep -n "body: dict" original/api.py` → **0**; all 8 endpoints have request models in `schemas.py`; malformed body → 422; `_to_response` typed + built via `model_validate(asdict(...))` with a passing round-trip test. — NOT DONE: `grep -c "body: dict" original/api.py` currently returns **10** (two more than this doc's own baseline of 8 — it missed `open_formation`, and one match is a non-endpoint occurrence at `api.py:2620`).
- [ ] `api.py` split into `routers/{auth,lti,bluebook,students,scoring,tenants,admin,lab}.py` + `services/scoring_service.py`; route inventory (method, path, response body) **identical** before/after; `python run.py --demo` boots. — NOT DONE: neither `original/routers/` nor `original/services/scoring_service.py` exist yet.
- [ ] The 4 file/CSV upload handlers no longer block the loop (`/health` responsive under a multi-PDF batch). — NOT DONE: `upload_file`, `upload_baseline_batch`, `import_turnitin_csv`, `list_canvas_submissions`, `import_canvas_baseline` are all still `async def`.
- [ ] `CONTEXT_MANIFEST_ENABLED`/`ADAPTIVE_WEIGHTS_ENABLED`/`NULL_MODEL` declared GA; off-branches removed; redundant `run.py` setdefaults gone; `AMPLITUDE`/`BAYESIAN`/`AI_LIKELIHOOD` remain flags. — NOT DONE: all three are still read as env flags in `api.py`, no GA collapse.
- [ ] One env var governs deploy tier (ORIGINAL_ENV/ENVIRONMENT merged via promoted `Settings`); CLAUDE.md flag table lists every behavior-affecting flag. — PARTIAL: `ORIGINAL_ENV`/`ENVIRONMENT` remain two distinct, unmerged vars (`api.py` comments explicitly note this is deliberate pending WS-7); the CLAUDE.md flag table itself is otherwise complete (WS-3 landed it, and this doc-audit pass added the two `LOGIN_THROTTLE_*` rows CLAUDE.md was missing).
- [ ] `operator.html`/`admin-context.html` gated on real deploys; `landing.html` deleted; Canvas stubs → 501; `run.py` banner fixed. — NOT DONE: `_DEMO_ONLY_STATICS` still doesn't include operator/admin-context; `demo/landing.html` still exists; the two Canvas stub endpoints still return placeholder 200 JSON, not 501.
- [ ] Tier registry: one `TIERS` tuple drives `constants.py` + `pipeline.py`; `ALL_FEATURE_CODES` byte-identical to pre-refactor (len 103). — NOT DONE / not attempted (correctly deferred — this edits `constants.py` feature ordering, which requires explicit permission per CLAUDE.md).
- [x] Full suite `.venv/bin/python -m pytest tests/ -q` → **0 failed** after every step. — DONE as of the current step-1-only state: full suite green, 0 failed.

## Risks & watch-outs
- **Byte-identical invariant (core).** Step 1 must default to today's flags-OFF path exactly; step 4's GA collapse touches only the three pipeline flags (manifest/adaptive/null — attach-only or weight-vector), never the Bayesian/amplitude/length-adaptive *math*. Any diff in flags-OFF `deviation_score` is a regression.
- **A9 module-shadowing trap.** `import original.api` resolves to the **dormant** package; the live app loads via `run.load_legacy_demo_app()` / `spec_from_file_location`. The router split must keep the app object where that loader expects it — do not assume normal package imports. (A9's rename is WS-6/out of scope here; don't trigger it accidentally.)
- **`constants.py` ordering is permission-gated + a serialization contract.** The S5 registry must reproduce `ALL_FEATURE_CODES` identically; legacy 74/89-dim profiles pad on load, so a reorder silently corrupts stored baselines. Assert equality; get explicit sign-off before touching it.
- **Router split is where silent behavior drift hides** (middleware order, dependency resolution, status codes). This is exactly why WS-5's net must exist first — do not start step 3 without it.
- **Env merge depends on WS-6 P0.** Step 4's `ORIGINAL_ENV`/`ENVIRONMENT` merge needs the promoted pydantic `Settings`; if WS-6 P0 slips, ship steps 1–3 + the A6/F2 half of step 4 and defer the merge.
- **Canvas 501 vs current 200.** Any pilot client currently swallowing the stub's placeholder JSON will now see 501 — confirm no demo flow depends on the fake success before flipping.

## Sequencing within the workstream
1. **7.1 `ScoringConfig`** — ship first (independently shippable; **WS-6 prerequisite**). Guarded by WS-5 flag-matrix tests.
2. **7.2 request/response models + typing** — independently shippable; no ordering dep on 7.1, but do after so the scoring-service extraction (7.3) inherits typed contracts.
3. **7.3 APIRouter split + `scoring_service`** — **requires WS-5 net in place.** Independently shippable once green; the largest mechanical change.
4. **7.4 de-async + flag GA + env merge** — the de-async and F2 GA-collapse ride on 7.3's service extraction; the ORIGINAL_ENV/ENVIRONMENT merge waits on WS-6 P0's `Settings`. Split the commit if P0 slips.
5. **7.5 static gating + Canvas 501 + tier registry** — gating/501/banner + `landing.html` delete are independently shippable and can land any time. The S5 tier registry is gated on `constants.py` sign-off; land it last, byte-identical-asserted.
