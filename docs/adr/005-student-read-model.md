# ADR-005: A redacting read-model for the student dashboard

**Status:** Accepted — implemented 2026-06-15
**Date:** 2026-06-13
**Deciders:** Product owner (Andrew)
**Relates to:** ADR-003 (multi-tenant auth / principal model); the Student Dashboard build prompt (formation over surveillance)

## Context

The student dashboard's whole posture — *"the student is the reader, not the
subject … never expose the machinery that would let them reverse-engineer or
game the system"* — is a **security boundary**, not a copy guideline. The build
prompt's "DO NOT EXPOSE" list (tracked features, thresholds, trigger logic,
submission counts, detection methodology) is an API-contract requirement: the
front end must receive *only already-resolved, display-ready results*.

Today it does the opposite. The current `demo/student.html` enforces the
posture **in client-side JavaScript over raw data**:

- `GET /students/{id}` returns `baseline_vector` — the literal stylometric
  **feature codes and per-feature values** (`schemas.py` StudentStateResponse) —
  plus `sample_count`, `authenticated_count`, `effective_sample_count`,
  `purity`, `trajectory_confidence`. That's the tracked-feature list, the
  minimum-submission counts, and a baseline-confidence signal, all on the wire.
- The student client also calls **`/admin/manifests`** and
  **`/admin/corrections`** — admin endpoints — and receives raw
  `divergence_score` and the `action` enum, then converts them to a friendly
  "fidelity" number and sympathetic prose in JS (`fidFromDev()`).

The reframing is real and well-intentioned, but it is **theatre at the network
layer**: any student with devtools open sees the feature taxonomy, their exact
deviation numbers, the action enum, and their sample counts. This directly
violates the build prompt and hands a motivated student everything needed to
game the system.

The investigation also surfaced a **horizontal-authorization gap** independent
of the UI: `assert_student_access` (principal.py) scopes a `student`-role
principal to its whole **tenant**, not to its own id — so a logged-in student
can read `GET /students/<sameTenant:otherStudent>`. For staff that's correct;
for students it's a privacy hole.

## Decision

Introduce a **server-side redacting read-model** that the student dashboard
consumes exclusively, and stop the student client from ever touching
`/students/{id}`, `/admin/*`, or the raw `/score` payload.

1. **One token-resolved endpoint, no id in the path:**
   `GET /me/voice` resolves the student **from the session token** (the
   `/student-auth/me` pattern) and returns a single display-ready document.
   Because the client never supplies an id, id-tampering and the
   cross-student read are structurally impossible.
2. **Redaction is authoritative (server-side).** The forbidden fields are
   *projected away* before serialization — never sent, so devtools cannot peel
   them back. The "DO NOT EXPOSE" list becomes a code-level guarantee, not a
   copy convention.
3. **A projection layer** maps the rich internal state → the formation view
   (table below). The rich endpoints (`/students/{id}`, `/score`, `/admin/*`)
   are unchanged — they remain the **staff** surface (professor/operator), just
   no longer reachable by the student client.
4. **Tighten student-role authz to self-only** in `assert_student_access`
   (defence in depth, even though `/me/voice` carries no id).

### The redaction contract (per dashboard feature)

| Dashboard surface | Server sends (display-ready) | Server **never** sends |
|---|---|---|
| **The Fingerprint** | 6–8 named **voice dimensions** (Cadence, Diction, Texture, Register, Restraint…), each a 0–1 value **already blended** from multiple underlying features | raw `baseline_vector`, any `ALL_FEATURE_CODES` name, the feature→dimension mapping |
| **The Arc** | pre-smoothed fidelity series `[{period, fidelity, note?}]`, fidelity already = resolved (no raw math) | `divergence_score`, `action`, `trajectory_confidence`, deltas |
| **Voice Notes** | array of finished prose strings (formational register, addressing the student by name) | the scores/manifests that generated them; `human_explanation` (it speaks in "deviation/anomaly") |
| **Review Opportunities** | `[{invitation_prose, excerpt_locator?}]` — server decides *what qualifies* | the score, the threshold, "AI detected", any number |
| **The Library** | the student's own works: `[{title, date, kind}]` | provenance weights, auth counts |
| **Focus Coach** | only the supportive nudge text (today: client-side time-rotation — fine) | trigger timing, summoning signals, "struggle detected" |
| **Verified Authorship Record** | a positive credential as **named milestones** ("Voice Established → Affirmed"), resolved server-side | raw counts / "3 of 5 samples" / thresholds |
| **Formation Track** | restorative state `{step_label, supportive_copy}` | the pathway `reason` text (can say "voice divergence"), submission ids, timing internals |

## Options Considered

### Option A: Server-side redacting read-model (`GET /me/voice`) — CHOSEN
| Dimension | Assessment |
|---|---|
| Complexity | Medium — one endpoint + a projection/mapper + a voice-dimension taxonomy |
| Cost | Low — same FastAPI app, no new infra |
| Scalability | High — read-only, cacheable per student |
| Team familiarity | High — mirrors `/student-auth/me` + the ADR-003 principal model |

**Pros:** the posture becomes a real guarantee (devtools-proof); one auditable
choke point; kills the cross-student read; staff surfaces keep their rich data.
**Cons:** requires a stable "voice dimension" taxonomy *decoupled* from the
feature codes; the existing `student.html` must be refactored to read only this.

### Option B: Keep client-side reframing (status quo)
| Dimension | Assessment |
|---|---|
| Complexity | None (already built) |
| Cost | Zero |
| Scalability | n/a |
| Team familiarity | High |

**Pros:** nothing to build.
**Cons:** **violates the build prompt at the network layer** — feature codes,
deviation numbers, counts, and the action enum are all on the wire and in the
browser; a student can reverse-engineer and game the system; students call
`/admin/*`. Disqualifying for a formation-posture product. **Rejected.**

### Option C: Dedicated student BFF service
Separate backend-for-frontend microservice doing the redaction.
**Pros:** hard process boundary. **Cons:** a whole deployment surface for a
solo-operator pilot on one app; ADR-004 keeps us on one SQLite service.
**Over-engineered. Rejected.**

## Trade-off Analysis

The decisive force is that **"formation over surveillance" is only true if it's
true on the wire.** Option B's reframing is honest in spirit but false in
mechanism — the redaction has to live where the student cannot reach it, which
is the server. Option A pays a one-time cost (a projection layer + a voice
taxonomy that is itself kept server-side and out of the frontend repo) to make
the product's central promise enforceable and auditable. The voice-dimension
blend is the subtle part: it must be a genuine, personal visualization *and*
not a lookup table back to the 103 features — so dimensions are blends of
several features, and the mapping never ships to the client.

## Consequences

**Easier**
- The "DO NOT EXPOSE" list is enforced in one place, in code, not in copy review.
- Cross-student reads are gone (no id on the path + self-only authz).
- Designers can iterate on student copy/visuals against a stable, safe contract.

**Harder / must-do**
- Define and maintain the voice-dimension taxonomy (server-side only).
- Refactor `demo/student.html` to read `GET /me/voice` exclusively and delete
  its `/students/{id}`, `/admin/manifests`, `/admin/corrections`, and raw-score
  reads.
- A **leak test** becomes a permanent gate: the student network trace must
  contain no feature code, no numeric deviation/divergence, no sample counts,
  no thresholds.

**Revisit later**
- If Focus Coach ever becomes server-summoned, only the nudge text crosses —
  the "why" stays server-side (same principle).
- The voice taxonomy may need per-institution tuning; keep it backend config.

## Action Items

1. [x] Define the `VoiceView` response schema (the table's left column) in `schemas.py`. — `VoiceView` + nested models added.
2. [x] Add `GET /me/voice` in `api.py` — resolve student from the session token, 401 if anonymous/expired. Also added the companion redacting write surfaces `POST /me/work` (scores server-side, returns a redacted `VoiceSubmitResult`) and `POST /me/formation/advance`, so the student client never needs `/students/{id}/score` or `/students/{id}/formation` either.
3. [x] Build the projection layer (`original/voice.py`): feature vector → named voice dimensions (blended, mapping server-side only); deviation history → resolved Arc; corrections → Voice Notes (formational register, **not** `professor_narrative`); manifests → Review Opportunities (prose + locator, no score); formation pathway → restorative state with `reason` stripped; counts → named milestones.
4. [x] Tighten `assert_student_access` (principal.py): `student` role → only its own `student_id`, not the whole tenant.
5. [x] Refactor `demo/student.html` to consume only `/me/*`; removed all `/students/{id}`, `/admin/manifests`, `/admin/corrections`, and raw `/score` reads, and moved the client-side reframing server-side. (The guest showcase keeps its synthetic, baked-in demo data and makes no server calls. The student's own typed prose stays in their browser's localStorage for the strongest-sentences / vocabulary extras — that is their own data, never server-shipped.)
6. [x] Add a regression "leak test" (`tests/test_voice_leak.py`): asserts the `/me/voice` and `/me/work` payloads (and the raw projection over adversarial inputs) contain none of the forbidden tokens (feature codes, `deviation`, `divergence`, `purity`, counts, action enums, thresholds), plus proves the self-only authz (a student cannot read a classmate via `/students/{id}`).

**Verification:** full suite green — 622 passed, 5 xpassed, 0 failed. The guest dashboard path was rendered in-browser (fingerprint, arc, metrics, no console errors). The live `/me/*` routes are exercised by the pytest gate against a freshly-loaded app; the long-running local preview server predates the new routes and was intentionally **not** restarted (CLAUDE.md).
