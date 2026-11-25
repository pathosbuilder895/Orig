"""Length-matched reference: compare a short paper with short pieces.

A 300-word paper is measured more noisily than a 1,200-word one, and some
measurements shift with length by construction (a type-token ratio falls as
a text grows). ``score()`` compares the new paper with the mean and spread
of the student's past papers measured WHOLE, so a short paper against long
past papers reads as a change of writer: on ``validation/corpus/`` 78% of
honest 300-word papers were flagged against 1,200-word past papers, versus
13% against 300-word ones (``docs/research/2026-11-10-opportunity-mask.md``).

``build_length_matched_state`` re-measures each long past paper in
consecutive pieces about the size of the paper being scored and returns a
state whose comparison reference (mean, spread, active set) comes from
those pieces. Everything else stays the student's real history: the sample
list, the paper counts readiness is judged on, the trajectory and the
density matrix. A piece is evidence about how this student writes at that
length; it is not another paper.

Gated by ``LENGTH_MATCHED_BASELINE`` (off | shadow | on), default off. This
module changes nothing by itself: ``score()`` only reads the state it is
handed under that flag.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ..constants import FEATURE_DIM, RECENCY_DECAY
from ..features import feature_flags as _ff
from ..features import part_overrides as _part_overrides
from ..features import preprocess as _pp
from ..features.baseline_scope import NOT_COMPUTED_FOR_BASELINES_MASK
from ..features.matter import without_page_breaks
from ..features.preprocess import _strip_backmatter
from .state import StudentState

# Below this the pieces themselves are too short to measure: most share-type
# features have no opportunities and the extractors return placeholders.
LENGTH_MATCH_MIN_WORDS = 100
# Ceiling on feature extractions per scoring request (one per piece). A
# student with more long past papers than this is not length-matched at all.
LENGTH_MATCH_MAX_PIECES = 24

_WORD = re.compile(r"\S+")


@dataclass
class LengthMatchedState(StudentState):
    """A student's state whose comparison reference is length-matched.

    ``piece_vectors`` holds one row per piece (an uncut paper is one piece,
    its stored vector). ``piece_weights`` gives every paper the weight it has
    in ``StudentState.baseline_mean`` (authentication x recency), shared
    equally among its pieces, so cutting a paper never changes how much that
    paper counts.
    """

    piece_vectors: np.ndarray | None = None  # (P, FEATURE_DIM)
    piece_weights: np.ndarray | None = None  # (P,)
    papers_cut: int = 0
    piece_words: int = 0

    @property
    def baseline_mean(self) -> np.ndarray:
        w = self.piece_weights
        return (w[:, None] * self.piece_vectors).sum(axis=0) / w.sum()

    @property
    def baseline_std(self) -> np.ndarray:
        # The floor keeps the PAPER count: sixteen pieces of four papers say
        # a lot about noise at this length and nothing new about how far this
        # student moves between papers, which is what the floor stands in for.
        n_papers = sum(1 for s in self.samples if s.auth_weight > 0)
        floor = max(0.005, 0.15 / math.sqrt(n_papers))
        return np.maximum(self.piece_vectors.std(axis=0), floor)

    @property
    def active_feature_mask(self) -> np.ndarray:
        V = self.piece_vectors
        stuck_at_neutral = np.all(np.abs(V - 0.5) < 0.002, axis=0)
        zero_frequency = np.all(V < 0.005, axis=0)
        constant_value = V.std(axis=0) < 0.008
        return ~(stuck_at_neutral | zero_frequency | constant_value) & (
            ~NOT_COMPUTED_FOR_BASELINES_MASK
        )


def split_into_pieces(text: str, n_words: int) -> list[str]:
    """Cut ``text`` into consecutive pieces of at least ``n_words`` words.

    ``len(words) // n_words`` pieces of near-equal size, so no word is
    dropped and no piece is shorter than the paper it will be compared with.
    A text under twice ``n_words`` comes back whole.

    Each piece is a slice of the original string, so line breaks and
    paragraph breaks inside it survive: the extractors read paragraphs and
    block quotes from them, and a piece flattened to one line would be
    measured as a single paragraph against a paragraphed paper.
    """
    words = list(_WORD.finditer(text))
    k = len(words) // n_words if n_words > 0 else 0
    if k < 2:
        return [text]
    bounds = [round(i * len(words) / k) for i in range(k + 1)]
    return [text[words[bounds[i]].start() : words[bounds[i + 1] - 1].end()] for i in range(k)]


#: Action cut points for the matched reference, in the cut-point shape
#: ``scoring._tuned_action_bands`` reads (each value is the upper edge of the
#: band named): monitor from 0.517, schedule_conversation from 0.622, escalate
#: from 0.703. The product's ACTION_THRESHOLDS (0.40 / 0.60 / 0.75) were set
#: for references built from a few whole papers, whose spread is narrower than
#: a reference of pieces. Chosen on the scholarly humanities calibration
#: partition and passed once on the locked partition (60 authors, published
#: scholars' journal articles, not student writing):
#: validation/length_match_thresholds/README.md. Used only when the match is
#: applied ("on", not abstained); the shadow preview reports the action they
#: give.
LENGTH_MATCHED_ACTION_THRESHOLDS = {"no_action": 0.517, "monitor": 0.622, "escalate": 0.703}


def _body(text: str) -> str:
    """The part of a paper that is measured, cut the way the measurement cuts
    it. Switch off: everything before the first back-matter heading, as
    always. ``MATTER_SPLITTER_ENABLED`` on (or a ``matter`` measurement in
    force): the text outside ``features.matter``'s set-aside parts (title
    page, abstract, notes, list of sources), the same ranges
    ``features.preprocess`` measures, so the length match and the reading set
    the same parts aside. A teacher's choice of parts carried by ``text``
    (``features.part_overrides``) is honoured the same way, because
    ``preprocess`` applies it, and only where it applies there: both switches
    on and the splitter's measurement in use."""
    if _ff.matter_splitter_enabled():
        return _pp._body(text)
    # An upload's page markers dropped, so the pieces are the base pieces.
    return without_page_breaks(_strip_backmatter(text))


def body_word_count(text: str) -> int:
    """The new paper's length measured the way past papers are cut: the body
    only, with the bibliography and other back matter removed first. Counting
    the raw text would let a bibliography inflate a short paper's length, so
    the match would abstain (no past paper twice as long) or cut past papers
    into pieces longer than the body they are compared with."""
    return len(_body(text).split())


def paper_pieces(text: str, n_words: int) -> list[str]:
    """The pieces of one past paper's BODY. The bibliography and any other
    back matter are removed first, as they are when the paper is measured
    whole: a piece cannot carry the heading the extractor recognises them
    by, so a piece of reference entries would be measured as prose."""
    return split_into_pieces(_body(text), n_words)


def build_length_matched_state(
    state: StudentState,
    n_words: int,
    vectorise: Callable[[str], np.ndarray],
    *,
    max_pieces: int = LENGTH_MATCH_MAX_PIECES,
) -> LengthMatchedState | None:
    """The length-matched view of ``state`` for a paper of ``n_words`` words.

    Returns None (the caller then scores exactly as if the flag were off)
    when the paper is under ``LENGTH_MATCH_MIN_WORDS``, when no contributing
    past paper is at least twice its length, when any contributing past
    paper has no retained text (its length is unknown, and a long paper left
    whole is the reference this exists to replace), or when more than
    ``max_pieces`` papers would be cut. ``state`` is not modified.
    """
    if n_words < LENGTH_MATCH_MIN_WORDS:
        return None
    contributing = [s for s in state.samples if s.auth_weight > 0]
    n = len(contributing)
    if n == 0:
        return None
    if any(not (s.text or "").strip() for s in contributing):
        return None
    # Each past paper is cut with its own stored choice of parts, if any.
    plans = [paper_pieces(_part_overrides.text_of(s), n_words) for s in contributing]
    cut = [len(p) > 1 for p in plans]
    if not any(cut) or sum(cut) > max_pieces:
        return None

    # Bound the extraction cost: when the pieces would exceed the ceiling,
    # each cut paper keeps the same number, spread evenly through its text.
    # With more than max_pieces / 2 papers cut, that number is one.
    per_paper = max_pieces // sum(cut)
    vectors: list[np.ndarray] = []
    weights: list[float] = []
    for i, (sample, pieces) in enumerate(zip(contributing, plans, strict=True)):
        paper_weight = sample.auth_weight * (RECENCY_DECAY ** (n - 1 - i))
        if len(pieces) == 1:
            rows = [np.asarray(sample.vector, dtype=np.float64)]
        else:
            if len(pieces) > per_paper:
                step = len(pieces) / per_paper
                pieces = [pieces[int(j * step)] for j in range(per_paper)]
            rows = [np.asarray(vectorise(p), dtype=np.float64) for p in pieces]
        for row in rows:
            if row.shape != (FEATURE_DIM,):
                return None
            vectors.append(row)
            weights.append(paper_weight / len(rows))

    return LengthMatchedState(
        student_id=state.student_id,
        samples=list(state.samples),
        baseline_kappa=state.baseline_kappa,
        kappa_log=list(state.kappa_log),
        _consecutive_drift_count=state._consecutive_drift_count,
        piece_vectors=np.stack(vectors),
        piece_weights=np.asarray(weights, dtype=np.float64),
        papers_cut=int(sum(cut)),
        piece_words=int(n_words),
    )
