"""
original/tension_arc.py
=======================
Tension Arc Analysis — Catastrophe/Eucatastrophe Stylometric Fingerprinting.

Theory
------
AI writing is structurally eucatastrophic by default: it almost always resolves
tension promptly and consistently because it was trained on human approval and
humans approve of resolution. Genuine human writing carries detectable catastrophic
moments — places where structure sags, confidence falters, threads are left open.

This module quantifies that difference as the Catastrophe Index κ:

    κ = σ(ρ_paragraphs) · (1 - μ(ρ_paragraphs))

where ρ is the per-paragraph resolution ratio (fraction of raised tensions that
actually close within the same paragraph). High κ → human; low κ → AI-typical.

Per-sentence tension:
    T(i) = α·S(i) + β·L(i) + γ·C(i)
    S = syntactic tension (unresolved subordinate structures)
    L = logical tension   (cumulative Q/K debt minus R resolution)
    C = cohesion tension  (semantic distance from prior context)

Dependencies: spacy, numpy, sentence-transformers (torch backend)
Call load_models() once at startup; all cosine similarity uses pure numpy.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)

# ── Model handles (loaded once at startup) ────────────────────────────────────

_nlp = None   # spacy.language.Language — loaded lazily
_embedder = None   # SentenceTransformer — typed loosely to avoid import-time crash
_spacy_available = None   # None = untested, True/False = cached result


def load_models() -> None:
    """Call once in FastAPI startup event (or lazily on first use)."""
    global _nlp, _embedder, _spacy_available
    if _nlp is None:
        try:
            import spacy as _spacy
            _nlp = _spacy.load("en_core_web_sm")
            _spacy_available = True
        except (ImportError, OSError) as exc:
            _spacy_available = False
            log.warning(
                "spaCy unavailable — tension_arc analysis will return fallback κ=0.0. "
                "Run: pip install spacy && python -m spacy download en_core_web_sm  (%s)", exc
            )
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError:
            log.warning("sentence-transformers unavailable — cohesion tension will be 0.")


def _get_nlp() -> Any:
    global _nlp, _spacy_available
    if _nlp is None and _spacy_available is not False:
        load_models()
    return _nlp


def _get_embedder() -> Any:
    global _embedder
    if _embedder is None:
        load_models()
    return _embedder


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class SentenceTension:
    index: int
    text: str
    syntactic: float     # S(i)
    logical: float       # L(i)
    cohesion: float      # C(i)
    total: float         # T(i) = α·S + β·L + γ·C
    move_type: str       # Q / C / E / K / R / N


@dataclass
class ParagraphArc:
    index: int
    sentences: List[SentenceTension]
    peak_count: int
    resolved_peaks: int
    resolution_ratio: float   # ρ for this paragraph
    mean_tension: float
    max_tension: float


@dataclass
class TensionArcResult:
    """Full tension arc analysis for one submission. Attach to your Layer7Output."""
    tension_series: List[float]           # per-sentence T(i), for chart rendering
    paragraph_arcs: List[ParagraphArc]
    resolution_ratio_mean: float          # μ(ρ)
    resolution_ratio_std: float           # σ(ρ)
    catastrophe_index: float              # κ = σ(ρ)·(1 - μ(ρ))
    mean_tension: float                   # μ(T) — amplitude signal (AI is much flatter)
    max_tension: float                    # max T(i) — AI rarely exceeds 0.25
    authenticity_signal: Optional[float]  # None if no student baseline yet
    arc_flag: str                         # "authentic" | "ai_typical" | "review"
    arc_flag_reason: str


# ── Tuning constants ──────────────────────────────────────────────────────────

ALPHA = 0.40   # syntactic weight
BETA  = 0.35   # logical weight
GAMMA = 0.25   # cohesion weight

TENSION_THRESHOLD = 0.28   # θ — minimum T(i) to count as a tension peak
#                            (academic prose scores 0.15–0.45; creative prose higher)
RESOLUTION_DROP   = 0.10   # δ — peak must drop by this much to count as resolved
RESOLUTION_WINDOW = 3      # k — sentences within which the drop must occur

# Dependency labels representing open syntactic structures
OPEN_DEP_LABELS = {"advcl", "ccomp", "xcomp", "acl", "relcl"}

# Lightweight move-type classifiers
_RE_RESOLUTION  = re.compile(
    r"^(therefore |thus |in conclusion |ultimately |finally |"
    r"this means |the answer |we can see |it is (clear|evident))",
    re.IGNORECASE,
)
_RE_CONCESSION  = re.compile(
    r"^(admittedly |granted |of course |to be (sure|fair)|"
    r"one must acknowledge |it is true that |while it is true)",
    re.IGNORECASE,
)
_RE_CLAIM       = re.compile(
    r"^(therefore |thus |hence |this (shows|means|demonstrates|suggests)|"
    r"clearly |obviously |the (key|central|main)|in (short|sum|brief))",
    re.IGNORECASE,
)
_RE_QUESTION    = re.compile(
    r"^(but |however |although |even though |yet |while |despite |"
    r"one might |critics |some argue |it could be |admittedly |granted )",
    re.IGNORECASE,
)
_RE_EVIDENCE    = re.compile(
    r"\d{4}|et al\.|ibid\.|op\. cit\.|for (example|instance)|"
    r"as (shown|demonstrated|evidenced|seen)",
    re.IGNORECASE,
)


# ── Feature extractors ────────────────────────────────────────────────────────

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Pure numpy cosine similarity — no sklearn required."""
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _syntactic_tension(sent: Any) -> float:
    """
    S(i) = (O - R) / max(O, 1)
    O = open subordinate / complement structures
    R = those resolved within the same sentence boundary
    Also penalises unclosed correlatives (not only…, either…, neither…).
    """
    open_count = resolved_count = 0
    for token in sent:
        if token.dep_ in OPEN_DEP_LABELS:
            open_count += 1
            if sent.start <= token.head.i < sent.end:
                resolved_count += 1

    text_lower = sent.text.lower()
    corr_open  = sum(1 for p in ["not only", "either ", "neither ", "both "] if p in text_lower)
    corr_close = sum(1 for p in ["but also", "or ", "nor ", "and "]          if p in text_lower)
    corr_unres = max(0, corr_open - corr_close)

    total_open = open_count + corr_unres
    return (total_open - resolved_count) / max(total_open, 1)


def _classify_move(text: str) -> str:
    """
    Q = question/problem | C = claim | E = evidence |
    K = concession       | R = resolution | N = neutral
    """
    s = text.strip()
    if s.endswith("?"):                return "Q"
    if _RE_RESOLUTION.match(s):       return "R"
    if _RE_CONCESSION.match(s):       return "K"
    if _RE_CLAIM.match(s):            return "C"
    if _RE_QUESTION.match(s):         return "Q"
    if _RE_EVIDENCE.search(s):        return "E"
    return "N"


def _logical_tension(move_sequence: List[str], current_index: int) -> float:
    """
    L(i) = (Q_count + K_count − R_count) / (i + 1)   clipped to [0, 1]
    Cumulative tension debt up to position i.
    """
    moves = move_sequence[: current_index + 1]
    q = moves.count("Q")
    k = moves.count("K")
    r = moves.count("R")
    return float(np.clip((q + k - r) / len(moves), 0.0, 1.0))


def _cohesion_tension(embeddings: np.ndarray, current_index: int, window: int = 3) -> float:
    """
    C(i) = 1 - cosine_similarity(v(i), mean(v(i-window)…v(i-1)))
    Returns 0 for the first sentence (no prior context).
    """
    if current_index == 0:
        return 0.0
    start  = max(0, current_index - window)
    prior  = embeddings[start:current_index]
    ctx    = prior.mean(axis=0)
    return float(np.clip(1.0 - _cosine(embeddings[current_index], ctx), 0.0, 1.0))


# ── Paragraph splitter ────────────────────────────────────────────────────────

def _split_paragraphs(text: str) -> List[str]:
    raw = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in raw if len(p.strip()) > 30]


# ── Peak detection & resolution ───────────────────────────────────────────────

def _find_peaks(vals: List[float]) -> List[int]:
    n = len(vals)
    peaks: List[int] = []
    for i in range(1, n - 1):
        if vals[i] > vals[i-1] and vals[i] > vals[i+1] and vals[i] >= TENSION_THRESHOLD:
            peaks.append(i)
    if n >= 2 and vals[0] >= TENSION_THRESHOLD and vals[0] > vals[1]:
        peaks.insert(0, 0)
    if n >= 2 and vals[-1] >= TENSION_THRESHOLD and vals[-1] > vals[-2]:
        peaks.append(n - 1)
    return peaks


def _count_resolved_peaks(vals: List[float], peaks: List[int]) -> int:
    resolved = 0
    n = len(vals)
    for p in peaks:
        peak_val   = vals[p]
        window_end = min(p + RESOLUTION_WINDOW + 1, n)
        for j in range(p + 1, window_end):
            if peak_val - vals[j] >= RESOLUTION_DROP:
                resolved += 1
                break
    return resolved


# ── Paragraph analysis ────────────────────────────────────────────────────────

def _analyze_paragraph(para_text: str, para_index: int) -> ParagraphArc:
    nlp      = _get_nlp()
    embedder = _get_embedder()

    if nlp is None:
        # spaCy not available — return a neutral arc so the pipeline can continue
        return ParagraphArc(
            index=para_index, sentences=[],
            peak_count=0, resolved_peaks=0, resolution_ratio=1.0,
            mean_tension=0.0, max_tension=0.0,
        )

    doc       = nlp(para_text)
    sentences = list(doc.sents)

    if not sentences:
        return ParagraphArc(
            index=para_index, sentences=[],
            peak_count=0, resolved_peaks=0, resolution_ratio=1.0,
            mean_tension=0.0, max_tension=0.0,
        )

    sent_texts = [s.text.strip() for s in sentences]
    embeddings = (embedder.encode(sent_texts, convert_to_numpy=True)   # (N, D)
                  if embedder is not None
                  else np.zeros((len(sent_texts), 1), dtype=np.float32))
    moves      = [_classify_move(t) for t in sent_texts]

    sentence_tensions: List[SentenceTension] = []
    tension_values:    List[float]           = []

    for i, sent in enumerate(sentences):
        s_val = _syntactic_tension(sent)
        l_val = _logical_tension(moves, i)
        c_val = _cohesion_tension(embeddings, i) if embedder is not None else 0.0

        t_val = float(np.clip(ALPHA * s_val + BETA * l_val + GAMMA * c_val, 0.0, 1.0))

        sentence_tensions.append(SentenceTension(
            index=i, text=sent_texts[i],
            syntactic=round(s_val, 4), logical=round(l_val, 4),
            cohesion=round(c_val, 4),  total=round(t_val, 4),
            move_type=moves[i],
        ))
        tension_values.append(t_val)

    peaks    = _find_peaks(tension_values)
    resolved = _count_resolved_peaks(tension_values, peaks)
    rho      = resolved / len(peaks) if peaks else 1.0

    return ParagraphArc(
        index=para_index,
        sentences=sentence_tensions,
        peak_count=len(peaks),
        resolved_peaks=resolved,
        resolution_ratio=round(rho, 4),
        mean_tension=round(float(np.mean(tension_values)), 4),
        max_tension=round(float(np.max(tension_values)), 4),
    )


# ── Document-level aggregation ────────────────────────────────────────────────

def _compute_catastrophe(rho_values: List[float]) -> Tuple[float, float, float]:
    """Returns (μ, σ, κ)  where κ = σ·(1 - μ)."""
    if not rho_values:
        return 1.0, 0.0, 0.0
    mu  = float(np.mean(rho_values))
    sig = float(np.std(rho_values))
    kappa = sig * (1.0 - mu)
    return round(mu, 4), round(sig, 4), round(kappa, 4)


def _authenticity_signal(kappa: float, kappa_baseline: float) -> float:
    """
    A_κ = 1 - |κ_submission - κ_baseline| / max(κ_baseline, 0.001)
    Clipped to [0, 1].  Below 0.70 → flag for review.
    """
    if kappa_baseline < 0.001:
        return 1.0
    raw = 1.0 - abs(kappa - kappa_baseline) / kappa_baseline
    return round(float(np.clip(raw, 0.0, 1.0)), 4)


def _arc_flag(
    kappa: float,
    mu_rho: float,
    mean_tension: float,
    max_tension: float,
    authenticity: Optional[float],
    num_rho_values: int = 0,
) -> Tuple[str, str]:
    """
    Multi-signal flag combining:
    - κ (catastrophe index) — structural variance in resolution
    - μ(ρ)  — mean resolution ratio
    - μ(T)  — mean tension amplitude (AI writing is characteristically flat)
    - max(T) — AI rarely builds tension above 0.18 in academic prose

    Calibrated ranges (academic theological prose):
      AI prose:        max(T) ≈ 0.10–0.15
      Human borderline: max(T) ≈ 0.20–0.28  → "review"
      Human clear:     max(T) ≈ 0.30–0.50  → "authentic"

    The κ rule requires num_rho_values ≥ 3 because σ(ρ) is structurally 0
    for short documents with fewer than 3 paragraphs containing tension peaks.
    """
    # Baseline deviation trumps everything
    if authenticity is not None and authenticity < 0.70:
        return (
            "review",
            f"Tension arc deviates significantly from this student's baseline "
            f"(authenticity signal: {authenticity:.2f}). May indicate AI assistance "
            f"or atypical writing conditions.",
        )

    # Strong AI signal: flat tension amplitude + high resolution
    # Threshold at 0.18 — AI academic prose consistently scores 0.10–0.15;
    # human academic prose rarely falls below 0.20 even in short essays.
    if max_tension < 0.18 and mu_rho > 0.80:
        return (
            "ai_typical",
            f"Writing tension is characteristically flat (max T={max_tension:.3f}, "
            f"AI-typical <0.18) with near-total resolution of every raised tension "
            f"(μ(ρ)={mu_rho:.2f}). Pattern is consistent with AI-generated prose.",
        )

    # κ-based signal — only reliable with 3+ paragraphs of peak data.
    # For short essays (1–2 paragraphs) σ(ρ) is structurally 0, making κ=0
    # an artefact of insufficient data, not an AI signal.
    if num_rho_values >= 3 and mu_rho > 0.85 and kappa < 0.08:
        return (
            "ai_typical",
            f"Resolution ratio μ={mu_rho:.2f} and catastrophe index κ={kappa:.3f} "
            f"match AI writing patterns: nearly all tension resolves promptly, "
            f"with minimal genuine catastrophic moments ({num_rho_values} paragraphs analysed).",
        )

    # Strong human signal: meaningful tension + variance in resolution
    if max_tension > 0.30 and (mu_rho < 0.75 or kappa > 0.08):
        return (
            "authentic",
            f"Writing shows genuine tension amplitude (max T={max_tension:.3f}) "
            f"with unresolved peaks (μ(ρ)={mu_rho:.2f}, κ={kappa:.3f}). "
            f"Pattern is consistent with authentic human writing.",
        )

    return (
        "review",
        f"Tension arc metrics (μ(T)={mean_tension:.3f}, max={max_tension:.3f}, "
        f"μ(ρ)={mu_rho:.2f}, κ={kappa:.3f}) are inconclusive. "
        f"Review alongside other stylometric signals.",
    )


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_tension_arc(
    text: str,
    baseline_kappa: Optional[float] = None,
) -> TensionArcResult:
    """
    Main entry point.  Call from your existing score pipeline.

    Args:
        text:             Full submission text.
        baseline_kappa:   Student's running κ from prior authenticated submissions.
                          Pass None if no baseline exists yet.

    Returns:
        TensionArcResult  with κ, μ(ρ), σ(ρ), arc_flag, and tension_series.
    """
    # Minimum-length guard
    word_count = len(text.split())
    if word_count < 200:
        return TensionArcResult(
            tension_series=[], paragraph_arcs=[],
            resolution_ratio_mean=1.0, resolution_ratio_std=0.0,
            catastrophe_index=0.0, mean_tension=0.0, max_tension=0.0,
            authenticity_signal=None,
            arc_flag="insufficient_length",
            arc_flag_reason=(
                f"Submission too short ({word_count} words) for reliable tension "
                f"arc analysis. Minimum 200 words required."
            ),
        )

    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return TensionArcResult(
            tension_series=[], paragraph_arcs=[],
            resolution_ratio_mean=1.0, resolution_ratio_std=0.0,
            catastrophe_index=0.0, mean_tension=0.0, max_tension=0.0,
            authenticity_signal=None,
            arc_flag="review",
            arc_flag_reason="Insufficient text structure for tension arc analysis.",
        )

    arcs: List[ParagraphArc] = [_analyze_paragraph(p, i) for i, p in enumerate(paragraphs)]

    tension_series = [s.total for arc in arcs for s in arc.sentences]
    rho_values     = [arc.resolution_ratio for arc in arcs if arc.peak_count > 0]

    mu_rho, sig_rho, kappa = _compute_catastrophe(rho_values)

    mean_t = float(np.mean(tension_series)) if tension_series else 0.0
    max_t  = float(np.max(tension_series))  if tension_series else 0.0

    auth_signal = (_authenticity_signal(kappa, baseline_kappa)
                   if baseline_kappa is not None else None)

    num_rho_values = len(rho_values)
    flag, reason = _arc_flag(kappa, mu_rho, mean_t, max_t, auth_signal,
                             num_rho_values=num_rho_values)

    return TensionArcResult(
        tension_series=[round(v, 4) for v in tension_series],
        paragraph_arcs=arcs,
        resolution_ratio_mean=mu_rho,
        resolution_ratio_std=sig_rho,
        catastrophe_index=kappa,
        mean_tension=round(mean_t, 4),
        max_tension=round(max_t, 4),
        authenticity_signal=auth_signal,
        arc_flag=flag,
        arc_flag_reason=reason,
    )


def update_student_baseline_kappa(existing_kappa_values: List[float], new_kappa: float) -> float:
    """
    Running mean of κ across a student's authenticated submissions.
    Append new_kappa, return updated mean to store as student.baseline_kappa.
    """
    existing_kappa_values.append(new_kappa)
    return float(np.mean(existing_kappa_values))


# ── Quick self-test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    load_models()

    # ~250-word authentic human theological essay (borderline case from calibration)
    HUMAN_SHORT = """
    There is something genuinely unsettling about the silence that follows a long argument.
    Not the comfortable silence of resolution — but the kind that sits between two people
    who have both said too much and too little. I have been thinking about this for weeks
    now, partly because of what happened with a colleague, but also because I am not sure
    the theological categories I was trained in actually help here. The tradition offers
    language — rupture, confession, forgiveness, restoration — but the sequence is cleaner
    than the experience ever is.

    Admittedly, reconciliation language assumes a rupture. But what if the rupture is
    not the thing that needs fixing? What if the silence itself is the honest thing,
    and we are too afraid to let it be what it is? I do not have an answer to this.
    I suspect I will not for some time. What I do know is that the categories I bring
    to this — categories borrowed from systematic theology and pastoral care — were built
    for a different kind of brokenness than the kind I am sitting with now.

    The tradition says: confess, forgive, restore. That sequence is clean. It resolves.
    But real guilt does not move in a sequence. It circles. It returns at 2am.
    And the person you wronged has their own arc, entirely independent of your repentance,
    and they are not obligated to move at your pace or according to your timetable.
    Whether theological frameworks can hold that tension without collapsing it into
    resolution too quickly is the question I cannot stop asking.
    """

    # ~250-word AI-generated academic prose on the same topic
    AI_SHORT = """
    Reconciliation is a fundamental concept in Christian theology that addresses the
    restoration of broken relationships between individuals and between humanity and God.
    This theological theme appears prominently throughout both the Old and New Testaments,
    providing a framework for understanding how estrangement can be overcome through
    intentional processes of acknowledgment, repentance, and forgiveness.

    In the New Testament, the apostle Paul develops the concept of reconciliation most
    extensively, particularly in his second letter to the Corinthians. Paul argues that
    God has entrusted believers with a ministry of reconciliation, calling them to be
    ambassadors of the reconciling work that Christ has accomplished through his atoning
    sacrifice. This theological framework provides important guidance for understanding
    how interpersonal reconciliation should function within the Christian community.

    Contemporary pastoral theology has built upon these biblical foundations to develop
    practical approaches to reconciliation in congregational and counseling contexts.
    Scholars such as John Paul Lederach have contributed significantly to understanding
    how reconciliation involves truth-telling, mercy, justice, and peace working together.
    These four elements must be held in careful balance if genuine reconciliation is to
    be achieved rather than merely a superficial resolution of conflict.

    In conclusion, reconciliation represents one of the most important theological and
    pastoral themes in Christian thought, offering both a description of what God has
    accomplished in Christ and a model for how human relationships can be restored when
    they have been broken by sin, misunderstanding, or conflict.
    """

    for label, text in [("HUMAN (borderline ~250w)", HUMAN_SHORT),
                        ("AI    (academic ~250w)", AI_SHORT)]:
        r = analyze_tension_arc(text)
        words = len(text.split())
        num_rho = len([a for a in r.paragraph_arcs if a.peak_count > 0])
        print(f"\n{'='*55}")
        print(f"  {label}  ({words} words)")
        print(f"{'='*55}")
        print(f"  κ  (catastrophe index):   {r.catastrophe_index:.4f}")
        print(f"  μ(ρ) (resolution mean):   {r.resolution_ratio_mean:.4f}")
        print(f"  σ(ρ) (resolution std):    {r.resolution_ratio_std:.4f}")
        print(f"  μ(T) (mean tension):      {r.mean_tension:.4f}")
        print(f"  max(T):                   {r.max_tension:.4f}")
        print(f"  num paragraphs w/ peaks:  {num_rho}")
        print(f"  Flag:                     {r.arc_flag}")
        print(f"  Reason:                   {r.arc_flag_reason[:80]}…")
        print(f"  Series ({len(r.tension_series)} pts): {[round(v,3) for v in r.tension_series[:8]]}...")
