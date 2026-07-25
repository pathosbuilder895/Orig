"""
Genre labeling must survive ingestion — regression guard for WS-7.3.

``POST /students/{id}/baseline`` best-effort labels each sample with a genre
via ``original.context.resolvers.resolve_genre``, inside a
``try/except Exception: pass``. The stored genre feeds the hierarchical
Bayesian prior (``original/quantum/scoring.py`` only blends the prior when the
genre is truthy), so a silent labeling failure degrades scoring while every
request still returns 200 and every other test stays green.

That is exactly what happened during the router split: the resolver's import
moved from ``original/api.py`` to ``original/routers/students_baseline.py``
byte-identically, but the relative import ``from .context.resolvers`` then
resolved against ``original.routers.context`` (nonexistent) instead of
``original.context``. The ModuleNotFoundError was swallowed by the bare
except, and samples were persisted with ``genre=None``.

These tests pin the observable behavior — a labeled sample stays labeled —
rather than the import statement, so any future move that breaks the resolver
fails loudly here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import run
from original import store
from original.context.resolvers import resolve_genre

# ~120 words — above the per-sample minimum, and long enough for the
# rule-based resolver to return a confident label.
ESSAY_TEXT = (
    "This paper argues that the received chronology of the correspondence "
    "requires revision. First, the manuscript tradition preserves a colophon "
    "that presupposes a later provenance than the standard dating allows. "
    "Second, the internal citations quote a source that did not circulate "
    "widely until the following century, which makes the earlier date "
    "difficult to sustain. Third, the vocabulary of the disputed section "
    "diverges from the undisputed sections in ways that resist explanation by "
    "subject matter alone. Taken together these observations suggest that the "
    "text reached its present form through a longer process of compilation "
    "than has generally been assumed, and that the traditional attribution "
    "should be treated as a claim about authority rather than about authorship."
)


@pytest.fixture
def client(store_reset):
    return TestClient(run.load_legacy_demo_app())


def test_resolver_labels_this_text():
    """Guard the fixture itself: if the resolver stops labeling this text, the
    ingestion test below would pass vacuously."""
    assert (resolve_genre(ESSAY_TEXT) or {}).get("primary") is not None


def test_ingested_sample_carries_the_resolver_genre(client):
    """A posted baseline sample must be stored with the genre the resolver
    assigns — not None. This is the regression that the swallowed
    ModuleNotFoundError produced."""
    sid = "demo:genre-regression"
    resp = client.post(f"/students/{sid}/baseline", json={"text": ESSAY_TEXT, "assignment": "a1"})
    assert resp.status_code == 200, resp.text

    state = store.get(sid)
    assert state is not None and state.samples, "sample was not persisted"
    stored_genre = getattr(state.samples[-1], "genre", None)

    assert stored_genre is not None, (
        "baseline sample was stored with genre=None — the genre resolver is not "
        "reachable from the ingestion path (check its import), which silently "
        "disables the hierarchical Bayesian prior"
    )
    assert stored_genre == (resolve_genre(ESSAY_TEXT) or {}).get("primary")
