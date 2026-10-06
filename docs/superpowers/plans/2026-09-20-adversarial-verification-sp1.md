# SP1 — Adversarial threat model, red-team harness, baseline hygiene — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first cycle of the adversarial-verification programme: a written threat model, a red-team measurement harness with gates, and the cheap baseline-poisoning / provenance-forgery fixes — so every later sub-project has a number to beat and the live P0 holes are closed.

**Architecture:** Three groups. (A) A design/threat-model spec doc + ADR + gap-register rows. (B) A new offline validation package `validation/adversarial/` that builds victim profiles from committed public-domain text, generates attacks (mechanical + cached-LLM), and scores them through the real API and `quantum.score()`, exposed as three-valued calibration gates. (C) Product-code hygiene: authorize the batch-upload route, gate the request-baseline route, bind proctor attestations to an exam and make them single-use, a report-only `baseline_integrity` block, and the keystroke→macro-summary change. Everything report-only or auth-tightening; nothing changes `deviation_score`/`recommendation` for an authorized caller.

**Tech Stack:** Python 3.12, FastAPI, scikit-learn 1.6.1, numpy, spaCy `en_core_web_sm`, pytest; JSON-doc persistence (SQLite + Postgres); esbuild for the Bluebook bundle; the Anthropic API in the validation environment only (offline attack generation, outputs cached & committed).

## Global Constraints

- **Venv (worktree):** use `/Users/andrew/Desktop/Original/.venv/bin/python` and `.../.venv/bin/pytest` — the relative `.venv` in a worktree does not exist. NEVER system python3.
- **Report-only / byte-identical:** no change here may alter `deviation_score`, `quantum_fidelity`, or `recommendation.action` for an *authorized* caller with unchanged input. New response fields default to `None`/absent. Prove with the `tests/fusion/test_wiring.py:193-210` cross-flag pattern and `tests/test_style_authorship.py:215-239` whole-body-equality pattern.
- **Feature ordering frozen:** do not touch `ALL_FEATURE_CODES` / `NORM_BOUNDS` ordering in `original/constants.py`. Tier 17 dims stay as 0.5 placeholders (removing the *tier* would renumber the vector — out of scope; we only remove *collection*).
- **Coverage floor:** CI runs `--cov-branch --cov-fail-under=98` on `original/`. New product code and new branches (especially abstention / uninformative paths) need tests. `validation/` is not under the 98% gate but harness code still gets tests.
- **Gates are three-valued:** `GateResult.verdict ∈ {pass, fail, uninformative}` and `passed == (verdict == "pass")` (`validation/calibration_gate.py:67-89`). A missing cached corpus → `uninformative`, never `pass`, never crash. Every `evaluate_g*` needs a failure witness in `validation/gate_contracts.py` (pass args after the first by KEYWORD — SIGNATURE TRAP at `:17-27`) or `tests/test_gate_falsifiability.py` fails.
- **Bluebook bundle:** after any `demo/bluebook/*.jsx` edit, rebuild (`cd demo/bluebook && npm run build`) and commit `bluebook.bundle.js` — production serves the committed bundle (Render has no Node).
- **Postgres layer:** repository/persistence changes must be run under `make test-postgres` (or local Docker Postgres) before push — a plain green local run does not cover that layer.
- **Provenance stays downgrade-never-reject:** an unauthorized trusted-provenance write is downgraded to `unverified`, not refused (matches `_authorize_provenance` at `original/routers/_shared.py:346-387`).
- **Commit style:** conventional (`Fix …`, `Add …`, `Refactor …`); one focused commit per step; co-author line per the session's attribution reminder.

## File Structure

**Group A (docs, no code):**
- Create `docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md` — the threat model.
- Create `docs/adr/ADR-010-keystroke-macro-only.md` — the keystroke decision.
- Modify `docs/testing/10-gap-register.md` — rows T-67…T-75.

**Group C (product code):**
- Modify `original/routers/students_baseline.py` — authorize batch upload; staff-gate request-baseline; consume attestation on write.
- Modify `original/student_auth.py` — attestation binds+checks `exam`; a `attestation_jti()` helper.
- Create `original/consumed_attestations.py` — single-use ledger (thin wrapper over the repo/store).
- Modify `original/store.py` + `original/postgres_repository.py` + `original/db/models/live.py` — `consumed_attestations` table; `composition_summary` in sample (de)serialize; stop persisting raw `keystroke_data`.
- Create `original/baseline_integrity.py` — the report-only diagnostic builder.
- Modify `original/quantum/scoring.py` + `original/schemas.py` + `original/routers/_shared.py` — attach `baseline_integrity` to the score response.
- Modify `original/quantum/professor_narrative.py` — mirror integrity notes under tone rules.
- Modify `original/schemas.py` — `composition_summary` on `AddSampleRequest`/`ScoreSubmissionRequest`; deprecate `keystroke_data`.
- Modify `original/quantum/state.py` — `composition_summary` field on `BaselineSample`.
- Modify `original/context/resolvers.py` — `resolve_composition_mode` reads `composition_summary`.
- Create `scripts/purge_keystroke_blobs.py` — one-off redaction (dry-run default).
- Modify `demo/bluebook/Exam.jsx` (+ rebuild `bluebook.bundle.js`) — `buildCompositionSummary`.
- Modify `docs/data_inventory.md`, `docs/STUDENT_DISCLOSURE.md`; delete `docs/TIER17_ENABLEMENT_RUNBOOK.md`.

**Group B (offline validation package):**
- Create `validation/adversarial/__init__.py`, `profiles.py` (victim construction), `generators.py` (attack generators over the `Generator` ABC), `corpus/` (committed Riddell-Juola + cached LLM attacks + manifests), `fetch_riddell_juola.py`, `gen_llm_attacks.py` (offline, needs API key), `runner.py` (score paths + metrics), `report.py`.
- Modify `validation/calibration_gate.py` — `evaluate_g_a1`…`evaluate_g_a6`, `run_all()` wiring, `GATE_LEGS`.
- Modify `validation/gate_contracts.py` — six failure witnesses.
- Create `docs/research/ADVERSARIAL_BASELINE_FINDINGS_2026-09-20.md` — first measurement.
- Tests: `tests/adversarial/` (harness unit tests), `tests/security/` additions, `tests/test_baseline_integrity.py`, `tests/context/test_composition_summary.py`.

---

## Phase 0 — Threat model spec

### Task 1: Threat-model spec, ADR-010, gap-register rows

**Files:**
- Create: `docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md`
- Create: `docs/adr/ADR-010-keystroke-macro-only.md`
- Modify: `docs/testing/10-gap-register.md`

**Interfaces:**
- Produces: gate names `G-A1`…`G-A6`, the frozen field contracts (`composition_summary`, `baseline_integrity`, three-band vocab, reason codes) that Tasks 5–20 implement. This doc is the source of truth those tasks cite.

- [x] **Step 1: Write the spec** using the repo pattern (Problem/Defects → Goals & non-goals → Architecture → Phase 0 gates → phases naming flags → Rollout → Risks → Deliverables). Paste the attacker-taxonomy table from the programme plan's "Sub-project 1 (detailed) → A" verbatim (attacks 1–9, motivating evidence R1–R10, existing control file:line, gap, severity, gate). Add the "What this product will not claim" section (R1/R2/R7: verification is unreliable under plausible register/genre shift or deliberate modification; cite the `professor_narrative.py:11-18` tone rules and the report-only posture as the existing expression of that). Define the five frozen contracts (band vocab `consistent|inconclusive|divergent`; reason codes `probe_too_short|artifact_unavailable|baseline_below_min|insufficient_peers|cross_genre_incomparable|channel_error`; `composition_summary` shape; `baseline_integrity` shape; signed-webhook contract for SP4).

- [x] **Step 2: Write ADR-010** (`docs/adr/ADR-010-keystroke-macro-only.md`) using the `ADR-0NN-<slug>.md` form: Context (raw per-key timing captured & stored at rest but Tier 17 disabled; FERPA posture; user decision 2026-09-20), Decision (macro summary only; retire Tier 17 collection & runbook; purge existing blobs; Tier 17 vector dims stay 0.5 placeholders since ordering is frozen), Consequences (no keystroke biometrics; `composition_summary` becomes the macro channel; `resolve_composition_mode` rewired).

- [x] **Step 3: Add gap-register rows** to `docs/testing/10-gap-register.md` (columns `ID | Gap | Blind spot | Doc | Effort | Acceptance | State`; last existing ID is T-66). Add:
  - `T-67 | Batch upload accepts trusted provenance without auth | B3 | this spec | S | test_unauthenticated_writes batch case green | red`
  - `T-68 | request-baseline callable by a student session | B3 | this spec | S | staff-only test green | red`
  - `T-69 | Proctor attestation replayable across exams/texts (6h, exam unchecked) | B3 | this spec | M | single-use per-exam test green | red`
  - `T-70 | No baseline-consistency/σ-inflation surfacing (obfuscated/outsourced/poisoned baselines) | B1 | this spec | M | baseline_integrity attached; G-A5/G-A6 measured | open`
  - `T-71 | Imitation of own baselines undetected (too-central band off) | B1 | this spec | L | G-A2 measured on committed corpus | open`
  - `T-72 | Paraphrase/round-trip laundering undetected | B1 | this spec | L | G-A3 measured | open`
  - `T-73 | Peer-imitation / collusion undetectable (aggregate null pool) | B1 | this spec | L | G-A4 measured | open`
  - `T-74 | Raw per-key keystroke timing stored at rest, uninventoried | B3 | this spec, data_inventory | M | purge script run; inventory row; capture is macro-only | open`
  - `T-75 | No minimum-baseline policy before primary score (cold-start FPR) | B1 | this spec, T-01 | M | baseline_readiness reported; G-A1 measured | open`

- [x] **Step 4: Verify cross-references resolve.** Run:
```bash
cd /Users/andrew/Desktop/Original/.claude/worktrees/original-dev-review-plan-c64201
grep -c "G-A[1-6]" docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md
grep -n "T-6[7-9]\|T-7[0-5]" docs/testing/10-gap-register.md | wc -l   # expect 9
test -f docs/adr/ADR-010-keystroke-macro-only.md && echo OK
```
Expected: gate references present, 9 new rows, ADR exists.

- [x] **Step 5: Commit**
```bash
git add docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md docs/adr/ADR-010-keystroke-macro-only.md docs/testing/10-gap-register.md
git commit -m "Add adversarial-verification threat model, ADR-010, gap rows T-67..T-75"
```

---

## Phase 1 — Provenance / replay security fixes (P0)

> **Correction after implementation (deep review 2026-09-20).** Tasks 2–3
> cite "existing red cases" at `tests/security/test_unauthenticated_writes.py:127,290`;
> those lines are route-list entries, not tests, so the "Expected: FAIL"
> steps below were never achievable as written. The tests landed as: the
> unit legs in `tests/test_students_baseline_batch.py`
> (`TestUploadBatchBranches`, `TestRequestProctoredBaseline`) and the
> real-deploy legs in the security file as two new dedicated tests. T-67's
> test asserts the **stored** sample, not only the response.

### Task 2: Authorize the batch-upload route

**Files:**
- Modify: `original/routers/students_baseline.py` (`upload_baseline_batch`, currently `:358`)
- Test: `tests/security/test_unauthenticated_writes.py` (existing red cases `:127,290`)

**Interfaces:**
- Consumes: `_authorize_provenance(request, student_id, requested) -> (effective, downgraded)` from `original/routers/_shared.py` (already imported in this module for `add_baseline`).
- Produces: batch upload downgrades unauthorized trusted provenance to `unverified` and reports `provenance_downgraded` on the response.

- [x] **Step 1: Read the existing red test** `tests/security/test_unauthenticated_writes.py` around `:127` and `:290` to see the exact request shape and current assertion (it currently documents the hole). Adjust it to assert the *fixed* behavior: an anonymous batch upload with `provenance=verified` results in stored samples at `unverified` weight (or `provenance_downgraded: true` in the response), not `verified`.

- [x] **Step 2: Run it to confirm it fails** (documents the hole today):
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/security/test_unauthenticated_writes.py -k batch -v
```
Expected: FAIL (currently accepts `verified`).

- [x] **Step 3: Add the `Request` param and authorize.** Change the signature to `def upload_baseline_batch(student_id: str, files: list[UploadFile] = File(...), provenance: str = Form("verified"), assignment: str = Form(""), request: Request = None):` and, immediately after the `if provenance not in AUTH_WEIGHTS` check, resolve the effective provenance once for the batch:
```python
provenance, provenance_downgraded = _authorize_provenance(request, student_id, provenance)
```
Then use `provenance` / `AUTH_WEIGHTS[provenance]` for every sample in the loop (they already read the local `provenance`), and add `"provenance_downgraded": provenance_downgraded` to the batch response dict.

- [x] **Step 4: Run the test to confirm it passes**, plus the full security file:
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/security/test_unauthenticated_writes.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**
```bash
git add original/routers/students_baseline.py tests/security/test_unauthenticated_writes.py
git commit -m "Fix batch baseline upload bypassing provenance authorization (T-67)"
```

### Task 3: Staff-gate the request-baseline route

**Files:**
- Modify: `original/routers/students_baseline.py` (`request_proctored_baseline`, `:246`)
- Test: `tests/security/test_unauthenticated_writes.py` (add a case)

**Interfaces:**
- Consumes: `_require_staff(request)` — the same guard the sibling `/baseline-requests/pending` uses (`students_baseline.py:334` area). Read it to copy the exact call and the 401/403 it raises.

- [x] **Step 1: Write the failing test** — a student-session (non-staff) POST to `/students/{id}/request-baseline` must be refused (401/403), while a staff principal is allowed (mock `bbook_client.is_enabled()` False so it 503s *after* the auth check, proving auth ran first).
```python
def test_request_baseline_requires_staff(client_student_session):
    r = client_student_session.post("/students/stu1/request-baseline", json={})
    assert r.status_code in (401, 403)
```

- [x] **Step 2: Run it, expect FAIL** (no auth today):
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/security/test_unauthenticated_writes.py -k request_baseline -v
```

- [x] **Step 3: Add the guard.** Give the handler a `request: Request` param and call `_require_staff(request)` as the first line of the body (before `bbook_client.is_enabled()`), mirroring `/baseline-requests/pending`.

- [x] **Step 4: Run, expect PASS.**
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/security/test_unauthenticated_writes.py -k request_baseline -v
```

- [x] **Step 5: Commit**
```bash
git add original/routers/students_baseline.py tests/security/test_unauthenticated_writes.py
git commit -m "Require staff for request-baseline provisioning route (T-68)"
```

### Task 4: Bind proctor attestations to an exam and make them single-use

**Files:**
- Modify: `original/student_auth.py` (`mint_proctor_attestation`, `verify_proctor_attestation` `:108-151`)
- Create: `original/consumed_attestations.py`
- Modify: `original/store.py` (+ `postgres_repository.py`, `db/models/live.py`) — `consumed_attestations` table
- Modify: `original/routers/students_baseline.py` (`add_baseline`) — consume on proctored write
- Test: `tests/test_student_auth.py`, `tests/security/test_unauthenticated_writes.py`

**Interfaces:**
- Produces: `attestation_jti(token: str) -> str` (a stable id = `sha256(payload)` of the attestation), and `consumed_attestations.mark_used(jti, tenant, exam, student_id) -> bool` returning `False` if already used (replay).

- [x] **Step 1: Write failing tests.** (a) `verify_proctor_attestation(token, student_id, exam=...)` returns False when the token's `exam` differs from the passed `exam`. (b) An attestation used once for a baseline write cannot be reused for a second write (replay refused). Put the crypto test in `tests/test_student_auth.py`, the route replay test in `tests/security/`.
```python
def test_attestation_checks_exam():
    t = mint_proctor_attestation("stu1", exam="EXAM_A")
    assert verify_proctor_attestation(t, "stu1", exam="EXAM_A") is True
    assert verify_proctor_attestation(t, "stu1", exam="EXAM_B") is False
```

- [x] **Step 2: Run, expect FAIL** (verify ignores exam today):
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_student_auth.py -k exam -v
```

- [x] **Step 3: Add `exam` checking.** In `verify_proctor_attestation`, add an optional `exam: str | None = None` param; after the existing `sid` check, `if exam is not None and body.get("exam") != exam: return False`. Add `attestation_jti(token)` returning `sha256(payload_part).hexdigest()`.

- [x] **Step 4: Add the single-use ledger.** Create `original/consumed_attestations.py` with `mark_used(jti, tenant, exam, student_id) -> bool` that inserts into a `consumed_attestations(jti TEXT PRIMARY KEY, tenant_id TEXT, exam TEXT, student_id TEXT, used_at TEXT)` table and returns `False` on `IntegrityError` (already used). Add the SQLite `CREATE TABLE IF NOT EXISTS` (PRAGMA-guarded, following `store.py:356-364`), the Postgres model in `db/models/live.py`, and the `postgres_repository.py` mirror. Wire consumption into `add_baseline`: when the effective provenance is `proctored` and an `X-Proctor-Attestation` header is present, call `mark_used`; if it returns `False`, downgrade to `unverified` with `provenance_downgraded=True` (do not 4xx — keep the sample, matching the downgrade-never-reject rule). Design note: consume only on a *successful* admit (after `state.add_sample`), so a drift-held 202/409 does not burn the attestation.

- [x] **Step 5: Run tests + full auth + security suites, expect PASS:**
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_student_auth.py tests/security/ -v
```

- [x] **Step 6: Postgres check** (persistence layer touched):
```bash
make test-postgres
```
Expected: consumed_attestations tests pass on the PG backend.

- [x] **Step 7: Commit**
```bash
git add original/student_auth.py original/consumed_attestations.py original/store.py original/postgres_repository.py original/db/models/live.py original/routers/students_baseline.py tests/test_student_auth.py tests/security/
git commit -m "Bind proctor attestation to exam and make single-use (T-69)"
```

---

## Phase 2 — Report-only baseline integrity diagnostic

### Task 5: `baseline_integrity` builder

**Files:**
- Create: `original/baseline_integrity.py`
- Test: `tests/test_baseline_integrity.py`

**Interfaces:**
- Consumes: `StudentState.loo_distances` (`state.py:559-596`), `StudentState.baseline_std` (`:248-272`), `StudentState.samples[*].provenance/submitted_at/auth_weight`, and an optional impostor `sigma_null` array from `original/quantum/null_pool.py:fit_impostor_gaussian`.
- Produces: `build_baseline_integrity(state, impostor_stats=None) -> BaselineIntegrity | None` where `BaselineIntegrity` is a frozen dataclass with fields `n_baselines:int, min_required:int (=3), readiness:str ("ready"|"thin"|"absent"), provenance_mix:dict[str,int], span_days:int|None, loo_outlier_samples:list[dict] ([{index:int, z:float}]), sigma_inflation:float|None, notes:list[str]`. Returns `None` only when the state has zero samples (mirror the abstain-to-None convention).

- [x] **Step 1: Write failing tests.** A state with 3 tight baselines → `readiness="ready"`, empty `loo_outlier_samples`, `sigma_inflation` small. A state with one register-mismatched outlier baseline → that index appears in `loo_outlier_samples` with `z` above a stated cutoff (use a modified-z / MAD rule over `loo_distances`, cutoff 3.5). A state with 2 samples → `readiness="thin"`. Zero samples → `None`.
```python
def test_flags_loo_outlier_baseline():
    state = _make_state_with_outlier()      # 3 tight + 1 far sample
    bi = build_baseline_integrity(state)
    assert any(o["z"] > 3.5 for o in bi.loo_outlier_samples)
```

- [x] **Step 2: Run, expect FAIL** (module absent):
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_baseline_integrity.py -v
```

- [x] **Step 3: Implement `original/baseline_integrity.py`.** Compute: `n_baselines` = count of `auth_weight>0` samples; `readiness` = `absent` if 0, `thin` if `< MIN_BASELINES` (import `MIN_BASELINES=3` — reuse the constant from `style_authorship`/`fusion`, do not redefine), else `ready`; `provenance_mix` = Counter of provenances; `span_days` from min/max parseable `submitted_at` (None if unparseable); `loo_outlier_samples` via modified z-score (`0.6745*(d - median)/MAD`, cutoff 3.5) over `state.loo_distances` (empty if `<2` samples); `sigma_inflation` = when `impostor_stats` given, the fraction of features where `state.baseline_std > sigma_null` (else None); `notes` = short deterministic strings ("baseline thinner than N=3", "one sample stylistically unlike the others", "baseline spread wider than the peer population") gated on the computed values. No text, no numbers-in-prose beyond counts. All wrapped so any exception returns `None`.

- [x] **Step 4: Run, expect PASS.**
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_baseline_integrity.py -v
```

- [x] **Step 5: Commit**
```bash
git add original/baseline_integrity.py tests/test_baseline_integrity.py
git commit -m "Add report-only baseline_integrity diagnostic (T-70)"
```

### Task 6: Attach `baseline_integrity` to the score response (byte-identical when absent)

**Files:**
- Modify: `original/quantum/scoring.py` (dataclass field, near `:749` where `style_authorship` lives)
- Modify: `original/schemas.py` (`BaselineIntegrityOut` + field on `Layer7OutputResponse` near `:864`)
- Modify: `original/routers/_shared.py` (populate near `:511-541`, the response assembly)
- Test: `tests/test_baseline_integrity.py`, reuse the `tests/fusion/test_wiring.py` pattern

**Interfaces:**
- Consumes: `build_baseline_integrity` (Task 5).
- Produces: `Layer7OutputResponse.baseline_integrity: BaselineIntegrityOut | None = None`.

- [x] **Step 1: Write the invariant test** — score a payload with and without a peer pool; assert `deviation_score`, `quantum_fidelity`, `recommendation.action` are identical whether `baseline_integrity` is present or not (pop the key, compare the rest), mirroring `test_api_flag_is_attach_only`.

- [x] **Step 2: Run, expect FAIL** (field absent).

- [x] **Step 3: Add the dataclass field** on the internal `Layer7Output` (default `None`), the `BaselineIntegrityOut` pydantic model (mirror the dataclass 1:1, `model_config = {"protected_namespaces": ()}` if any `model_*` field — none here), the response field, and populate it in `_shared.py` where the other report-only experts are attached. It is computed **unconditionally** (no flag — it changes no score) but only when a state exists; on any error leave `None`.

- [x] **Step 4: Run, expect PASS**, plus the broad score-response tests:
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_baseline_integrity.py tests/test_scoring_router_branches.py -v
```

- [x] **Step 5: Commit**
```bash
git add original/quantum/scoring.py original/schemas.py original/routers/_shared.py tests/test_baseline_integrity.py
git commit -m "Attach report-only baseline_integrity to score response (T-70)"
```

### Task 7: Mirror integrity notes into the professor narrative

**Files:**
- Modify: `original/quantum/professor_narrative.py` (near the `ai_likelihood` consumption at `:751-755`)
- Test: `tests/test_professor_narrative.py`

- [x] **Step 1: Write failing test** — when `baseline_integrity.readiness == "thin"` or `loo_outlier_samples` non-empty, the narrative's `observations`/`confidence_note` gains a neutral, innocent-first note (no "cheating"/verdict/numbers), and when integrity is clean the narrative is unchanged.

- [x] **Step 2: Run, expect FAIL.**

- [x] **Step 3: Implement** — read `getattr(layer7, "baseline_integrity", None)` defensively; append tone-compliant notes (e.g., "This student's baseline is still small, so treat any signal as provisional." / "One of the baseline writings looks stylistically unlike the others; consider confirming its source."). Follow the module's tone rules (`:11-18`).

- [x] **Step 4: Run, expect PASS.**
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_professor_narrative.py -v
```

- [x] **Step 5: Commit**
```bash
git add original/quantum/professor_narrative.py tests/test_professor_narrative.py
git commit -m "Surface baseline_integrity notes in professor narrative (T-70)"
```

---

## Phase 3 — `composition_summary` and keystroke macro-only

### Task 8: `composition_summary` on schemas, sample, and persistence

**Files:**
- Modify: `original/schemas.py` (`AddSampleRequest`, `ScoreSubmissionRequest`)
- Modify: `original/quantum/state.py` (`BaselineSample`)
- Modify: `original/store.py` + `original/postgres_repository.py` (`_serialize`/`_deserialize`)
- Test: `tests/context/test_composition_summary.py`

**Interfaces:**
- Produces: the frozen `composition_summary` object `{session_seconds:int, word_count:int, paste_attempts:int, focus_losses:int, revision_count:int, started_at:str, ended_at:str, exam_config:{block_copy:bool, min_words:int, duration_min:int}}` on requests and on `BaselineSample.composition_summary: dict | None = None`.

- [x] **Step 1: Write failing round-trip test** — a `BaselineSample` with a `composition_summary` serializes and deserializes intact through `store._serialize`/`_deserialize`, and a sample without it deserializes to `None` (additive `.get()` default, per `store.py:761-762`).

- [x] **Step 2: Run, expect FAIL.**

- [x] **Step 3: Add the field** to `AddSampleRequest` and `ScoreSubmissionRequest` (`composition_summary: dict | None = None`, documented as the macro replacement for `keystroke_data`), to `BaselineSample` (dataclass field + include in `add_baseline`'s constructor call), and to `_serialize`/`_deserialize` in both `store.py` and `postgres_repository.py` (`.get("composition_summary")`).

- [x] **Step 4: Run, expect PASS** + Postgres:
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/context/test_composition_summary.py -v && make test-postgres
```

- [x] **Step 5: Commit**
```bash
git add original/schemas.py original/quantum/state.py original/store.py original/postgres_repository.py tests/context/test_composition_summary.py
git commit -m "Add composition_summary macro-timing field (schema + persistence)"
```

### Task 9: `resolve_composition_mode` reads the macro summary (byte-identical output vocab)

**Files:**
- Modify: `original/context/resolvers.py` (`resolve_composition_mode` `:538-566`)
- Test: `tests/context/test_composition_summary.py`

- [x] **Step 1: Write failing test** — given a `composition_summary` carrying `paste_attempts>0` / high `revision_count`, `resolve_composition_mode` returns the SAME output vocabulary as it did from the equivalent `keystroke_data` blob (`software_mediated=True` on paste; `edit_signature='heavy'` on the existing thresholds). Add a byte-identity assertion: for a summary derived from a given blob, the resolver output equals the resolver output from that blob.

- [x] **Step 2: Run, expect FAIL.**

- [x] **Step 3: Implement** — teach `resolve_composition_mode` to prefer `composition_summary` when present, deriving `paste_event_rate`/`deletion_rate`/`revision_depth` proxies from `paste_attempts`/`revision_count`/`session_seconds` with the *same thresholds* it used on `keystroke_data`; keep the `keystroke_data` path working for one release. Do not change the output keys or the text-only fallback.

- [x] **Step 4: Run, expect PASS**, then the score-invariance check under the manifest flag (this is the one score-touching path):
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/context/ -v
CONTEXT_MANIFEST_ENABLED=1 /Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/context/test_composition_summary.py -v
```

- [x] **Step 5: Commit**
```bash
git add original/context/resolvers.py tests/context/test_composition_summary.py
git commit -m "Read composition_summary in resolve_composition_mode (unchanged output vocab)"
```

### Task 10: Stop persisting raw keystrokes + purge script

**Files:**
- Modify: `original/routers/students_baseline.py` + `original/routers/students_scoring.py` (drop raw arrays on ingest)
- Create: `scripts/purge_keystroke_blobs.py`
- Test: `tests/test_purge_keystroke_blobs.py`

- [x] **Step 1: Write failing tests** — (a) after `add_baseline` with a `keystroke_data` blob containing `keystrokes`/`pauses` arrays, the persisted sample's stored blob has those arrays stripped (only macro fields, if any, retained), and `composition_summary` (when supplied) is stored; (b) `purge_keystroke_blobs.py --apply` rewrites an existing profile row removing `keystrokes`/`pauses`, and `--dry-run` (default) changes nothing and reports the count.

- [x] **Step 2: Run, expect FAIL.**

- [x] **Step 3: Implement** — on ingest, before constructing `BaselineSample`, strip `keystrokes`/`pauses` from any incoming `keystroke_data` (keep the field accepted for one release for backward compat, but never persist raw arrays); prefer `composition_summary`. Write `scripts/purge_keystroke_blobs.py` with a dry-run default that iterates `student_profiles` (SQLite and Postgres via the repo), removes `keystrokes`/`pauses` from each sample's `keystroke_data`, and reports counts; `--apply` writes back.

- [x] **Step 4: Run, expect PASS** + Postgres:
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_purge_keystroke_blobs.py -v && make test-postgres
```

- [x] **Step 5: Commit**
```bash
git add original/routers/students_baseline.py original/routers/students_scoring.py scripts/purge_keystroke_blobs.py tests/test_purge_keystroke_blobs.py
git commit -m "Stop persisting raw keystroke arrays; add purge script (T-74)"
```

### Task 11: Bluebook emits `composition_summary`

**Files:**
- Modify: `demo/bluebook/Exam.jsx` (`buildKeystrokeData` → add `buildCompositionSummary`; `bbSubmitToOriginal` payload)
- Rebuild: `demo/bluebook/bluebook.bundle.js`

- [x] **Step 1: Add `buildCompositionSummary()`** returning the frozen shape from the refs already maintained (`totalRef`, `revsRef`, `delsRef`, `startRef`, `pausesRef`, blur/warn counters, `cfg`): `{session_seconds, word_count, paste_attempts: revsRef.filter(type==='paste').length, focus_losses: warnings, revision_count, started_at, ended_at, exam_config:{block_copy: !!cfg.blockCopy, min_words: cfg.minWords, duration_min: cfg.duration}}`. Stop building the per-key `keystrokes` array.

- [x] **Step 2: Send it** — in `bbSubmitToOriginal` (`Exam.jsx:214-226`) replace `keystroke_data: keystrokeData` with `composition_summary: buildCompositionSummary()`; do the same in `bbScoreWithOriginal`.

- [x] **Step 3: Rebuild and verify the bundle changed:**
```bash
cd /Users/andrew/Desktop/Original/.claude/worktrees/original-dev-review-plan-c64201/demo/bluebook && npm run build
git status --porcelain bluebook.bundle.js   # expect it modified
```

- [x] **Step 4: Dispatch the `bluebook-builder` agent** (per the session's agent list) to confirm the build is clean and the bundle is byte-consistent, or run `npm run build` twice and diff.

- [x] **Step 5: Commit**
```bash
git add demo/bluebook/Exam.jsx demo/bluebook/bluebook.bundle.js
git commit -m "Bluebook: emit macro composition_summary instead of per-key keystrokes"
```

### Task 12: Docs — inventory, disclosure, retire Tier 17 runbook

**Files:**
- Modify: `docs/data_inventory.md` (add a keystroke/macro-timing row reflecting reality)
- Modify: `docs/STUDENT_DISCLOSURE.md` (`:19` — focus events are discarded, not retained; capture is macro-only)
- Delete: `docs/TIER17_ENABLEMENT_RUNBOOK.md` (use `git rm`)

- [x] **Step 1: Update `docs/data_inventory.md`** — add a row: composition macro-summary (session seconds, counts) retained on the sample; raw per-key timing NO LONGER collected or stored (was previously stored uninventoried — now purged).

- [x] **Step 2: Correct `docs/STUDENT_DISCLOSURE.md:19`** — focus/blur events are shown to the student during the exam and NOT transmitted or retained; keystroke *dynamics* are not collected.

- [x] **Step 3: Retire the runbook**
```bash
git rm docs/TIER17_ENABLEMENT_RUNBOOK.md
```

- [x] **Step 4: Commit**
```bash
git add docs/data_inventory.md docs/STUDENT_DISCLOSURE.md
git commit -m "Docs: macro-only keystroke posture; retire Tier 17 runbook (ADR-010)"
```

---

## Phase 4 — Red-team harness and gates

> These tasks build the offline measurement rig. The LLM-attack *generation* (Task 15) runs once, offline, in the validation env with an API key; its outputs are committed so the gates (Task 19) replay hermetically. On a fresh checkout without the committed LLM cache, the LLM-driven gates return `uninformative`, never `pass`.

### Task 13: Harness package + victim-profile construction

**Files:**
- Create: `validation/adversarial/__init__.py`, `validation/adversarial/profiles.py`
- Test: `tests/adversarial/test_profiles.py`

**Interfaces:**
- Consumes: `validation/public_authors/` loaders and `validation/pan20_cross_fandom/` (deterministic SHA-256 selection convention).
- Produces: `build_victim_profiles(n_baselines:int, seed:int) -> list[VictimProfile]` where `VictimProfile = {victim_id:str, baselines:list[str], genuine_holdout:list[str], impostor_docs:list[str]}`; `N` ∈ {3,5,10}.

- [x] **Step 1: Write failing test** — `build_victim_profiles(3, seed=…)` returns ≥8 victims, each with exactly 3 baselines, ≥1 genuine holdout drawn from a *different work* of the same author where possible, and impostor docs from other authors; selection is deterministic across two calls with the same seed.

- [x] **Step 2: Run, expect FAIL.**

- [x] **Step 3: Implement `profiles.py`** reusing the public-author corpus loaders; deterministic ordering by `sha256`; cross-work holdout where the manifest supports it (note `validation/public_authors/cross_work_manifest.json` has 2 works/author).

- [x] **Step 4: Run, expect PASS.** **Step 5: Commit.**

### Task 14: Mechanical obfuscation generator

**Files:**
- Create: `validation/adversarial/generators.py` (`MechanicalObfuscation`)
- Test: `tests/adversarial/test_generators_mechanical.py`

**Interfaces:**
- Consumes: the `Generator` ABC (`validation/diagnostics/generators.py:49-73` — `configured`, `skip_reason()`, `load_samples()`, must raise not fabricate); `original/data/word_frequencies.json`; spaCy `en_core_web_sm`.
- Produces: `MechanicalObfuscation(seed).transform(text) -> str` — deterministic "dumbing down" (split at coordinating conjunctions, thin adjectives/adverbs, swap high-syllable words for frequent shorter ones).

- [x] **Step 1: Write failing test** — output has strictly lower mean sentence length and lower mean word length than input on a fixture paragraph, and is deterministic for a fixed seed.

- [x] **Step 2: Run, expect FAIL. Step 3: Implement** (no randomness beyond the seed; per study §4.5). **Step 4: PASS. Step 5: Commit.**

### Task 15: LLM attack generators + offline generation script (cached, hermetic)

**Files:**
- Modify: `validation/adversarial/generators.py` (`LLMImitation`, `LLMParaphrase`, `LLMRoundTrip`)
- Create: `validation/adversarial/gen_llm_attacks.py` (offline runner; needs `ANTHROPIC_API_KEY`)
- Create: `validation/adversarial/corpus/llm_attacks/` (committed cache + `manifest.json`)
- Test: `tests/adversarial/test_generators_llm_cache.py`

**Interfaces:**
- Produces: each LLM generator implements the `Generator` ABC; `configured` is True iff the committed cache covers the requested victim/attack; `load_samples()` returns cached docs; **raises** on a cache miss (never fabricates). The manifest records `{model_id, prompt_sha, doc_sha, victim_id, attack}` per doc.

- [x] **Step 1: Write failing test** — with the committed cache present, `LLMParaphrase.configured` is True and `load_samples()` returns docs whose SHA matches the manifest; with the cache absent, `configured` is False and `skip_reason()` explains it; `load_samples()` on a miss raises (hermetic — no network in tests).

- [x] **Step 2: Run, expect FAIL.**

- [x] **Step 3: Implement the generators as cache-readers** (no API client in the product/test path). Implement `gen_llm_attacks.py` as the offline populator: it imports `anthropic`, reads victim profiles, prompts the latest Claude model (imitation = "write ~N words on {topic} in the style of these baselines: …"; paraphrase = "rewrite preserving meaning"; round-trip = EN→DE→EN and EN→JA→EN), and writes docs + manifest into `corpus/llm_attacks/`. Lock the env (`validation/benchmark/reproducibility.lock_environment()` pattern) before importing `original.*`.

- [ ] **Step 4: BLOCKED — needs a human with an `ANTHROPIC_API_KEY` in the validation environment.** Not run in this session (no key available). Run the offline generator once to populate and commit the cache:
```bash
pip install anthropic   # not installed in this venv yet
ANTHROPIC_API_KEY=sk-ant-… /Users/andrew/Desktop/Original/.venv/bin/python -m validation.adversarial.gen_llm_attacks --n-baselines 3,5,10
```
Until this runs, `validation/adversarial/corpus/llm_attacks/` does not exist, and `LLMImitation`/`LLMParaphrase`/`LLMRoundTrip` correctly report `configured=False` — gates G-A2/G-A3 (Task 19) will read as `uninformative`, by design, not `fail`.

- [x] **Step 5: Run tests, expect PASS. Step 6: Commit** the generators, the script (cache-reader classes + populator script only — the committed cache itself is Step 4's output, still pending).

### Task 16: Import the Riddell-Juola CC0 corpus

**Files:**
- Create: `validation/adversarial/fetch_riddell_juola.py`, `validation/adversarial/corpus/riddell_juola/` (committed), `validation/adversarial/corpus/riddell_juola/PROVENANCE.md`
- Test: `tests/adversarial/test_riddell_juola.py`

- [x] **Step 1:** Write `fetch_riddell_juola.py` to download the CC0 bundle (Zenodo DOI 10.5281/zenodo.18729526), verify size/hash, and extract control/obfuscation/imitation essays into `corpus/riddell_juola/`. **Step 2:** Run it, commit the extracted CC0 text + a `PROVENANCE.md` (DOI, CC0, retrieval date). **Step 3:** Write a loader test asserting the three splits load. **Step 4:** PASS. **Step 5:** Commit.

### Task 17: Baseline-poisoning scenarios

**Files:**
- Create: `validation/adversarial/poisoning.py`
- Test: `tests/adversarial/test_poisoning.py`

**Interfaces:**
- Produces: `poison_profile(profile, mode) -> VictimProfile` for `mode ∈ {"obfuscated_baselines","sigma_inflation","outsourced_baselines"}` (obfuscated = MechanicalObfuscation over baselines; sigma_inflation = mix in a different author's registers; outsourced = replace baselines with another public author's text).

- [x] **Step 1:** Failing test that each mode returns a profile whose baselines differ from the original in the intended direction (σ up for inflation; different author for outsourced). **Step 2–5:** implement, PASS, commit.

### Task 18: Runner + metrics

**Files:**
- Create: `validation/adversarial/runner.py`
- Test: `tests/adversarial/test_runner.py`

**Interfaces:**
- Consumes: `original.quantum.score` (fast path) and a TermSim-style API client (deployment path); `ACTION_THRESHOLDS`.
- Produces: `run_attack(profile, attack, path="score"|"api") -> AttackResult` with per-action-bar impostor catch rate, genuine-holdout FPR at N∈{3,5,10}, imitation success (fraction at `no_action`), poisoning success, and the σ-inflation curve.

- [x] **Step 1:** Failing test on a tiny fixture — a genuine holdout scores below `escalate`, a blatant impostor scores at/above `monitor`; metrics dict has the documented keys. **Step 2:** Run, FAIL. **Step 3:** Implement both paths (report the API-path number; use the fast path for the σ curve); cap corpus so a full run is < 30 min. **Step 4:** PASS. **Step 5:** Commit.

### Task 19: Gates G-A1…G-A6 + falsifiability witnesses + wiring

**Files:**
- Modify: `validation/calibration_gate.py` (`evaluate_g_a1`…`evaluate_g_a6`, `run_all`, `GATE_LEGS`, `_want`/`_mark`)
- Modify: `validation/gate_contracts.py` (six witnesses)
- Test: `tests/test_gate_falsifiability.py` (auto-enforced), `tests/adversarial/test_gates.py`

**Interfaces:**
- Produces: G-A1 cold-start FPR (genuine holdout FPR at N∈{3,5,10} ≤ bar); G-A2 imitation catch; G-A3 paraphrase/MT catch; G-A4 peer-imitation separation; G-A5 σ-inflation (catch rate must not collapse as σ grows); G-A6 baseline-integrity detects poisoned profiles. Each three-valued; `uninformative` when its corpus (esp. the committed LLM cache) is absent.

- [ ] **Step 1:** Write failing witness tests — each witness constructs an input on which the gate must return `verdict="fail"` (pass args after the first by KEYWORD, per the SIGNATURE TRAP). **Step 2:** Run `tests/test_gate_falsifiability.py`, expect FAIL (gates unregistered). **Step 3:** Implement the six `evaluate_g_a*` with the `uninformative` guards (missing corpus → uninformative; zero attacks generated → uninformative), register witnesses, wire into `run_all`/`GATE_LEGS`/`_want`/`_mark` with `try/except → _machinery_error_result`. **Step 4:** Run:
```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_gate_falsifiability.py -v
/Users/andrew/Desktop/Original/.venv/bin/python -m validation.calibration_gate --only "G-A1,G-A2,G-A3,G-A4,G-A5,G-A6"
```
Expected: witnesses pass; gates run (uninformative without cache, pass/fail with it). **Step 5:** Commit.

### Task 20: First findings doc

**Files:**
- Create: `docs/research/ADVERSARIAL_BASELINE_FINDINGS_2026-09-20.md`

- [ ] **Step 1:** Run the harness with the committed corpora and record, per attack, the catch rate at each action bar and the genuine FPR at N∈{3,5,10} — the numbers every later SP must beat. Include the honesty caveats (R1 contested; R2 verification≠attribution; corpus≠students). **Step 2:** Commit.

---

## Verification checklist (whole SP1)

- [ ] Full suite green: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ -q` (budget 11–12 min).
- [ ] Postgres layer: `make test-postgres` (Tasks 4, 8, 10 touch persistence).
- [ ] Security suite green: `tests/security/` (T-67/68/69 flip red→green).
- [ ] Gate legs: `/Users/andrew/Desktop/Original/.venv/bin/python -m validation.calibration_gate --only "G-A1,G-A2,G-A3,G-A4,G-A5,G-A6"` — pass with committed corpora, uninformative without.
- [ ] Falsifiability: `tests/test_gate_falsifiability.py` green.
- [ ] Score-invariance: `baseline_integrity` and `composition_summary` do not move `deviation_score`/`recommendation` — the `tests/fusion/test_wiring.py:193-210` pattern; and `python -m validation.termsim run --matrix standard` `baseline` cell diff is empty (Task 9 is the only score-touching path).
- [ ] Coverage: `--cov-branch --cov-fail-under=98` on `original/` still passes (new branches in `baseline_integrity.py`, `consumed_attestations.py`, resolver path covered).
- [ ] Bluebook bundle rebuilt and committed (Task 11).
- [ ] Docs: threat model, ADR-010, gap rows, data_inventory, STUDENT_DISCLOSURE updated; Tier 17 runbook removed.
