"""
original/context/genre_v2.py — the abstaining genre resolver.

Stage 1 of docs/superpowers/specs/2026-08-08-genre-resolution-design.md.

v1 (``resolvers._resolve_genre_v1``) does not classify genre: measured
2026-08-08 over all 356 committed documents across 23 provenance groups, 86%
come out ``correspondence`` — rule 8's terminal ``else``, not a positive
class — reported at a hardcoded confidence of 0.5, and four of its eight
labels are never produced at all. The cause is that rules 1-3 gate on
signal-verb count and imperative density, whose medians are 0 on every
corpus including oratory, and rule 7 needs markup no prose has.

This module keeps the rules that can fire, fixes the one outright bug among
them (the straight-quotes-only dialogue regex), and returns ``GENRE_UNKNOWN``
instead of inventing a label. Stage 2 replaces the rule tree with a
calibrated model; the abstention contract established here does not change.

Lives outside resolvers.py deliberately: that module is already 650+ lines
covering four unrelated resolvers, and this one grows a signal extractor, an
artifact loader and an inference path in Stage 2.
"""

from __future__ import annotations

import re
from typing import Any

from ..constants import GENRE_LABELS, GENRE_RULES, GENRE_UNKNOWN

# Rule hits are UNCALIBRATED. 0.5 says "a rule matched", not "probability
# 0.5" — which is exactly why GENRE_CONFIDENCE_MIN is NOT applied in Stage 1
# (see the spec's Stage 1 section): thresholding a placeholder against a real
# floor would abstain on every rule hit and classify nothing at all.
RULE_CONFIDENCE = 0.5

# Markup is syntactic certainty rather than a stylistic judgement, so the
# structured_template rule is the one label that needs no corpus evidence.
MARKUP_CONFIDENCE = 1.0

# v1 used r'"[^"]{1,80}"' — STRAIGHT quotes only. Gutenberg-sourced prose uses
# typographic quotes, so the creative_fiction branch could never fire on it:
# measured 2026-08-08, Douglass is 0% straight / 64% curly and the Federalist
# papers 0% / 36%. A plain bug, independent of the calibration problem.
_DIALOGUE_RE = re.compile(r'"[^"]{1,80}"|“[^”]{1,80}”|‘[^’]{1,80}’')

_STRUCTURE_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)]|#{1,6}\s|\[\s*[xX ]\s*\])")


def dialogue_present(text: str) -> bool:
    """True when the text contains a quoted span, straight or typographic."""
    return _DIALOGUE_RE.search(text or "") is not None


# v1's _looks_structured needs >= 30% of non-blank lines to carry markup, with
# no floor on how many lines that is. Over two lines the ratio is meaningless:
# one paragraph plus one stray bullet scores 50%. v1 got away with it because
# the rule sat SEVENTH, after every prose branch had already had its chance.
# Here it runs FIRST — which is what makes it high-precision rather than a
# catch-all — so it needs a real floor. v1's own helper is left untouched;
# byte-identity under GENRE_RESOLVER_V2=off depends on that.
_MIN_STRUCTURED_LINES = 4


def looks_structured(text: str) -> bool:
    """Heuristic: text full of headings / numbered lists / bullets."""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if len(lines) < _MIN_STRUCTURED_LINES:
        return False
    return sum(1 for line in lines if _STRUCTURE_RE.match(line)) / len(lines) >= 0.3


def _abstain() -> dict[str, Any]:
    return {"primary": GENRE_UNKNOWN, "confidence": 0.0, "secondary": None}


def _resolve_by_rules(text: str, citation_data=None) -> dict[str, Any]:
    """
    v1's decision tree minus its two dishonest branches.

    Dropped: rule 5 (``blog_post``) and rule 8's ``correspondence`` fallback.
    Neither label has any corpus evidence behind it, and rule 8 in particular
    was the terminal ``else`` that produced 86% of all v1 output. Anything
    that reaches the end of the tree now abstains.
    """
    text = text or ""
    if not text.strip():
        return _abstain()

    # Evaluated FIRST and at full confidence: syntax, not style.
    if looks_structured(text):
        return {
            "primary": "structured_template",
            "confidence": MARKUP_CONFIDENCE,
            "secondary": None,
        }

    from ..features.preprocess import preprocess
    from ..features.tier1 import TextDoc
    from ..features.tier3 import first_person_ratio, imperative_density
    from .resolvers import _tokenize

    doc = TextDoc(text)
    word_count = max(1, doc.word_count)
    if citation_data is None:
        _, citation_data = preprocess(text)
    cite_total = (
        citation_data.paren_citation_count
        + citation_data.footnote_marker_count
        + citation_data.ibid_count
    )
    cite_density = (cite_total / word_count) * 100.0
    block_quote_ratio = citation_data.block_quote_word_count / word_count
    imp_density = imperative_density(doc)
    fp_ratio = first_person_ratio(doc)
    msl = sum(len(_tokenize(s)) for s in doc.sentences) / max(1, doc.sentence_count)
    signal_verb_total = sum(citation_data.signal_verb_counts.values())

    primary: str | None = None
    if (
        cite_density >= GENRE_RULES["academic_citation_density_min"]
        and msl >= GENRE_RULES["academic_msl_min"]
        and signal_verb_total >= GENRE_RULES["scholarly_signal_verb_min"]
    ):
        primary = "academic_exegesis"
    elif (
        cite_density >= GENRE_RULES["academic_citation_density_min"] * 0.5
        and signal_verb_total >= GENRE_RULES["scholarly_signal_verb_min"]
    ):
        primary = "scholarly_essay"
    elif (
        imp_density >= GENRE_RULES["sermon_imperative_min"]
        and fp_ratio >= GENRE_RULES["sermon_first_person_min"]
        and cite_density < GENRE_RULES["academic_citation_density_min"] * 0.5
    ):
        primary = "sermon"
    elif (
        fp_ratio >= GENRE_RULES["sermon_first_person_min"]
        and cite_density < 0.3
        and msl <= GENRE_RULES["informal_msl_max"] + 4.0
    ):
        primary = "personal_essay"
    elif (
        block_quote_ratio < 0.05
        and signal_verb_total == 0
        and cite_density < 0.1
        and msl < GENRE_RULES["academic_msl_min"]
        and dialogue_present(text)
    ):
        primary = "creative_fiction"

    if primary is None or primary not in GENRE_LABELS:
        return _abstain()
    return {"primary": primary, "confidence": RULE_CONFIDENCE, "secondary": None}


# ── Stage 2: signals ──────────────────────────────────────────────────────────
#
# Ten interpretable quantities the pipeline can already compute. The ORDER is
# load-bearing: the committed artifact pins it, and the loader refuses an
# artifact whose order disagrees, because a silent reorder would feed the
# model shuffled columns and produce confident nonsense.

# Naming rule: a genre signal that shares a name with a code in
# ALL_FEATURE_CODES carries a `raw_` prefix. The pipeline's version of that
# quantity is NORM_BOUNDS-normalised into [0, 1]; this one is the raw
# measurement (words per sentence, citations per 100 words). Same idea,
# different scale — reading one for the other would be a real error, and an
# artifact that pins these names should not invite it.
SIGNAL_ORDER: tuple[str, ...] = (
    "raw_mean_sentence_length",
    "sentence_length_dispersion",
    "raw_first_person_ratio",
    "second_person_ratio",
    "dialogue_density",
    "citation_density",
    "raw_imperative_density",
    "signal_verb_rate",
    "question_rate",
    "mean_word_length",
)

# Second-person address is a strong homiletic/instructional signal ("you must
# consider…"). Computed here rather than added to tier3: ALL_FEATURE_CODES
# ordering is frozen, and genre signals are deliberately NOT pipeline
# features — they inform a metadata resolver, not the deviation score.
_SECOND_PERSON = frozenset(
    {"you", "your", "yours", "yourself", "yourselves", "thou", "thee", "thy", "thine", "ye"}
)


def extract_signals(text: str, citation_data=None) -> dict[str, float]:
    """
    The ten genre signals. Returns zeros for empty input rather than raising:
    this runs inside a best-effort resolver on the baseline-ingestion path,
    where a crash would fail the upload.
    """
    import statistics

    from ..features.preprocess import preprocess
    from ..features.tier1 import TextDoc
    from ..features.tier3 import first_person_ratio, imperative_density
    from .resolvers import _tokenize

    text = text or ""
    if not text.strip():
        return dict.fromkeys(SIGNAL_ORDER, 0.0)

    doc = TextDoc(text)
    word_count = max(1, doc.word_count)
    sentences = doc.sentences or [text]
    lengths = [len(_tokenize(s)) for s in sentences] or [0]
    if citation_data is None:
        _, citation_data = preprocess(text)

    tokens = [t.lower() for t in _tokenize(text)]
    cite_total = (
        citation_data.paren_citation_count
        + citation_data.footnote_marker_count
        + citation_data.ibid_count
    )

    return {
        "raw_mean_sentence_length": float(statistics.fmean(lengths)),
        "sentence_length_dispersion": (
            float(statistics.pstdev(lengths)) if len(lengths) > 1 else 0.0
        ),
        "raw_first_person_ratio": float(first_person_ratio(doc)),
        "second_person_ratio": sum(1 for t in tokens if t in _SECOND_PERSON) / word_count,
        "dialogue_density": len(_DIALOGUE_RE.findall(text)) / len(sentences),
        "citation_density": (cite_total / word_count) * 100.0,
        "raw_imperative_density": float(imperative_density(doc)),
        "signal_verb_rate": (sum(citation_data.signal_verb_counts.values()) / word_count) * 100.0,
        "question_rate": sum(1 for s in sentences if s.strip().endswith("?")) / len(sentences),
        "mean_word_length": sum(len(t) for t in tokens) / max(1, len(tokens)),
    }


def signal_vector(text: str, citation_data=None) -> list[float]:
    """`extract_signals` flattened into SIGNAL_ORDER."""
    signals = extract_signals(text, citation_data)
    return [float(signals[name]) for name in SIGNAL_ORDER]


def resolve(text: str, citation_data=None) -> dict[str, Any]:
    """
    Genre with abstention. Same return shape as ``resolvers.resolve_genre``:
    ``{"primary", "confidence", "secondary"}``.

    Stage 2 swaps the rule tree here for the calibrated model while keeping
    the markup rule ahead of it and the abstention contract unchanged.
    """
    return _resolve_by_rules(text, citation_data)
