"""Topic-masked (POSNoise) distortion signals for the pan_stack fusion,
computed per partition -- mirrors compression_signals.py in shape, keying and
abstention contract.

Why this channel exists
-----------------------
The measured failure this targets is cross-topic false positives: on the
leave-one-genre-out Lewis corpus, raw ``deviation_score`` reaches AUC 0.387 --
*inverted* -- because a student writing on a new topic looks like a different
author. Phase 2's hypothesis is that scoring the same probe twice, once raw
and once with content vocabulary masked out, separates the two causes:

* raw evidence high, masked evidence high   => the author's structure matches
* raw evidence high, masked evidence low    => the match was topical
* raw evidence low,  masked evidence high   => a genuine author on a new topic
  (this is the false-positive mode)

so the *contrast between the two arms*, not either arm alone, is the evidence.

The divergence choice (raw-vs-masked contrast over one shared estimator)
-----------------------------------------------------------------------
The contrast could be built either by comparing two *distributions* (a KL /
Jensen-Shannon divergence between raw and masked feature-vector or n-gram
distributions) or by computing one scalar authorship quantity twice and
subtracting. This module does the latter, for two reasons, both about not
building a third thing:

1. **Cost and reuse.** The subtraction reuses Phase 1's already-built,
   already-reviewed character-LM machinery verbatim --
   ``compression_signals.build_char_lm`` / ``char_cross_entropy`` /
   ``_peer_blob`` -- and adds exactly one new operation, ``mask_text``. A
   distributional divergence would need a new estimator, new smoothing
   decisions, and a new support-mismatch story (raw and masked text do not
   share a vocabulary at all, so a KL between them is not even well posed
   without an alignment step that would itself be a modelling choice).
2. **Apples-to-apples.** Because both arms run the *identical* estimator at
   the *identical* order over the *identical* peer-pool construction, the
   difference between them isolates the masking and nothing else. If the two
   arms used different estimators, any divergence would confound "content did
   not survive masking" with "the two estimators disagree."

The rejected alternative that is closest to being free is a token-level LM
over the POSNoise tuples directly. That is deliberately *not* used here: it
changes the estimator between arms (characters vs. grammar tokens), and it
would substantially duplicate ``validation/verify/lambdag_signals.py``, which
already runs a Kneser-Ney LM over exactly those tuples as its own separate
fusion channel. Re-deriving LambdaG under a new name would put two correlated
copies of one idea into the same fusion.

Masking is therefore applied to the *text*, and the masked text is re-joined
into a flat string so the unchanged character-LM pipeline consumes it.

Signals emitted
---------------
``undistorted_delta``
    ``H(probe | peer LM) - H(probe | author LM)`` in bits/char on raw text.
    Positive = the claimed author's own model predicts the probe better, the
    same "higher = more similar" convention every other signal in this fusion
    uses. Numerically this is Phase 1's ``compression_delta`` at matched
    hyperparameters; it is recomputed here rather than imported so that both
    arms of the contrast are produced by one call over one normalisation.
``distorted_delta``
    The same quantity computed on POSNoise-masked text. Content vocabulary is
    gone, so what remains is function-word and punctuation sequencing.
``distorted_h_author``
    The raw ``H(masked probe | masked author LM)`` term, kept separately for
    ablation -- exactly the role ``compression_h_author`` played in Phase 1
    (where it turned out inert).
``distorted_divergence``
    ``undistorted_delta - distorted_delta``. Large positive => the raw-text
    evidence rests on content that does not survive masking. Near zero => the
    evidence is structural. Negative => the masked arm carries *more*
    same-author evidence than the raw arm, which is the signature of the
    genuine-author-on-a-new-topic case this phase is aimed at. The fusion is
    a logistic model and recovers the useful sign itself; no direction is
    asserted here in advance.

Abstention
----------
``None``, never 0.0 and never a neutral value: ``validation.stacked.fusion``
imputes with the median and appends a missingness indicator, so an abstaining
channel is handled correctly while a fake neutral value would be silently
treated as evidence. A trial abstains on **all four** signals together if
either arm is uncomputable, so ``distorted_divergence`` is never formed from a
half-observed pair.

Determinism and cost
--------------------
No RNG anywhere. The peer reference pool is the same deterministic round-robin
slice over the other authors of the same partition that Phase 1 used -- the
helper is imported rather than reimplemented so the two arms cannot drift.

Every document in a partition is POSNoise-tagged ONCE, up front, and the
masked text is reused for every candidate's model and every peer pool --
the same amortisation ``lambdag_signals.py`` documents, for the same reason:
tagging per candidate would be an O(n^2) spaCy cost for no benefit.
"""

from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import NamedTuple, Sequence

from validation.attribution.lambdag import posnoise_sentences
from validation.verify.compression_signals import (
    MIN_TRAIN_CHARS,
    MIN_UNKNOWN_CHARS,
    _normalize,
    _peer_blob,
    abstention_rate,
    build_char_lm,
    char_cross_entropy,
)

__all__ = [
    "SIGNAL_NAMES",
    "abstention_rate",
    "distortion_trial_signals",
    "mask_text",
]

SIGNAL_NAMES = (
    "undistorted_delta",
    "distorted_delta",
    "distorted_h_author",
    "distorted_divergence",
)


class _MaskedAuthor(NamedTuple):
    """Minimal stand-in with the two attributes ``_peer_blob`` reads, so the
    masked arm pools peers through the *identical* helper as the raw arm."""

    author_id: str
    baselines: tuple[str, ...]


def mask_text(text: str) -> str:
    """POSNoise-mask ``text`` and re-join it into a flat string.

    Function words and punctuation survive as literal lowercased tokens;
    content words are replaced by their universal POS tag. See
    ``validation/attribution/lambdag.py``'s module docstring for the exact
    category split and its honest deviation from the published POSNoise
    whitelist (POS categories, not a curated ~1000-word lexicon).

    Returns ``""`` for empty or whitespace-only input rather than raising, so
    a degenerate document abstains instead of aborting a partition.
    """
    if not text or not text.strip():
        return ""
    return " ".join(" ".join(sentence) for sentence in posnoise_sentences(text))


def _mask_one(args: tuple[str, str]) -> tuple[str, str]:
    """Top-level (picklable) worker: mask one document."""
    key, text = args
    return key, mask_text(text)


def _mask_partition(authors: Sequence, *, max_workers: int | None) -> dict[str, str]:
    """Mask every baseline and probe of a partition exactly once.

    Keyed by ``f"{author_id}|{kind}|{index}"``. spaCy tagging is the dominant
    cost of this module, and each document is independent, so this is
    parallelised for the same reason feature_cache.py parallelises extraction.
    """
    tasks: list[tuple[str, str]] = []
    for author in authors:
        for index, text in enumerate(author.baselines):
            tasks.append((f"{author.author_id}|baseline|{index}", text))
        for index, text in enumerate(author.probes):
            tasks.append((f"{author.author_id}|probe|{index}", text))

    if max_workers == 1:
        return dict(_mask_one(task) for task in tasks)

    masked: dict[str, str] = {}
    completed = 0
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_mask_one, task) for task in tasks]
        for future in as_completed(futures):
            key, value = future.result()
            masked[key] = value
            completed += 1
            if completed % 25 == 0 or completed == len(tasks):
                print(
                    f"[distortion] tagged {completed}/{len(tasks)} documents",
                    file=sys.stderr,
                )
    return masked


def _arm_signals(
    author_text: str,
    peer_text: str,
    unknown: str,
    *,
    order: int,
    min_unknown_chars: int,
    min_train_chars: int,
) -> tuple[float, float] | None:
    """``(delta, h_author)`` for one arm, or ``None`` if the floors are unmet.

    Split out so the raw and masked arms cannot diverge in their floor logic.
    """
    if len(author_text) < min_train_chars or len(peer_text) < min_train_chars:
        return None
    if len(unknown) < min_unknown_chars:
        return None
    author_lm = build_char_lm([author_text], order=order)
    peer_lm = build_char_lm([peer_text], order=order)
    h_author = char_cross_entropy(unknown, author_lm)
    h_peer = char_cross_entropy(unknown, peer_lm)
    return h_peer - h_author, h_author


def _score_one_target(args: tuple) -> tuple[str, dict]:
    """Top-level (picklable) worker: all trials that claim one target author.

    Both arms' language models are built once per target and reused across
    every probe, so the per-target cost is four LM builds regardless of how
    many probes the partition holds.
    """
    (
        target_id,
        raw_author_text,
        raw_peer_text,
        masked_author_text,
        masked_peer_text,
        raw_probes_by_source,
        masked_probes_by_source,
        order,
        min_unknown_chars,
        min_train_chars,
    ) = args

    raw_trainable = (
        len(raw_author_text) >= min_train_chars and len(raw_peer_text) >= min_train_chars
    )
    masked_trainable = (
        len(masked_author_text) >= min_train_chars
        and len(masked_peer_text) >= min_train_chars
    )

    raw_author_lm = build_char_lm([raw_author_text], order=order) if raw_trainable else None
    raw_peer_lm = build_char_lm([raw_peer_text], order=order) if raw_trainable else None
    masked_author_lm = (
        build_char_lm([masked_author_text], order=order) if masked_trainable else None
    )
    masked_peer_lm = (
        build_char_lm([masked_peer_text], order=order) if masked_trainable else None
    )

    abstain = {name: None for name in SIGNAL_NAMES}
    rows: dict[tuple[str, int], dict[str, float | None]] = {}
    for source_id in sorted(raw_probes_by_source):
        for probe_index, raw_probe in enumerate(raw_probes_by_source[source_id]):
            masked_probe = masked_probes_by_source[source_id][probe_index]
            raw_ok = raw_trainable and len(raw_probe) >= min_unknown_chars
            masked_ok = masked_trainable and len(masked_probe) >= min_unknown_chars
            # Both arms are required: the divergence is a contrast, and a
            # contrast against a missing arm is not a weaker measurement, it
            # is a different quantity.
            if not (raw_ok and masked_ok):
                rows[(source_id, probe_index)] = dict(abstain)
                continue
            raw_delta = char_cross_entropy(raw_probe, raw_peer_lm) - char_cross_entropy(
                raw_probe, raw_author_lm
            )
            masked_h_author = char_cross_entropy(masked_probe, masked_author_lm)
            masked_delta = char_cross_entropy(masked_probe, masked_peer_lm) - masked_h_author
            rows[(source_id, probe_index)] = {
                "undistorted_delta": raw_delta,
                "distorted_delta": masked_delta,
                "distorted_h_author": masked_h_author,
                "distorted_divergence": raw_delta - masked_delta,
            }
    return target_id, rows


def distortion_trial_signals(
    partitions: dict[str, Sequence],
    *,
    order: int = 4,
    peer_pool_chars: int | None = 200_000,
    min_unknown_chars: int = MIN_UNKNOWN_CHARS,
    min_train_chars: int = MIN_TRAIN_CHARS,
    max_workers: int | None = None,
) -> dict[str, dict[str, dict[str, float | None]]]:
    """Per-partition distortion signals, keyed like
    ``pan_stack.original_trial_signals`` / ``compression_signals`` so the
    ``_merge``-style helpers can pick them up.

    Returns ``{partition_name: {trial_id: {signal_name: float | None}}}`` over
    the full target x source x probe cross-product of each partition. See the
    module docstring for what each signal means and why the contrast is built
    by subtraction over one shared estimator.

    Defaults for ``order`` and ``peer_pool_chars`` match the values Phase 1
    selected on the ``fusion_development`` partition; Phase 2 re-checks them on
    the same development partition and never on the locked one.
    """
    from validation.verify.pan_stack import trial_id

    output: dict[str, dict[str, dict[str, float | None]]] = {}
    for partition_name, authors in partitions.items():
        print(
            f"[distortion] {partition_name}: POSNoise-tagging "
            f"{len(authors)} authors' documents...",
            file=sys.stderr,
        )
        masked = _mask_partition(authors, max_workers=max_workers)

        masked_authors = [
            _MaskedAuthor(
                author_id=author.author_id,
                baselines=tuple(
                    masked[f"{author.author_id}|baseline|{i}"]
                    for i in range(len(author.baselines))
                ),
            )
            for author in authors
        ]

        raw_probes_by_source = {a.author_id: [_normalize(p) for p in a.probes] for a in authors}
        masked_probes_by_source = {
            a.author_id: [
                _normalize(masked[f"{a.author_id}|probe|{i}"]) for i in range(len(a.probes))
            ]
            for a in authors
        }

        tasks = []
        for target in authors:
            masked_target = next(
                m for m in masked_authors if m.author_id == target.author_id
            )
            tasks.append(
                (
                    target.author_id,
                    _normalize(" ".join(target.baselines)),
                    _normalize(
                        _peer_blob(authors, target.author_id, peer_pool_chars=peer_pool_chars)
                    ),
                    _normalize(" ".join(masked_target.baselines)),
                    _normalize(
                        _peer_blob(
                            masked_authors,
                            target.author_id,
                            peer_pool_chars=peer_pool_chars,
                        )
                    ),
                    raw_probes_by_source,
                    masked_probes_by_source,
                    order,
                    min_unknown_chars,
                    min_train_chars,
                )
            )

        rows: dict[str, dict[str, float | None]] = {}
        if max_workers == 1:
            results = [_score_one_target(task) for task in tasks]
        else:
            results = []
            completed = 0
            with ProcessPoolExecutor(max_workers=max_workers) as pool:
                futures = [pool.submit(_score_one_target, task) for task in tasks]
                for future in as_completed(futures):
                    results.append(future.result())
                    completed += 1
                    print(
                        f"[distortion] {partition_name}: {completed}/{len(tasks)} "
                        f"target model pairs scored",
                        file=sys.stderr,
                    )
        for target_id, target_rows in results:
            for (source_id, probe_index), signals in target_rows.items():
                rows[trial_id(target_id, source_id, probe_index)] = signals
        output[partition_name] = rows
    return output
