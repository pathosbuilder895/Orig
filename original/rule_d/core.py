"""Rule D: a report-only, testing-phase consistency observation. Never changes a score.

The formula is the one pre-registered and tested on held-out authors in study
``scholarly-rule-d-2026-11-12`` (docs/research/2026-11-12-scholarly-locked-test-preregistration.md
and ...-rule-d-locked-test-results.md):

    D = -(B + C + zO) / 3

For the new paper scored against the claimed student A, and the pool O = every other student
in the same workspace with approved papers:

* B (character profile): zB_c = (cos(paper, A's centroid) - mean over O) / sd over O, zB_n the
  same with each student's nearest single past paper; B = (zB_c + zB_n) / 2. Whole past papers.
* C (topic-masked profile): the same on topic-masked text; C = (zC_c + zC_n) / 2.
* zO (Original's z): r(X) = rms of |z| (capped at 6, active features) of the paper's feature
  vector against student X's baseline built from past papers cut to the new paper's length;
  zO = -(r(A) - mean over O of r(X)) / sd over O.

Higher D means the paper reads less like A than A's classmates' writing does relative to
theirs. The observation is "reads less like" when D is above the threshold measured for the
nearest tested length setting (calibration partition, humanities, 95th percentile of honest
papers). Below the class-size floor, or for a very short paper, the answer is "inconclusive".
"""

from __future__ import annotations

import hashlib
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from . import textprofile as tp

STUDY_ID = "scholarly-rule-d-2026-11-12"
TESTING_LABEL = (
    "Testing phase · not validated on student writing · a consistency observation, not a judgment"
)

# Thresholds fixed on the calibration partition (humanities) before the single locked-test
# opening; validation/scholarly/rule_d_thresholds_humanities.json on the PR #336 branch.
THRESHOLDS = {
    "matched_300_300": -0.529301,
    "matched_1200_1200": -1.244517,
    "long_past_1200_short_new_300": -0.919008,
}
MIN_PEER_STUDENTS = 3  # other students with approved papers in the workspace
MIN_PEER_PAPERS = 5  # approved papers across those students
MIN_NEW_WORDS = 250  # nothing shorter was measured (shortest tested: 300 words)
PIECE_WORDS = 300  # past papers are cut into pieces of this length for short new papers
MAX_PIECES = 8  # per past paper, to bound the cost of feature extraction
LONG_WORDS = 750  # midpoint between the two measured lengths (300 and 1200)
Z_CAP = 6.0

PUNCTUATION = (
    ("semicolons", (";",)),
    ("colons", (":",)),
    ("dashes", ("\u2014", "\u2013", " - ", "--")),
    ("parentheses", ("(",)),
    ("question marks", ("?",)),
    ("quotation marks", ('"', "“", "”")),
)


# --------------------------------------------------------------------- profiles --
def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def word_count(text: str) -> int:
    return len(text.split())


def pieces(text: str, size: int = PIECE_WORDS, limit: int = MAX_PIECES) -> list[str]:
    w = text.split()
    return [" ".join(w[i : i + size]) for i in range(0, len(w) - size + 1, size)][:limit]


def build_paper_profile(
    text: str, vector: Sequence[float], label: str, feature_fn: Callable[[str], np.ndarray]
) -> dict:
    """Everything rule D keeps about one approved past paper. Stored per paper, inside the
    deployment, keyed by the SHA-256 of its text; deleted with the student or the approval."""
    vecs = tp.vectorizers()
    return {
        "sha": text_sha256(text),
        "words": word_count(text),
        "label": label,
        "char": {str(k): v for k, v in vecs["char"].profile(text).items()},
        "masked": {str(k): v for k, v in vecs["masked"].profile(text).items()},
        "vector": [float(x) for x in vector],
        "pieces": [[float(x) for x in feature_fn(p)] for p in pieces(text)],
        "punct": punctuation_rates(text),
    }


def _sparse(d: dict) -> tp.Profile:
    return {int(k): float(v) for k, v in d.items()}


def punctuation_rates(text: str) -> dict[str, float]:
    """Uses per 1,000 words of each punctuation habit."""
    n = max(word_count(text), 1)
    return {name: 1000.0 * sum(text.count(m) for m in marks) / n for name, marks in PUNCTUATION}


# ------------------------------------------------------------------ configuration --
def configuration(new_words: int, past_words: Sequence[int]) -> str:
    """Nearest measured length setting for this comparison."""
    median_past = statistics.median(past_words) if past_words else 0
    if new_words >= LONG_WORDS:
        return "matched_1200_1200"
    if median_past >= LONG_WORDS:
        return "long_past_1200_short_new_300"
    return "matched_300_300"


def rel_z(own: float, others: np.ndarray) -> float:
    return float((own - others.mean()) / (others.std() + 1e-9))


def rule_d(zB_c: float, zB_n: float, zC_c: float, zC_n: float, zO: float) -> float:
    """The pre-registered formula: equal thirds; higher = less like the claimed student."""
    return -(((zB_c + zB_n) / 2.0) + ((zC_c + zC_n) / 2.0) + zO) / 3.0


def baseline_rms(x: np.ndarray, vectors: list[Sequence[float]]) -> float:
    """r(X): rms of |z| (capped) of x against a baseline built from ``vectors`` with Original's
    own StudentState statistics (mean, floored spread, active-feature mask)."""
    from original.quantum.state import BaselineSample, StudentState

    st = StudentState(student_id="rule-d")
    for v in vectors:
        st.add_sample(
            BaselineSample(
                text="",
                vector=np.asarray(v, dtype=float),
                provenance="verified",
                auth_weight=1.0,
                genre="essay",
            )
        )
    active = st.active_feature_mask
    z = np.clip(np.abs((x - st.baseline_mean) / st.baseline_std), 0, Z_CAP) * active
    return float(np.sqrt((z**2).sum() / max(int(active.sum()), 1)))


# --------------------------------------------------------------------- the rule --
@dataclass
class Observation:
    status: str  # "observed" | "inconclusive"
    testing_phase_label: str = TESTING_LABEL
    study_id: str = STUDY_ID
    reason: str | None = None  # why inconclusive
    reads_less_like_student: bool | None = None
    summary: str = ""
    configuration: str | None = None
    configuration_note: str = ""
    index: float | None = None  # D; compared only with the threshold below
    threshold: float | None = None
    components: dict[str, float] = field(default_factory=dict)
    reads_like: list[str] = field(default_factory=list)
    reads_less_like: list[str] = field(default_factory=list)
    confidence_note: str = ""
    classmates: int = 0
    classmate_papers: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def inconclusive(reason: str, classmates: int = 0, papers: int = 0) -> Observation:
    return Observation(
        status="inconclusive",
        reason=reason,
        summary="Inconclusive: " + reason + " Rule D does not give a result here.",
        confidence_note=CONFIDENCE["inconclusive"],
        classmates=classmates,
        classmate_papers=papers,
    )


def observe(
    new_text: str, new_vector: np.ndarray, claimed: list[dict], peers: dict[str, list[dict]]
) -> Observation:
    """Rule D for one new paper. ``claimed`` = the claimed student's paper profiles;
    ``peers`` = {other student id: their paper profiles}, same workspace only."""
    peers = {k: v for k, v in peers.items() if v}
    n_peer_papers = sum(len(v) for v in peers.values())
    words = word_count(new_text)
    if not claimed:
        return inconclusive("this student has no approved past papers with text.")
    if len(peers) < MIN_PEER_STUDENTS or n_peer_papers < MIN_PEER_PAPERS:
        return inconclusive(
            f"the class needs at least {MIN_PEER_STUDENTS} other students with "
            f"{MIN_PEER_PAPERS} approved "
            f"papers between them (it has {len(peers)} and {n_peer_papers}).",
            len(peers),
            n_peer_papers,
        )
    if words < MIN_NEW_WORDS:
        return inconclusive(
            f"the new paper has {words} words; rule D was only measured on papers of "
            f"300 words or more.",
            len(peers),
            n_peer_papers,
        )

    vecs = tp.vectorizers()
    new = {k: vecs[k].profile(new_text) for k in ("char", "masked")}
    groups = [claimed] + list(peers.values())  # index 0 = the claimed student
    sims = {}
    char_cents = [tp.centroid(_sparse(p["char"]) for p in g) for g in groups]
    for k in ("char", "masked"):
        cent_k = (
            char_cents if k == "char" else [tp.centroid(_sparse(p[k]) for p in g) for g in groups]
        )
        cents = np.array([tp.dot(new[k], c) for c in cent_k])
        near = np.array([max(tp.dot(new[k], _sparse(p[k])) for p in g) for g in groups])
        sims[k] = (cents, near)
    cfg = configuration(words, [p["words"] for p in claimed])
    x = np.asarray(new_vector, dtype=float)

    def base_vectors(g):
        if cfg == "matched_1200_1200":
            return [p["vector"] for p in g]
        cut = [v for p in g for v in p.get("pieces", [])]
        return cut or [p["vector"] for p in g]  # a paper shorter than one piece: use it whole

    r = np.array([baseline_rms(x, base_vectors(g)) for g in groups])
    zB_c, zB_n = (
        rel_z(sims["char"][0][0], sims["char"][0][1:]),
        rel_z(sims["char"][1][0], sims["char"][1][1:]),
    )
    zC_c, zC_n = (
        rel_z(sims["masked"][0][0], sims["masked"][0][1:]),
        rel_z(sims["masked"][1][0], sims["masked"][1][1:]),
    )
    zO = -rel_z(r[0], r[1:])
    D = rule_d(zB_c, zB_n, zC_c, zC_n, zO)
    thr = THRESHOLDS[cfg]
    less = D > thr

    from .explain import explain

    obs = Observation(
        status="observed",
        reads_less_like_student=bool(less),
        configuration=cfg,
        configuration_note=configuration_note(cfg, words, [p["words"] for p in claimed]),
        index=round(D, 4),
        threshold=thr,
        components={
            "character_profile": round((zB_c + zB_n) / 2, 3),
            "word_shape_profile": round((zC_c + zC_n) / 2, 3),
            "original_features": round(zO, 3),
        },
        confidence_note=CONFIDENCE[cfg],
        classmates=len(peers),
        classmate_papers=n_peer_papers,
    )
    class_mean: dict[int, float] = {}
    for c in char_cents[1:]:
        for k2, v in c.items():
            class_mean[k2] = class_mean.get(k2, 0.0) + v / (len(char_cents) - 1)
    explain(
        obs,
        new_text=new_text,
        new_profiles=new,
        claimed=claimed,
        sims=sims,
        words=words,
        own_centroid=char_cents[0],
        class_mean=class_mean,
    )
    return obs


def configuration_note(cfg: str, words: int, past_words: Sequence[int]) -> str:
    median_past = int(statistics.median(past_words)) if past_words else 0
    setting = {
        "matched_1200_1200": (
            "long new paper against long past papers (tested at about 1,200 words each)"
        ),
        "long_past_1200_short_new_300": (
            "short new paper against long past papers (tested at about 300 vs 1,200 words)"
        ),
        "matched_300_300": (
            "short new paper against short past papers (tested at about 300 words each)"
        ),
    }[cfg]
    return (
        f"Compared using the nearest tested setting: {setting}. This paper has {words} words; "
        f"the past papers have about {median_past} words each."
    )


CONFIDENCE = {
    "matched_1200_1200": (
        "Strongest setting. In testing on published scholarly papers, with long papers on both "
        "sides, "
        "about 87-98% of other writers were noticed while about 5% of honest papers were flagged. "
        "Not yet validated on student writing."
    ),
    "long_past_1200_short_new_300": (
        "Weaker setting. In testing on published scholarly papers, a short new paper against "
        "long past "
        "papers noticed about 90-94% of other writers in general, but only about 78-81% of "
        "writers in "
        "the same field or journal, while about 5% of honest papers were flagged. "
        "Not yet validated on student writing."
    ),
    "matched_300_300": (
        "Weakest setting. In testing on published scholarly papers, with short papers on both "
        "sides, "
        "only about 67-90% of other writers were noticed while about 5% of honest papers were "
        "flagged. "
        "Not yet validated on student writing."
    ),
    "inconclusive": "No result, so nothing to weigh. Not yet validated on student writing.",
}
