"""Phase 5A probe: do dependency-parse / morphosyntactic features carry
authorship signal worth adding to the 109-dim production vector?

Validation-only. This script decides gate **G-P5a** and emits the frozen
feature list Phase 5B would implement. Nothing under ``original/`` is written
by this module; ``original.features.tier5`` is imported read-only, to measure
redundancy against the two syntax-complexity features the pipeline already has.

Run:
    ~/Desktop/Original/.venv/bin/python -m validation.verify.dependency_probe

═══════════════════════════════════════════════════════════════════════════
PRE-REGISTERED CRITERIA -- fixed in this file and committed BEFORE the probe
was run for the first time. See the commit that introduced this module; the
results commit is separate and later. A criterion chosen after seeing a result
is not a criterion, it is a description (COMPRESSION_CHANNEL_FINDINGS_2026-08-10
declined to claim an unregistered NCD arm for exactly this reason).
═══════════════════════════════════════════════════════════════════════════

A candidate is KEPT only if it clears every one of:

G-P5a.1  Individual discrimination:  AUC >= 0.550
    Same-author vs different-author AUC of ``-|f(d_i) - f(d_j)|`` on the PAN
    2020 *development* partition. 0.550 is the floor the task brief proposes
    for a single weak member of a 109-dim ensemble, and it is defensible
    independently: with ~1,000 same-author pairs the standard error of an AUC
    near 0.5 is roughly 0.015, so 0.550 sits more than three standard errors
    above chance. Anything closer to 0.5 cannot be told from noise at this
    sample size, and Phase 5B's cost (a protected-surface change to
    ``original/constants.py``, retraining the committed AI-detector artifact,
    two hard-coded dimension literals, and a baseline re-extraction) is far
    too high to pay for a feature that might be nothing.

G-P5a.2  Within-author stability:  ICC(1) >= 0.30
    One-way random-effects intraclass correlation over the same documents:
    the share of the feature's total variance that lies BETWEEN authors rather
    than WITHIN an author's own documents. This is the same
    representative-and-distinctive criterion Phase 3 implemented at scoring
    time (``sigma_null / baseline_std``), measured at corpus level. A feature
    that wanders as much across one author's documents as it does across
    authors is noise however it scores on a pairwise AUC. 0.30 is the
    conventional lower edge of "moderate" reliability; below it the between-
    author component is a small minority of the variance.

G-P5a.3  Non-redundancy with the existing vector:  max |Pearson r| < 0.90
    against all seven tier-5 features as the production pipeline computes
    them -- primarily ``subordination_ratio`` and ``clause_depth_mean``, the
    only two syntax-complexity numbers in the vector, but the other five are
    free to compute from the same parse and the redundancy question is real.
    A candidate 0.9-correlated with something already in the vector adds
    109->110 cost and no information.

G-P5a.4  Non-redundancy among survivors:  max |Pearson r| < 0.90
    Applied after G-P5a.1-3, greedily in descending AUC order: the
    higher-AUC survivor is kept and the correlated one is dropped. Two
    near-copies of one measurement pay the Phase 5B cascade twice.

G-P5a.5  Corroboration does not invert:  AUC >= 0.50 on the second corpus
    (``validation/public_authors/cross_work_corpus``, 6 authors x 2 works x 3
    chunks, same-author pairs restricted to CROSS-WORK pairs). A directional
    check only, not a magnitude bar -- 54 same-author pairs cannot support
    one. A feature that inverts on an independent corpus is a corpus artefact,
    which is the specific failure this project was burned by before
    (``GENRE_INVARIANT_WEIGHTS_ENABLED``: built, tested, fires once in six
    folds, and that once is classifier noise).

Pair construction, also pre-registered
--------------------------------------
* Same-author pairs are **cross-group only** -- cross-fandom on PAN,
  cross-work on the public-author corpus. Two documents from the same fandom
  share topic as well as author, and a feature that tracks topic would be
  flattered by them. The harder set is the honest one, and cross-topic
  robustness is the whole reason this project is interested in syntax.
* Different-author pairs are **all** cross-author document pairs, with no
  group restriction and no sampling.
* The feature-level comparison is the absolute difference between the two
  documents' feature values; the discriminant is its negation, so that
  "small difference" ranks as "same author".

Determinism
-----------
There is no RNG anywhere in this module and nothing is sampled. Author
selection is PAN's existing deterministic SHA-256 ordering
(``pan_style_expert.load_author_partitions``); document windows are its
existing deterministic ``_fixed_window``. Repeat runs are bit-identical.

Partition hygiene
-----------------
The probe reads the **development** partition only. The 12 locked authors and
the 40 calibration authors used by every ``pan_stack`` ablation in this repo
are never loaded, so this study cannot contaminate them.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from validation.verify.dependency_signals import (
    CANDIDATE_CODES,
    dependency_features,
    get_nlp,
)

# ── Pre-registered gate constants ────────────────────────────────────────────
GATE_MIN_AUC = 0.550
GATE_MIN_ICC = 0.30
GATE_MAX_EXISTING_ABS_R = 0.90
GATE_MAX_MUTUAL_ABS_R = 0.90
GATE_MIN_CORROBORATION_AUC = 0.50

#: Development-partition author count. PAN's loader selects locked authors
#: first, so this slice never overlaps the locked or calibration cohorts.
DEFAULT_N_AUTHORS = 120

REPO_ROOT = Path(__file__).resolve().parents[2]
CROSS_WORK_MANIFEST = REPO_ROOT / "validation/public_authors/cross_work_manifest.json"
CROSS_WORK_CORPUS = REPO_ROOT / "validation/public_authors/cross_work_corpus"
DEFAULT_RESULTS_PATH = REPO_ROOT / "validation/verify/dependency_probe_results.json"

TIER5_CODES = (
    "pos_bigram_entropy",
    "pos_trigram_entropy",
    "noun_verb_ratio",
    "adjective_rate",
    "adverb_rate",
    "subordination_ratio",
    "clause_depth_mean",
)


@dataclass(frozen=True)
class ProbeDocument:
    author_id: str
    group_id: str  # fandom (PAN) or work (public authors)
    doc_id: str
    text: str


# ── Corpora ──────────────────────────────────────────────────────────────────


def load_pan_documents(n_authors: int = DEFAULT_N_AUTHORS) -> list[ProbeDocument]:
    """PAN 2020 development partition: 3 baselines + 3 probes per author, in
    two disjoint fandoms, 2500-word deterministic windows."""
    from validation.verify.pan_style_expert import load_author_partitions

    partitions = load_author_partitions(n_development=n_authors)
    documents = []
    for author in partitions["development"]:
        for index, text in enumerate(author.baselines):
            documents.append(
                ProbeDocument(author.author_id, author.baseline_fandom, f"b{index}", text)
            )
        for index, text in enumerate(author.probes):
            documents.append(
                ProbeDocument(author.author_id, author.probe_fandom, f"p{index}", text)
            )
    return documents


def load_cross_work_documents() -> list[ProbeDocument]:
    """Public-author cross-work corpus, or [] if it is not populated."""
    if not CROSS_WORK_MANIFEST.exists() or not CROSS_WORK_CORPUS.exists():
        return []
    manifest = json.loads(CROSS_WORK_MANIFEST.read_text(encoding="utf-8"))
    documents = []
    for entry in sorted(manifest.get("entries", []), key=lambda e: e["filename"]):
        path = CROSS_WORK_CORPUS / entry["filename"]
        if not path.exists():
            continue
        documents.append(
            ProbeDocument(
                author_id=entry["author_id"],
                group_id=entry.get("work_id", Path(entry["filename"]).stem),
                doc_id=entry["filename"],
                text=path.read_text(encoding="utf-8"),
            )
        )
    return documents


# ── Shared-parse extraction ──────────────────────────────────────────────────


class _CachingNLP:
    """Memoise ``nlp(text)`` on the exact input string.

    ``original.features.tier5`` calls its spaCy pipeline once per feature
    function -- ``_get_pos_tags`` from each of six extractors plus
    ``_get_dep_depths`` -- so ``extract_tier5`` parses each document SEVEN
    times. Installing this in place of ``tier5._nlp`` for the duration of the
    probe changes no value (the pipeline is deterministic, the key is the full
    input string) and takes the run from ~25 minutes to ~4. It also lets the
    candidate extractor share the identical Doc, which is exactly the
    shared-parse arrangement the cost section is arguing about.
    """

    def __init__(self, nlp):
        self._nlp = nlp
        self._cache: dict[str, object] = {}
        self.misses = 0

    def __call__(self, text: str):
        cached = self._cache.get(text)
        if cached is None:
            self.misses += 1
            cached = self._nlp(text)
            self._cache[text] = cached
        return cached

    def clear(self) -> None:
        self._cache.clear()


def extract_corpus(
    documents: Sequence[ProbeDocument], *, with_tier5: bool, label: str
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Return ``(candidate_values, tier5_values)`` as code -> array over docs.

    ``tier5_values`` is empty when ``with_tier5`` is False (the corroboration
    corpus does not need the redundancy analysis re-run on it).
    """
    from original.features import tier5
    from original.features.tier1 import TextDoc

    caching = _CachingNLP(get_nlp())
    original_nlp = tier5._nlp
    tier5._nlp = caching
    try:
        candidate_rows: list[dict[str, float]] = []
        tier5_rows: list[dict[str, float]] = []
        for index, document in enumerate(documents, start=1):
            text_doc = TextDoc(document.text)
            # Parse exactly the string tier5 parses, so the Doc is shared and
            # the candidate features see the production normalisation.
            parsed = caching(text_doc.clean)
            candidate_rows.append(dependency_features(parsed))
            if with_tier5:
                tier5_rows.append(tier5.extract_tier5(text_doc))
            caching.clear()  # one document's Doc at a time; these are 2.5k words
            if index % 50 == 0 or index == len(documents):
                print(f"[dep-probe] {label}: {index}/{len(documents)} documents", file=sys.stderr)
    finally:
        tier5._nlp = original_nlp

    candidates = {
        code: np.array([row[code] for row in candidate_rows], dtype=np.float64)
        for code in CANDIDATE_CODES
    }
    tier5_values = {
        code: np.array([row[code] for row in tier5_rows], dtype=np.float64)
        for code in TIER5_CODES
    } if with_tier5 else {}
    return candidates, tier5_values


# ── Statistics ───────────────────────────────────────────────────────────────


def ranked_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """Tie-corrected Mann-Whitney AUC, identical to
    ``binary_auc.auc`` but O(n log n) instead of O(P*N).

    ``binary_auc.auc`` materialises a P x N boolean matrix; at 1,080 positive
    and ~257,000 negative pairs that is 280 MB per feature per comparison.
    ``tests/validation/test_dependency_signals.py`` asserts the two agree.
    """
    from scipy.stats import rankdata

    labels = np.asarray(labels)
    scores = np.asarray(scores, dtype=np.float64)
    n_pos = int((labels == 1).sum())
    n_neg = int((labels == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return 0.5
    ranks = rankdata(scores)
    return float((ranks[labels == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def icc1(values: np.ndarray, author_index: np.ndarray) -> float:
    """One-way random-effects ICC(1): between-author share of total variance.

    Computed from the standard one-way ANOVA decomposition with the harmonic
    group size, so it is defined for unbalanced author document counts.
    Clipped at 0.0 -- a negative ICC means the between-author mean square came
    in below the within-author one, which is "no detectable between-author
    component", not a meaningful negative quantity.
    """
    groups = [values[author_index == a] for a in np.unique(author_index)]
    groups = [g for g in groups if g.size >= 2]
    k = len(groups)
    if k < 2:
        return float("nan")
    n_total = sum(g.size for g in groups)
    grand_mean = float(np.concatenate(groups).mean())
    ss_between = sum(g.size * (g.mean() - grand_mean) ** 2 for g in groups)
    ss_within = sum(float(((g - g.mean()) ** 2).sum()) for g in groups)
    df_between, df_within = k - 1, n_total - k
    if df_within <= 0:
        return float("nan")
    ms_between = ss_between / df_between
    ms_within = ss_within / df_within
    if ms_between == 0 and ms_within == 0:
        return 0.0
    # Harmonic-ish average group size for the unbalanced case (Shrout & Fleiss).
    sizes = np.array([g.size for g in groups], dtype=np.float64)
    k0 = (n_total - (sizes**2).sum() / n_total) / (k - 1)
    denominator = ms_between + (k0 - 1) * ms_within
    if denominator == 0:
        return 0.0
    return float(max(0.0, (ms_between - ms_within) / denominator))


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson r, returning 0.0 when either side is constant (undefined r; a
    constant feature is uncorrelated with everything by any useful reading)."""
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def build_pairs(documents: Sequence[ProbeDocument]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(left_index, right_index, label)`` over document pairs.

    Same-author pairs are cross-group only; different-author pairs are every
    cross-author combination. See the module docstring for why.
    """
    left, right, label = [], [], []
    for i in range(len(documents)):
        for j in range(i + 1, len(documents)):
            a, b = documents[i], documents[j]
            if a.author_id == b.author_id:
                if a.group_id == b.group_id:
                    continue  # same author, same topic -- excluded by design
                left.append(i)
                right.append(j)
                label.append(1)
            else:
                left.append(i)
                right.append(j)
                label.append(0)
    return (
        np.array(left, dtype=np.int64),
        np.array(right, dtype=np.int64),
        np.array(label, dtype=np.int8),
    )


# ── Cost ─────────────────────────────────────────────────────────────────────


def measure_cost(documents: Sequence[ProbeDocument], n_sample: int = 12) -> dict:
    """Wall-clock, on the first ``n_sample`` documents in corpus order (a
    deterministic head slice, not a sample draw).

    Three numbers, because the interesting one is the ratio:
      * ``parse_ms`` -- one uncached ``nlp(clean_text)``.
      * ``extract_ms`` -- ``dependency_features`` over an already-parsed Doc,
        i.e. the marginal cost of the whole candidate set if the parse is
        shared.
      * ``tier5_asis_ms`` -- ``extract_tier5`` exactly as production runs it
        today, which re-parses the document once per feature function.
    """
    from original.features import tier5
    from original.features.tier1 import TextDoc

    nlp = get_nlp()
    sample = list(documents[:n_sample])
    text_docs = [TextDoc(d.text) for d in sample]
    words = sum(td.word_count for td in text_docs)

    nlp(text_docs[0].clean)  # warm the model

    start = time.perf_counter()
    parsed = [nlp(td.clean) for td in text_docs]
    parse_seconds = time.perf_counter() - start

    start = time.perf_counter()
    for doc in parsed:
        dependency_features(doc)
    extract_seconds = time.perf_counter() - start

    start = time.perf_counter()
    for text_doc in text_docs[: min(4, len(text_docs))]:
        tier5.extract_tier5(text_doc)
    tier5_seconds = time.perf_counter() - start
    tier5_n = min(4, len(text_docs))

    return {
        "n_documents": len(sample),
        "mean_words_per_document": words / len(sample),
        "parse_ms_per_document": parse_seconds / len(sample) * 1000,
        "extract_ms_per_document": extract_seconds / len(sample) * 1000,
        "tier5_asis_ms_per_document": tier5_seconds / tier5_n * 1000,
        "extract_fraction_of_parse": extract_seconds / parse_seconds if parse_seconds else None,
    }


# ── Probe ────────────────────────────────────────────────────────────────────


def evaluate_corpus(documents: Sequence[ProbeDocument], *, with_tier5: bool, label: str) -> dict:
    candidates, tier5_values = extract_corpus(documents, with_tier5=with_tier5, label=label)
    left, right, labels = build_pairs(documents)
    author_index = np.array(
        [sorted({d.author_id for d in documents}).index(d.author_id) for d in documents]
    )

    rows = {}
    for code in CANDIDATE_CODES:
        values = candidates[code]
        discriminant = -np.abs(values[left] - values[right])
        rows[code] = {
            "auc": ranked_auc(labels, discriminant),
            "icc1": icc1(values, author_index),
            "mean": float(values.mean()),
            "std": float(values.std()),
            "p01": float(np.percentile(values, 1)),
            "p50": float(np.percentile(values, 50)),
            "p99": float(np.percentile(values, 99)),
        }
        if with_tier5:
            correlations = {
                existing: pearson(values, tier5_values[existing]) for existing in TIER5_CODES
            }
            worst = max(correlations, key=lambda k: abs(correlations[k]))
            rows[code]["existing_correlations"] = correlations
            rows[code]["max_abs_r_existing"] = abs(correlations[worst])
            rows[code]["max_abs_r_existing_with"] = worst

    mutual = {
        a: {b: pearson(candidates[a], candidates[b]) for b in CANDIDATE_CODES}
        for a in CANDIDATE_CODES
    }
    return {
        "n_documents": len(documents),
        "n_authors": len(set(d.author_id for d in documents)),
        "n_same_author_pairs": int((labels == 1).sum()),
        "n_different_author_pairs": int((labels == 0).sum()),
        "features": rows,
        "mutual_correlations": mutual,
    }


def apply_gate(primary: dict, corroboration: dict | None) -> dict:
    """Apply G-P5a.1-5 in the pre-registered order and return the verdict."""
    verdicts = {}
    for code in CANDIDATE_CODES:
        row = primary["features"][code]
        checks = {
            "auc": row["auc"] >= GATE_MIN_AUC,
            "icc1": (row["icc1"] == row["icc1"]) and row["icc1"] >= GATE_MIN_ICC,
            "non_redundant_existing": row["max_abs_r_existing"] < GATE_MAX_EXISTING_ABS_R,
        }
        if corroboration:
            checks["corroboration"] = (
                corroboration["features"][code]["auc"] >= GATE_MIN_CORROBORATION_AUC
            )
        verdicts[code] = {
            "checks": checks,
            "passes_1_3_5": all(checks.values()),
            "failed": sorted(name for name, ok in checks.items() if not ok),
        }

    stage_one = [c for c in CANDIDATE_CODES if verdicts[c]["passes_1_3_5"]]
    stage_one.sort(key=lambda c: primary["features"][c]["auc"], reverse=True)

    kept: list[str] = []
    for code in stage_one:
        clash = next(
            (
                other
                for other in kept
                if abs(primary["mutual_correlations"][code][other]) >= GATE_MAX_MUTUAL_ABS_R
            ),
            None,
        )
        if clash is None:
            kept.append(code)
        else:
            verdicts[code]["failed"].append(f"mutual_redundancy_with:{clash}")
            verdicts[code]["dropped_for"] = clash

    # ── Three-valued verdict ────────────────────────────────────────────────
    # validation/README.md: gate verdicts are pass / fail / uninformative, and
    # a gate that cannot separate the cases it exists to separate downgrades a
    # would-be pass to uninformative -- it must never be quoted as a pass.
    #
    # A filter that admits EVERY candidate has demonstrated no ability to tell
    # a feature worth adding from one that is not. This is a property of the
    # gate, evaluable from the gate's own output, not a new threshold: no
    # criterion below is altered, and the raw accept-list is still reported as
    # ``gate_output``. ``frozen_list`` -- what Phase 5B would consume -- is
    # empty unless the verdict is an actual pass.
    if not kept:
        verdict = "fail"
        reason = "no candidate cleared the pre-registered criteria"
    elif len(kept) == len(CANDIDATE_CODES):
        verdict = "uninformative"
        reason = (
            "every candidate cleared every criterion, so the gate did not "
            "discriminate; see the calibration baseline in "
            "validation/verify/dependency_redundancy.py, where the seven "
            "features already in the production vector clear the same bars"
        )
    else:
        verdict = "pass"
        reason = f"{len(kept)} of {len(CANDIDATE_CODES)} candidates cleared every criterion"

    return {
        "per_feature": verdicts,
        "gate_output": kept,
        "verdict": verdict,
        "verdict_reason": reason,
        "frozen_list": kept if verdict == "pass" else [],
    }


def run(n_authors: int = DEFAULT_N_AUTHORS, results_path: Path = DEFAULT_RESULTS_PATH) -> dict:
    started = time.time()
    pan_documents = load_pan_documents(n_authors)
    cost = measure_cost(pan_documents)
    primary = evaluate_corpus(pan_documents, with_tier5=True, label="pan-development")

    cross_work = load_cross_work_documents()
    corroboration = (
        evaluate_corpus(cross_work, with_tier5=False, label="public-authors-cross-work")
        if cross_work
        else None
    )

    gate = apply_gate(primary, corroboration)
    report = {
        "schema": "validation.dependency_probe.v1",
        "preregistered": {
            "min_auc": GATE_MIN_AUC,
            "min_icc1": GATE_MIN_ICC,
            "max_abs_r_existing": GATE_MAX_EXISTING_ABS_R,
            "max_abs_r_mutual": GATE_MAX_MUTUAL_ABS_R,
            "min_corroboration_auc": GATE_MIN_CORROBORATION_AUC,
        },
        "primary_corpus": "PAN 2020 development partition (cross-fandom same-author pairs)",
        "corroboration_corpus": (
            "validation/public_authors/cross_work_corpus (cross-work same-author pairs)"
            if corroboration
            else None
        ),
        "cost": cost,
        "primary": primary,
        "corroboration": corroboration,
        "gate_g_p5a": gate,
        "wall_clock_seconds": time.time() - started,
    }
    results_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _print_table(report: dict) -> None:
    primary = report["primary"]
    corroboration = report["corroboration"]
    gate = report["gate_g_p5a"]
    print()
    print(
        f"{'feature':<28}{'AUC':>8}{'ICC1':>8}{'maxR_exist':>12}{'with':>22}"
        f"{'xwork AUC':>11}  verdict"
    )
    print("-" * 100)
    for code in sorted(CANDIDATE_CODES, key=lambda c: primary["features"][c]["auc"], reverse=True):
        row = primary["features"][code]
        cross = corroboration["features"][code]["auc"] if corroboration else float("nan")
        status = "clears" if code in gate["gate_output"] else "drop: " + ",".join(
            gate["per_feature"][code]["failed"]
        )
        print(
            f"{code:<28}{row['auc']:>8.3f}{row['icc1']:>8.3f}"
            f"{row['max_abs_r_existing']:>12.3f}{row['max_abs_r_existing_with']:>22}"
            f"{cross:>11.3f}  {status}"
        )
    print("-" * 100)
    print(
        f"documents={primary['n_documents']} authors={primary['n_authors']} "
        f"same-author pairs={primary['n_same_author_pairs']} "
        f"different-author pairs={primary['n_different_author_pairs']}"
    )
    if corroboration:
        print(
            f"corroboration: documents={corroboration['n_documents']} "
            f"authors={corroboration['n_authors']} "
            f"same={corroboration['n_same_author_pairs']} "
            f"diff={corroboration['n_different_author_pairs']}"
        )
    cost = report["cost"]
    print(
        f"cost: parse {cost['parse_ms_per_document']:.0f} ms/doc, "
        f"candidate extract {cost['extract_ms_per_document']:.1f} ms/doc "
        f"({cost['extract_fraction_of_parse']:.1%} of a parse), "
        f"tier5 as-is {cost['tier5_asis_ms_per_document']:.0f} ms/doc, "
        f"mean {cost['mean_words_per_document']:.0f} words/doc"
    )
    print(
        f"\nG-P5a verdict: {gate['verdict'].upper()} "
        f"({len(gate['gate_output'])}/{len(CANDIDATE_CODES)} candidates cleared)"
    )
    print(f"  {gate['verdict_reason']}")
    print(f"frozen list for Phase 5B ({len(gate['frozen_list'])}): {gate['frozen_list']}")
    print(f"wall clock: {report['wall_clock_seconds']:.0f}s")


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    n_authors = DEFAULT_N_AUTHORS
    if argv:
        n_authors = int(argv[0])
    report = run(n_authors=n_authors)
    _print_table(report)
    print(f"\nwrote {DEFAULT_RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
