"""Character n-gram profiles for rule D, without scikit-learn at run time.

Re-implements exactly the two TF-IDF vectorizers frozen for the pre-registered rule D study
(``scholarly-rule-d-2026-11-12``): scikit-learn ``TfidfVectorizer(analyzer="char")`` with
sublinear term frequency, smoothed IDF and L2 normalisation. The vocabularies and IDF weights
ship as ``original/data/rule_d_vectorizer_v1.json.gz`` (n-gram statistics only; no paper text).

* ``char``: lower-cased text, character 3-5-grams.
* ``masked``: :func:`mask_topic` text (not lower-cased), character 3-6-grams. Masking keeps
  function words and punctuation and replaces other letters with ``*`` and digits with ``#``,
  so the profile describes word shapes and punctuation, not subject matter.

A profile is a sparse unit vector: ``{index: weight}``.
"""

from __future__ import annotations

import gzip
import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parent.parent / "data" / "rule_d_vectorizer_v1.json.gz"

FUNCTION_WORDS = tuple(
    """a about above after again against all also although am among an and another any are as at
be because been before being below between both but by can could did do does doing down
during each either enough even ever every few for from further had has have having he her
here hers herself him himself his how however i if in indeed into is it its itself just
least less many may me might more moreover most much must my myself neither never no nor
not now of off often on once one only or other others otherwise our ours ourselves out
over own perhaps rather same she should since so some still such than that the their
theirs them themselves then there therefore these they this those though through thus to
too under until up upon us very was we well were what whatever when where whereas whether
which while who whom whose why will with within without would yet you your yours""".split()
)
_FW_SET = frozenset(FUNCTION_WORDS)
_WHITE_SPACES = re.compile(r"\s\s+")  # scikit-learn's char analyzer normalisation

Profile = dict[int, float]


def mask_topic(text: str) -> str:
    """Keep function words and punctuation; replace other letters with '*' and digits with '#'."""
    out = []
    for tok in text.split():
        core = tok.strip(".,;:!?\"'()[]")
        if core.lower() in _FW_SET:
            out.append(tok)
        else:
            out.append("".join("*" if ch.isalpha() else "#" if ch.isdigit() else ch for ch in tok))
    return " ".join(out)


class Vectorizer:
    def __init__(self, spec: dict):
        self.lo, self.hi = spec["ngram_range"]
        self.lowercase = spec["lowercase"]
        self.masked = spec["masked"]
        self.vocab = {g: i for i, g in enumerate(spec["vocabulary"])}
        self.idf = spec["idf"]
        self.terms = spec["vocabulary"]

    def prepare(self, text: str) -> str:
        if self.masked:
            return mask_topic(text)
        return text.lower() if self.lowercase else text

    def ngrams(self, text: str) -> Counter:
        doc = _WHITE_SPACES.sub(" ", self.prepare(text))
        n_chars = len(doc)
        counts: Counter = Counter()
        for n in range(self.lo, min(self.hi + 1, n_chars + 1)):
            for i in range(n_chars - n + 1):
                j = self.vocab.get(doc[i : i + n])
                if j is not None:
                    counts[j] += 1
        return counts

    def profile(self, text: str) -> Profile:
        """Sparse L2-normalised TF-IDF vector, sublinear term frequency."""
        w = {j: (1.0 + math.log(c)) * self.idf[j] for j, c in self.ngrams(text).items()}
        norm = math.sqrt(sum(v * v for v in w.values()))
        return {j: v / norm for j, v in w.items()} if norm > 0 else {}


@lru_cache(maxsize=1)
def vectorizers() -> dict[str, Vectorizer]:
    with gzip.open(ARTIFACT, "rt", encoding="utf-8") as f:
        spec = json.load(f)
    return {name: Vectorizer(spec["vectorizers"][name]) for name in ("char", "masked")}


def artifact_meta() -> dict:
    with gzip.open(ARTIFACT, "rt", encoding="utf-8") as f:
        spec = json.load(f)
    return {k: v for k, v in spec.items() if k != "vectorizers"}


def dot(a: Profile, b: Profile) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def centroid(profiles) -> Profile:
    """Unit-length mean of unit profiles (rule D's author centroid)."""
    acc: dict[int, float] = {}
    n = 0
    for p in profiles:
        n += 1
        for k, v in p.items():
            acc[k] = acc.get(k, 0.0) + v
    if not n:
        return {}
    norm = math.sqrt(sum(v * v for v in acc.values()))
    return {k: v / norm for k, v in acc.items()} if norm > 0 else {}
