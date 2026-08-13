"""Compression / character-language-model signals for the pan_stack fusion,
computed per partition -- mirrors delta_signals.py and lambdag_signals.py in
shape, keying and abstention contract.

Why this channel exists: every signal already in the pan_stack fusion
(Original's 109-dim hand-curated feature vector via raw/peer probability,
the LUAR-family character/content similarities, Burrows' Delta, LambdaG's
POSNoise grammar) is built on top of a curated inventory -- word lists,
POS tags, feature definitions. A character-level language model measures
character-sequence predictability directly, with no inventory at all, so
its errors have no structural reason to correlate with the others'. Nothing
in this repo did compression-based verification before this module.

Two backends, both stdlib-or-already-present:

1. Character n-gram LM (primary). Reuses ``validation.attribution.lambdag``'s
   ``NGramLM`` -- a constant-discount (D=0.75) Kneser-Ney model that is
   alphabet-agnostic (it never inspects its tokens) and whose
   ``token_logprob`` already returns log2 probability, i.e. bits. Feeding it
   character tuples instead of POSNoise tuples turns it into a character LM
   for free, with no second implementation of Kneser-Ney to keep correct.
   ``_CachedCharLM`` memoises the two pure functions of the training counts
   that dominate scoring cost (``_extension_total`` and the per-n-gram
   logprob). Character vocabularies are ~100 symbols, so the un-memoised
   ``_extension_total`` sums over the whole alphabet at every backoff level
   of every character -- the memo is the difference between minutes and
   hours over a PAN partition, and it changes no value.

2. zlib normalized compression distance (NCD), the classic Cilibrasi-Vitanyi
   quantity: ``(C(ab) - min(C(a),C(b))) / max(C(a),C(b))``. Each side is
   truncated to ``ncd_max_chars`` (default 16,000) so that a concatenation
   fits inside DEFLATE's 32 KiB sliding window -- past that limit zlib
   cannot see the reference material while compressing the unknown text and
   NCD degrades toward a constant. That bound comes from the format, not
   from any measurement on the evaluation data.

Abstention is ``None``, never 0.0 and never a neutral value:
``validation.stacked.fusion`` imputes with the median and appends a
missingness indicator, so an abstaining channel is handled correctly, while
a fake neutral value would be silently treated as evidence.

Determinism: there is no RNG anywhere in this module. The peer reference
pool is a deterministic round-robin slice over the other authors of the same
partition, taken in sorted author_id order.
"""

from __future__ import annotations

import math
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Iterable, Sequence

from validation.attribution.lambdag import BOS, NGramLM

__all__ = [
    "build_char_lm",
    "char_cross_entropy",
    "compression_trial_signals",
    "normalized_compression_distance",
]

SIGNAL_NAMES = ("compression_delta", "compression_h_author", "compression_ncd")

#: Below this many characters an unknown text's per-character cross-entropy is
#: dominated by the model's backoff mass rather than by the author's habits.
MIN_UNKNOWN_CHARS = 200
#: Below this the author model has not seen enough characters to have any
#: higher-order n-gram structure worth calling a profile.
MIN_TRAIN_CHARS = 1_000


class _CachedCharLM(NGramLM):
    """``NGramLM`` with the two hot read-only lookups memoised.

    Both overridden methods are pure functions of the (immutable after
    construction) training counts, so caching them returns identical values;
    this is a speed change only. See the module docstring for why it matters
    at character granularity.
    """

    def __init__(self, sentences, order: int, discount: float = 0.75):
        super().__init__(sentences, order, discount)
        self._ext_cache: dict[tuple, int] = {}
        self._lp_cache: dict[tuple, float] = {}

    def _extension_total(self, context: tuple) -> int:
        cached = self._ext_cache.get(context, -1)
        if cached >= 0:
            return cached
        value = super()._extension_total(context)
        self._ext_cache[context] = value
        return value

    def token_logprob(self, token: str, context: tuple) -> float:
        trimmed = context[-(self.order - 1) :] if self.order > 1 else ()
        key = trimmed + (token,)
        cached = self._lp_cache.get(key)
        if cached is not None:
            return cached
        value = super().token_logprob(token, trimmed)
        self._lp_cache[key] = value
        return value


def _normalize(text: str) -> str:
    """Collapse whitespace runs to a single space.

    Line-wrapping and indentation are artefacts of how a document was stored,
    not of how its author writes; leaving them in would let a character LM
    score formatting instead of style.
    """
    return " ".join(text.split())


def build_char_lm(texts: Iterable[str], *, order: int = 5) -> _CachedCharLM:
    """Train a character Kneser-Ney LM on ``texts``.

    Each text becomes one sequence of character tokens, so BOS/EOS padding is
    a negligible fraction of the training counts.
    """
    sentences = [tuple(_normalize(t)) for t in texts]
    sentences = [s for s in sentences if s]
    if not sentences:
        raise ValueError("build_char_lm requires at least one non-empty text")
    return _CachedCharLM(sentences, order=order)


def char_cross_entropy(text: str, lm: NGramLM) -> float:
    """Mean negative log2 probability per character, i.e. bits/char.

    Lower means the model predicts this text better. Raises ``ValueError`` on
    an empty text; callers decide whether short input warrants abstention.
    """
    chars = tuple(_normalize(text))
    if not chars:
        raise ValueError("char_cross_entropy requires non-empty text")
    order = lm.order
    padded = (BOS,) * (order - 1) + chars
    total = 0.0
    for index, token in enumerate(chars):
        total += lm.token_logprob(token, padded[index : index + order - 1])
    return -total / len(chars)


def _compressed_size(payload: bytes, backend: str) -> int:
    if backend == "zlib":
        return len(zlib.compress(payload, 9))
    if backend == "lzma":
        import lzma

        return len(lzma.compress(payload, preset=6))
    raise ValueError(f"unknown NCD backend {backend!r}")


def normalized_compression_distance(
    a: str, b: str, *, backend: str = "zlib", max_chars: int = 16_000
) -> float:
    """Cilibrasi-Vitanyi NCD in [0, ~1]. Lower means more similar.

    Both sides are truncated to ``max_chars`` -- see the module docstring for
    why (DEFLATE's 32 KiB window), and note the truncation is a deterministic
    head slice, not a sample.
    """
    left = _normalize(a)[:max_chars].encode("utf-8")
    right = _normalize(b)[:max_chars].encode("utf-8")
    if not left or not right:
        raise ValueError("NCD requires two non-empty texts")
    c_a = _compressed_size(left, backend)
    c_b = _compressed_size(right, backend)
    c_ab = _compressed_size(left + right, backend)
    return (c_ab - min(c_a, c_b)) / max(c_a, c_b)


def _peer_blob(authors: Sequence, target_id: str, *, peer_pool_chars: int | None) -> str:
    """Deterministic pooled sample of the OTHER authors' baseline text.

    Round-robin by sorted author_id with an equal per-author character budget,
    so no single prolific peer dominates the reference model and the result is
    reproducible without an RNG. The target author is excluded by construction;
    only same-partition material is used, so a locked-partition peer model
    never sees development or calibration text either.

    ``peer_pool_chars=None`` means "match the target author's own baseline
    character count". An n-gram LM's cross-entropy falls as its training set
    grows regardless of style, so an unmatched pool would make
    ``compression_delta`` partly a measurement of training-set size rather
    than of authorship. Matching removes that confound by construction.
    """
    others = sorted(
        (a for a in authors if a.author_id != target_id), key=lambda a: a.author_id
    )
    if not others:
        return ""
    if peer_pool_chars is None:
        target = next(a for a in authors if a.author_id == target_id)
        peer_pool_chars = len(_normalize(" ".join(target.baselines)))
    budget = max(1, peer_pool_chars // len(others))
    return " ".join(
        _normalize(" ".join(other.baselines))[:budget] for other in others
    )


def _score_one_target(args: tuple) -> tuple[str, dict]:
    """Top-level (picklable) worker: all trials that claim one target author."""
    (
        target_id,
        target_baselines,
        peer_blob,
        probes_by_source,
        order,
        ncd_backend,
        ncd_max_chars,
        min_unknown_chars,
        min_train_chars,
    ) = args

    author_text = _normalize(" ".join(target_baselines))
    peer_text = _normalize(peer_blob)
    trainable = len(author_text) >= min_train_chars and len(peer_text) >= min_train_chars

    author_lm = build_char_lm([author_text], order=order) if trainable else None
    peer_lm = build_char_lm([peer_text], order=order) if trainable else None

    rows: dict[tuple[str, int], dict[str, float | None]] = {}
    for source_id in sorted(probes_by_source):
        for probe_index, probe in enumerate(probes_by_source[source_id]):
            unknown = _normalize(probe)
            if not trainable or len(unknown) < min_unknown_chars:
                rows[(source_id, probe_index)] = {name: None for name in SIGNAL_NAMES}
                continue
            h_author = char_cross_entropy(unknown, author_lm)
            h_peer = char_cross_entropy(unknown, peer_lm)
            ncd = normalized_compression_distance(
                author_text, unknown, backend=ncd_backend, max_chars=ncd_max_chars
            )
            rows[(source_id, probe_index)] = {
                "compression_delta": h_peer - h_author,
                "compression_h_author": h_author,
                "compression_ncd": ncd,
            }
    return target_id, rows


def compression_trial_signals(
    partitions: dict[str, Sequence],
    *,
    order: int = 5,
    peer_pool_chars: int | None = None,
    ncd_backend: str = "zlib",
    ncd_max_chars: int = 16_000,
    min_unknown_chars: int = MIN_UNKNOWN_CHARS,
    min_train_chars: int = MIN_TRAIN_CHARS,
    max_workers: int | None = None,
) -> dict[str, dict[str, dict[str, float | None]]]:
    """Per-partition compression signals, keyed like
    ``pan_stack.original_trial_signals`` / ``delta_signals.delta_trial_signals``
    so the ``_merge``-style helpers can pick them up.

    Returns ``{partition_name: {trial_id: {signal_name: float | None}}}`` over
    the full target x source x probe cross-product of each partition.

    compression_delta: ``H(unknown | peer_model) - H(unknown | author_model)``
      in bits/char. Positive means the claimed author's own character model
      predicts the unknown text better than a pool of their partition peers
      does -- same-author evidence, on the same "higher = more similar" sign
      convention every other signal in this fusion uses.
    compression_h_author: the raw ``H(unknown | author_model)`` term, kept
      separately so an ablation can tell whether the contrast against the peer
      pool is doing the work or whether raw predictability alone suffices.
      Note it is NOT peer-normalised, so it also tracks how intrinsically
      compressible the unknown text is.
    compression_ncd: zlib NCD between the author's baselines and the unknown
      text. Lower = more similar (the opposite direction to the other two;
      the fusion is a logistic model and recovers the sign itself).

    Work is parallelised per target author, mirroring lambdag_signals.py:
    each target's two language models are independent and are the dominant
    cost, so building them concurrently is a pure wall-clock win.
    """
    from validation.verify.pan_stack import trial_id

    output: dict[str, dict[str, dict[str, float | None]]] = {}
    for partition_name, authors in partitions.items():
        probes_by_source = {a.author_id: list(a.probes) for a in authors}
        tasks = [
            (
                target.author_id,
                list(target.baselines),
                _peer_blob(authors, target.author_id, peer_pool_chars=peer_pool_chars),
                probes_by_source,
                order,
                ncd_backend,
                ncd_max_chars,
                min_unknown_chars,
                min_train_chars,
            )
            for target in authors
        ]

        rows: dict[str, dict[str, float | None]] = {}
        completed = 0
        if max_workers == 1:
            results = [_score_one_target(task) for task in tasks]
        else:
            results = []
            with ProcessPoolExecutor(max_workers=max_workers) as pool:
                futures = [pool.submit(_score_one_target, task) for task in tasks]
                for future in as_completed(futures):
                    results.append(future.result())
                    completed += 1
                    print(
                        f"[compression] {partition_name}: {completed}/{len(tasks)} "
                        f"target models scored",
                        file=sys.stderr,
                    )
        for target_id, target_rows in results:
            for (source_id, probe_index), signals in target_rows.items():
                rows[trial_id(target_id, source_id, probe_index)] = signals
        output[partition_name] = rows
    return output


def abstention_rate(rows: dict[str, dict[str, float | None]], signal: str) -> float:
    """Fraction of trials where ``signal`` abstained -- reported alongside any
    ablation so a channel that never fires cannot be mistaken for one that
    fired and did not help."""
    if not rows:
        return math.nan
    return sum(1 for r in rows.values() if r.get(signal) is None) / len(rows)
