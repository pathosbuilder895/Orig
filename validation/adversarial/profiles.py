"""
validation/adversarial/profiles.py — victim-profile construction (Task 13).

`build_victim_profiles(n_baselines, seed)` assembles the per-victim
material the rest of SP1's offline red-team harness needs: a claimed
author's baseline writing, a genuine held-out document to confirm the
harness doesn't just flag everything, and a pool of other authors'
writing to stand in for an impostor/adversary.

Data sources (read-only, both already committed under
validation/public_authors/):

  - manifest.json — 11 authors (emerson, douglass, thoreau, mill,
    chesterton, newman, james, kempis, augustine, boethius, edwards), 61
    "authentic" entries. `is_baseline` is the PRIMARY holdout signal:
    True → baseline material, False → held-out/scored material. There is
    no guarantee a False entry is a genuinely different literary work
    from the True entries of the same author — often it's the same essay
    collection.

  - cross_work_manifest.json — a STRICTER holdout for 6 authors (dickens,
    chesterton, christie, emerson, mill, thoreau): its `split_rule` is "A
    work appears in exactly one of baseline or probe", i.e. baseline and
    probe documents are drawn from genuinely different books. Two of
    those six (dickens, christie) have NO entry in the plain manifest at
    all — they exist only via this stricter split.

Design decision (see task-13-brief.md and the docstring on
`build_victim_profiles` below for the full reasoning): every victim is
sourced from exactly ONE of the two manifests, never a mix of both for
baselines vs. holdout. For the 4 authors present in both manifests
(chesterton, emerson, mill, thoreau) the cross-work split wins — it is
the "real different-work holdout" the brief asks for, and mixing a
cross-work baseline with a plain-manifest holdout (or vice versa) would
blur which invariant a downstream test is actually measuring. The
remaining 7 plain-manifest-only authors (douglass, newman, james, kempis,
augustine, boethius, edwards) fall back to the plain manifest's own
is_baseline=False documents — same-work-family, not literally
cross-work, and this module says so rather than pretending otherwise.

Selection within a document pool follows the deterministic SHA-256
convention already used by validation/verify/pan_corpus.py: documents are
sorted by the SHA-256 of their own text content (or the manifest's
precomputed `text_sha256` where present) and the first N are taken. Any
seed-dependent choice (currently: which OTHER victims contribute impostor
documents) instead sorts by the SHA-256 of `f"{seed}:{namespace}:{key}"`,
mirroring `pan_corpus._stable_order`. This keeps `n_baselines`/holdout
selection stable across seeds (a legitimate, content-addressed choice)
while still giving `seed` a real, reproducible effect on the impostor
pool composition.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PUBLIC_AUTHORS_DIR = _HERE.parent / "public_authors"

_MANIFEST_PATH = _PUBLIC_AUTHORS_DIR / "manifest.json"
_CORPUS_DIR = _PUBLIC_AUTHORS_DIR / "corpus"

_CROSS_WORK_MANIFEST_PATH = _PUBLIC_AUTHORS_DIR / "cross_work_manifest.json"
_CROSS_WORK_CORPUS_DIR = _PUBLIC_AUTHORS_DIR / "cross_work_corpus"

# How many genuine-holdout documents to attach per victim, when the
# source pool has more than this available. Only ">= 1" is required by
# the brief; a small handful (rather than every available probe/scored
# document) keeps profiles a manageable size while still giving a
# downstream test more than one holdout sample to check against.
_HOLDOUT_DOCS_PER_VICTIM = 2

# How many OTHER victims' writing to draw one impostor document each
# from. "A handful is fine" per the brief — enough for a real impostor
# pool without needing every other author's every document.
_IMPOSTOR_AUTHORS_PER_VICTIM = 5


@dataclass(frozen=True)
class VictimProfile:
    """One simulated victim for the adversarial harness.

    All three document fields hold actual text content (not file paths):
      - baselines: n_baselines documents used to build the victim's
        stylometric baseline.
      - genuine_holdout: document(s) by the SAME author, drawn from a
        different work where the corpus supports it (see module
        docstring), used to confirm the harness doesn't flag genuine
        writing.
      - impostor_docs: documents by OTHER authors, standing in for an
        adversary attempting to pass as this victim.
    """

    victim_id: str
    baselines: list[str]
    genuine_holdout: list[str]
    impostor_docs: list[str]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _group_plain_manifest_by_author(manifest: dict) -> dict[str, dict[str, list]]:
    """author_id -> {"baseline": [entries], "scored": [entries]} over
    "authentic"-labelled entries only."""
    by_author: dict[str, dict[str, list]] = {}
    for entry in manifest["entries"]:
        if entry.get("label") != "authentic":
            continue
        bucket = by_author.setdefault(entry["author_id"], {"baseline": [], "scored": []})
        bucket["baseline" if entry["is_baseline"] else "scored"].append(entry)
    return by_author


def _group_cross_work_manifest_by_author(manifest: dict) -> dict[str, dict[str, list]]:
    """author_id -> {"baseline": [entries], "probe": [entries]} over
    "authentic"-labelled entries only, keyed by partition_role."""
    by_author: dict[str, dict[str, list]] = {}
    for entry in manifest["entries"]:
        if entry.get("label") != "authentic":
            continue
        role = entry.get("partition_role")
        if role not in ("baseline", "probe"):
            continue
        bucket = by_author.setdefault(entry["author_id"], {"baseline": [], "probe": []})
        bucket[role].append(entry)
    return by_author


def _with_content_hash(entries: list, corpus_dir: Path) -> list[tuple[str, str]]:
    """Read each entry's text off disk; pair it with a content SHA-256
    (reusing the manifest's own text_sha256 where present, else computed
    fresh) for deterministic, content-addressed ordering."""
    pairs = []
    for entry in entries:
        text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
        content_hash = entry.get("text_sha256") or _digest(text)
        pairs.append((content_hash, text))
    return pairs


def _select_by_content_hash(pairs: list[tuple[str, str]], n: int) -> list[str]:
    """Deterministic selection convention (validation/verify/pan_corpus.py:
    `sorted(docs, key=lambda d: d.text_sha256)[:n]`): sort by content hash,
    take the first n."""
    ordered = sorted(pairs, key=lambda pair: pair[0])
    return [text for _, text in ordered[:n]]


def _seeded_order(values: list[str], seed: int, namespace: str) -> list[str]:
    """Seed-dependent deterministic ordering, mirroring
    validation/verify/pan_corpus.py's `_stable_order`: sort by the
    SHA-256 of f"{seed}:{namespace}:{value}"."""
    return sorted(values, key=lambda value: _digest(f"{seed}:{namespace}:{value}"))


@dataclass(frozen=True)
class _Candidate:
    """Intermediate per-victim material before the impostor pool (which
    needs every OTHER victim's material already assembled) is attached."""

    victim_id: str
    baselines: list[str]
    genuine_holdout: list[str]


def _build_cross_work_candidates(
    n_baselines: int,
) -> tuple[dict[str, _Candidate], list[tuple[str, str]]]:
    """Victims sourced from cross_work_manifest.json — the strict,
    genuinely-different-work holdout. Restricted to authors that actually
    have a corpus directory on disk (the manifest and the fetched corpus
    can drift; verify rather than assume)."""
    manifest = _load_json(_CROSS_WORK_MANIFEST_PATH)
    by_author = _group_cross_work_manifest_by_author(manifest)

    candidates: dict[str, _Candidate] = {}
    skipped: list[tuple[str, str]] = []
    for author_id in sorted(by_author):
        if not (_CROSS_WORK_CORPUS_DIR / author_id).is_dir():
            skipped.append((author_id, "cross_work_manifest entry has no corpus directory on disk"))
            continue
        bucket = by_author[author_id]
        baseline_pairs = _with_content_hash(bucket["baseline"], _CROSS_WORK_CORPUS_DIR)
        probe_pairs = _with_content_hash(bucket["probe"], _CROSS_WORK_CORPUS_DIR)
        if len(baseline_pairs) < n_baselines:
            skipped.append(
                (
                    author_id,
                    f"only {len(baseline_pairs)} cross-work baseline documents available, "
                    f"need {n_baselines}",
                )
            )
            continue
        if not probe_pairs:
            skipped.append((author_id, "no cross-work probe (different-work) documents available"))
            continue
        candidates[author_id] = _Candidate(
            victim_id=author_id,
            baselines=_select_by_content_hash(baseline_pairs, n_baselines),
            genuine_holdout=_select_by_content_hash(
                probe_pairs, min(_HOLDOUT_DOCS_PER_VICTIM, len(probe_pairs))
            ),
        )
    return candidates, skipped


def _build_fallback_candidates(
    n_baselines: int, already_used_authors: set
) -> tuple[dict[str, _Candidate], list[tuple[str, str]]]:
    """Victims sourced from the plain manifest.json, for authors that
    don't have a (usable) cross-work split. `is_baseline=False` documents
    stand in for the holdout — same-work-family, not literally a
    different work, which is why cross-work-eligible authors are excluded
    here rather than double-counted."""
    manifest = _load_json(_MANIFEST_PATH)
    by_author = _group_plain_manifest_by_author(manifest)

    candidates: dict[str, _Candidate] = {}
    skipped: list[tuple[str, str]] = []
    for author_id in sorted(by_author):
        if author_id in already_used_authors:
            continue
        if not (_CORPUS_DIR / author_id).is_dir():
            skipped.append((author_id, "manifest.json entry has no corpus directory on disk"))
            continue
        bucket = by_author[author_id]
        baseline_pairs = _with_content_hash(bucket["baseline"], _CORPUS_DIR)
        scored_pairs = _with_content_hash(bucket["scored"], _CORPUS_DIR)
        if len(baseline_pairs) < n_baselines:
            skipped.append(
                (
                    author_id,
                    f"only {len(baseline_pairs)} baseline documents available in manifest.json, "
                    f"need {n_baselines}",
                )
            )
            continue
        if not scored_pairs:
            skipped.append(
                (author_id, "no is_baseline=False documents available for fallback holdout")
            )
            continue
        candidates[author_id] = _Candidate(
            victim_id=author_id,
            baselines=_select_by_content_hash(baseline_pairs, n_baselines),
            genuine_holdout=_select_by_content_hash(
                scored_pairs, min(_HOLDOUT_DOCS_PER_VICTIM, len(scored_pairs))
            ),
        )
    return candidates, skipped


def build_victim_profiles(n_baselines: int, seed: int) -> list[VictimProfile]:
    """Build deterministic victim profiles for the adversarial harness.

    Args:
        n_baselines: number of baseline documents per victim (N in
            {3, 5, 10} per the harness design; not enforced here so the
            function degrades gracefully — an author without enough
            baseline documents at a given N is excluded from that call's
            result rather than raising).
        seed: seeds the (only) non-content-addressed choice this function
            makes — which other victims' writing populates a given
            victim's impostor pool. Baseline and holdout selection are
            content-addressed (sorted by SHA-256 of the document text)
            and therefore identical across seeds; the victim's own
            baseline/holdout choice never depends on `seed`.

    Returns:
        One VictimProfile per eligible author, sorted by victim_id for a
        stable, seed-independent ordering. At n_baselines=3 this is
        currently 13 victims: 6 from the cross-work split (dickens,
        christie, chesterton, emerson, mill, thoreau — the first two have
        no plain-manifest entry at all) and 7 from the plain-manifest
        fallback (augustine, boethius, douglass, edwards, james, kempis,
        newman). An author lacking enough baseline documents for the
        requested `n_baselines` is silently excluded (not padded, not
        repeated) — at n_baselines=10 every plain-manifest-fallback
        author currently drops out, since none has 10 is_baseline=True
        documents.
    """
    cross_work_candidates, _cross_work_skipped = _build_cross_work_candidates(n_baselines)
    fallback_candidates, _fallback_skipped = _build_fallback_candidates(
        n_baselines, already_used_authors=set(cross_work_candidates)
    )

    candidates: dict[str, _Candidate] = {**cross_work_candidates, **fallback_candidates}
    victim_ids = sorted(candidates)

    profiles: list[VictimProfile] = []
    for victim_id in victim_ids:
        other_ids = [v for v in victim_ids if v != victim_id]
        impostor_authors = _seeded_order(other_ids, seed, f"impostor-authors:{victim_id}")[
            :_IMPOSTOR_AUTHORS_PER_VICTIM
        ]
        impostor_docs = [candidates[author_id].baselines[0] for author_id in impostor_authors]
        candidate = candidates[victim_id]
        profiles.append(
            VictimProfile(
                victim_id=victim_id,
                baselines=list(candidate.baselines),
                genuine_holdout=list(candidate.genuine_holdout),
                impostor_docs=impostor_docs,
            )
        )
    return profiles
