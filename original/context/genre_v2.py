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

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

from ..constants import GENRE_LABELS, GENRE_RULES, GENRE_UNKNOWN

log = logging.getLogger(__name__)

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
#
# The 80-character span cap is also v1's, and it was harmless there because
# the rule only asked "is there ANY dialogue". As the basis of a continuous
# model feature it silently scored zero on extended character speech and on
# block-style source quotation — undercounting precisely where quoting is
# heaviest, and asymmetrically across classes. Raised to 400, which covers
# ordinary speech and quoted sentences.
#
# A cap is still needed rather than removed: an unbalanced quotation mark
# would otherwise let one match swallow the rest of the document. `[^"\n]`
# additionally stops a match crossing a line break, so a stray opening quote
# costs at most the remainder of its own line.
_MAX_QUOTE_SPAN = 400
_DIALOGUE_RE = re.compile(
    rf'"[^"\n]{{1,{_MAX_QUOTE_SPAN}}}"'
    rf"|“[^”\n]{{1,{_MAX_QUOTE_SPAN}}}”"
    rf"|‘[^’\n]{{1,{_MAX_QUOTE_SPAN}}}’"
)

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
# Sixteen interpretable quantities the pipeline can already compute: the ten
# original style signals plus the six argument-versus-narration signals added
# when the first ten proved unable to separate argument from account. The
# ORDER is
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
    # Argument-versus-narration. The six below exist because the ten above
    # could not tell personal_essay from scholarly_essay: on the derivation
    # split raw_first_person_ratio separated them by only 1.0 pooled SD
    # (0.413 vs 0.278). First-person RATIO cannot distinguish "I arguing"
    # from "I narrating" — Mill writes "I" while arguing about liberty,
    # Thoreau writes "I" about what he did at Walden. The codebook's own
    # deciding test is which kind of work the first person is doing, and
    # these operationalise it.
    "past_tense_ratio",
    "modal_verb_rate",
    "argumentative_connective_rate",
    "narrative_connective_rate",
    "abstract_noun_ratio",
    "proper_noun_rate",
)

# Second-person address is a strong homiletic/instructional signal ("you must
# consider…"). Computed here rather than added to tier3: ALL_FEATURE_CODES
# ordering is frozen, and genre signals are deliberately NOT pipeline
# features — they inform a metadata resolver, not the deviation score.
_SECOND_PERSON = frozenset(
    {"you", "your", "yours", "yourself", "yourselves", "thou", "thee", "thy", "thine", "ye"}
)

_MODALS = frozenset(
    {"must", "ought", "should", "shall", "may", "might", "cannot", "can", "would", "could"}
)

_ARGUMENTATIVE_CONNECTIVES = frozenset(
    {
        "therefore",
        "however",
        "thus",
        "hence",
        "moreover",
        "nevertheless",
        "consequently",
        "furthermore",
        "accordingly",
        "conversely",
        "whereas",
        "indeed",
        "nonetheless",
        "otherwise",
    }
)

_NARRATIVE_CONNECTIVES = frozenset(
    {
        "then",
        "afterwards",
        "afterward",
        "suddenly",
        "meanwhile",
        "presently",
        "next",
        "later",
        "once",
        "soon",
        "immediately",
        "finally",
    }
)

# Nominalisation suffixes: abstraction is the hallmark of expository prose,
# and its absence of concrete narrative.
_ABSTRACT_SUFFIXES = ("tion", "sion", "ness", "ity", "ism", "ment", "ance", "ence", "ship")

# Words ending in -ed that are not past-tense verbs. Without this the suffix
# test counted 'need' and 'indeed' — both markedly frequent in argumentative
# prose, which is the class this signal exists to distinguish narrative FROM.
# 'indeed' was doubly wrong: it also sits in _ARGUMENTATIVE_CONNECTIVES, so a
# single token incremented an argument marker and a narrative marker at once.
_NOT_PAST_ED = frozenset(
    {
        "need",
        "indeed",
        "hundred",
        "sacred",
        "united",
        "wicked",
        "naked",
        "seed",
        "deed",
        "creed",
        "breed",
        "speed",
        "greed",
        "freed",
        "agreed",
        "exceed",
        "succeed",
        "proceed",
        "indebted",
        "aged",
        "learned",
        "blessed",
        "beloved",
        "hatred",
        "embed",
        "shed",
        "sled",
        "bed",
        "fed",
        "led",
        "red",
        "wed",
    }
)

# Irregular past forms common enough that an -ed test alone would miss the
# narrative signal entirely.
#
# EXCLUDES forms identical in the present tense — "let", "put", "read", "set",
# "cut", "cost", "hurt". "let us consider" and "put simply" are exposition,
# and counting them pushed scholarly prose toward the narrative end of the
# very axis this signal defines.
_IRREGULAR_PAST = frozenset(
    {
        "was",
        "were",
        "had",
        "did",
        "said",
        "went",
        "came",
        "saw",
        "took",
        "made",
        "knew",
        "thought",
        "found",
        "gave",
        "told",
        "became",
        "left",
        "felt",
        "brought",
        "began",
        "kept",
        "held",
        "stood",
        "heard",
        "sat",
        "spoke",
        "lay",
        "ran",
        "drew",
        "fell",
        "rose",
        "grew",
        "wrote",
    }
)


def _is_past_tense(token: str) -> bool:
    """True for tokens that genuinely mark past-tense narration."""
    if token in _NOT_PAST_ED:
        return False
    return token in _IRREGULAR_PAST or (token.endswith("ed") and len(token) > 3)


def _tokens_for_rates(text: str):
    """
    The ONE tokenisation every per-word rate divides by.

    Named and shared deliberately. Three signals used to divide by
    ``TextDoc.word_count`` while six divided by ``len(_tokenize(text))`` —
    two different tokenisers, which disagree on punctuation, for quantities
    that read as parallel "per word" rates. The standardiser absorbs a
    constant factor so a model still fits, but the two groups drifted apart
    differently as punctuation density changed, and nothing in the names said
    which denominator a given signal used.
    """
    from .resolvers import _tokenize

    return _tokenize(text)


def extract_signals(text: str, citation_data=None) -> dict[str, float]:
    """
    The sixteen genre signals, keyed by SIGNAL_ORDER. Returns zeros for empty
    input rather than raising: this runs inside a best-effort resolver on the
    baseline-ingestion path, where a crash would fail the upload.
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
    sentences = doc.sentences or [text]
    lengths = [len(_tokenize(s)) for s in sentences] or [0]
    if citation_data is None:
        _, citation_data = preprocess(text)

    # One denominator for every per-word rate below — see _tokens_for_rates.
    tokens = [t.lower() for t in _tokens_for_rates(text)]
    n_tokens = max(1, len(tokens))
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
        "second_person_ratio": sum(1 for t in tokens if t in _SECOND_PERSON) / n_tokens,
        "dialogue_density": len(_DIALOGUE_RE.findall(text)) / len(sentences),
        "citation_density": (cite_total / n_tokens) * 100.0,
        "raw_imperative_density": float(imperative_density(doc)),
        "signal_verb_rate": (sum(citation_data.signal_verb_counts.values()) / n_tokens) * 100.0,
        "question_rate": sum(1 for s in sentences if s.strip().endswith("?")) / len(sentences),
        "mean_word_length": sum(len(t) for t in tokens) / max(1, len(tokens)),
        "past_tense_ratio": sum(1 for t in tokens if _is_past_tense(t)) / n_tokens,
        "modal_verb_rate": sum(1 for t in tokens if t in _MODALS) / n_tokens,
        "argumentative_connective_rate": sum(1 for t in tokens if t in _ARGUMENTATIVE_CONNECTIVES)
        / n_tokens,
        "narrative_connective_rate": sum(1 for t in tokens if t in _NARRATIVE_CONNECTIVES)
        / n_tokens,
        "abstract_noun_ratio": sum(
            1 for t in tokens if len(t) > 5 and t.endswith(_ABSTRACT_SUFFIXES)
        )
        / n_tokens,
        # Capitalised tokens that are NOT sentence-initial: names of people
        # and places, which peopled narrative has and abstract argument does
        # not. Sentence-initial capitals are excluded because every sentence
        # has one regardless of genre.
        "proper_noun_rate": _proper_noun_rate(sentences),
    }


def _proper_noun_rate(sentences) -> float:
    """Share of tokens that are capitalised but not sentence-initial."""
    from .resolvers import _tokenize

    total = 0
    proper = 0
    for sentence in sentences:
        words = _tokenize(sentence)
        total += len(words)
        proper += sum(1 for w in words[1:] if w[:1].isupper())
    return proper / max(1, total)


def signal_vector(text: str, citation_data=None) -> list[float]:
    """`extract_signals` flattened into SIGNAL_ORDER."""
    signals = extract_signals(text, citation_data)
    return [float(signals[name]) for name in SIGNAL_ORDER]


# ── Stage 2: the calibrated model ─────────────────────────────────────────────
#
# A multinomial logistic regression stored as plain coefficients plus a
# standardiser (original/data/genre_model_v1.json), NOT a pickled estimator.
# The artifact is committed to git, so a pickle there would be a
# code-execution surface; and keeping inference to numpy means this resolver
# has NO sklearn runtime dependency — sklearn appears only in the dev and
# demo locks, not the base requirements.txt. sklearn is used solely by the
# offline derivation in validation/genre_2026-08/derive.py.

_DEFAULT_ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "data" / "genre_model_v1.json"
_EXPECTED_SCHEMA_VERSION = 1

_UNLOADED, _READY, _FAILED = 0, 1, 2
_state = _UNLOADED
_artifact: dict | None = None
_lock = threading.Lock()


def _artifact_path() -> Path:
    override = os.environ.get("GENRE_MODEL_PATH", "").strip()
    return Path(override) if override else _DEFAULT_ARTIFACT_PATH


def _reset_artifact_for_test() -> None:
    """Drop the cached artifact so a test can point GENRE_MODEL_PATH
    elsewhere. Not used in production — the load is once per process."""
    global _state, _artifact
    with _lock:
        _state, _artifact = _UNLOADED, None


def _fail(reason: str) -> None:
    global _state, _artifact
    log.warning("Genre model disabled: %s (path=%s)", reason, _artifact_path())
    _state, _artifact = _FAILED, None


def _load_artifact() -> None:
    """
    Validate and cache the artifact, failing CLOSED on any drift.

    "Closed" here means the resolver abstains — it does NOT fall back to the
    rule tree. Silently swapping mechanisms is how a measurement stops meaning
    what its label says: a "genre" recorded on a submission would sometimes be
    a model verdict and sometimes a rule verdict, with nothing in the record
    saying which.
    """
    global _state, _artifact
    try:
        import json

        import numpy as np

        path = _artifact_path()
        if not path.exists():
            _fail("artifact not found")
            return
        artifact = json.loads(path.read_text())

        if not isinstance(artifact, dict):
            _fail("artifact is not an object")
            return
        if artifact.get("schema_version") != _EXPECTED_SCHEMA_VERSION:
            _fail("schema version mismatch")
            return
        if tuple(artifact.get("signal_order") or ()) != SIGNAL_ORDER:
            _fail("signal order mismatch")
            return

        classes = artifact.get("classes") or []
        coef = np.asarray(artifact.get("coef"), dtype=np.float64)
        intercept = np.asarray(artifact.get("intercept"), dtype=np.float64)
        mean = np.asarray(artifact.get("mean"), dtype=np.float64)
        scale = np.asarray(artifact.get("scale"), dtype=np.float64)
        if coef.shape != (len(classes), len(SIGNAL_ORDER)):
            _fail("coefficient shape mismatch")
            return
        if intercept.shape != (len(classes),):
            _fail("intercept shape mismatch")
            return
        if mean.shape != (len(SIGNAL_ORDER),) or scale.shape != (len(SIGNAL_ORDER),):
            _fail("scaler shape mismatch")
            return
        if not np.all(scale > 0):
            # A zero-scale column divides by zero and makes its coefficient
            # meaningless — the artifact is not usable, not merely imprecise.
            _fail("scaler has a non-positive scale")
            return

        threshold = float(artifact.get("confidence_min", -1.0))
        if not 0.0 < threshold < 1.0:
            _fail("invalid confidence floor")
            return

        # Numeric drift: the committed reference rows must still produce the
        # probabilities they produced at derivation time. This catches a
        # coefficient edited by hand, a numpy version that changed the
        # arithmetic, and a truncated float in the JSON.
        reference = np.asarray(artifact["reference_signals"], dtype=np.float64)
        expected = np.asarray(artifact["reference_probabilities"], dtype=np.float64)
        got = _softmax(((reference - mean) / scale) @ coef.T + intercept)
        if float(np.max(np.abs(got - expected))) > 1e-8:
            _fail("reference prediction drift")
            return

        artifact["_coef"] = coef
        artifact["_intercept"] = intercept
        artifact["_mean"] = mean
        artifact["_scale"] = scale
        _artifact, _state = artifact, _READY
    except Exception as exc:  # noqa: BLE001 — any failure means abstain
        _fail(f"{type(exc).__name__}: {exc}")


def _softmax(z):
    import numpy as np

    z = np.asarray(z, dtype=np.float64)
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def _ensure_loaded() -> bool:
    global _state
    if _state == _READY:
        return True
    if _state == _FAILED:
        return False
    with _lock:
        if _state == _UNLOADED:
            _load_artifact()
    return _state == _READY


def _confidence_min() -> float:
    if not _ensure_loaded() or _artifact is None:
        from ..constants import GENRE_CONFIDENCE_MIN

        return GENRE_CONFIDENCE_MIN
    return float(_artifact["confidence_min"])


def _class_probabilities(signals: list[float]) -> dict[str, float]:
    """Calibrated class probabilities for one signal vector."""
    import numpy as np

    if not _ensure_loaded() or _artifact is None:
        return {}
    x = np.asarray(signals, dtype=np.float64)
    z = ((x - _artifact["_mean"]) / _artifact["_scale"]) @ _artifact["_coef"].T + _artifact[
        "_intercept"
    ]
    probabilities = _softmax(z)
    return {cls: float(p) for cls, p in zip(_artifact["classes"], probabilities, strict=True)}


def predict(text: str, citation_data=None) -> dict[str, Any]:
    """
    Model verdict, or abstention.

    Abstains when the artifact will not load, when the text is empty, or when
    the winning class probability falls below the artifact's frozen
    confidence floor.
    """
    text = text or ""
    if not text.strip():
        return _abstain()
    probabilities = _class_probabilities(signal_vector(text, citation_data))
    if not probabilities:
        return _abstain()
    winner, confidence = max(probabilities.items(), key=lambda kv: kv[1])
    if confidence < _confidence_min():
        return _abstain()
    return {"primary": winner, "confidence": float(confidence), "secondary": None}


def resolve(text: str, citation_data=None) -> dict[str, Any]:
    """
    Genre with abstention. Same return shape as ``resolvers.resolve_genre``:
    ``{"primary", "confidence", "secondary"}``.

    The markup rule runs FIRST — it keys on syntax rather than style, so it
    needs no corpus evidence and no model — and everything else goes to the
    calibrated classifier, which abstains rather than guessing.
    """
    text = text or ""
    if not text.strip():
        return _abstain()
    if looks_structured(text):
        return {
            "primary": "structured_template",
            "confidence": MARKUP_CONFIDENCE,
            "secondary": None,
        }
    return predict(text, citation_data)
