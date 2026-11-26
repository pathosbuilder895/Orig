"""One shared ``en_core_web_sm`` pipeline for every spaCy user in the engine.

Tier 5, Tier 11, the prosodic tier and the tension arc each used to call
``spacy.load("en_core_web_sm", ...)`` on their own, so one process held four
copies of the same model (about 40 MB each on top of spaCy itself). On the
512 MB pilot instance that duplication was the difference between headroom
and an out-of-memory restart (2026-11-17).

Now the model is loaded once, guarded by a lock, and each caller gets a
:class:`PipelineView` that runs it with the same components switched off as
its old reduced load (``nlp(text, disable=...)``). Switching a component off
per call skips exactly what a load-time ``disable=`` skipped: the remaining
components see the same tokens and predict the same tags, parses and
sentence boundaries, so the measurements are unchanged
(``tests/test_shared_spacy_model.py`` checks the whole feature vector).

Failures behave as before: :func:`load_view` raises the ``ImportError`` /
``OSError`` that ``spacy.load`` raised, and each caller keeps its own
"unavailable" handling.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import Any

MODEL_NAME = "en_core_web_sm"

_lock = threading.Lock()
# (spacy module, loaded pipeline). Keyed on the module object so a substitute
# ``spacy`` placed in ``sys.modules`` (the tests' "model missing" arm) is
# asked to load instead of the cached real pipeline being handed back.
_shared: tuple[Any, Any] | None = None


def shared_nlp():
    """The full pipeline, loaded once per process. Raises what ``spacy.load`` raises."""
    global _shared
    import spacy  # looked up each call: honours a substituted module

    cached = _shared
    if cached is not None and cached[0] is spacy:
        return cached[1]
    with _lock:
        cached = _shared
        if cached is not None and cached[0] is spacy:
            return cached[1]
        nlp = spacy.load(MODEL_NAME)
        _shared = (spacy, nlp)
        return nlp


class PipelineView:
    """The shared pipeline with some components switched off for every call."""

    __slots__ = ("_nlp", "_disable")

    def __init__(self, nlp: Any, disable: Iterable[str]) -> None:
        self._nlp = nlp
        self._disable = tuple(disable)

    @property
    def disabled(self) -> tuple[str, ...]:
        return self._disable

    def __call__(self, text, **kwargs):
        return self._nlp(text, disable=self._disable, **kwargs)

    def pipe(self, texts, **kwargs):
        return self._nlp.pipe(texts, disable=self._disable, **kwargs)

    def __getattr__(self, name: str) -> Any:  # vocab, pipe_names, meta, ...
        return getattr(self._nlp, name)


def load_view(disable: Iterable[str] = ()):
    """The shared pipeline as the caller's old ``spacy.load(..., disable=...)``.

    With nothing disabled this is the shared pipeline itself.
    """
    nlp = shared_nlp()
    disable = tuple(disable)
    return PipelineView(nlp, disable) if disable else nlp


def reset_for_tests() -> None:
    global _shared
    with _lock:
        _shared = None
