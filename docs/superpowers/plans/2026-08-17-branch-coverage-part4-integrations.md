# Branch Coverage Part 4 — Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-08-17-branch-coverage-index.md` §Global Constraints first — they all apply here.

**Goal:** Close the 75 missing branches in the integrations cluster (72.63%): the Bbook HTTP client (0% branch), the calibration-lab runner (0%), the report-only expert loaders (`style_authorship`, `ai_likelihood`, `fusion/`), and Canvas live import.

**Architecture:** Every external HTTP surface is faked at the `httpx` seam (a stub client class recording requests and replaying canned responses) — no network, no respx dependency. Loader tests exercise the documented **fail-closed** contracts: a bad artifact must yield abstention (`None`), never a fallback or a raise.

**Tech Stack:** pytest, monkeypatch, tmp_path JSON artifacts.

**Baseline data:** `2026-08-17-branch-coverage-baseline.md` §integrations.

## Global Constraints (additional to the index's)

- **No test may perform real network I/O.** If a test hangs without env config, the stub seam is wrong.
- **Fail-closed loader tests must assert flag-off equivalence:** a loader returning `None` puts the system in exactly the flag-off state (CLAUDE.md documents this for `genre_model_v1`, `fused_score_v1`, style-authorship, AI-likelihood). Assert the abstention, not just the absence of an exception.
- **The lab runner spawns background work** (`trigger_run`/`_execute_run`) — tests drive the execution function synchronously with a stubbed dataset; never sleep-and-poll.

## Measured gap tables (2026-08-17)

| File | Missing | Functions |
|---|---|---|
| `lab/runner.py` | 22 | `_filter_report_by_authors` **14/14**, `trigger_run` 4/4, `_execute_run` 4/4 |
| `bbook_client.py` | 18 | `request_baseline` **12/12**, `fetch_status` 4/4, `_headers` 2/2 |
| `style_authorship.py` | 11 | `_load_artifact` 6/14, `predict_style_authorship` 3/12, `content_reduced_signature` 1/4, `_ensure_loaded` 1/6 |
| `ai_likelihood.py` | 7 | `predict_ai_likelihood_batch` 2/6, `_load_artifact` 2/12, singles in `predict_ai_likelihood`, `_ensure_loaded`, `_band` |
| `fusion/peers.py` | 5 | `_evict_oldest_locked` 4/8, `build_profile` 1/8 |
| `lab/suggestions.py` | 4 | `generate_suggestions` 3/26, `_per_author_auc` 1/6 |
| `canvas/live_import.py` | 4 | `get_submission_text` 4/10 |
| `fusion/artifact.py` | 3 | `load_artifact` 2/6, `_parse` 1/20 |
| `lab/datasets.py` | 1 | `get_dataset` 1/2 |

---

### Task 1: `bbook_client.py` — 18/18 arms (worked example)

**Files:**
- Create: `tests/test_bbook_client.py`

**Interfaces:**
- Consumes: `original.bbook_client.{_headers, request_baseline, fetch_status, is_enabled}`; env `BBOOK_API_URL`, `BBOOK_EXTERNAL_SECRET`.
- Produces: the `_FakeHttpxClient` stub pattern reused by Task 5 (Canvas).

- [ ] **Step 1: Write the failing tests**

```python
"""Branch tests for the Bbook HTTP client (part 4, task 1). No network I/O."""

from __future__ import annotations

import pytest

from original import bbook_client


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise bbook_client.httpx.HTTPStatusError(
                "boom", request=None, response=None
            )


class _FakeClient:
    """Records the request; replays a canned response."""

    last_json = None
    response = _FakeResponse()

    def __init__(self, *a, **kw): ...
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        type(self).last_json = json
        return type(self).response

    def get(self, url, headers=None):
        return type(self).response


@pytest.fixture
def bbook_env(monkeypatch):
    monkeypatch.setenv("BBOOK_API_URL", "https://bbook.example/")
    monkeypatch.setenv("BBOOK_EXTERNAL_SECRET", "test-secret")
    monkeypatch.setattr(bbook_client.httpx, "Client", _FakeClient)
    _FakeClient.last_json = None
    _FakeClient.response = _FakeResponse(
        200,
        {  # reconcile field names against BaselineRequestResult's model
            "externalRequestId": "x-1", "examId": "e-1", "status": "pending",
        },
    )


class TestHeaders:
    def test_missing_secret_raises(self, monkeypatch):
        monkeypatch.delenv("BBOOK_EXTERNAL_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="BBOOK_EXTERNAL_SECRET"):
            bbook_client._headers()

    def test_secret_present(self, monkeypatch):
        monkeypatch.setenv("BBOOK_EXTERNAL_SECRET", "s")
        assert bbook_client._headers()["x-external-secret"] == "s"


class TestRequestBaseline:
    def test_unset_url_raises(self, monkeypatch):
        monkeypatch.delenv("BBOOK_API_URL", raising=False)
        with pytest.raises(RuntimeError, match="BBOOK_API_URL"):
            bbook_client.request_baseline(student_email="a@b.c", student_name="A")

    def test_minimal_payload_omits_every_optional_field(self, bbook_env):
        bbook_client.request_baseline(student_email="a@b.c", student_name="A")
        sent = _FakeClient.last_json
        assert set(sent) == {
            "externalRequestId", "studentEmail", "studentName",
            "examTitle", "durationMins",
        }

    def test_full_payload_includes_all_optional_fields_and_idempotency_key(self, bbook_env):
        bbook_client.request_baseline(
            student_email="a@b.c", student_name="A",
            institution_name="Sem", requested_by="prof@sem.edu",
            min_word_count=200, max_word_count=800,
            prompt_text="Discuss.", external_request_id="fixed-key",
        )
        sent = _FakeClient.last_json
        assert sent["externalRequestId"] == "fixed-key"
        for key in ("institutionName", "requestedBy", "minWordCount",
                    "maxWordCount", "promptText"):
            assert key in sent


class TestFetchStatus:
    def test_404_maps_to_none(self, bbook_env):
        _FakeClient.response = _FakeResponse(404)
        assert bbook_client.fetch_status("nope") is None

    def test_unset_url_raises(self, monkeypatch):
        monkeypatch.delenv("BBOOK_API_URL", raising=False)
        with pytest.raises(RuntimeError):
            bbook_client.fetch_status("x")
```

- [ ] **Step 2: Run and reconcile**

Run: `.venv/bin/python -m pytest tests/test_bbook_client.py -q`
Expected: the canned response fields must satisfy `BaselineRequestResult.model_validate` — read the model at the top of `bbook_client.py` and fill in required fields; everything else should pass as written (source read 2026-08-17: the six optional-field conditionals at lines 124-133, the uuid-default idempotency arm at 118, both config guards).

- [ ] **Step 3: Add the success-path `fetch_status` test** (canned 200 with a valid `BaselineRequestStatus` payload) so both arms of the 404 check are taken.

- [ ] **Step 4: Verify + commit**

```bash
.venv/bin/python -m pytest tests/test_bbook_client.py -q \
  --cov=original.bbook_client --cov-branch --cov-report=term-missing
git add tests/test_bbook_client.py
git commit -m "Add Bbook client branch tests covering config guards and payload arms (was 0%)"
```

---

### Task 2: `lab/runner.py` (22) + `lab/suggestions.py` (4) + `lab/datasets.py` (1)

- [ ] `_filter_report_by_authors` 14/14: pure report-transform — build a small report dict (read the function for its expected shape) and test: empty author filter, filter matching some/none, per-section pruning arms.
- [ ] `trigger_run` 4/4 / `_execute_run` 4/4: already-running guard, unknown dataset, success, failure-capture arm — stub the dataset registry and run synchronously.
- [ ] `generate_suggestions`'s 3 arms + `_per_author_auc` degenerate-input arm (single-class labels), `get_dataset` unknown-name arm.
- [ ] Verify + commit `"Add calibration-lab runner and suggestions branch tests"`.

### Task 3: Report-only expert loaders — `style_authorship.py` (11) + `ai_likelihood.py` (7)

- [ ] For each `_load_artifact`: tmp_path JSON artifacts triggering each validation arm the digest counts (missing file, schema-version mismatch, signal-order/vocabulary drift, reference-prediction drift — the loader docstrings enumerate them). EVERY bad artifact must produce abstention identical to flag-off.
- [ ] `predict_style_authorship`'s 3 arms: below-peer-floor abstention, missing-raw-text abstention, success. `predict_ai_likelihood_batch`'s 2 arms: empty batch, mixed None-vector rows. `_band`'s uncovered boundary.
- [ ] Verify + commit `"Add fail-closed loader and abstention branch tests for the report-only experts"`.

### Task 4: `fusion/peers.py` (5) + `fusion/artifact.py` (3)

- [ ] `_evict_oldest_locked` 4/8: cache-at-capacity eviction arms — fill the profile cache past its bound and assert oldest-first eviction; `build_profile`'s remaining arm (read it; likely the no-text guard).
- [ ] `fusion/artifact.py`: `load_artifact`'s 2 arms (path-override env vs default, missing file) and `_parse`'s one remaining validation arm — same tmp-JSON style as Task 3.
- [ ] Verify + commit `"Add fusion peer-cache eviction and artifact-loader branch tests"`.

### Task 5: `canvas/live_import.py` (4)

- [ ] `get_submission_text` 4/10: reuse Task 1's `_FakeHttpxClient` for the Canvas API seam — attachment-vs-body arms, empty submission, HTTP-error arm. CLAUDE.md: without `CANVAS_BASE_URL`/token the endpoints 400 with manual-upload guidance — pin that message at the router level if not already covered (check `tests/test_canvas_live.py` first; extend it rather than creating a parallel file).
- [ ] Verify + commit `"Add Canvas live-import branch tests"`.

### Task 6: Sweep + part completion

- [ ] Re-measure; cluster ≥95% or annotated; drain partials; update index dashboard; CI ratchet; commit `"Record part 4 integrations branch-coverage completion"`.

## Self-Review Notes

- Task 1 was written from the actual client source (read 2026-08-17); the single declared reconcile point is the `BaselineRequestResult`/`BaselineRequestStatus` model fields.
- The `_FakeClient` seam patches `bbook_client.httpx.Client` — module-attribute patching, robust to `import httpx` style. If `canvas/live_import.py` imports differently (`from httpx import Client`), patch its module attribute instead.
- Loader tests (Task 3) double as regression guards for the "fail closed, never fall back to rules" contract that `GENRE_RESOLVER_V2` documents as a deliberate design decision.
