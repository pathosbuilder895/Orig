"""Fixtures and helpers for the certification suite.

Holds the three things every certification test needs and none of the
assertions:

  * ``corpus_authors`` — the committed public-domain corpus, split per author
    into baseline chunks (one work) and a holdout chunk (a genuinely different
    work where the author has one, otherwise a different section of the same
    work — see ``Author``).
  * ``provision_and_score`` — drives one author through the *live API*:
    N ``POST /students/{id}/baseline`` calls followed by one
    ``POST /students/{id}/score``. Nothing here calls ``quantum.scoring.score``
    directly; the 2026-09-02 architecture review found the unit path and the
    production path disagree, so a certification that ran on the unit path
    would certify the wrong thing.
  * ``record_verdict`` — appends a pass/fail/uninformative verdict to the JSON
    report CI uploads.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

# ── Corpus ───────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = REPO_ROOT / "validation" / "public_authors"
MANIFEST_PATH = CORPUS_ROOT / "manifest.json"
CORPUS_DIR = CORPUS_ROOT / "corpus"

#: Actions that count as "this submission was flagged" for FPR purposes.
#: `no_action` and `monitor` are not flags — nobody is asked to do anything
#: about the student. See ACTION_THRESHOLDS in original/constants.py.
FLAG_ACTIONS = frozenset({"schedule_conversation", "escalate"})

#: Below this many usable authors a rate is noise, not a measurement: the
#: verdict is `uninformative`, never a pass (plan §Global Constraints,
#: "three-valued honesty").
MIN_AUTHORS = 8


@dataclass
class Author:
    """One author's certification material.

    ``baseline_chunks`` all come from a *single* work, which is the pilot's
    real shape — a student's first few authenticated samples are typically
    from one course, not a career.

    ``holdout`` is a *genuinely different work* for the authors that have one,
    and otherwise **a different section of the same work**. The committed
    corpus carries only one work for 8 of its 11 authors (their files are
    ``X_part_01.txt``, ``X_part_02.txt``, … of a single book), so for those
    eight the holdout is the next section of the book the baselines came from.
    ``holdout_same_work`` records which case each author is, and the rate is
    reported with that count attached — same-work authors are *kept* (dropping
    them would leave three authors and make every N uninformative) and
    labelled, because a same-work holdout is the easier test: shared topic and
    vocabulary should, if anything, depress the false-positive rate rather than
    inflate it.
    """

    author_id: str
    baseline_chunks: list[str]
    holdout: str
    baseline_work: str = ""
    holdout_work: str = ""
    #: True when ``holdout_work`` is another section of ``baseline_work``
    #: rather than a different work by the same author.
    holdout_same_work: bool = False


_PART_SUFFIX_RE = re.compile(r"_part_\d+$")


def _work_key(filename: str) -> str:
    """The *work* a corpus file belongs to, not the file.

    Most of this corpus is one long book split across ``X_part_01.txt`` …
    ``X_part_NN.txt``. Comparing filenames alone would call the next section
    of the same book "a different work"; stripping the ``_part_NN`` suffix
    gives the key that actually distinguishes works.
    """
    return _PART_SUFFIX_RE.sub("", Path(filename).stem)


def _load_authors() -> list[Author]:
    manifest = json.loads(MANIFEST_PATH.read_text())
    by_author: dict[str, list[dict]] = {}
    for entry in manifest["entries"]:
        by_author.setdefault(entry["author_id"], []).append(entry)

    from validation.termsim.personas import chunk_text

    authors: list[Author] = []
    for author_id, entries in by_author.items():
        baseline_entries = [e for e in entries if e.get("is_baseline")] or entries
        baseline_entry = baseline_entries[0]
        # Prefer a holdout from a genuinely different work; fall back to a
        # different *section* of the same work when the corpus has only one
        # work for this author (true for 8 of 11 — see Author). An author with
        # neither cannot supply a holdout at all and is excluded rather than
        # scored against its own baseline text.
        baseline_key = _work_key(baseline_entry["filename"])
        other_work = [e for e in entries if _work_key(e["filename"]) != baseline_key]
        same_work = [e for e in entries if e["filename"] != baseline_entry["filename"]]
        holdout_entry = (other_work or same_work or [None])[0]
        if holdout_entry is None:
            continue
        holdout_same_work = not other_work

        baseline_chunks = chunk_text((CORPUS_DIR / baseline_entry["filename"]).read_text())
        holdout_chunks = chunk_text((CORPUS_DIR / holdout_entry["filename"]).read_text())
        if not baseline_chunks or not holdout_chunks:
            continue

        authors.append(
            Author(
                author_id=author_id,
                baseline_chunks=baseline_chunks,
                holdout=holdout_chunks[0],
                baseline_work=baseline_entry["filename"],
                holdout_work=holdout_entry["filename"],
                holdout_same_work=holdout_same_work,
            )
        )
    return authors


@pytest.fixture(scope="session")
def corpus_authors() -> list[Author]:
    """The committed public-domain corpus, chunked once per session.

    Chunking is cheap; feature extraction is not, and it cannot be cached
    here — the baseline route takes raw text only (``AddSampleRequest``), so
    every baseline is re-extracted server-side by design. See the report for
    the resulting wall time.
    """
    return _load_authors()


# ── Provisioning through the live API ────────────────────────────────────────


@dataclass
class Outcome:
    """What the API did with one author at one baseline count."""

    author_id: str
    student_id: str
    action: str | None = None
    deviation_score: float | None = None
    baselines_accepted: int = 0
    #: Baselines the drift gate held for instructor review (HTTP 202/409).
    #: Counted, never silently treated as accepted — a held sample is not in
    #: the baseline, so the student is not at the N this test claims.
    baselines_held: int = 0
    #: Baselines the API did not add to the profile: a non-2xx status, or a
    #: 200 carrying ``{"skipped": true}`` (the seal-replay dedup path). A 200
    #: is NOT by itself acceptance.
    baselines_rejected: int = 0
    #: ``authenticated_count`` as the API last reported it. This is the
    #: server's own count of samples carrying auth_weight > 0, so it catches a
    #: silent ``verified`` → ``unverified`` provenance downgrade that leaves
    #: every POST at HTTP 200 while contributing nothing to baseline_mean.
    authenticated_count: int | None = None
    #: True/False when this outcome scored the author's OWN holdout (see
    #: Author.holdout_same_work); None when it scored someone else's.
    holdout_same_work: bool | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.action is not None

    @property
    def flagged(self) -> bool:
        return self.action in FLAG_ACTIONS


def provision_and_score(
    client,
    author: Author,
    n_baselines: int,
    student_id: str,
    holdout: str | None = None,
) -> Outcome:
    """Add ``n_baselines`` authenticated baselines, then score ``holdout``.

    Both legs go over HTTP through the live app. ``holdout`` defaults to the
    author's own holdout chunk; the witness test passes someone else's.

    An author whose baseline work yields fewer than ``n_baselines`` chunks, or
    whose baselines are not all accepted, comes back unusable (``action`` is
    None) and is excluded from the rate rather than counted as a non-flag.

    "Accepted" is checked against the server's own bookkeeping, not against the
    HTTP status: the route answers 200 with ``{"skipped": true}`` on a replayed
    text, and ``_authorize_provenance`` can silently downgrade ``verified`` to
    ``unverified`` (auth_weight 0) while still answering 200. The final
    ``authenticated_count`` is asserted to equal ``baselines_accepted`` so a
    profile that is nominally at N but authenticated at 0 cannot be scored and
    reported as if it were at N.
    """
    outcome = Outcome(
        author_id=author.author_id,
        student_id=student_id,
        holdout_same_work=author.holdout_same_work if holdout is None else None,
    )

    if len(author.baseline_chunks) < n_baselines:
        outcome.notes.append(
            f"only {len(author.baseline_chunks)} chunks in {author.baseline_work}; "
            f"need {n_baselines}"
        )
        return outcome

    for index, chunk in enumerate(author.baseline_chunks[:n_baselines]):
        response = client.post(
            f"/students/{student_id}/baseline",
            json={
                "text": chunk,
                "provenance": "verified",
                "assignment": f"cert-baseline-{index}",
            },
        )
        if response.status_code == 200:
            body = response.json()
            if body.get("authenticated_count") is not None:
                outcome.authenticated_count = body["authenticated_count"]
            if body.get("skipped"):
                outcome.baselines_rejected += 1
                outcome.notes.append(
                    f"baseline {index} returned 200 but was not added "
                    f"({body.get('reason', 'skipped')})"
                )
            else:
                outcome.baselines_accepted += 1
        elif response.status_code in (202, 409):
            outcome.baselines_held += 1
            outcome.notes.append(f"baseline {index} held for drift review ({response.status_code})")
        else:
            outcome.baselines_rejected += 1
            outcome.notes.append(f"baseline {index} rejected ({response.status_code})")

    # Not a soft check. If these disagree, every rate computed from this
    # profile is measuring something other than "a student with N
    # authenticated baselines", and reporting it would be the lie the whole
    # certification exists to prevent.
    if outcome.authenticated_count is not None:
        assert outcome.authenticated_count == outcome.baselines_accepted, (
            f"{student_id}: API reports authenticated_count="
            f"{outcome.authenticated_count} after {outcome.baselines_accepted} "
            f"accepted baselines — samples were recorded but not authenticated "
            f"(silent provenance downgrade?), so this profile is not at N"
        )

    if outcome.baselines_accepted != n_baselines:
        return outcome

    response = client.post(
        f"/students/{student_id}/score",
        json={"text": author.holdout if holdout is None else holdout, "assignment": "cert"},
    )
    if response.status_code != 200:
        outcome.notes.append(f"score rejected ({response.status_code})")
        return outcome

    body = response.json()
    outcome.action = body["recommendation"]["action"]
    outcome.deviation_score = body["authorship"]["deviation_score"]
    return outcome


def score_text(client, student_id: str, text: str) -> float | None:
    """Score one more text against an ALREADY-provisioned student.

    Used by the witness to score a second holdout against the same baselines
    it just posted, without paying for a second provisioning pass. Safe to
    call repeatedly: ``POST /students/{id}/score`` reads the profile and never
    writes to it, so the two scores are independent of their order.
    """
    response = client.post(
        f"/students/{student_id}/score", json={"text": text, "assignment": "cert"}
    )
    if response.status_code != 200:
        return None
    return response.json()["authorship"]["deviation_score"]


# ── Verdict reporting ────────────────────────────────────────────────────────


def _report_path() -> Path:
    return Path(os.environ.get("CERT_REPORT_PATH", str(REPO_ROOT / "certification-report.json")))


def record_verdict(name: str, verdict: str, value=None, n=None, **extra) -> dict:
    """Append one verdict to the JSON list at ``CERT_REPORT_PATH``.

    ``verdict`` is one of "pass" / "fail" / "uninformative" — the same
    three-valued vocabulary the validation gates use, so the weekly workflow
    can merge this report with the battery report.
    """
    entry = {
        "name": name,
        "verdict": verdict,
        "value": value,
        "n": n,
        "params": extra,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    path = _report_path()
    entries: list = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, list):
            entries = loaded
    entries.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2) + "\n")
    return entry
