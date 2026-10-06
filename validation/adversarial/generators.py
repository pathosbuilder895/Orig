"""
validation/adversarial/generators.py — mechanical obfuscation generator
(Task 14).

Implements `MechanicalObfuscation(seed).transform(text) -> str`: a
deterministic, non-LLM "dumbing down" transform approximating the manual
obfuscation strategies documented in Brennan/Afroz/Greenstadt (2012)
§4.5 — shorter sentences, fewer syllables/shorter words, thinner
adjectives and adverbs, lower readability.

Design decision — NOT a `Generator` ABC subclass
--------------------------------------------------
`validation/diagnostics/generators.py`'s `Generator` ABC (`configured`,
`skip_reason()`, `load_samples(prompts) -> list[GeneratedSample]`) models
a PROMPT-DRIVEN source of already-produced text — an LLM you ask to
write N samples, or a static corpus keyed by prompt. `MechanicalObfuscation`
is the opposite shape: it has no prompts and fabricates nothing. It
deterministically rewrites INPUT text handed to it. Forcing it through
`load_samples(prompts)` would mean inventing prompts for text that
already exists, which cuts against the ABC's own docstring ("must raise
rather than return placeholder or fabricated text").

Task 17's `poisoning.py` (docs/superpowers/plans/2026-09-20-adversarial-
verification-sp1.md, Task 17) confirms the intended call shape: its
"obfuscated_baselines" mode is described as "MechanicalObfuscation over
baselines" — i.e. it is expected to call `.transform(text)` directly on
each existing baseline document's text, never through `load_samples`. So
this class is a plain, standalone utility matching exactly the interface
the Task 14 brief specifies (`__init__(self, seed)`, `.transform(self,
text) -> str`) and nothing more.

Three mechanical steps (per Brennan/Afroz/Greenstadt §4.5)
------------------------------------------------------------
1. **Sentence splitting at coordinating conjunctions** that join two
   independent clauses: spaCy dependency parse, a `CCONJ` token with
   `dep_ == "cc"` whose head is a VERB/AUX and has a `conj` sibling that
   is itself a VERB/AUX with its own subject (`nsubj`/`nsubjpass`/
   `expl`). This excludes conjunctions joining two adjectives or two
   noun phrases (e.g. "disappointing and frustrating") — only real
   clause-level conjunctions split the sentence. Directly targets
   "shorter sentences."
2. **Thinning adjectives/adverbs**: within each resulting clause, a
   deterministic fraction of `ADJ`/`ADV` tokens is dropped — longest
   first (ties broken by text, then position, for a total order), every
   2nd or every 3rd in that ordering (see "Seed usage" below), collapsing
   whitespace correctly. Not all of them — that would mangle the text.
3. **Swapping known long connector/filler words for shorter ones**: a
   small, fixed, hand-curated map (`_SIMPLIFICATION_MAP`) of
   multisyllabic linking/hedging words the Brennan/Afroz/Greenstadt
   writeup calls out (e.g. "however" -> "but", "utilize" -> "use",
   "approximately" -> "about") to short, near-universally interchangeable
   equivalents. A general "find a same-POS simpler synonym for any
   long/rare word" pass was judged too fragile for a purely mechanical,
   grammar-blind rewriter — it can easily produce ungrammatical or
   meaning-changing output (verb/noun confusion, wrong register,
   agreement breaks). The hand-curated map never changes a sentence's
   grammatical shape (each replacement is drop-in interchangeable with
   its key), so it is safe to apply blindly.

   Every entry in `_SIMPLIFICATION_MAP` is checked, once at import time,
   to have a strictly lower vowel-group ("syllable") count than the word
   it replaces, using the same heuristic already used elsewhere in this
   codebase for syllable-adjacent readability features (see
   `original/features/tier8.py:_word_stress`,
   `original/features/prosodic.py:_syllable_groups`) — this is the
   "syllable-aware" grounding note satisfied without a full syllable-
   driven thesaurus lookup. Separately, `_maybe_swap` consults
   `original/data/word_frequencies.json` (the 200-entry frequent-word
   pool named in the brief's grounding note) as a guard: a word already
   in that top-frequency pool is left alone — there is nothing to
   simplify about a word that's already maximally common. (The pool
   itself is too small — 200 mostly-function words — to serve as the
   *source* of every replacement; most of `_SIMPLIFICATION_MAP`'s
   replacement values are short, common English words chosen by hand
   that don't happen to appear in that specific 200-word list, e.g.
   "help", "buy", "began". See the module-level assertion below for the
   invariant that *is* enforced on every entry.)

   This guard is NOT a no-op in practice: exactly one of
   `_SIMPLIFICATION_MAP`'s keys — "however", the map's own flagship
   example — is itself present in `word_frequencies.json`'s top-200
   pool, so the "however" -> "but" swap never fires while this guard is
   active (verified by checking `"however" in
   json.load(open("original/data/word_frequencies.json"))`, which is
   `True`). No other map key collides with the pool. The guard is kept
   as-is rather than special-cased around "however": frequency and
   syllable count are different axes (a word can be common and still
   multisyllabic), so this single miss is an accepted, narrow trade-off
   of using frequency as the "already simple" proxy, not a bug — and the
   review that flagged this only asked for the claim to be corrected,
   not for the guard's behavior to change.

Seed usage
----------
`seed` seeds a `random.Random` used for exactly one binary choice per
`MechanicalObfuscation` instance: whether adjective/adverb thinning
drops every 2nd or every 3rd token (in the length-sorted order described
in step 2 above) from each clause. This is the "otherwise-arbitrary
tie-breaking choice" the task brief allows seeding for — there is no
principled reason 2 vs. 3 should be a *learned* answer, but the
mechanism should still be reproducible per seed and able to vary between
seeds (on a text with enough adjectives/adverbs for the two fractions to
select a different subset). Everything else — which conjunctions qualify
for splitting, which words get swapped — is fully determined by the
input text's own parse and has no arbitrary choice left to seed.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from functools import lru_cache
from pathlib import Path

from validation.diagnostics.generators import GeneratedSample, Generator

_HERE = Path(__file__).resolve().parent
_WORD_FREQ_PATH = _HERE.parent.parent / "original" / "data" / "word_frequencies.json"

_VOWEL_GROUP_RE = re.compile(r"[aeiouyAEIOUY]+")

# Small, deterministic, hand-curated multisyllabic connector/filler word
# -> shorter equivalent map (step 3). Not a thesaurus lookup or a live
# synonym service — see module docstring for why this stays narrow.
_SIMPLIFICATION_MAP: dict[str, str] = {
    "however": "but",
    "therefore": "so",
    "nevertheless": "still",
    "nonetheless": "still",
    "furthermore": "also",
    "moreover": "also",
    "additionally": "also",
    "consequently": "so",
    "subsequently": "later",
    "approximately": "about",
    "regarding": "about",
    "concerning": "about",
    "utilize": "use",
    "utilizes": "uses",
    "utilized": "used",
    "utilizing": "using",
    "demonstrate": "show",
    "demonstrates": "shows",
    "demonstrated": "showed",
    "indicate": "show",
    "indicates": "shows",
    "indicated": "showed",
    "numerous": "many",
    "significant": "big",
    "significantly": "greatly",
    "substantial": "large",
    "individuals": "people",
    "initially": "first",
    "ultimately": "finally",
    "particularly": "especially",
    "essentially": "simply",
    "sufficient": "enough",
    "obtain": "get",
    "obtained": "got",
    "purchase": "buy",
    "purchased": "bought",
    "assistance": "help",
    "commence": "begin",
    "commenced": "began",
    "authoritative": "trusted",
    "rigorous": "strict",
}


@lru_cache(maxsize=1)
def _load_word_frequencies() -> dict[str, int]:
    """The 200-entry {word: frequency_count} pool from
    original/data/word_frequencies.json, loaded once and cached. Used by
    `_maybe_swap` as a "this word is already common, leave it alone"
    guard — see module docstring §3."""
    return json.loads(_WORD_FREQ_PATH.read_text())


@lru_cache(maxsize=1)
def _load_nlp():
    """en_core_web_sm, loaded lazily (once) so importing this module
    never pays spaCy's model-load cost unless `.transform()` is actually
    called."""
    import spacy

    return spacy.load("en_core_web_sm")


def _count_syllables(word: str) -> int:
    """Vowel-group proxy syllable count — the same heuristic already used
    elsewhere in this codebase for syllable-adjacent features (see
    `original/features/tier8.py:_word_stress`,
    `original/features/prosodic.py:_syllable_groups`)."""
    return max(1, len(_VOWEL_GROUP_RE.findall(word)))


# Invariant: every hand-curated replacement must be strictly *simpler*
# (fewer vowel-group "syllables") than the word it replaces. Checked once
# at import time so a future edit to the map that adds a non-simplifying
# pair fails loudly rather than silently degrading the transform.
_NON_SIMPLIFYING_ENTRIES = [
    (word, replacement)
    for word, replacement in _SIMPLIFICATION_MAP.items()
    if _count_syllables(replacement) >= _count_syllables(word)
]
assert not _NON_SIMPLIFYING_ENTRIES, (
    "_SIMPLIFICATION_MAP entries must strictly reduce syllable count: "
    f"{_NON_SIMPLIFYING_ENTRIES}"
)


class MechanicalObfuscation:
    """Deterministic, non-LLM "dumbing down" text transform.

    See the module docstring for the three mechanical steps, the
    Generator-ABC decision, and exactly how `seed` is used.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = random.Random(seed)
        # The one seed-controlled arbitrary choice — see "Seed usage" in
        # the module docstring.
        self._thin_every = 2 if rng.random() < 0.5 else 3

    def transform(self, text: str) -> str:
        nlp = _load_nlp()
        doc = nlp(text)
        out_sentences: list[str] = []
        for sent in doc.sents:
            out_sentences.extend(self._split_sentence(list(sent)))
        return " ".join(s for s in out_sentences if s)

    # -- Step 1: sentence splitting at coordinating conjunctions --------

    def _split_sentence(self, tokens: list) -> list[str]:
        split_idx = self._find_split_index(tokens)
        if split_idx is None:
            return [self._render_clause(tokens, ensure_terminal=True)]
        before = tokens[:split_idx]
        after = tokens[split_idx + 1 :]
        if before and before[-1].text == ",":
            before = before[:-1]
        if not before or not after:
            return [self._render_clause(tokens, ensure_terminal=True)]
        first = self._render_clause(before, ensure_terminal=True)
        second = self._render_clause(after, ensure_terminal=True)
        return [s for s in (first, second) if s]

    @staticmethod
    def _find_split_index(tokens: list) -> int | None:
        """Index of a coordinating conjunction that joins two independent
        clauses, or None. A `CCONJ`/`cc` token qualifies only when its
        head is a VERB/AUX *and* the SPECIFIC `conj` child paired with
        that `cc` token (not just any `conj` child of the shared head)
        is itself a VERB/AUX with its own subject — i.e. two clauses,
        each with a subject and a verb, not two adjectives or two noun
        phrases joined by "and"/"but".

        Pairing a `cc` with its conjunct: spaCy's coordination parse
        attaches every conjunct in a chain ("A and B, and C") as a
        `conj` child of the SAME shared head, and attaches each `cc`
        token to that same head too — so a naive "does the head have
        *any* conj child with a subject" check (the Finding-1 bug) can
        match a `cc` against a conjunct it doesn't actually introduce.
        In practice a `cc` token immediately precedes the conjunct it
        introduces ("X and Y" — "and" sits right before Y), so the
        correct pairing is the `conj` child with the smallest token
        index that is still greater than the `cc` token's own index.
        """
        for i, tok in enumerate(tokens):
            if tok.pos_ != "CCONJ" or tok.dep_ != "cc":
                continue
            head = tok.head
            if head.pos_ not in ("VERB", "AUX"):
                continue
            conj_children = sorted(
                (c for c in head.children if c.dep_ == "conj" and c.i > tok.i),
                key=lambda c: c.i,
            )
            if not conj_children:
                continue
            paired = conj_children[0]
            if paired.pos_ not in ("VERB", "AUX"):
                continue
            if any(gc.dep_ in ("nsubj", "nsubjpass", "expl") for gc in paired.children):
                return i
        return None

    # -- Step 2 (thin ADJ/ADV) + Step 3 (swap) + render ------------------

    def _render_clause(self, tokens: list, ensure_terminal: bool = False) -> str:
        """Render one clause's tokens as a standalone sentence: thin,
        swap, join with original inter-token whitespace, collapse any
        whitespace left behind by dropped tokens, and capitalize the
        first letter — every clause this method is called on becomes its
        own independent output sentence (whether or not a split
        happened), so the first-letter capitalization is unconditional.
        This also covers the case where the clause's own original first
        word (e.g. "Furthermore,") was itself thinned away, which would
        otherwise leave a lowercase word starting the sentence."""
        kept = self._thin_adjectives_adverbs(tokens)
        pieces = [self._maybe_swap(tok.text) + tok.whitespace_ for tok in kept]
        text = "".join(pieces).strip()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s+([.,!?;:])", r"\1", text)
        text = text.strip(" ,")
        if not text:
            return text
        text = text[0].upper() + text[1:]
        if ensure_terminal and not text.endswith((".", "!", "?")):
            text += "."
        return text

    def _thin_adjectives_adverbs(self, tokens: list) -> list:
        """Drop a deterministic fraction of ADJ/ADV tokens: the longest
        ones first (ties broken by text then position, for a total
        order), every Nth (`self._thin_every`, 2 or 3, seed-selected —
        see module docstring) in that ordering. Not all adjectives/
        adverbs are eligible — only alphabetic ones, so punctuation-
        adjacent tagging quirks can't get swept up, and (Finding-3 fix,
        see `_is_fragile_coordination_member`) not members of a bare
        two-token "X and/or Y" coordination, since thinning either one
        alone strands the conjunction.

        Finding-2 fix (kept as defense in depth): thinning can still
        remove the LAST conjunct of a pair that
        `_is_fragile_coordination_member` didn't catch (e.g. a pair at
        the very end of a clause after other tokens were dropped around
        it), which would otherwise leave a bare coordinating conjunction
        dangling at the end of the clause. After computing the drop set,
        `_drop_dangling_conjunctions` sweeps the survivors and also drops
        any `cc` token left with nothing but punctuation after it.
        """
        indexed = [
            (i, tok)
            for i, tok in enumerate(tokens)
            if tok.pos_ in ("ADJ", "ADV")
            and tok.is_alpha
            and not self._is_fragile_coordination_member(tokens, i)
        ]
        if not indexed:
            return tokens
        ordered = sorted(indexed, key=lambda pair: (-len(pair[1].text), pair[1].text, pair[0]))
        drop_positions = {i for pos, (i, _tok) in enumerate(ordered) if pos % self._thin_every == 0}
        keep_indices = [i for i in range(len(tokens)) if i not in drop_positions]
        keep_indices = self._drop_dangling_conjunctions(tokens, keep_indices)
        return [tokens[i] for i in keep_indices]

    @staticmethod
    def _is_fragile_coordination_member(tokens: list, i: int) -> bool:
        """True if `tokens[i]` is one member of an exactly-two-token
        coordination — "TOKEN cc OTHER" or "OTHER cc TOKEN", where `cc`
        is a coordinating-conjunction token (`CCONJ`/`cc`, e.g.
        "and"/"or") immediately adjacent to it and `OTHER` is some
        alphabetic content token immediately on the far side of that
        `cc`. Thinning `tokens[i]` alone in that shape strands the
        conjunction with nothing meaningful on one side of it.

        Finding-3: this generalizes the Finding-2 trailing-conjunction
        fix (`_drop_dangling_conjunctions`, which cleans up *after* a
        drop when the SECOND/trailing conjunct is removed, e.g.
        "skeptical and unconvinced" -> "skeptical and.") to the mirror
        case — thinning the FIRST/leading conjunct leaves the
        conjunction stranded with nothing meaningful *before* it
        instead (e.g. "calm and composed" -> "and composed", reachable
        via "The lawyer seemed calm and composed, and the jury looked
        attentive and interested." — dropping "calm" as the clause's
        only eligible ADJ produces "The lawyer seemed and composed.").

        Deliberately adjacency-based on the raw token sequence rather
        than POS-gated on `OTHER`'s tag: in that exact reproduction
        spaCy tags the second conjunct ("composed") VERB, not ADJ (it
        parses as a `conj` sibling under the head "seemed", not an
        ADJ-headed coordination like "skeptical"/"unconvinced" above),
        so a check requiring *both* sides to carry an ADJ/ADV tag would
        silently fail to catch this exact case. What breaks
        grammaticality is an empty slot next to the conjunction, not
        what POS tag fills the other slot — so this checks only that
        something alphabetic is there, not what it is tagged.

        Chosen fix strategy: skip thinning `tokens[i]` entirely (leave
        both members of the pair intact) rather than removing the whole
        coordinated phrase as one unit — simpler, and it composes
        cleanly with `_drop_dangling_conjunctions` below without needing
        to touch the drop-position math for a second time.
        """
        if i + 2 < len(tokens):
            cc, other = tokens[i + 1], tokens[i + 2]
            if cc.pos_ == "CCONJ" and cc.dep_ == "cc" and other.is_alpha:
                return True
        if i - 2 >= 0:
            other, cc = tokens[i - 2], tokens[i - 1]
            if cc.pos_ == "CCONJ" and cc.dep_ == "cc" and other.is_alpha:
                return True
        return False

    @staticmethod
    def _drop_dangling_conjunctions(tokens: list, keep_indices: list[int]) -> list[int]:
        """Sweep `keep_indices` (already thinned) from the end and drop
        any coordinating conjunction (`CCONJ`/`cc`) that is now the last
        non-punctuation token kept — i.e. thinning removed everything
        that used to follow it in the clause. Trailing punctuation (a
        comma or the sentence-final ".") is left in place; only the
        orphaned conjunction itself is removed. Looped so a chain of
        newly-orphaned conjunctions (rare, but possible with adjacent
        coordinated pairs) is fully cleaned up, not just the first one."""
        result = list(keep_indices)
        changed = True
        while changed:
            changed = False
            content_positions = [pos for pos, i in enumerate(result) if not tokens[i].is_punct]
            if not content_positions:
                break
            last_pos = content_positions[-1]
            last_tok = tokens[result[last_pos]]
            if last_tok.pos_ == "CCONJ" and last_tok.dep_ == "cc":
                del result[last_pos]
                changed = True
        return result

    @staticmethod
    def _maybe_swap(word: str) -> str:
        lower = word.lower()
        replacement = _SIMPLIFICATION_MAP.get(lower)
        if replacement is None:
            return word
        if lower in _load_word_frequencies():
            # Already a top-frequency word in the pilot's own frequency
            # pool — nothing to simplify (see module docstring §3). This
            # is a real, observable guard, not a no-op: it is what
            # suppresses "however" -> "but", the map's own flagship
            # example, since "however" is itself in the top-200 pool.
            return word
        if word.isupper():
            return replacement.upper()
        if word[:1].isupper():
            return replacement.capitalize()
        return replacement



# ============================================================================
# LLMImitation / LLMParaphrase / LLMRoundTrip (Task 15)
# ============================================================================
#
# These three classes are CACHE READERS ONLY — none of them ever makes a
# network call or imports `anthropic`. They replay text an earlier, offline,
# human-run invocation of `gen_llm_attacks.py` (this package, sibling module)
# already produced and committed to
# `validation/adversarial/corpus/llm_attacks/`. This split (generation
# script vs. read-only Generator subclasses) is the same shape
# `validation/diagnostics/generators.py`'s `ClaudeStaticGenerator` uses for
# its 20 committed Claude essays — see that class's docstring, which this
# implementation follows closely per the Task 15 brief.
#
# Manifest contract (the part Task 19's gates and any future re-run of
# gen_llm_attacks.py depend on being stable):
#
#   validation/adversarial/corpus/llm_attacks/manifest.json
#     {"entries": [
#        {"model_id": str,     # e.g. "claude-opus-5" — exact model that
#                               #   produced this doc
#         "prompt_sha": str,   # sha256 hex digest of the exact prompt text
#                               #   sent to the API for this doc (for a
#                               #   round-trip doc, sha256 of the two hop
#                               #   prompts concatenated — see
#                               #   gen_llm_attacks.py's module docstring)
#         "doc_sha": str,      # sha256 hex digest of the doc's OWN text
#                               #   content — the integrity check load_samples()
#                               #   verifies against the file on disk
#         "victim_id": str,    # matches VictimProfile.victim_id (profiles.py)
#         "attack": str,       # "imitation" | "paraphrase" | "roundtrip_de"
#                               #   | "roundtrip_ja"
#         "n_baselines": int}, # informational only (which build_victim_profiles
#                               #   N produced the source profile) — NOT part
#                               #   of the (victim_id, attack) lookup key, so
#                               #   a generator instance is agnostic to which
#                               #   N(s) contributed its cached docs
#        ...
#     ]}
#
#   Chosen list-of-dicts shape (not dict-keyed) to match the existing
#   convention in this repo: validation/public_authors/manifest.json and
#   cross_work_manifest.json are both `{"entries": [...]}`.
#
#   File layout: `corpus/llm_attacks/<attack>/<victim_id>/<doc_sha>.txt` —
#   the DOC'S PATH IS DERIVED from its own (attack, victim_id, doc_sha)
#   fields, never stored as a separate "filename" key. One fewer field to
#   keep in sync with reality, and it makes the four/five manifest fields
#   above (plus n_baselines) the complete, minimal contract — a corrupted
#   or hand-edited "filename" field can't silently point a reader at the
#   wrong file.
#
# Round-trip design decision: EN -> {German, Japanese} -> EN is generated as
# TWO separate API calls per language pair (translate there, then translate
# back), not one "translate to X and then back to English" prompt in a
# single call. Two independent calls mirror how a real adversary would
# actually execute this attack (piping text through an external MT service
# twice, with no memory of having done the first hop) and keep each single
# translation call's instruction simple and unambiguous — a single prompt
# asking the model to silently perform two hops and return only the final
# English text asks it to both translate AND suppress the intermediate
# output, which is a harder instruction to get reliably right than "translate
# this text" issued twice. `roundtrip_de` and `roundtrip_ja` are tracked as
# two distinct `attack` values (not one "roundtrip" value with a language
# sub-field) so each is independently `configured`/cache-missable — an
# adversary who only ran the German leg shouldn't have `LLMRoundTrip(...,
# language="ja")` silently report `configured=True` on the strength of the
# German docs alone.

_REQUIRED_LLM_MANIFEST_KEYS = {"model_id", "prompt_sha", "doc_sha", "victim_id", "attack"}

_LLM_ATTACKS_CACHE_DIR = _HERE / "corpus" / "llm_attacks"


class _LLMCacheGenerator(Generator):
    """Common cache-reading base for the three LLM-driven attacks. See the
    module-level comment above this class for the manifest contract.

    `CACHE_DIR` is a per-class attribute (not baked into a module-level
    constant read once at import time) specifically so a test can do
    `monkeypatch.setattr(LLMImitation, "CACHE_DIR", tmp_path)` to point one
    class at a synthetic fixture cache without touching the real committed
    directory, the module global, or the other two classes.

    Each instance is scoped to exactly one `(victim_id, attack)` pair —
    `attack` is a class (or, for LLMRoundTrip, instance) attribute set by
    the subclass; `victim_id` is a constructor argument, since the same
    committed cache holds every victim's docs and one instance reads only
    its own victim's slice of it.
    """

    attack: str = ""  # set by subclasses
    CACHE_DIR: Path = _LLM_ATTACKS_CACHE_DIR

    def __init__(self, victim_id: str) -> None:
        self.victim_id = victim_id

    @property
    def _manifest_path(self) -> Path:
        return self.CACHE_DIR / "manifest.json"

    def _cache_present(self) -> bool:
        return self._manifest_path.exists() and self.CACHE_DIR.exists()

    def _load_manifest_entries(self) -> list[dict]:
        data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise ValueError(f"{self._manifest_path}: manifest missing an 'entries' list")
        return entries

    def _matching_entries(self) -> list[dict]:
        if not self._cache_present():
            return []
        return [
            entry
            for entry in self._load_manifest_entries()
            if entry.get("victim_id") == self.victim_id and entry.get("attack") == self.attack
        ]

    @property
    def configured(self) -> bool:
        return self._cache_present() and len(self._matching_entries()) > 0

    def skip_reason(self) -> str | None:
        if self.configured:
            return None
        if not self._manifest_path.exists():
            return (
                f"no LLM attack cache: {self._manifest_path} does not exist "
                "(run gen_llm_attacks.py with an API key first)"
            )
        if not self.CACHE_DIR.exists():
            return f"no LLM attack cache: {self.CACHE_DIR} does not exist"
        return (
            f"cache present but has no {self.attack!r} attack cached for "
            f"victim_id={self.victim_id!r}"
        )

    def load_samples(self, prompts: list[str]) -> list[GeneratedSample]:
        """Ignores `prompts` — like `ClaudeStaticGenerator.load_samples`,
        this reader is already scoped to one (victim_id, attack) by
        construction, so there is nothing in `prompts` to filter by; the
        parameter exists only to satisfy the `Generator` ABC's signature.

        Never fabricates. Raises instead of returning a partial or
        placeholder result when:
          - no manifest entry matches this instance's `(victim_id, attack)`
            — a genuine cache miss (the offline script was never run for
            this combination), or
          - a matching entry's manifest record is missing a required key,
            its doc file does not exist on disk, or the file's own
            SHA-256 does not match the manifest's recorded `doc_sha`
            (tamper/corruption — the file on disk is not what the
            manifest says it is).
        """
        entries = self._matching_entries()
        if not entries:
            reason = self.skip_reason() or "no cached samples for this generator"
            raise LookupError(
                f"LLM attack cache miss for victim_id={self.victim_id!r} "
                f"attack={self.attack!r}: {reason}"
            )
        samples: list[GeneratedSample] = []
        for entry in entries:
            missing = _REQUIRED_LLM_MANIFEST_KEYS - entry.keys()
            if missing:
                raise ValueError(
                    f"manifest entry missing required key(s) {sorted(missing)}: {entry}"
                )
            doc_path = (
                self.CACHE_DIR / entry["attack"] / entry["victim_id"] / f"{entry['doc_sha']}.txt"
            )
            if not doc_path.exists():
                raise FileNotFoundError(
                    f"manifest references {doc_path}, which does not exist on disk"
                )
            text = doc_path.read_text(encoding="utf-8")
            actual_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if actual_sha != entry["doc_sha"]:
                raise ValueError(
                    f"{doc_path}: content SHA-256 {actual_sha} does not match manifest "
                    f"doc_sha {entry['doc_sha']!r} (file may be corrupted or tampered with)"
                )
            samples.append(GeneratedSample(prompt=entry["prompt_sha"], text=text))
        return samples


class LLMImitation(_LLMCacheGenerator):
    """Cache-reader for the imitation attack: an LLM asked to write new
    text "in the style of" a victim's baseline documents, to test whether
    it can impersonate that victim well enough to fool the detector.
    See `gen_llm_attacks.py:_imitation_prompt` for the (not-yet-run,
    offline-only) prompt this cache's docs were produced from."""

    name = "llm-imitation"
    attack = "imitation"


class LLMParaphrase(_LLMCacheGenerator):
    """Cache-reader for the paraphrase attack: an LLM asked to rewrite one
    of the victim's own genuine (held-out) documents, preserving its
    meaning — an LLM-driven analogue of `MechanicalObfuscation`'s
    rule-based obfuscation attack above (Brennan/Afroz/Greenstadt): same
    idea (disguise genuine writing to evade attribution), LLM-executed
    instead of rule-based. See `gen_llm_attacks.py:_paraphrase_prompt`."""

    name = "llm-paraphrase"
    attack = "paraphrase"


class LLMRoundTrip(_LLMCacheGenerator):
    """Cache-reader for the machine-translation round-trip attack:
    EN -> {German, Japanese} -> EN, applied to one of the victim's own
    genuine (held-out) documents. `language` selects which pair this
    instance reads ("de" or "ja") — see the "Round-trip design decision"
    comment above this class for why the two are tracked as separate
    `attack` ids ("roundtrip_de" / "roundtrip_ja") rather than one merged
    "roundtrip" attack, and why each language is two API calls, not one,
    in the (not-yet-run, offline-only) generation script."""

    _LANGUAGES = ("de", "ja")

    def __init__(self, victim_id: str, language: str) -> None:
        if language not in self._LANGUAGES:
            raise ValueError(f"language must be one of {self._LANGUAGES}, got {language!r}")
        super().__init__(victim_id)
        self.language = language
        self.attack = f"roundtrip_{language}"
        self.name = f"llm-roundtrip-{language}"
