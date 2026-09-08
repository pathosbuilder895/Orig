# 07 — Performance, concurrency, and reliability tests

Scope: request latency on the scoring path, event-loop blocking in async
handlers, per-score table scans under `NULL_MODEL=impostor` and any non-`off`
`CHARACTERISTIC_WEIGHTS`, the single-worker assumption behind three in-memory
caches, SQLite contention, memory growth, and outbound timeouts.

Today: **no latency assertion exists anywhere**, one `threading.Thread` test
in the suite, no load harness, and the only throughput data is the CI timeout
comment. `scripts/benchmark.py` and `validation/benchmark/` measure accuracy,
not speed. This is the weakest surface in the repo.

---

## 1. Latency budgets (per PR, in-process)

Budgets are asserted with `TestClient` on a fixed synthetic profile
(5 baselines, 8 peers, 600-word submission), warm cache, measured as the
median of 5 calls after 1 warm-up. They are *generous* — the goal is to catch a
10× regression, not a 10 % one — and run on every PR.

| Path | Budget | Why this number |
|---|---|---|
| `POST /students/{id}/score`, flags off | 1.5 s | one feature extraction + one `score()`; spaCy load excluded by warm-up |
| same, demo flag set (`CONTEXT_MANIFEST`, `ADAPTIVE_WEIGHTS`, `NULL_MODEL=impostor`) | 3.0 s | adds the manifest pipeline and the peer-pool build |
| `POST /students/{id}/score/blend` | 6.0 s | rolling windows; scales with text length — fix the text |
| `POST /students/{id}/baseline/batch` with 10 × 400-word files | 8.0 s | ten extractions; §2 makes it non-blocking |
| `GET /students` (100 students, one tenant) | 0.3 s | listing must not deserialise state |
| `GET /health` | 0.05 s | it is polled |

Put them in `tests/perf/test_latency_budgets.py`, marker `perf`, with the
budget table as a committed dict so a change to a budget is a reviewed diff.
Use `time.perf_counter`, not wall-clock fixtures, and skip with
`uninformative` if the runner reports fewer than 2 CPUs (CI runners vary; the
30-minute-cap comment in `test.yml` is the history here).

## 2. Event-loop blocking (the exam-freeze bug)

Five `async def` handlers do CPU-bound work inline
(`routers/imports.py:26,110,147,235`, `students_baseline.py:342`,
`students.py:341`). During a bulk upload the event loop is held and live
exam heartbeats (`/proctor/*/beat`, seal writes) stall.

Test, `tests/perf/test_event_loop_not_blocked.py`, with `httpx.AsyncClient`
over the ASGI app:

```python
async def test_bulk_upload_does_not_starve_heartbeat(async_client, ten_files):
    upload = asyncio.create_task(async_client.post("/students/s1/baseline/batch", files=ten_files))
    beats = []
    while not upload.done():                        # keep beating until the upload ends
        due = perf_counter() + 0.05
        await asyncio.sleep(0.05)                   # this sleep is ITSELF starved if the loop is held
        beat = await async_client.get("/health")
        assert beat.status_code == 200
        beats.append(perf_counter() - due)          # lateness from when the beat was DUE
    await asyncio.wait_for(upload, 60)
    assert max(beats) < 0.25, f"heartbeat up to {max(beats):.2f}s late"
```

Red today. Two traps, learned in Phase A: timing the probe from *after* a
`sleep` gives a false green, because the sleep itself is starved and returns
only once the loop is free — measure lateness from when the beat was due;
and a single beat can be dodged by a handler that yields once early — beat
until the upload completes and assert on the maximum. The fix is
`run_in_threadpool` / `def` instead of `async def` for CPU handlers; the
test does not care which. Parametrise over all five
handlers so the fix cannot be partial.

## 3. Per-score full-table scans

`NULL_MODEL=impostor` builds the peer pool from `_repo().all_states()` — a
full select plus JSON deserialisation of every state in the store — on every
score. Any non-`off` `CHARACTERISTIC_WEIGHTS` does the same even on
`NULL_MODEL=none` deployments. `students_scoring.py:105` already memoises the
three call sites within one request (the I3 fix); nothing bounds it across
requests.

Tests:

- **Scan count.** Wrap `all_states` with a counting spy; one `/score` call
  makes at most one scan (pins I3). Two consecutive scores of the *same*
  tenant within N seconds make at most one scan once a cross-request cache
  exists — write it now, red, register it.
- **Scaling.** Seed 50 / 200 / 800 students in one tenant; score once at each
  size; assert latency grows sub-linearly (ratio of 800 to 50 < 4). Marker
  `slow`; weekly. Today it is linear in store size — the finding.
- **Tenant scoping.** The scan must only deserialise same-tenant states.
  Seed 100 states in tenant B, 8 in tenant A; scoring in A deserialises ≤ 8
  (spy on the deserialiser). If the implementation filters after
  deserialising, this is red and is also a privacy-adjacent cost.

## 4. The single-worker constraint

Three process-global structures assume one uvicorn worker: the login-throttle
bucket (`routers/_shared.py:227`), `principal._ENV_CACHE`
(tenant → environment, no invalidation), and `store._GENRE_STATS_CACHE` /
`PostgresRepository._genre_stats_cache`. `docs/AUDIT_2026-07-06.md` A4 names
the assumption; nothing enforces it.

- **Assert the deployment.** A test reads `render.yaml` / `start.sh` and
  asserts `--workers 1` (or the absence of a workers flag, with the default
  documented). If someone scales out, this fails first and points at the three
  caches.
- **Prove the failure mode.** Two `PostgresRepository` instances (the
  cross-instance coherence test in `03-api-persistence.md` §2) — red until the
  caches are invalidated by write or replaced by a TTL.
- **`_ENV_CACHE` staleness.** Upgrade a tenant demo→pilot mid-process; the
  *next* request must see pilot. Red today; a demo tenant that becomes real
  keeps the permissive rules until restart.

## 5. SQLite contention

`PRAGMA journal_mode=WAL` and `busy_timeout=5000` are set (`store.py:173`) and
asserted by reading the PRAGMA. Assert them by *contention*: 8 threads each
adding a baseline to the same student for 2 s; zero `database is locked`
errors; final `sample_count` equals total writes. Same test on Postgres proves
the contract suite's idempotency claims hold under real concurrency.

## 6. Memory

- Score 500 times in one process; RSS growth < 50 MB (`resource.getrusage`).
  Catches an unbounded cache — `_JWKS_CACHE` and `_all_states_cache` are the
  candidates.
- `_JWKS_CACHE` bounded: after fetching 100 distinct JWKS URLs, the dict holds
  ≤ the documented cap. Red until a TTL/LRU exists (also `04-security` §4).

## 7. Outbound timeouts and failure modes

Timeouts exist (Canvas 30 s, Bbook 10 s, JWKS 8 s, S3 60 s). Assert each is
*honoured* using a `MockTransport` that sleeps past the budget: the route
returns 502/504 within budget + 1 s, and the event loop is not blocked
meanwhile (reuse §2's heartbeat probe). For Bbook, replace the hand-rolled
`_FakeClient` with `MockTransport` so this test is possible — the fake cannot
sleep.

## 8. Load harness (weekly, not per PR)

`scripts/load_smoke.py`: 20 concurrent students each doing
login → 3 baseline uploads → 1 score → 1 blend, against a locally started
pilot-mode server with `NULL_MODEL=impostor`, 2-minute run. Reports p50/p95
per route and error count. Fails if p95 score > 5 s or any 5xx. Uses `httpx`
+ `asyncio`; no new dependency. Wire it into the weekly battery workflow
(§06 §7) and store the JSON as an artifact so the trend is visible.

Do not add locust/k6. The suite already has everything it needs.

## 9. Reliability of the tests themselves

Time-based assertions are the flakiest kind. Rules for this slice:

- Budgets are ≥ 3× the measured median at authoring time; write the measured
  number in the test's docstring.
- Every perf test is `uninformative`-aware: fewer than 2 CPUs, or a
  `CI_RUNNER_SLOW=1` env, downgrades a fail to a skip *with a recorded
  reason*, never silently.
- No `time.sleep` polling; `asyncio.wait_for` with explicit timeouts.
- Perf tests never share a `TestClient` with functional tests; they build
  their own so warm-up state is controlled.

## 10. Acceptance for this slice

- `tests/perf/` exists with budgets, the heartbeat-starvation test (red), the
  scan-count test, and the contention test.
- `render.yaml` worker-count assertion exists.
- `scripts/load_smoke.py` runs in the weekly workflow and posts p95s.
- Bbook client tests use `httpx.MockTransport`.
