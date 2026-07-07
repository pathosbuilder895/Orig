# WS-3 — Trust surface: docs & compliance

> Part of the [Master Implementation Plan](../AUDIT_2026-07-06.md) (Audit §9). Refs are a 2026-07-07 snapshot — resolve each cited `path:line` by its **named symbol** via [ANCHORS.md](ANCHORS.md); the tree is under active edit and line numbers drift.
> **Findings:** D1–D8, D10–D16, F3 (flag-table slice), F8 (97/103) · **Effort:** 3–4 days (can run same week as WS-1/2) · **Depends on:** — · **Unblocks:** the compliance/procurement conversation a seminary's legal office will start (encryption + data-inventory honesty), and a defensible MODEL_CARD/README for any pilot go-live review. VPAT is deferred until WS-4/WS-8 land the a11y fixes it must describe.

## Objective
This is a documentation workstream: no code behavior changes. "Done" means every operator-, compliance-, and API-consumer-facing document describes the **live stack** (`original/api.py` + `demo/` + `/lti/*`) truthfully, and every document that describes the **dormant v1 stack** (`original/api/`, `original/main.py`, `original/core/`, `frontend/`) says so in a banner. The single most important outcome: the compliance set (`encryption_policy.md`, `data_inventory.md`) and the institutional claims document (`MODEL_CARD.md`) stop asserting controls and thresholds the code does not implement. Accuracy of every claim is the deliverable — each task below states how to verify it against code.

## Prerequisites & dependencies
- No other WS output is required to start. WS-1/2/3 run in parallel.
- **Shared-finding boundaries (do not double-own):**
  - **F3 is split three ways.** WS-1 owns the `MAINTENANCE_TOKEN` + `GUARD_DESTRUCTIVE` runbook prose (operational/security subset). WS-7 owns the `ORIGINAL_ENV`/`ENVIRONMENT` *merge* (a code change). **WS-3 owns only the flag-table documentation slice**: completing the CLAUDE.md env-flag table so every behavior-affecting flag is listed (task 6). WS-3 documents `ORIGINAL_ENV` vs `ENVIRONMENT` as they exist today; it does not merge them.
  - **D7** (version identifiers) is shared with the MODEL_CARD title fix here (task 1) — WS-3 fixes the doc title; the pyproject/app-version source-of-truth pick is a one-line note, not a WS-3 code task.
- The banner template is already in the repo: `deploy/DEPLOY.md:1–8` (the `> ## ⚠️ NOT the current deployment path` block). Reuse it verbatim in structure — task 3.
- Ground truth for the "live vs dormant" split is `docs/ARCHITECTURE.md` (audit §5 calls it the single best doc). Link it from README (task 4); do not re-derive it.

## Tasks
One `###` per §9 WS-3 item; §9 numbering preserved. All `path:line` refs below were re-verified against the working tree on 2026-07-07.

### 1. Threshold + MODEL_CARD version fixes — D2, D7
- **Current state:** `original/constants.py:652–659` is the source of truth: `no_action (0.00,0.40)`, `monitor (0.40,0.60)` (comment: "raised from 0.55 — absorbs same-author natural variance; holdout σ≈0.036, observed max 0.554"), `schedule_conversation (0.60,0.75)`, `escalate (0.75,1.00)`. Two docs publish the **old** boundaries: `README.md:107–108` (`0.40–0.55 monitor`, `0.55–0.75 schedule_conversation`) and `MODEL_CARD.md:103–104` (`0.40-0.55`, `0.55-0.75`). `docs/OWNERS_MANUAL.md:91` already has the correct `0.60`, so the docs currently contradict each other. Separately, `MODEL_CARD.md:1` title reads `v1.1.0` but its own history table `MODEL_CARD.md:277` ends at `1.3.0 | 2026-07-04` (D7).
- **Change:**
  - `README.md:107` `0.00 – 0.40 … 0.40 – 0.55` → boundary at **0.60**: `0.40 – 0.60 monitor`, `0.60 – 0.75 schedule_conversation`.
  - `MODEL_CARD.md:103–104` `0.40-0.55` → `0.40-0.60`; `0.55-0.75` → `0.60-0.75`.
  - `MODEL_CARD.md:1` title `v1.1.0` → `v1.3.0` (match the history table's newest row).
  - Add a comment on `constants.py:652` `ACTION_THRESHOLDS` naming the dependent docs: `# Publish-sync: README.md action table, MODEL_CARD.md action table, OWNERS_MANUAL.md — update all three if these boundaries move.` (Comment only; NORM_BOUNDS/feature-ordering untouched → no "requires-permission" trip.)
- **Files touched:** `README.md`, `MODEL_CARD.md`, `original/constants.py` (comment line only).
- **Verify:** `grep -n "0.40, 0.60\|0.60, 0.75" original/constants.py` and `grep -n "0.40 – 0.60\|0.40-0.60\|0.60 – 0.75\|0.60-0.75" README.md MODEL_CARD.md` — all three surfaces agree. `grep -n "^# Model Card" MODEL_CARD.md` shows `v1.3.0`.

### 2. Correct the compliance docs to implemented reality — D5
- **Current state:** the only cryptography in `original/` is **LTI/Canvas RSA** (`original/canvas/keys.py:28–30` imports `cryptography.hazmat`; `keys.py:91` serializes with `NoEncryption()`). There is **no** AES/GCM/Fernet anywhere in the live package (verified: `grep -rniE "aes|fernet|GCM" original/ --include=*.py` returns nothing outside dormant/test). The live store is plain SQLite (`store.py:41` `_DB_PATH = os.environ.get("ORIGINAL_DB", …)` → `sqlite3.connect`). Yet:
  - `encryption_policy.md:15–17,29–38` claims "Encryption at Rest: AES-256-GCM … per-institution keys" and tabulates every data type as `AES-256-GCM` in **PostgreSQL** (the live stack is SQLite, not Postgres).
  - `data_inventory.md:15–19` marks every category `AES-256`; `:137` claims "Raw text NOT stored by default"; `:54,132,258` promise "Automatic Deletion … Triggers 1 year … via background job … overwrites with null."
  - **Contradicted by code:** raw baseline text IS retrievable via the live `GET /students/{id}/samples/{index}/text` (`api.py:889`), and `PILOT_RUNBOOK.md:150` states "Raw text is stored." The automatic-deletion / retention-scheduler machinery exists only in the **dormant** stack (`original/core/config.py:135` `DEFAULT_RETENTION_DAYS`, `original/api/v1/admin.py:289–290`) — no scheduler runs in the live app.
  - **Nuance to preserve (refines audit D5):** *manual* deletion is real and live — `store.delete_student()` (`store.py:1021`) and the CLI `python -m original.cli.delete_student` (`original/cli/delete_student.py`) both exist and work. Only *automatic/scheduled* deletion is fictional. Keep the manual path in the docs; strike the automatic one.
- **Change:**
  - `encryption_policy.md`: replace "AES-256-GCM at rest / per-institution keys" with the truth — **Render managed-disk encryption at rest** (platform-level, not application-level), **TLS 1.3 in transit** (Render edge). State plainly that the application does not encrypt row data and that feature vectors are non-reversible. Keep LTI RSA (`canvas/keys.py`) as the one app-managed key material.
  - `data_inventory.md`: change the Encryption column from `AES-256` to "Render disk encryption (platform)"; delete `:137` "Raw text NOT stored by default" (replace with "Raw baseline/submission text IS stored; retrievable by authorized instructors via `GET /students/{id}/samples/{index}/text`"); **delete or future-mark** the §10.1 auto-deletion pseudo-code and the "Automatic Deletion via background job" lines — mark them `> Planned — not implemented in the pilot stack (no retention scheduler runs).` Keep the manual `delete_student` CLI/endpoint rows.
  - Meet the honesty bar `dpa_template.md` sets for itself (its banner forbids "aspirational security claims").
- **Files touched:** `docs/encryption_policy.md`, `docs/data_inventory.md`.
- **Verify:** `grep -rniE "AES|GCM" docs/encryption_policy.md docs/data_inventory.md` returns only historical/"planned" context, never a present-tense claim. `grep -n "Render disk\|platform-level\|TLS 1.3" docs/encryption_policy.md` present. Cross-check the store is still SQLite: `grep -n "sqlite3.connect" original/store.py`.

### 3. Banner the dormant-stack docs — D4, D10
- **Current state:** `deploy/DEPLOY.md:1–8` carries the canonical banner; three docs that describe dormant artifacts carry **none** (verified: first-3-line grep finds no `⚠️`/`NOT the current` marker):
  - `docs/SECURITY_AUDIT.md` — dated 2026-05-11; audits `original/core/config.py:32` JWT (dormant), SQLAlchemy ORM injection (`:52`), `deploy/nginx.conf` TLS (`:21`), and rate limits on `/api/v1/*` (`:75–76`) — all dormant — then concludes `:24` "Overall posture: SECURE for pilot deployment." The pilot actually runs principal tokens + PBKDF2 + SQLite/WAL + Render TLS (`original/api.py`), none of it examined.
  - `docs/BETA_PHASE1_TECH.md`, `docs/phase3-httpOnly-cookie-auth.md` — read as current work but describe v1 auth/frontend.
- **Change:** prepend the `deploy/DEPLOY.md` banner block, adapted per file, to all three. For SECURITY_AUDIT add one line: "This report audited the dormant v1 stack. A live-stack re-audit is scheduled — see task below." Then **schedule** (as a tracked follow-up, not executed here) a live-stack security re-audit covering the auditable live surface: auth throttle, `X-Guard-Token`/`MAINTENANCE_TOKEN` guard (`api.py:319–334`), tenant isolation, CORS fail-fast (`ALLOWED_ORIGINS`).
- **Files touched:** `docs/SECURITY_AUDIT.md`, `docs/BETA_PHASE1_TECH.md`, `docs/phase3-httpOnly-cookie-auth.md`.
- **Verify:** `for f in docs/SECURITY_AUDIT.md docs/BETA_PHASE1_TECH.md docs/phase3-httpOnly-cookie-auth.md; do head -3 "$f" | grep -q "NOT the current\|dormant v1" && echo "$f OK"; done` prints all three.

### 4. Rewrite README + SETUP around the live stack — D1, D3, D6, D8
- **Current state:**
  - **README endpoint table** `README.md:224–243` lists `/api/v1/auth/login`, `/api/v1/students/`, `/api/v1/submissions/{id}/score`, `/canvas/lti/login`, `/canvas/lti/jwks`, etc. — **all dormant routes**. The live LTI is `/lti/login|launch|jwks` (`original/lti.py`); the live scoring path is `POST /students/{id}/score` (`api.py:1669`); ~76 live routes are absent.
  - **README "Production deployment"** `README.md:270–292` describes start-prod.sh / `DATABASE_URL` / alembic — the exact path `deploy/DEPLOY.md:1` banners as "NOT the current deployment path." The live deploy is `render.yaml` (`startCommand: python run.py --demo --port $PORT --skip-seed`).
  - **README FERPA claim** `README.md:260`: "With `ferpa_mode: true`, raw submission text is deleted after feature extraction" — contradicts `api.py:889` + `PILOT_RUNBOOK.md:150` (see task 2). There is no live `ferpa_mode` deletion path.
  - **README never links `docs/ARCHITECTURE.md`.**
  - **SETUP.md** `:4,173,190,194,231` says 74 features and "pads old 62-dimension vectors to 74"; code is `constants.py:206` `FEATURE_DIM = 103`. SETUP also inverts the DB story ("PostgreSQL production / SQLite testing" vs. the live hardened-SQLite pilot per ADR-004). `SETUP.md:77–124` + `README.md:189–207` send a Canvas admin to `POST /api/v1/admin/canvas/registrations` (dormant); the live flow is env `LTI_PLATFORMS` + `/lti/*` per `CANVAS_RUNBOOK.md` (D6).
  - **Stale counts:** `README.md:377` "32 tests"; `CLAUDE.md:21` "~497 tests"; actual `pytest --co` today = **613**. `CLAUDE.md:8` "port 8001 by default" but `run.py:113` default is 8000 (8001 comes from start.sh/CI) — align the port note (defer the code change to B16/WS-1).
- **Change:**
  - Replace the README endpoint table with a **live** table grouped by audience (students/instructors/admin/LTI/health) sourced from `api.py` route decorators. Minimum set to show: `POST /students/{id}/score`, `GET /students/{id}/samples/{index}/text`, `GET /health`, `/lti/login`, `/lti/launch`, `/lti/jwks`. Point "full docs" at FastAPI `/docs` (already correct).
  - Replace "Production deployment" with the `render.yaml` reality; link `deploy/DEPLOY.md` only as "self-hosted future option (dormant)."
  - Fix `README.md:260` FERPA prose to match task 2 (raw text stored; manual deletion via CLI/endpoint).
  - Add a prominent `docs/ARCHITECTURE.md` link near the top of README.
  - Reduce `SETUP.md` to a live-stack quickstart (74→103; drop the Postgres-production inversion → hardened SQLite per ADR-004); both LTI sections (SETUP + README) → pointers to `CANVAS_RUNBOOK.md` + `canvas_developer_key.md`.
  - Update counts: README "32 tests" → "613 tests"; `CLAUDE.md` "~497 tests" → "613"; align the CLAUDE.md/README port note to "8001 (start.sh/CI/render); `run.py` default is 8000 until B16."
- **Files touched:** `README.md`, `SETUP.md`, `CLAUDE.md`.
- **Verify:** `grep -n "/api/v1/" README.md SETUP.md` returns nothing (or only under an explicit "dormant" heading). `grep -n "ARCHITECTURE.md" README.md` present. `grep -n "74" SETUP.md` returns no feature-count claim. `grep -n "613" README.md CLAUDE.md` present. `grep -rn "delete_student\|samples/{index}/text" README.md` matches the live reality.

### 5. Status headers on planning docs + OWNERS_MANUAL sentence — D11, D16
- **Current state:** `FEATURE_EXPANSION_PLAN.md:1–2` and `ADAPTIVE_SCORING_SPEC.md:1–3` sit at repo root with no status header — the former reads "34 features … to ~62–69" (superseded twice; code is 103), the latter says "Phase 1 in place / implement in phases" though Phases 2–8 shipped 2026-05-12. `docs/OWNERS_MANUAL.md:4` begins mid-sentence: `` `OPS_RUNBOOK.md`; this is **how you personally use and present the product**. `` — the clause distinguishing it from OPS_RUNBOOK was lost in an edit.
- **Change:**
  - Prepend `> **Status: historical / superseded.** …` headers to `FEATURE_EXPANSION_PLAN.md` and `ADAPTIVE_SCORING_SPEC.md` (or move both to `docs/history/`). Note the current dimension is 103/17 tiers.
  - Restore `OWNERS_MANUAL.md:4` to a complete sentence, e.g. "Where `OPS_RUNBOOK.md` covers operating the server, this is **how you personally use and present the product.**"
- **Files touched:** `FEATURE_EXPANSION_PLAN.md`, `ADAPTIVE_SCORING_SPEC.md`, `docs/OWNERS_MANUAL.md`.
- **Verify:** `head -3 FEATURE_EXPANSION_PLAN.md ADAPTIVE_SCORING_SPEC.md | grep -i "status:"` present; `sed -n '4p' docs/OWNERS_MANUAL.md` is a complete sentence.

### 6. Complete the CLAUDE.md env-flag table (F3 slice) + document 97/103 (F8) — F3, F8
- **Current state — flag table (F3):** `CLAUDE.md:44–50` documents **7** flags: `CONTEXT_MANIFEST_ENABLED`, `ADAPTIVE_WEIGHTS_ENABLED`, `AMPLITUDE_SCORING_ENABLED`, `SECRET_KEY`, `BAYESIAN_PRIOR_ENABLED`, `PRIOR_WEIGHT`, `NULL_MODEL`. A grep of `os.environ`/`getenv` across `original/` + `run.py` finds **31** distinct env vars read in the live package. **Missing from the table** (grouped by impact; the *bolded* two are the priority — they silently change scores):
  - **Scoring-math (highest priority):** **`LENGTH_ADAPTIVE_WEIGHTS`** (`quantum/scoring.py:515` — rescales the per-feature deviation weight vector when `=1`), **`RANK_REMEDIATION`** (`quantum/state.py:190` — `=shrinkage` blends ρ toward isotropic I/D via Ledoit-Wolf, altering the density-matrix estimator). Both default OFF; both change deviation output if set.
  - **AI-likelihood second scorer:** `AI_LIKELIHOOD_ENABLED`, `AI_LIKELIHOOD_SHADOW`, `AI_LIKELIHOOD_MODEL_PATH` (report-only detector; shadow/enabled/gate semantics).
  - **Security/ops (documented in WS-1's runbook slice; list them here as *pointers*, don't re-specify):** `GUARD_DESTRUCTIVE`, `MAINTENANCE_TOKEN` (`api.py:2642` — role-granting `X-Guard-Token` secret), `ENABLE_HSTS`, `ALLOWED_ORIGINS`.
  - **Deploy/runtime seams:** `ORIGINAL_ENV` (deploy gate, `run.py:59/96`) vs `ENVIRONMENT` (repository/tenant seam) — document the confusing pair as-is; note the WS-7 merge is pending. `ORIGINAL_DB` (`store.py:41` — SQLite path).
  - **Integrations (config-gated, no-op without config):** `BACKUP_DIR`, `BACKUP_INTERVAL_MINUTES`, `BACKUP_KEEP`; `BBOOK_API_URL`, `BBOOK_EXTERNAL_SECRET`; `LTI_PLATFORMS`, `LTI_PRIVATE_KEY`, `LTI_PRIVATE_KEY_FILE`, `LTI_PRIVATE_KEY_PEM`, `LTI_TOOL_URL`; `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `SENDGRID_API_KEY`.
- **Current state — 97/103 (F8):** `constants.py:206` `FEATURE_DIM = 103` (17 tiers). Two groups degrade to neutral 0.5 and are masked from the density matrix via `active_feature_mask` (`state.py`): **Tier 17 behavioral biometrics = 6 features** (`TIER17_CODES`, `constants.py:157–164`: `typing_speed_cv, burst_ratio, deletion_rate, pause_density, paste_event_rate, revision_depth`) is in `DISABLED_FEATURE_GROUPS` by default (`constants.py:364–366` — "requires live keystroke data from Bbook"); **Tier 10 semantic = 2 features** (`semantic_field_dispersion, semantic_centroid_proximity`, `constants.py:111–113`) degrades to neutral without sentence-transformers. `FEATURE_GROUPS`/`DISABLED_FEATURE_GROUPS` is a mutable module-global **set**, not env-controlled (`constants.py:357–366`). Net: 103 dimensional − 6 tier-17 = **97 active** in the default pilot config (fewer if sentence-transformers is absent, which drops the 2 semantic). Related nuance: `BASE_FEATURE_DIM = 96` (`constants.py:222`) is the stored-baseline dimension (tier-17 included as 0.5 placeholders) — distinct from the 97 "active" count; keep the two numbers from being conflated in the doc.
- **Change:**
  - Extend the `CLAUDE.md:44–50` table with rows for every flag above. For the two scoring-math flags give a default and a one-line "changes scores" warning. For security flags, add a one-line entry that points to OPS_RUNBOOK (owned by WS-1) rather than duplicating semantics. Mark integration flags "no-op without config."
  - Add a short "Feature dimensionality" note (in CLAUDE.md and/or MODEL_CARD-facing docs): "103 dimensional / **97 active** in the default pilot config — Tier 17 behavioral (6) is in `DISABLED_FEATURE_GROUPS` pending live keystroke data; Tier 10 semantic (2) needs sentence-transformers. `BASE_FEATURE_DIM=96` is the stored-baseline width, not the active count."
- **Files touched:** `CLAUDE.md`; the 97/103 note also lands where MODEL_CARD/README describe the pipeline.
- **Verify:** every name from `grep -rhoE "(os\.environ\.get|os\.getenv)\(['\"][A-Z_]+" original/ run.py --include=*.py | sort -u` that is behavior-affecting appears in the CLAUDE.md table (diff the two lists). `grep -n "97 active\|LENGTH_ADAPTIVE_WEIGHTS\|RANK_REMEDIATION" CLAUDE.md` present.

### 7. New documents, in priority order — D12, D13, D15
- **Current state:** ~76 live routes are documented only via FastAPI `/docs` (no prose reference — D12). `docs/adr/` holds 5 well-formed ADRs (001 quantum scoring … 005 student read-model) but three shipped decisions are unrecorded: default-OFF env-flag strategy, peer-pool null model, AI-likelihood detector (D13). No CHANGELOG, no incident-response runbook — while `dpa_template.md:84` commits to 48-hour breach notification with nothing backing it; no VPAT (D15).
- **Change (create, in this order):**
  1. **Incident-response runbook** backing the 48-hour DPA commitment (highest priority — a live legal commitment with no internal process).
  2. **Live API reference** page (or generated `openapi.md`) grouped by audience — pairs with task 4's endpoint table.
  3. **ADR-006** — Postgres convergence decision (cross-ref §10; the decision itself is owned by WS-6, this records it).
  4. **ADR-007** — AI-likelihood gating rationale (report-only contract + enablement gate criteria).
  5. **CHANGELOG.md**.
  6. **VPAT / accessibility conformance statement** — **write AFTER WS-4 (hotfix) and WS-8 (React AA) land**, so it describes the shipped a11y state, not the current one.
- **Files touched (new):** `docs/INCIDENT_RESPONSE.md`, `docs/API_REFERENCE.md` (or generated), `docs/adr/006-*.md`, `docs/adr/007-*.md`, `CHANGELOG.md`, `docs/VPAT.md` (deferred).
- **Verify:** files exist and cross-link; `grep -rn "48-hour\|48 hour" docs/dpa_template.md` now resolves to a runbook link. ADR-006/007 follow the 001–005 template shape.

### 8. Docstring pass on quantum/scoring.py — D14 (owned here, executed with WS-7)
- **Current state:** `original/quantum/scoring.py` docstring coverage is 1/10 (10%) — the module the MODEL_CARD's claims rest on. Adjacent live modules are well-covered (amplitude/conformal/null_pool 100%).
- **Change:** docstring pass on `scoring.py`'s public functions. **Do not execute standalone** — fold into WS-7's `ScoringConfig`/`ScoringContext` refactor so the code isn't documented twice (once now, once after the signature changes). WS-3 owns the *requirement*; WS-7 owns the *timing*.
- **Files touched:** `original/quantum/scoring.py` (during WS-7).
- **Verify:** `.venv/bin/python -m pytest` unaffected (docstrings only); a docstring-coverage check on `scoring.py` rises from 10% toward parity with the rest of `quantum/`.

## Acceptance criteria
- [ ] `ACTION_THRESHOLDS` (`constants.py:652`), README, and MODEL_CARD publish the **same** boundaries (`monitor 0.40–0.60`, `schedule_conversation 0.60–0.75`); `constants.py` carries the publish-sync comment. (D2)
- [ ] MODEL_CARD title version matches its history table (`v1.3.0`). (D7)
- [ ] `grep -rniE "AES|GCM" docs/encryption_policy.md docs/data_inventory.md` yields no present-tense at-rest claim; both docs describe Render disk encryption + TLS and state raw text IS stored; automatic-deletion claims are struck or marked "planned"; manual `delete_student` path retained. (D5)
- [ ] `docs/SECURITY_AUDIT.md`, `docs/BETA_PHASE1_TECH.md`, `docs/phase3-httpOnly-cookie-auth.md` each open with the dormant-stack banner; a live-stack re-audit is scheduled. (D4, D10)
- [ ] `grep -n "/api/v1/" README.md SETUP.md` returns nothing outside an explicit "dormant" heading; README has a live endpoint table, the `render.yaml` deploy story, a corrected FERPA paragraph, and an `ARCHITECTURE.md` link; both LTI sections point to CANVAS_RUNBOOK. (D1, D3, D6)
- [ ] Test-count and port claims updated in README + CLAUDE.md (`613`; port note aligned). (D8)
- [ ] Status headers on both root planning docs; OWNERS_MANUAL:4 is a complete sentence. (D11, D16)
- [ ] CLAUDE.md flag table lists every behavior-affecting env var (31-var grep ⊆ table for the behavioral ones), with the two scoring-math flags flagged as score-changing; 97-active/103-dimensional documented with the `BASE_FEATURE_DIM=96` distinction noted. (F3 slice, F8)
- [ ] Incident-response runbook, live API reference, ADR-006, ADR-007, CHANGELOG created; VPAT scheduled after WS-4/WS-8. (D12, D13, D15)
- [ ] scoring.py docstring requirement recorded against WS-7 (not executed standalone). (D14)

## Risks & watch-outs
- **This workstream touches `original/constants.py` and `original/quantum/scoring.py`.** The only permitted constants edit is the **comment** on `ACTION_THRESHOLDS` — do **not** reorder `ALL_FEATURE_CODES` or alter `NORM_BOUNDS` (CLAUDE.md "requires explicit permission"). The scoring.py change (task 8) is docstrings only and is deferred to WS-7; adding docstrings must not alter any executable line (flags-OFF scoring stays byte-identical to Phase 1).
- **Don't over-correct the compliance docs into a *new* false claim.** Manual deletion (`store.delete_student`, `original.cli.delete_student`) is real and live — the audit's "no retention scheduler" is about *automatic* deletion only. Strike automatic; keep manual. Verify Render's actual at-rest guarantee before asserting "disk encryption" as fact rather than "platform-managed."
- **F3 triple-ownership trap.** If WS-1 (runbook) and WS-7 (`ORIGINAL_ENV`/`ENVIRONMENT` merge) land in a different order, keep the CLAUDE.md table describing flags *as they currently behave*; do not pre-document a merge that hasn't shipped, or the table will lie in the other direction.
- **Version source-of-truth (D7) is only half-fixed here.** WS-3 aligns the MODEL_CARD *title*; pyproject (`0.0.0`) and the FastAPI app (`0.1.0`, `api.py:170`) still disagree. Note it; the code fix is out of WS-3 scope.
- **VPAT sequencing.** Writing it before WS-4/WS-8 would document a11y conformance the product doesn't yet meet — a procurement-facing false claim. Hold it.
- **Endpoint table drift.** The live route list is large (~76); a hand-written table will rot. Prefer generating `API_REFERENCE.md` from OpenAPI (task 7.2) and having README link it, rather than maintaining two hand tables.

## Sequencing within the workstream
1. **Task 1** (thresholds + MODEL_CARD version) — smallest, highest-signal, independently shippable. Do first.
2. **Task 2** (compliance docs) — highest institutional risk; independently shippable.
3. **Task 3** (dormant banners) — mechanical, independently shippable; unblocks the honest framing tasks 4/7 rely on.
4. **Task 6** (flag table + 97/103) — independent; coordinate only the *pointer* rows with WS-1's runbook.
5. **Task 5** (status headers + OWNERS_MANUAL) — trivial, independent.
6. **Task 4** (README/SETUP rewrite) — larger; depends on task 3's banner framing and pairs with task 7.2's API reference. Land task 7.2 (API reference) together with task 4 so README links a real page.
7. **Task 7** (new docs) — incident-response first (live legal commitment); ADRs/CHANGELOG next; **VPAT deferred** until WS-4 + WS-8.
8. **Task 8** (scoring.py docstrings) — **do not ship in WS-3**; hand to WS-7 to execute alongside `ScoringConfig`.

Independently shippable now: 1, 2, 3, 5, 6. Must land together: 4 + 7.2. Deferred/handed-off: 7.6 (VPAT → after WS-4/WS-8), 8 (→ WS-7).
