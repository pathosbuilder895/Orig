"""
tests/perf/test_event_loop_not_blocked.py — T-09, the exam-freeze bug
(docs/testing/07-performance-reliability.md §2, gap register T-09).

Several route handlers are declared ``async def`` but do their CPU-bound work
inline, so for the whole duration of that work the event loop belongs to them
and nothing else in the process runs. During a bulk baseline import that is
seconds, and every live proctoring heartbeat waits behind it.

The probe here is ``GET /health``: the spec names the proctor beat
(``/proctor/*/beat``), but /health is the same event-loop probe without the
session setup — it is unauthenticated, cheap, and, being a plain ``def``
handler, is dispatched to Starlette's threadpool, so anything it waits on is
the loop itself and not its own work.

HOW THE LATENCY IS MEASURED (and why not the obvious way)
---------------------------------------------------------
The obvious shape — start the upload as a task, ``await asyncio.sleep(0.05)``
to let it get going, and only then start timing the probe — measures nothing
on this app. Measured on 2026-09-07: with the batch upload blocking the loop
for 10.8 s, that shape reported a probe latency of **3.5-6.8 ms** and would have
called the handler healthy. The reason is that the settle sleep is itself a
loop operation: the handler starts blocking almost immediately, the 50 ms
timer expires *inside* the block, and the sleeping coroutine is not resumed
until the block is over — ``await asyncio.sleep(0.05)`` returned after
**10 772 ms**. By the time the probe is issued the loop is already free, so
the starvation lands in the sleep and is invisible to the probe.

So the beat is timed from the moment it is *due*, not the moment the loop
finally gets around to issuing it:

    t_due = perf_counter() + 0.05   # a heartbeat due 50 ms into the upload
    await asyncio.sleep(0.05)
    response = await client.get("/health")
    late = perf_counter() - t_due

That is exactly what the proctoring client experiences — a beat scheduled for
time T is answered at T + late — and it cannot be dodged by the block landing
on one side or the other of the timer. ``_beat`` below returns the split
(dispatch delay vs. the probe's own round trip) so a failure says which half
the time went to; for a starved loop it is essentially all dispatch delay.

Nothing here changes production code: the fix is ``def`` (or
``run_in_threadpool``) for the CPU handlers, and the test is indifferent to
which — under either, the loop stays free, the settle timer fires on time, and
the beat is answered in single-digit milliseconds.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import statistics
from dataclasses import dataclass
from time import perf_counter

import httpx
import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# ── Budgets ───────────────────────────────────────────────────────────────────
# §9: a budget is >= 3x the value measured at authoring time. Measured
# 2026-09-07 on this checkout (Darwin, 12 CPUs, warm spaCy pipeline):
#   unloaded beat  — median 7 ms over 5 samples (3.4-7.0 ms) -> control
#                    budget 50 ms, ~7x
#   loaded beat, healthy handler (students/upload, no feature extraction)
#                  — 7 ms late over a 60 ms request -> budget 250 ms, ~36x
BEAT_BUDGET_S = 0.25
CONTROL_BUDGET_S = 0.05
# How far into the upload the heartbeat is due.
SETTLE_S = 0.05
# Generous ceiling on the heavy request itself: asyncio.wait_for, never a
# sleep-poll (§9). The slowest case measured 10.8 s.
UPLOAD_TIMEOUT_S = 60.0

pytestmark = [
    pytest.mark.perf,
    pytest.mark.skipif(
        (os.cpu_count() or 1) < 2,
        reason=(
            "uninformative: a single-CPU runner cannot distinguish event-loop "
            "starvation from ordinary contention"
        ),
    ),
    pytest.mark.skipif(
        os.environ.get("CI_RUNNER_SLOW") == "1",
        reason=(
            "uninformative: CI_RUNNER_SLOW=1 — the operator has declared this "
            "runner too slow for a latency budget to mean anything"
        ),
    ),
]


# ── Deterministic payload text ────────────────────────────────────────────────
# No randomness: the same bytes every run, so a change in timing is a change in
# the code and not in the corpus. The extractor needs real words, so this is
# ordinary prose rather than filler tokens.
_SENTENCES = (
    "The doctrine of vocation situates daily labor within a larger account of providence.",
    "Faithful work in an ordinary calling honors the same God who ordained the extraordinary.",
    "Scripture repeatedly affirms that diligence in one station is itself a form of worship.",
    "Yet the preacher must not flatter the congregation with easy consolations about labor.",
    "A pastor who says nothing of drudgery has not read the book of Ecclesiastes carefully.",
    "The reformers wrote of the plowman and the magistrate in the same breath, deliberately.",
)


def _document(words: int, salt: str) -> str:
    """Roughly ``words`` words of deterministic prose, unique per ``salt``.

    The salt varies the text between documents so the batch importer's
    content-hash dedup admits all of them — ten identical files would be nine
    skipped duplicates and nine extractions that never happen.
    """
    out: list[str] = []
    count = 0
    index = 0
    while count < words:
        sentence = _SENTENCES[index % len(_SENTENCES)]
        out.append(f"In section {salt}{index}, {sentence[0].lower()}{sentence[1:]}")
        count += len(sentence.split()) + 3
        index += 1
    return " ".join(out)


def _txt(name: str, text: str) -> tuple[str, bytes, str]:
    return (name, text.encode("utf-8"), "text/plain")


# Paragraph count tuned by measurement (2026-09-07, Darwin, 12 CPUs): 25,000
# paragraphs of ~40 words each builds in ~0.3 s and parses with python-docx's
# Document(io.BytesIO(...)) + a per-paragraph .text join in ~1.1-1.2 s — the
# actual inline work of POST /students/{sid}/upload's .docx branch
# (original/routers/students.py:350-354). Paragraph *count* drives parse time, not
# word count: 5,000 paragraphs at 2,000,000 words parses faster (~0.24 s) than
# 15,000 paragraphs at 810,000 words (~0.77 s), so this builds many small
# paragraphs rather than a few huge ones. Building goes through OxmlElement
# directly rather than Document.add_paragraph(), which is markedly slower at
# this paragraph count (~4.2 s vs ~0.3 s for 22,000 paragraphs) without
# affecting what gets parsed back out.
_DOCX_PARAGRAPHS = 25_000
_DOCX_WORDS_PER_PARAGRAPH = 40


def _heavy_docx(salt: str) -> bytes:
    """A deterministic multi-thousand-paragraph .docx, slow to parse.

    Built directly at the oxml level (bypassing python-docx's
    ``add_paragraph``, which does not scale to this paragraph count) so
    generation stays well under a second while the resulting file still
    takes python-docx over a second to parse back — see the module-level
    comment above for the measurements this is tuned from.
    """
    doc = Document()
    reps = (_DOCX_WORDS_PER_PARAGRAPH // len(_SENTENCES[0].split())) + 1
    text = (_SENTENCES[0] + " ") * reps
    body = doc.element.body
    sect_pr = body.find(qn("w:sectPr"))
    for i in range(_DOCX_PARAGRAPHS):
        p = OxmlElement("w:p")
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = f"Paragraph {salt}{i}: {text}"
        t.set(qn("xml:space"), "preserve")
        r.append(t)
        p.append(r)
        if sect_pr is not None:
            sect_pr.addprevious(p)
        else:
            body.append(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _docx(name: str, raw: bytes) -> tuple[str, bytes, str]:
    return (
        name,
        raw,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ── The three handlers under test ─────────────────────────────────────────────
# Each returns the coroutine for one upload request. The three Canvas import
# handlers (imports.py:110, 147, 235) are not covered: they need a slow fake
# upstream to hold the loop, which is §7's MockTransport work — follow-up,
# tracked there.


def _batch_upload(client: httpx.AsyncClient):
    """POST /students/{sid}/baseline/upload-batch — ten 400-word .txt files.

    original/routers/students_baseline.py:342. Calls feature_vector() per
    file inline: ~1 s each with spaCy warm.
    """
    files = [
        ("files", _txt(f"baseline-{i}.txt", _document(400, f"b{i}-")))
        for i in range(10)
    ]
    return client.post(
        "/students/perf-s1/baseline/upload-batch",
        files=files,
        data={"provenance": "verified", "assignment": ""},
    )


def _single_upload_docx(client: httpx.AsyncClient):
    """POST /students/{sid}/upload — one parse-heavy .docx file.

    original/routers/students.py:341, ``.docx`` branch at 350-354: python-docx
    ``Document(io.BytesIO(raw))`` plus a per-paragraph ``.text`` join, both
    inline in the ``async def`` handler. A 25,000-paragraph file (see
    ``_heavy_docx``) measures ~1.1-1.2 s to parse — the actual blocking case
    this route has, unlike the ``.txt`` branch (see ``_single_upload_txt``).
    """
    return client.post(
        "/students/perf-s2/upload",
        files={"file": _docx("essay.docx", _heavy_docx("u-"))},
    )


def _single_upload_txt(client: httpx.AsyncClient):
    """POST /students/{sid}/upload — one ~2,000-word .txt file.

    original/routers/students.py:341. Declared ``async def`` like the others,
    but its inline work for a .txt is decode + split, not feature extraction.
    Kept as the green control for this route: unlike the .docx/.pdf branches,
    the .txt branch never blocks, so this case should stay green forever and
    is not parametrised with ``blocker``.
    """
    return client.post(
        "/students/perf-s3/upload",
        files={"file": _txt("essay.txt", _document(2000, "u-"))},
    )


def _turnitin_csv(client: httpx.AsyncClient):
    """POST /import/courses/{course_id}/turnitin-csv — a 2,000-row roster.

    original/routers/imports.py:26. No feature extraction; the inline work is
    a repository get + get_or_create per row.
    """
    header = (
        "Last Name,First Name,Student ID,Assignment Title,"
        "Date Submitted,Similarity,File Name\n"
    )
    rows = "".join(
        f"Last{i},First{i},perf-csv-{i},Essay {i},2026-01-01,12,paper{i}.docx\n"
        for i in range(2000)
    )
    return client.post(
        "/import/courses/c1/turnitin-csv",
        files={"file": ("roster.csv", (header + rows).encode("utf-8"), "text/csv")},
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def warm_extractor():
    """Load spaCy and the feature pipeline before anything is timed.

    The first feature_vector() call costs ~8 s (model load) against ~1 s warm.
    Left cold, the first timed case would measure the model load rather than
    the per-document cost, and the control could be charged for it too.
    """
    from original.features.pipeline import feature_vector

    feature_vector(_document(400, "warmup-"))


@pytest.fixture
async def perf_client(live_app, warm_extractor):
    """A client of this module's own, never shared with the functional suite (§9)."""
    transport = httpx.ASGITransport(app=live_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        # One warm-up beat: first-call costs (route resolution, response-model
        # construction) belong to neither the control nor the budget.
        warmup = await client.get("/health")
        assert warmup.status_code == 200
        yield client


@dataclass(frozen=True)
class _Beat:
    """One heartbeat, timed from when it was due."""

    response: httpx.Response
    late: float  # due -> answered
    dispatch: float  # due -> actually issued (the loop-starvation share)

    def describe(self) -> str:
        return (
            f"answered {self.late * 1000:.0f} ms after it was due "
            f"({self.dispatch * 1000:.0f} ms waiting for the event loop, "
            f"{(self.late - self.dispatch) * 1000:.0f} ms in the request)"
        )


async def _beat(client: httpx.AsyncClient, settle: float = SETTLE_S) -> _Beat:
    """Issue a heartbeat that is due ``settle`` seconds from now, timed from due."""
    t_due = perf_counter() + settle
    await asyncio.sleep(settle)
    t_issued = perf_counter()
    response = await client.get("/health")
    t_answered = perf_counter()
    return _Beat(response=response, late=t_answered - t_due, dispatch=t_issued - t_due)


# ── Control: the probe itself is fast ─────────────────────────────────────────


async def test_heartbeat_probe_is_fast_with_no_load(store_reset, perf_client):
    """Control for T-09: an unloaded heartbeat is answered in ~milliseconds.

    Without this, a slow /health could masquerade as event-loop starvation and
    the starvation tests below would be measuring the wrong thing. Uses the
    identical `_beat` instrument, so it validates the measurement end to end
    (settle timer included), not just the route. Measured 2026-09-07 (Darwin,
    12 CPUs): median 7 ms over the 5 samples, range 3.4-7.0 ms; the 50 ms
    budget is ~7x that per §9.
    """
    beats = [await _beat(perf_client) for _ in range(5)]

    assert all(b.response.status_code == 200 for b in beats), [
        b.response.status_code for b in beats
    ]

    median = statistics.median(b.late for b in beats)
    assert median < CONTROL_BUDGET_S, (
        f"the probe itself is slow: median beat {median * 1000:.0f} ms with no "
        f"load, budget {CONTROL_BUDGET_S * 1000:.0f} ms. Samples (ms): "
        f"{[round(b.late * 1000, 1) for b in beats]}. Until this passes, a slow "
        "beat in the starvation tests below cannot be blamed on the upload."
    )


# ── The gap ───────────────────────────────────────────────────────────────────
# One case per handler. Only the handlers that are actually red carry
# `blocker`, so the marker stays an accurate inventory of open gaps: the
# batch importer, the CSV importer, and the .docx branch of the single-file
# upload all hold the loop for a while; the .txt branch of that same route is
# a green control kept alongside it (see `_single_upload_txt`).


@pytest.mark.parametrize(
    "send_upload",
    [
        pytest.param(
            _batch_upload, id="baseline-upload-batch", marks=pytest.mark.blocker
        ),
        pytest.param(_turnitin_csv, id="turnitin-csv", marks=pytest.mark.blocker),
        pytest.param(
            _single_upload_docx, id="students-upload", marks=pytest.mark.blocker
        ),
        pytest.param(_single_upload_txt, id="students-upload-txt"),
    ],
)
async def test_upload_does_not_starve_the_heartbeat(
    store_reset, perf_client, send_upload
):
    """T-09: bulk upload blocks the event loop; live exam heartbeats stall.

    RED for the batch importer, the CSV importer, and the .docx branch of the
    single-file upload (docs/testing/10-gap-register.md). Measured
    2026-09-07 on this checkout (Darwin, 12 CPUs), beats due every 50 ms for
    the life of the upload, worst (maximum) lateness across all beats
    (3 runs each):

      baseline/upload-batch   8.6-9.7 s late, 1 beat (8.7-9.7 s request)  — RED
      turnitin-csv             2.4-2.6 s late, 1 beat (2.5-2.7 s request) — RED
      students/upload (.docx)  1.1-1.3 s late, 1 beat (1.4-1.6 s request) — RED
      students/upload (.txt)     4-7 ms late, 1 beat (50-60 ms request)  — green

    All three red handlers hold the loop solidly for the whole request, so
    only one beat ever gets collected before `upload.done()` — that single
    beat's lateness tracks the request duration almost exactly (e.g. the
    .docx case: 1.1-1.3 s late against a 1.1-1.2 s python-docx parse). A
    handler that yielded partway through and then blocked would instead show
    two-or-more beats, an early cheap one followed by a late one; the max-
    over-all-beats assertion below catches that shape too, not just the
    solid-block shape these three handlers happen to have today.

    The three red numbers move with machine load but not by anything
    approaching the margin that would be needed to reach the budget; the
    green one is bounded by the request's own ~60 ms, well under it.

    Beats are issued in a loop for as long as the upload task is running
    (`_Beat`'s regular 50 ms cadence, not a single sample), and the assertion
    below is on the *maximum* lateness across every beat collected, not just
    the first. A single early beat can be dodged by a handler that yields
    once, answers it, and then blocks for the rest of the request; a beat
    that keeps firing until the upload completes cannot be.

    The .txt case is not an exception to the gap: /students/{id}/upload is
    ``async def`` and inline like the others, but for a .txt its inline work
    is a decode and a word count, so there is nothing there to hold the loop
    with. It stays in the parametrisation, unmarked, as the regression guard
    for that route — the day feature extraction (or something else heavy)
    moves into the .txt branch, this case turns red on its own. The .docx
    branch of the same route, by contrast, is genuinely heavy today
    (python-docx parses the whole document inline) and is red now.
    """
    t_started = perf_counter()
    upload = asyncio.create_task(send_upload(perf_client))

    beats: list[_Beat] = []
    completed = False
    try:
        # At least one beat is always collected, even for a fast upload: the
        # loop condition is checked only after a beat has been issued, so the
        # latency assertion below is never vacuous.
        while True:
            beats.append(await _beat(perf_client))
            if upload.done():
                break
            # The loop's own bound: a handler that hangs (rather than merely
            # blocks for seconds) must fail here at the documented ceiling,
            # not spin until the CI job is killed.
            if perf_counter() - t_started > UPLOAD_TIMEOUT_S:
                raise AssertionError(
                    f"upload still running after {UPLOAD_TIMEOUT_S:.0f} s "
                    f"({len(beats)} beats issued) — the handler hung, not merely blocked"
                )
        completed = True
    finally:
        if not completed:
            # A raised exception (e.g. from _beat, or the bound above) would
            # otherwise orphan the upload task ("Task exception was never
            # retrieved"). If the task already finished, retrieve its result
            # so a stored exception is marked consumed; if it is still
            # running, cancel it. The normal path and the wait_for timeout
            # path below are untouched by this.
            if upload.done():
                if not upload.cancelled():
                    with contextlib.suppress(Exception):
                        upload.exception()
            else:
                upload.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await upload

    upload_response = await asyncio.wait_for(upload, timeout=UPLOAD_TIMEOUT_S)
    upload_seconds = perf_counter() - t_started

    # Setup floors first, so a red case fails on the budget below and never on
    # a broken payload: every probe has to have worked, and the load has to
    # have been a real accepted upload rather than a 4xx that returned
    # instantly.
    assert all(b.response.status_code == 200 for b in beats), [
        b.response.status_code for b in beats
    ]
    assert 200 <= upload_response.status_code < 300, (
        f"the upload under test did not succeed ({upload_response.status_code}) "
        f"— nothing was loading the event loop: {upload_response.text[:300]}"
    )

    worst = max(beats, key=lambda b: b.late)
    assert worst.late < BEAT_BUDGET_S, (
        f"heartbeat waited on the upload: {len(beats)} beat(s) sent, worst was "
        f"{worst.describe()}, budget {BEAT_BUDGET_S * 1000:.0f} ms. The upload "
        f"itself took {upload_seconds:.2f} s — so the loop was held by the "
        "handler for essentially all of it. A live exam heartbeat arriving "
        "during this upload waits exactly this long. Fix: run the CPU work "
        "off the loop (`def` handler or run_in_threadpool); this test does "
        "not care which."
    )
