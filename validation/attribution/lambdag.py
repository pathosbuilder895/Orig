"""LambdaG: a grammar-based likelihood-ratio authorship verification signal.

Nini, Halvani, Graner, Titze, Gherardi, Ishihara (2026), "Grammar as a
behavioral biometric: Using cognitively motivated grammar models for
authorship verification," arXiv:2403.08462 / Humanit Soc Sci Commun 13:455.
Flagged #3 in the 2026-08-05 stylometry literature sweep (see
docs/research/STYLOMETRY_LITERATURE_SWEEP_2026-08-05.md) as the closest
published claim to this codebase's exact constraint: the paper reports
LambdaG "robust to small variations in the composition of the reference
population" -- i.e. designed for few-reference-document verification, not
large-training-corpus classification.

Algorithm (paper's Algorithm 1): build a Kneser-Ney n-gram language model
G_A over the candidate author's "grammar" (a content-masked token stream --
function words kept literal, content words abstracted to their POS
category), build r reference models G_1..G_r from resampled reference-
population sentences matched in count to the candidate's, then score the
probe document by the mean log-likelihood-ratio of each probe token under
G_A versus the r reference models. Positive = more grammatical/entrenched
for the candidate than for the reference population; negative = the
opposite. This is a raw, UNCALIBRATED score (see lambda_g_score's
docstring) -- Cllr(lambda_G) is poor in the paper's own numbers; a fusion
signal, not a decision on its own.

HONEST DEVIATION FROM THE PUBLISHED METHOD: the paper's content-masking
step, POSNoise (Halvani & Graner 2021), uses a curated whitelist of ~1000
topic-agnostic words and phrases across 20 hand-built linguistic categories
(their Table 6) -- that whitelist was not published in the paper excerpts
available here. This module approximates it with spaCy's universal POS
tags instead: DET/ADP/PRON/CCONJ/SCONJ/AUX/PART/PUNCT kept as literal
(lowercased) tokens, NOUN/PROPN/VERB/ADJ/ADV/NUM/INTJ/SYM abstracted to
their POS tag. Sanity-checked against the paper's own worked example
("If they actually censor anything is another question." ->
"If they [ADV] [VERB] anything is another [NOUN].") -- every one of the 7
non-punctuation tokens in that sentence gets the same keep/mask decision
under this scheme as under the paper's own POSNoise output, including
"anything," which POSNoise's own Table 6 lists as a whitelisted pronoun.
This is corroborating, not proof of exact equivalence: POS-category-based
masking is coarser than a curated lexical whitelist and will diverge on
closed-class words a tagger mis-assigns to an open-class tag (e.g. certain
quantifiers tagged ADJ). Treat lambda_G's absolute values as this
approximation's output, not the published method's.

Kneser-Ney smoothing follows the paper's Eq. 15-19 exactly, with one
simplification the paper itself makes: despite calling it "modified"
Kneser-Ney, Section 6.3.4 states plainly that a CONSTANT discount D=0.75 is
used for every count (not Chen & Goodman's per-count-bucket discounts),
which collapses Eq. 18's infinite sum to D * N_1+(g*). This module
implements exactly that constant-discount form.
"""

from __future__ import annotations

import logging
import math
import random
from collections import Counter
from dataclasses import dataclass

log = logging.getLogger(__name__)

BOS = "<BOS>"
EOS = "<EOS>"

# Universal POS tags (spaCy's en_core_web_sm scheme) kept as literal,
# lowercased tokens -- the closed-class/function-word categories POSNoise's
# whitelist is built from (conjunctions, determiners, prepositions,
# pronouns, auxiliary/helping verbs, contractions collapse into PART/AUX)
# plus punctuation, which the paper explicitly includes in T_L.
_FUNCTION_POS = frozenset({"DET", "ADP", "PRON", "CCONJ", "SCONJ", "AUX", "PART", "PUNCT"})
# Open-class categories abstracted to their POS tag string -- this IS the
# token identity for these words, matching the paper's "abstract
# grammatical categories" (NOUN, VERB, ADJECTIVE, ...) in T_L.
_CONTENT_POS = frozenset({"NOUN", "PROPN", "VERB", "ADJ", "ADV", "NUM", "INTJ", "X", "SYM"})

_nlp = None
_spacy_unavailable = False


def _get_nlp():
    """Lazy-loaded spaCy singleton, mirroring original/features/tier5.py's
    pattern (same model, same disabled pipes -- POS tagging only)."""
    global _nlp, _spacy_unavailable
    if _nlp is None and not _spacy_unavailable:
        try:
            import spacy

            _nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
        except (ImportError, OSError) as exc:
            _spacy_unavailable = True
            log.warning("spaCy model unavailable -- LambdaG cannot run. (%s)", exc)
    return _nlp


def posnoise_sentences(text: str) -> list[tuple[str, ...]]:
    """Content-mask `text` into POSNoise-style function-token sentences.

    Returns a list of sentences, each a tuple of tokens: function words and
    punctuation kept literal (lowercased), content words replaced by their
    POS tag. See module docstring for the exact category split and the
    honest deviation from the published POSNoise whitelist.
    """
    nlp = _get_nlp()
    if nlp is None:
        raise RuntimeError("spaCy model unavailable -- cannot compute LambdaG")

    sentences: list[tuple[str, ...]] = []
    for sent in nlp(text).sents:
        tokens: list[str] = []
        for token in sent:
            if token.is_space:
                continue
            if token.pos_ in _FUNCTION_POS:
                tokens.append(token.text.lower())
            elif token.pos_ in _CONTENT_POS:
                tokens.append(token.pos_)
            else:  # SPACE handled above; anything else (rare) -> its own tag
                tokens.append(token.pos_)
        if tokens:
            sentences.append(tuple(tokens))
    return sentences


class NGramLM:
    """Constant-discount Kneser-Ney n-gram language model over a closed,
    per-model-observed vocabulary. Implements Nini et al. 2026, Eq. 15-19.

    Vocabulary size |T| (the "+1" term in Eq. 16) is this model's own
    training-time distinct-unigram count -- not shared across models. A
    deliberate simplification (see module docstring): |T| only affects the
    minor unigram-level smoothing term, not the higher-order matches that
    carry the actual discriminative signal, so using each model's own
    observed vocabulary rather than a shared global one is a standard,
    low-risk choice absent an externally fixed vocabulary.
    """

    def __init__(self, sentences: list[tuple[str, ...]], order: int, discount: float = 0.75):
        if order < 1:
            raise ValueError("order must be >= 1")
        if not sentences:
            raise ValueError("NGramLM requires at least one sentence")
        self.order = order
        self.discount = discount

        # raw[n]: Counter of n-grams (as tuples) at exactly order n.
        self._raw: list[Counter] = [Counter() for _ in range(order + 1)]
        for sentence in sentences:
            padded = (BOS,) * (order - 1) + sentence + (EOS,)
            length = len(padded)
            for n in range(1, order + 1):
                for i in range(0, length - n + 1):
                    self._raw[n][padded[i : i + n]] += 1

        # left_ext[n][g] = set of tokens t such that (t,)+g was observed as
        # an (n+1)-gram -- gives N1+(*g), i.e. c_KN(g) when len(g) < order.
        # right_ext[n][g] = set of tokens t' such that g+(t',) was observed
        # -- gives N1+(g*), used in gamma(g) and as the summation domain for
        # the shared alpha/gamma denominator.
        self._left_ext: list[dict] = [dict() for _ in range(order)]
        self._right_ext: list[dict] = [dict() for _ in range(order)]
        for n in range(0, order):
            for ngram_plus1, count in self._raw[n + 1].items():
                if count <= 0:
                    continue
                prefix_token, suffix_ngram = ngram_plus1[0], ngram_plus1[1:]
                self._left_ext[n].setdefault(suffix_ngram, set()).add(prefix_token)
                prefix_ngram, suffix_token = ngram_plus1[:-1], ngram_plus1[-1]
                self._right_ext[n].setdefault(prefix_ngram, set()).add(suffix_token)

        self.vocab_size = len(self._left_ext[0].get((), set()))

    def _c_kn(self, ngram: tuple[str, ...]) -> int:
        n = len(ngram)
        if n == self.order:
            return self._raw[self.order].get(ngram, 0)
        return len(self._left_ext[n].get(ngram, ()))

    def _extension_total(self, context: tuple[str, ...]) -> int:
        k = len(context)
        continuations = self._right_ext[k].get(context)
        if not continuations:
            return 0
        return sum(self._c_kn(context + (t,)) for t in continuations)

    def _gamma(self, context: tuple[str, ...]) -> float:
        k = len(context)
        continuations = self._right_ext[k].get(context)
        if not continuations:
            return 1.0  # c(g) == 0: Eq. 18's "otherwise" branch
        total = self._extension_total(context)
        if total <= 0:
            return 1.0
        return self.discount * len(continuations) / total

    def _pkn(self, token: str, context: tuple[str, ...]) -> float:
        k = len(context)
        gt = context + (token,)
        total = self._extension_total(context)
        alpha = max(self._c_kn(gt) - self.discount, 0) / total if total > 0 else 0.0
        if k == 0:
            return alpha + self._gamma(context) * (1.0 / (self.vocab_size + 1))
        return alpha + self._gamma(context) * self._pkn(token, context[1:])

    def token_logprob(self, token: str, context: tuple[str, ...]) -> float:
        """log2 P(token | context), backing off through shorter contexts
        per Eq. 15. Context longer than order-1 is truncated to the most
        recent order-1 tokens, matching the paper's fixed-order n-gram
        assumption."""
        context = context[-(self.order - 1) :] if self.order > 1 else ()
        p = self._pkn(token, context)
        # p > 0 always: the k=0 uniform-interpolation term is strictly
        # positive, so log2 is always defined (Eq. 16's stated purpose).
        return math.log2(p)


@dataclass(frozen=True)
class LambdaGResult:
    lambda_g: float
    n_sentences: int
    n_tokens: int
    repetitions: int
    order: int


def lambda_g_score(
    probe_sentences: list[tuple[str, ...]],
    candidate_model: NGramLM,
    reference_models: list[NGramLM],
) -> LambdaGResult:
    """Eq. 2-4: mean-log-likelihood-ratio of the probe's tokens under the
    candidate model versus the reference-population models, summed over
    every token in every probe sentence.

    Report-only, uncalibrated (see module docstring) -- positive favors the
    candidate, negative favors the reference population, magnitude is not
    meaningful on an absolute scale without the paper's own logistic
    calibration step (a fusion-signal concern, handled by whatever wires
    this in, not by this function).
    """
    if not reference_models:
        raise ValueError("need at least one reference model")
    total = 0.0
    n_tokens = 0
    for sentence in probe_sentences:
        for k in range(len(sentence)):
            token, context = sentence[k], sentence[:k]
            candidate_lp = candidate_model.token_logprob(token, context)
            mean_ref_lp = sum(
                model.token_logprob(token, context) for model in reference_models
            ) / len(reference_models)
            total += candidate_lp - mean_ref_lp
            n_tokens += 1
    return LambdaGResult(
        lambda_g=total,
        n_sentences=len(probe_sentences),
        n_tokens=n_tokens,
        repetitions=len(reference_models),
        order=candidate_model.order,
    )


@dataclass(frozen=True)
class CandidateGrammar:
    """A built candidate model plus its matched reference population --
    the expensive, reusable half of Algorithm 1. The r reference models
    depend only on the candidate's sentence count (matched sampling), not
    on any specific probe, so building this once and scoring many probes
    against it (`lambda_g_score(probe_sentences, grammar.candidate,
    grammar.reference)`) is both correct per the algorithm and far cheaper
    than rebuilding the reference population per probe -- at production
    settings (order=10, repetitions=30) building this is ~19s per candidate
    on a 2500-word baseline; scoring one additional probe against an
    already-built CandidateGrammar costs a fraction of a second.
    """

    candidate: NGramLM
    reference: list[NGramLM]


def build_candidate_grammar(
    candidate_texts: list[str],
    reference_pool_texts: list[str],
    *,
    order: int = 10,
    repetitions: int = 30,
    discount: float = 0.75,
    rng: random.Random | None = None,
) -> CandidateGrammar:
    """Build G_A and the r resampled reference Grammar Models (Algorithm 1,
    lines 7, 9-13) for one candidate author. See `CandidateGrammar`'s
    docstring for why this is split from scoring.

    `repetitions=30` (not the paper's default 100): Section 4/Figure 3
    reports "in most corpora, setting r=100 is unnecessary, as performance
    stabilizes at r=30" -- a paper-justified reduction, not a corner cut for
    convenience, and 30 reference Grammar Models is already the dominant
    cost of this function.
    """
    rng = rng or random.Random()

    candidate_sentences = [s for text in candidate_texts for s in posnoise_sentences(text)]
    reference_sentences = [s for text in reference_pool_texts for s in posnoise_sentences(text)]

    if not candidate_sentences:
        raise ValueError("candidate produced no usable sentences after POSNoise")
    if len(reference_sentences) < len(candidate_sentences):
        raise ValueError(
            f"reference pool has {len(reference_sentences)} sentences, fewer than "
            f"the candidate's {len(candidate_sentences)} -- cannot sample a matched "
            "reference set without replacement"
        )

    candidate_model = NGramLM(candidate_sentences, order=order, discount=discount)
    reference_models = [
        NGramLM(
            rng.sample(reference_sentences, len(candidate_sentences)),
            order=order,
            discount=discount,
        )
        for _ in range(repetitions)
    ]
    return CandidateGrammar(candidate_model, reference_models)


def compute_lambda_g(
    probe_text: str,
    candidate_texts: list[str],
    reference_pool_texts: list[str],
    *,
    order: int = 10,
    repetitions: int = 30,
    discount: float = 0.75,
    rng: random.Random | None = None,
) -> LambdaGResult:
    """Top-level orchestration matching Algorithm 1 end to end for a SINGLE
    probe: build the candidate grammar (see `build_candidate_grammar`) and
    score one probe against it. Scoring more than one probe against the
    same candidate: call `build_candidate_grammar` once and
    `lambda_g_score` per probe instead of calling this repeatedly, which
    would rebuild the (expensive) reference population from scratch every
    time.
    """
    grammar = build_candidate_grammar(
        candidate_texts, reference_pool_texts, order=order, repetitions=repetitions,
        discount=discount, rng=rng,
    )
    probe_sentences = posnoise_sentences(probe_text)
    return lambda_g_score(probe_sentences, grammar.candidate, grammar.reference)
