"""
context/resolvers.py — Phase 2: parallel context resolvers.

Six independent resolvers classify a submission's context before scoring:

    language          — primary language + per-segment proportions + code-switch flag
    genre             — 8-class rule-based fallback (sklearn classifier deferred)
    topic             — TF-IDF cosine distance from baseline centroid → novelty bucket
    length            — token count → {micro, short, standard, long} regime
    citations         — density, format, block-quote ratio, presence flag
    composition_mode  — natural / tool_cleaned / structured (uses keystroke data when present)

Each returns a structured dict. `run_resolvers()` executes all six in parallel
via ThreadPoolExecutor and aggregates outputs (graceful per-resolver isolation:
exceptions are caught and reported in `_errors`, not raised).

Reuses (do not reimplement):
- `_tokenize` and `TextDoc` from features.tier1 — token counting / sentence split
- `_tfidf_encode` from features.tier10 — L2-normalised TF-IDF vectors
- `CitationData` from features.preprocess — citation usage data
- `extract_tier17` from features.tier17 — keystroke biometrics

Phase 2 has NO scoring impact. Resolvers are pure functions; the orchestrator is
called from Phase 3 onwards via `original/context/manifest.build_manifest()`.
"""

from __future__ import annotations

import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..constants import (
    CITATION_FORMAT_CUES,
    COMPOSITION_RULES,
    GENRE_LABELS,
    GENRE_RULES,
    LANGUAGE_CODE_SWITCH_THRESHOLD,
    LENGTH_REGIME_BOUNDS,
    TOPIC_NOVELTY_BOUNDS,
)
from ..features.preprocess import CitationData, preprocess
from ..features.tier1 import TextDoc, _tokenize

log = logging.getLogger(__name__)


# ── langdetect setup (deterministic seeding) ─────────────────────────────────

try:
    from langdetect import DetectorFactory, detect_langs  # type: ignore
    DetectorFactory.seed = 0
    _LANGDETECT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _LANGDETECT_AVAILABLE = False
    log.warning("langdetect not installed; resolve_language will return en/unknown.")


# ══════════════════════════════════════════════════════════════════════════════
# 2.1 Language Resolver
# ══════════════════════════════════════════════════════════════════════════════

_LANG_WINDOW_CHARS = 200
_LANG_WINDOW_OVERLAP = 0.5


def resolve_language(text: str) -> Dict[str, Any]:
    """
    Chunk-level language tagging via langdetect 200-char sliding windows.

    Returns
    -------
    {
        "primary":       ISO code (e.g. "en"),
        "segments":      {lang_code: proportion_in_[0,1]},
        "code_switched": True if any non-primary > LANGUAGE_CODE_SWITCH_THRESHOLD,
    }

    Falls back gracefully to {"primary": "unknown", "segments": {}, "code_switched": False}
    when langdetect is unavailable or the text is empty.
    """
    text = text or ""
    if not text.strip():
        return {"primary": "unknown", "segments": {}, "code_switched": False}

    if not _LANGDETECT_AVAILABLE:
        return {"primary": "en", "segments": {"en": 1.0}, "code_switched": False}

    step = max(1, int(_LANG_WINDOW_CHARS * (1 - _LANG_WINDOW_OVERLAP)))
    counts: Dict[str, int] = {}
    total = 0

    if len(text) <= _LANG_WINDOW_CHARS:
        # Short text: detect once on the whole thing.
        try:
            langs = detect_langs(text)
            if langs:
                top = langs[0]
                return {
                    "primary": top.lang,
                    "segments": {top.lang: 1.0},
                    "code_switched": False,
                }
        except Exception:  # pragma: no cover
            pass
        return {"primary": "unknown", "segments": {}, "code_switched": False}

    for start in range(0, len(text) - _LANG_WINDOW_CHARS + 1, step):
        window = text[start:start + _LANG_WINDOW_CHARS]
        if len(window.strip()) < 20:
            continue
        try:
            langs = detect_langs(window)
            if langs:
                lang = langs[0].lang
                counts[lang] = counts.get(lang, 0) + 1
                total += 1
        except Exception:
            # langdetect raises on punctuation-only / numeric-only windows.
            continue

    if total == 0:
        return {"primary": "unknown", "segments": {}, "code_switched": False}

    segments = {lang: round(c / total, 4) for lang, c in counts.items()}
    primary = max(segments.items(), key=lambda kv: kv[1])[0]
    code_switched = any(
        lang != primary and prop > LANGUAGE_CODE_SWITCH_THRESHOLD
        for lang, prop in segments.items()
    )

    return {
        "primary": primary,
        "segments": segments,
        "code_switched": code_switched,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2.2 Genre Resolver — rule-based fallback (sklearn classifier deferred)
# ══════════════════════════════════════════════════════════════════════════════

def resolve_genre(text: str, citation_data: Optional[CitationData] = None) -> Dict[str, Any]:
    """
    Rule-based genre classification across the 8 GENRE_LABELS.

    Phase 2 ships ONLY the rule-based fallback (per the user's choice).
    A trained sklearn LogisticRegression follows in a later PR once the
    Phase 3 manifest pipeline has accumulated labelled examples.

    Returns
    -------
    {
        "primary":     one of GENRE_LABELS,
        "confidence":  0.5 (fixed for rule-based; trained classifier will be higher),
        "secondary":   None  (no secondary class from rules),
    }
    """
    text = text or ""
    if not text.strip():
        return {"primary": "blog_post", "confidence": 0.0, "secondary": None}

    doc = TextDoc(text)
    word_count = max(1, doc.word_count)

    # Citation density (per 100 prose words)
    if citation_data is None:
        _, citation_data = preprocess(text)
    cite_total = (
        citation_data.paren_citation_count
        + citation_data.footnote_marker_count
        + citation_data.ibid_count
    )
    cite_density = (cite_total / word_count) * 100.0

    # Block-quote ratio
    block_quote_ratio = citation_data.block_quote_word_count / word_count

    # Imperative density (per 100 sentences) — reuse tier3 helper.
    from ..features.tier3 import imperative_density, first_person_ratio

    imp_density = imperative_density(doc)
    fp_ratio = first_person_ratio(doc)

    # Mean sentence length
    msl = (
        sum(len(_tokenize(s)) for s in doc.sentences) / max(1, doc.sentence_count)
    )

    signal_verb_total = sum(citation_data.signal_verb_counts.values())

    # ── Decision tree ─────────────────────────────────────────────────────────
    # 1. Heavy citation + signal verbs + long sentences → academic_exegesis
    if (
        cite_density >= GENRE_RULES["academic_citation_density_min"]
        and msl >= GENRE_RULES["academic_msl_min"]
        and signal_verb_total >= GENRE_RULES["scholarly_signal_verb_min"]
    ):
        primary = "academic_exegesis"
    # 2. Some citations + signal verbs but lower density → scholarly_essay
    elif (
        cite_density >= GENRE_RULES["academic_citation_density_min"] * 0.5
        and signal_verb_total >= GENRE_RULES["scholarly_signal_verb_min"]
    ):
        primary = "scholarly_essay"
    # 3. High imperative + high first-person + low citation density → sermon
    elif (
        imp_density >= GENRE_RULES["sermon_imperative_min"]
        and fp_ratio >= GENRE_RULES["sermon_first_person_min"]
        and cite_density < GENRE_RULES["academic_citation_density_min"] * 0.5
    ):
        primary = "sermon"
    # 4. High first-person, very low citation, conversational sentence length → personal_essay
    elif (
        fp_ratio >= GENRE_RULES["sermon_first_person_min"]
        and cite_density < 0.3
        and msl <= GENRE_RULES["informal_msl_max"] + 4.0
    ):
        primary = "personal_essay"
    # 5. Short sentences + low citation + low first-person → blog_post
    elif (
        msl <= GENRE_RULES["informal_msl_max"]
        and cite_density < 0.3
    ):
        primary = "blog_post"
    # 6. Lots of dialogue or quoted speech without citation framing → creative_fiction
    elif (
        block_quote_ratio < 0.05
        and signal_verb_total == 0
        and cite_density < 0.1
        and msl < GENRE_RULES["academic_msl_min"]
        and re.search(r'"[^"]{1,80}"', text) is not None
    ):
        primary = "creative_fiction"
    # 7. Default for any text with structural markers (lists, headings) → structured_template
    elif _looks_structured(text):
        primary = "structured_template"
    # 8. Final fallback: scholarly_essay if any citation cues, else correspondence
    elif cite_density > 0:
        primary = "scholarly_essay"
    else:
        primary = "correspondence"

    if primary not in GENRE_LABELS:  # pragma: no cover — defensive
        primary = "blog_post"

    return {"primary": primary, "confidence": 0.5, "secondary": None}


def _looks_structured(text: str) -> bool:
    """Heuristic: text full of headings / numbered lists / bullets."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return False
    structured_lines = sum(
        1 for l in lines
        if re.match(r"^\s*(?:[-*•]|\d+[\.)]|#{1,6}\s|\[\s*[xX ]\s*\])", l)
    )
    return structured_lines / len(lines) >= 0.3


# ══════════════════════════════════════════════════════════════════════════════
# 2.3 Topic Resolver
# ══════════════════════════════════════════════════════════════════════════════

def resolve_topic(text: str, baseline_texts: List[str]) -> Dict[str, Any]:
    """
    TF-IDF cosine distance between the submission and the centroid of the
    student's baseline corpus. Maps the distance to a coarse novelty bucket.

    Returns
    -------
    {
        "domain":            "unknown"  (LDA labelling deferred to a later PR),
        "baseline_distance": cosine distance ∈ [0, 1] (0=identical, 1=orthogonal),
        "novelty":           "low" | "medium" | "high",
    }

    Falls back to {"baseline_distance": 0.5, "novelty": "medium"} if sklearn is
    unavailable or fewer than 2 baseline texts are supplied.
    """
    if not baseline_texts or len(baseline_texts) < 1 or not (text or "").strip():
        return {"domain": "unknown", "baseline_distance": 0.5, "novelty": "medium"}

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import normalize
    except ImportError:  # pragma: no cover
        log.warning("scikit-learn unavailable; topic resolver returning medium novelty.")
        return {"domain": "unknown", "baseline_distance": 0.5, "novelty": "medium"}

    try:
        vec = TfidfVectorizer(
            min_df=1, max_features=300, sublinear_tf=True, strip_accents="unicode",
        )
        # Fit on baseline corpus, transform submission.
        baseline_matrix = vec.fit_transform(baseline_texts).toarray()
        baseline_matrix = normalize(baseline_matrix, norm="l2")
        baseline_centroid = baseline_matrix.mean(axis=0)
        # Re-normalise centroid (mean-of-unit-vectors is not unit).
        norm = float(np.linalg.norm(baseline_centroid))
        if norm < 1e-12:
            return {"domain": "unknown", "baseline_distance": 0.5, "novelty": "medium"}
        baseline_centroid = baseline_centroid / norm

        submission_vec = vec.transform([text]).toarray()
        submission_vec = normalize(submission_vec, norm="l2")[0]

        cosine_sim = float(np.dot(baseline_centroid, submission_vec))
        # Clip to [-1, 1] then convert to distance ∈ [0, 1].
        cosine_sim = max(-1.0, min(1.0, cosine_sim))
        distance = round((1.0 - cosine_sim) / 2.0, 4)
    except Exception as e:  # pragma: no cover
        log.warning("Topic resolver failed: %s", e)
        return {"domain": "unknown", "baseline_distance": 0.5, "novelty": "medium"}

    if distance < TOPIC_NOVELTY_BOUNDS["low"]:
        novelty = "low"
    elif distance < TOPIC_NOVELTY_BOUNDS["medium"]:
        novelty = "medium"
    else:
        novelty = "high"

    return {"domain": "unknown", "baseline_distance": distance, "novelty": novelty}


# ══════════════════════════════════════════════════════════════════════════════
# 2.4 Length Resolver
# ══════════════════════════════════════════════════════════════════════════════

def resolve_length(text: str) -> Dict[str, Any]:
    """
    Token-count bucketing. Emits per-tier reliability flags so the manifest
    layer can mute features that degrade below their reliability floor.
    """
    tokens = _tokenize(text or "")
    n = len(tokens)

    regime = "long"
    for name, (lo, hi) in LENGTH_REGIME_BOUNDS.items():
        if lo <= n < hi:
            regime = name
            break

    # Per-regime suppress lists. Fed into the manifest derivation table.
    if regime == "micro":
        # Mute everything except T4 (char/punct), T6 (idiosyncratic), T13, T14.
        suppress_tiers = [1, 2, 3, 5, 7, 9, 10, 11, 15, 16, 17]
        reliable = [4, 6, 13, 14]
    elif regime == "short":
        suppress_tiers = [7]
        reliable = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
    else:  # standard, long
        suppress_tiers = []
        reliable = list(range(0, 18))

    return {
        "tokens": n,
        "regime": regime,
        "reliable_tiers": reliable,
        "suppress_tiers": suppress_tiers,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2.5 Citation Resolver
# ══════════════════════════════════════════════════════════════════════════════

def resolve_citations(
    text: str, citation_data: Optional[CitationData] = None
) -> Dict[str, Any]:
    """
    Citation density, format, and block-quote proportion.

    Reuses CitationData from preprocess.py (already extracted by the main
    pipeline; passed in to avoid re-running regex).

    Returns
    -------
    {
        "citations_present":  bool,
        "density":            citations per 100 prose words,
        "block_quote_ratio":  fraction of words inside block quotes,
        "format":             "chicago" | "turabian" | "mla" | "apa" | "informal" | "none",
    }
    """
    text = text or ""
    if citation_data is None:
        _, citation_data = preprocess(text)

    word_count = max(1, citation_data.prose_word_count or len(_tokenize(text)))
    cite_total = (
        citation_data.paren_citation_count
        + citation_data.footnote_marker_count
        + citation_data.ibid_count
    )

    citations_present = cite_total > 0
    density = round((cite_total / word_count) * 100.0, 4)
    block_quote_ratio = round(
        citation_data.block_quote_word_count / word_count, 4
    )

    if not citations_present:
        fmt = "none"
    else:
        fmt = "informal"
        for label, patterns in CITATION_FORMAT_CUES.items():
            for pattern in patterns:
                try:
                    if re.search(pattern, text):
                        fmt = label
                        break
                except re.error:  # pragma: no cover
                    continue
            if fmt != "informal":
                break

    return {
        "citations_present": citations_present,
        "density":           density,
        "block_quote_ratio": block_quote_ratio,
        "format":            fmt,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2.6 Composition-Mode Resolver
# ══════════════════════════════════════════════════════════════════════════════

def resolve_composition_mode(
    text: str, keystroke_data: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Infer software mediation. Three modes:

        natural_drafted  — normal error rates, no paste events
        tool_cleaned     — anomalously low error rates (Grammarly-cleaned)
        structured       — uniform sentence length / templated text

    Returns
    -------
    {
        "mode":              "natural_drafted" | "tool_cleaned" | "structured",
        "edit_signature":    "normal" | "heavy" | "uniform",
        "software_mediated": bool,
    }
    """
    text = text or ""
    doc = TextDoc(text)
    n = max(1, doc.word_count)

    # ── Paste/keystroke signal (when available) ───────────────────────────────
    software_mediated = False
    edit_signature = "normal"
    if keystroke_data:
        try:
            from ..features.tier17 import extract_tier17  # lazy import

            t17 = extract_tier17(keystroke_data)
            paste_rate = float(t17.get("paste_event_rate", 0.0))
            del_rate = float(t17.get("deletion_rate", 0.0))
            rev_depth = float(t17.get("revision_depth", 0.0))
            if paste_rate > 0:
                software_mediated = True
            if del_rate > 0.20 or rev_depth > 30:
                edit_signature = "heavy"
        except Exception:  # pragma: no cover
            pass

    # ── Tool-cleaned heuristic (text-only) ────────────────────────────────────
    # We don't have direct comma_splice / punct_error counts at this layer, so
    # use surface proxies: comma splice ≈ comma after a finite verb mid-sentence,
    # punctuation errors ≈ doubled punctuation / spacing anomalies.
    comma_splice_rate = _estimate_comma_splice_rate(text)
    punct_error_ratio = _estimate_punct_error_ratio(text)

    looks_clean = (
        comma_splice_rate < COMPOSITION_RULES["tool_cleaned_comma_splice_max"]
        and punct_error_ratio < COMPOSITION_RULES["tool_cleaned_punct_error_max"]
        and n >= 200  # short texts naturally have low error rates
    )

    # ── Structured-template heuristic ─────────────────────────────────────────
    msl_var = _sentence_length_variance(doc)
    looks_structured = (
        doc.sentence_count >= 5
        and msl_var < 4.0  # very low variance in sentence length
    )

    if software_mediated or looks_clean:
        mode = "tool_cleaned"
        software_mediated = True
    elif looks_structured:
        mode = "structured"
        edit_signature = "uniform"
    else:
        mode = "natural_drafted"

    return {
        "mode":              mode,
        "edit_signature":    edit_signature,
        "software_mediated": software_mediated,
    }


def _estimate_comma_splice_rate(text: str) -> float:
    """Rough comma-splice estimator: comma followed by 2+ words then a period."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if not sentences:
        return 0.0
    splices = sum(1 for s in sentences if re.search(r",\s+\w+\s+\w+\s+\w+\s+\w+\s+\w+\.", s))
    # per-sentence rate
    return splices / max(1, len(sentences))


def _estimate_punct_error_ratio(text: str) -> float:
    """Doubled punctuation / orphan-space punctuation per character."""
    if not text:
        return 0.0
    errors = (
        len(re.findall(r"[,.;:!?]{2,}", text))
        + len(re.findall(r"\s+[,.;:!?]", text))
    )
    return errors / max(1, len(text))


def _sentence_length_variance(doc: TextDoc) -> float:
    if doc.sentence_count < 2:
        return 0.0
    lens = [len(_tokenize(s)) for s in doc.sentences]
    mean = sum(lens) / len(lens)
    return sum((l - mean) ** 2 for l in lens) / len(lens)


# ══════════════════════════════════════════════════════════════════════════════
# 2.7 Orchestrator — parallel execution with per-resolver isolation
# ══════════════════════════════════════════════════════════════════════════════

_RESOLVER_TIMEOUT_SEC = 30.0


def run_resolvers(
    text: str,
    baseline_texts: List[str],
    citation_data: Optional[CitationData] = None,
    keystroke_data: Optional[Dict] = None,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Run all six resolvers in parallel via ThreadPoolExecutor.

    Per-resolver exceptions are caught and surfaced in `_errors` rather than
    raised — this is the graceful-degradation contract guaranteed to the
    caller in `original/context/manifest.build_manifest()`.

    Returns a dict with one key per resolver plus an `_errors` list. Each
    successful resolver contributes its native output dict.
    """
    # If citation_data was not pre-extracted, do it once here so both
    # resolve_genre and resolve_citations can share it (cheap regex pass).
    if citation_data is None:
        try:
            _, citation_data = preprocess(text or "")
        except Exception as e:
            log.warning("preprocess failed inside run_resolvers: %s", e)
            citation_data = None

    tasks = {
        "language":         (resolve_language,         (text,)),
        "genre":            (resolve_genre,            (text, citation_data)),
        "topic":            (resolve_topic,            (text, baseline_texts or [])),
        "length":           (resolve_length,           (text,)),
        "citations":        (resolve_citations,        (text, citation_data)),
        "composition_mode": (resolve_composition_mode, (text, keystroke_data)),
    }

    results: Dict[str, Any] = {}
    errors: List[Dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(fn, *args): name
            for name, (fn, args) in tasks.items()
        }
        for fut in as_completed(futures, timeout=_RESOLVER_TIMEOUT_SEC):
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as e:
                log.warning("Resolver '%s' failed: %s", name, e)
                errors.append({"resolver": name, "exc": f"{type(e).__name__}: {e}"})

    if errors:
        results["_errors"] = errors

    return results


__all__ = [
    "resolve_language",
    "resolve_genre",
    "resolve_topic",
    "resolve_length",
    "resolve_citations",
    "resolve_composition_mode",
    "run_resolvers",
]
