"""
evidence_features.py — plain-English descriptions of every measurement in
Original's feature vector, for the staff-only evidence pages (ADR-013).

Each entry was written from the extractor code in ``original/features/``
(and ``tension_arc.py`` for the catastrophe index), not from the feature's
name. Where a measurement is a heuristic or an approximation, the entry says
so. Where it cannot be put in everyday words, it says what is computed.

``unit`` names the natural unit of the extractor's raw value, the number
before Original maps it onto its 0–1 scale with ``NORM_BOUNDS``. ``None``
means the extractor already returns a 0–1 score, so the raw value and the
0–1 value carry the same information.

``kind`` is one of:

* ``"measured"``: computed from the paper's text on every scoring call.
* ``"off"``: a switched-off group (``DISABLED_FEATURE_GROUPS``). Every paper
  gets the fixed middle value, so it cannot differ.
* ``"not_compared"``: a comparison measurement
  (``features.baseline_scope.NOT_COMPUTED_FOR_BASELINES``). The paper being
  scored gets a real value, measured against its past papers, but a past
  paper's stored vector never has one, so scoring does not compare it.

A test fails if this table and ``constants.ALL_FEATURE_CODES`` ever disagree,
so a new measurement cannot ship without a description.
"""

from __future__ import annotations

from functools import cache, lru_cache
from typing import Any

from .constants import TIER17_CODES, TIER18_CODES
from .features.baseline_scope import NOT_COMPUTED_FOR_BASELINES

_OFF_KEYSTROKE = (
    "Keystroke measurement from the Bluebook exam app. This group is switched off, so "
    "every paper gets the fixed middle value and it cannot differ."
)
_OFF_UNIFORMITY = (
    "Uniformity measurement (how evenly a habit is spread through the text). This group is "
    "switched off, so every paper gets the fixed middle value and it cannot differ."
)
_NOT_COMPARED = (
    " Original computes it for the paper being scored, against that paper's past papers, "
    "but not for the past papers themselves, which only hold a fixed stand-in value. "
    "So it is not compared: it is left out of the score, the top list and the counts."
)

# code -> (description, unit of the raw value or None)
_MEASURED: dict[str, tuple[str, str | None]] = {
    # ── Tier 1: surface ──────────────────────────────────────────────────────
    "type_token_ratio": (
        "How varied the vocabulary is: distinct words divided by all words (lower-cased "
        "alphabetic words). Longer texts score lower on this naturally.",
        "distinct words per word",
    ),
    "hapax_legomena_rate": (
        "Share of words that are used exactly once in the paper, out of all words.",
        "once-only words per word",
    ),
    "mean_sentence_length": ("Average number of words per sentence.", "words per sentence"),
    "sentence_length_variance": (
        "How much sentence length varies: the variance of words per sentence.",
        "words² (variance)",
    ),
    "function_word_ratio": (
        "Share of words that are function words (the, of, and, to, in, …) from Original's list.",
        "function words per word",
    ),
    "passive_voice_ratio": (
        "Approximate share of sentences in the passive voice, found with a word pattern "
        "(is/was/been … followed by an -ed/-en word), counted at most once per sentence.",
        "share of sentences",
    ),
    "modal_verb_ratio": (
        "Share of words that are modal verbs (can, could, should, must, might, …).",
        "modal verbs per word",
    ),
    "stop_word_ratio": (
        "Share of words on Original's stop-word list (function words plus other very common "
        "words).",
        "stop words per word",
    ),
    "avg_word_length": ("Average length of a word in letters.", "letters per word"),
    # ── Tier 2: discourse ────────────────────────────────────────────────────
    "discourse_marker_density": (
        "Linking words and phrases (however, therefore, in addition, …) per 100 words. Each "
        "marker on Original's list is counted once if it appears at all, not every time.",
        "distinct linking words per 100 words",
    ),
    "additive_ratio": (
        "Of the distinct linking words used, the share that add on (also, furthermore, …).",
        "share of linking words",
    ),
    "adversative_ratio": (
        "Of the distinct linking words used, the share that contrast (but, however, …).",
        "share of linking words",
    ),
    "causal_ratio": (
        "Of the distinct linking words used, the share that give cause or effect (because, "
        "therefore, …).",
        "share of linking words",
    ),
    "temporal_ratio": (
        "Of the distinct linking words used, the share about time or sequence (then, finally, …).",
        "share of linking words",
    ),
    "thematic_progression_score": (
        "How often a sentence picks up where the last one ended: share of neighbouring "
        "sentence pairs where the opening content words of the second repeat a word from the "
        "second half of the first. A word-overlap approximation.",
        "share of sentence pairs",
    ),
    "pronoun_reference_density": (
        "Pointing words per sentence: he, she, it, they, this, that, these, those, such and "
        "their forms.",
        "pointing words per sentence",
    ),
    "lexical_chain_density": (
        "How much neighbouring sentences share vocabulary: the average overlap (Jaccard) of "
        "their content words (three letters or more, not stop words).",
        "average overlap (share of shared words)",
    ),
    "paragraph_topic_position": (
        "Share of paragraphs whose first sentence has the highest share of content words in "
        "that paragraph (one-sentence paragraphs count as yes). A stand-in for opening with a "
        "topic sentence.",
        "share of paragraphs",
    ),
    "avg_paragraph_length": (
        "Average number of sentences per paragraph.",
        "sentences per paragraph",
    ),
    "sentence_opener_variety": (
        "How varied sentence openings are: entropy over six opening types (pronoun, "
        "subordinating word, linking adverb, the/a/an, lower-case continuation, other), "
        "scaled so 1 means all types equally often.",
        None,
    ),
    "cohesion_device_ratio": (
        "Share of words that tie the text together: pronouns, distinct linking words, and "
        "repeated content words of four letters or more, divided by all words (capped at 1).",
        "share of words",
    ),
    "transition_density": (
        "Transition words and phrases per 100 words (every occurrence counted).",
        "transitions per 100 words",
    ),
    # ── Tier 3: stance and register ──────────────────────────────────────────
    "epistemic_certainty_ratio": (
        "Of all hedging and assertion words, the share that assert (clearly, certainly, …). "
        "0.5 when neither appears.",
        "share of stance words",
    ),
    "hedging_density": (
        "Hedging words (perhaps, may, seems, …) per 100 words.",
        "hedges per 100 words",
    ),
    "assertion_density": (
        "Strong assertion words (clearly, certainly, undoubtedly, …) per 100 words.",
        "assertions per 100 words",
    ),
    "source_integration_style": (
        "After a sentence that cites (a scripture reference or an authority phrase), how often "
        "the next sentence is the writer's own comment (four or more longer content words, not "
        "itself a citation). Share of citing sentences followed that way; without citations, a "
        "small score from summary phrases such as “in other words”.",
        "share of citing sentences",
    ),
    "counter_argument_ratio": (
        "Share of sentences whose first six words include a contrast or concession word "
        "(however, but, although, one might argue, …).",
        "share of sentences",
    ),
    "claim_density": (
        "Claim and conclusion phrases (therefore, thus, I argue, …) per 100 words.",
        "claim phrases per 100 words",
    ),
    "question_ratio": ("Share of sentences that end with a question mark.", "share of sentences"),
    "imperative_density": (
        "Sentences that start with a command verb from a fixed list (consider, note, pray, "
        "remember, …), per 100 words.",
        "per 100 words",
    ),
    "first_person_ratio": (
        "Of all personal pronouns, the share that are first person (I, me, my, we, us, our, …).",
        "share of personal pronouns",
    ),
    "appeal_to_authority_density": (
        "Phrases that appeal to an authority or source (according to, as … argues, scholars, "
        "…) per 100 words.",
        "per 100 words",
    ),
    "conclusion_strategy_score": (
        "In the last fifth of the text, how many of three kinds of closing phrase appear: a "
        "summary phrase, an implication phrase, an open-question phrase. 0, 1/3, 2/3 or 1.",
        None,
    ),
    "theological_register_score": (
        "Density of theological vocabulary: words from Original's theology term list plus "
        "confessional phrases, per word, divided by 0.15 and capped at 1.",
        "extractor score (term rate ÷ 0.15, capped at 1)",
    ),
    # ── Tier 4: characters and punctuation ───────────────────────────────────
    "char_trigram_entropy": (
        "How varied three-letter sequences are across the whole text (Shannon entropy of "
        "character trigrams, spaces included).",
        "bits",
    ),
    "punctuation_diversity": (
        "How evenly the writer spreads use across punctuation marks (Shannon entropy of the "
        "marks used).",
        "bits",
    ),
    "comma_rate": ("Commas per 100 words.", "commas per 100 words"),
    "semicolon_colon_rate": ("Semicolons and colons per 100 words.", "per 100 words"),
    "parenthetical_rate": ("Opening parentheses per 100 words.", "per 100 words"),
    "dash_rate": ("Dashes (—, – or --) per 100 words.", "dashes per 100 words"),
    "quote_rate": ("Opening quotation marks per 100 words.", "per 100 words"),
    # ── Tier 5: grammar (spaCy part-of-speech tags) ─────────────────────────
    "pos_bigram_entropy": (
        "How varied the grammar is from word to word: entropy of pairs of part-of-speech "
        "tags (noun, verb, adjective, …) assigned by the spaCy tagger.",
        "bits",
    ),
    "pos_trigram_entropy": (
        "Like the pair measure above, over runs of three part-of-speech tags.",
        "bits",
    ),
    "noun_verb_ratio": (
        "Nouns (including names) per verb (including auxiliaries), from the spaCy tagger; "
        "capped at 5.",
        "nouns per verb",
    ),
    "adjective_rate": ("Adjectives per 100 tokens, from the spaCy tagger.", "per 100 tokens"),
    "adverb_rate": ("Adverbs per 100 tokens, from the spaCy tagger.", "per 100 tokens"),
    "subordination_ratio": (
        "Subordinating conjunctions (because, although, if, …) per sentence, from the spaCy "
        "tagger.",
        "per sentence",
    ),
    "clause_depth_mean": (
        "How deeply sentences nest: the average depth of each sentence's grammatical tree "
        "from the spaCy parser.",
        "tree levels",
    ),
    # ── Tier 6: personal habits ──────────────────────────────────────────────
    "contraction_rate": ("Contractions (don't, it's, they're, …) per 100 words.", "per 100 words"),
    "sentence_initial_conjunction_rate": (
        "Share of sentences that start with And, But, So, Or, Yet, For or Nor.",
        "share of sentences",
    ),
    "that_which_ratio": (
        "Preference for “that” over “which”: “that” uses in a relative-clause pattern divided "
        "by those plus “which” uses. 0.5 when neither appears.",
        "share of that/which",
    ),
    "citation_style_consistency": (
        "How mixed the citation formats are (author-year, footnote-style, “X argues”, ibid., "
        "scripture references): normalised entropy over the formats used; 0 when one format "
        "or none is used.",
        None,
    ),
    "list_marker_preference": (
        "Which list style dominates, encoded as a number: none 0, numbered 0.2, lettered 0.4, "
        "roman 0.6, bullets 0.8, inline (first, second, finally) 1.0. A category, not an amount.",
        "category code",
    ),
    "abbreviation_tendency": (
        "For theological terms that have a short form (NT, cf., Rom, …), the share written "
        "short rather than in full. 0.5 when neither appears.",
        "share of short forms",
    ),
    # ── Tier 7: distribution ─────────────────────────────────────────────────
    "burstiness": (
        "How uneven sentence lengths are: variance of words per sentence divided by the average.",
        "variance ÷ mean",
    ),
    "perplexity_proxy": (
        "How unusual the word choices are against a general English word-frequency table: the "
        "average of −log₂ of each word's frequency (unknown words get a fixed floor).",
        "bits per word",
    ),
    "repetition_gap_entropy": (
        "How varied the distances are between repeats of the same content word (four letters "
        "or more): entropy of those gaps.",
        "bits",
    ),
    "transition_predictability": (
        "How similar neighbouring paragraphs are in vocabulary: average cosine similarity of "
        "their word counts. 0.5 for a single paragraph.",
        None,
    ),
    "vocabulary_introduction_rate": (
        "How early new vocabulary appears: the text is cut into ten equal parts, and at the "
        "end of each part Original notes the share of the paper's distinct words already "
        "used; this is the average of those ten shares (higher means more arrives early). "
        "0.5 under 20 words.",
        None,
    ),
    "filler_hedge_cluster_rate": (
        "Whether hedging words bunch together or spread out: inequality (Gini) of the gaps "
        "between them. 0 with fewer than three hedges.",
        None,
    ),
    # ── Tier 8: rhythm (approximate stress) ──────────────────────────────────
    "stress_entropy_unigram": (
        "Rhythm from an approximate syllable-stress rule (vowel groups as syllables, stress on "
        "the second-to-last): entropy of stressed vs unstressed syllables.",
        None,
    ),
    "stress_entropy_bigram": (
        "The same approximate stress pattern, entropy over pairs of syllables.",
        None,
    ),
    "clausulae_consistency": (
        "How consistently sentences end on the same kind of syllable (stressed or not) under "
        "the approximate stress rule: 1 minus the spread of final-syllable stress.",
        None,
    ),
    "breath_group_variance": (
        "How much the number of syllables per sentence varies (coefficient of variation ÷ 2, "
        "capped at 1).",
        None,
    ),
    # ── Tiers 9–12 standalone ────────────────────────────────────────────────
    "structural_centrist_penalty": (
        "Each sentence is tagged as question, contrast, resolution, evidence, claim or other "
        "by keyword rules; this is 1 minus the share of distinct move-to-move pairs. Higher "
        "means the same few patterns repeat.",
        None,
    ),
    "semantic_field_dispersion": (
        "How widely sentence meanings range: variance of the distances between sentence "
        "embeddings (a language-model representation of each sentence), divided by 0.1 and "
        "capped at 1.",
        None,
    ),
    "catastrophe_index": (
        "Technical: Original's tension-arc analysis tags tension raised and resolved within "
        "each paragraph (unfinished clauses, questions and contrasts not yet answered, and "
        "shifts in meaning between sentences) and computes κ = spread × (1 − average) of the "
        "per-paragraph resolution ratio, divided by 0.3 and capped at 1.",
        None,
    ),
    # ── Tier 13: prosody (approximate stress) ────────────────────────────────
    "clausula_type_consistency": (
        "How consistently sentences close with the same rhythmic pattern (classified from the "
        "last syllables under the approximate stress rule): 1 minus the normalised entropy of "
        "those patterns.",
        None,
    ),
    "breath_group_regularity": (
        "How regular the stretches between pauses are: spans of words between commas, "
        "semicolons, colons and dashes, scored 1 ÷ (1 + their coefficient of variation).",
        None,
    ),
    "vowel_sonority_ratio": (
        "Share of vowel groups that are long-vowel spellings (ee, ea, oo, ou, ai, …).",
        None,
    ),
    "arc_resolution_score": (
        "Whether sentences get shorter at the end: compares the average sentence length in the "
        "last quarter of the text with the longest of the first three quarters. Higher means a "
        "shorter final quarter. 0.5 under eight sentences.",
        None,
    ),
    "metric_flatness_score": (
        "How alike paragraphs are in their share of words of two or more syllables: 1 minus "
        "their coefficient of variation ÷ 0.4. Higher means more alike.",
        None,
    ),
    "clausula_shape_preference": (
        "The usual closing rhythm of sentences, as an average of pattern scores from light "
        "endings (0) to heavy classical endings (1), under the approximate stress rule.",
        None,
    ),
    # ── Tier 14: error patterns (heuristics) ─────────────────────────────────
    "error_topology_consistency": (
        "Where in their paragraphs likely comma splices fall (early, middle, late), scored 1 "
        "minus the entropy of those positions. 0.5 with fewer than two splices. Splices are "
        "found by a heuristic, not a grammar check.",
        None,
    ),
    "article_omission_rate": (
        "Approximate rate of singular nouns after a preposition with no article (the, a, an, "
        "…), per 100 words, from the spaCy parser (or a word pattern without it), scaled to 0–1. "
        "Many such nouns are correct English; this is a heuristic count.",
        None,
    ),
    "pronoun_ambiguity_rate": (
        "Of the sentences with a third-person pronoun (he, she, it, they and their forms), "
        "the share whose previous two sentences hold four or more noun-like words (a word "
        "after the/a/an, or a capitalised word). A rough sign the reference could be unclear. "
        "0.5 with no such pronouns.",
        None,
    ),
    "comma_splice_rate": (
        "Likely comma splices (two clauses each with a common verb, joined by a comma before a "
        "pronoun or similar subject word) per 100 sentences, ÷ 30 and capped at 1. A heuristic.",
        None,
    ),
    # ── Tier 15: word architecture ───────────────────────────────────────────
    "semantic_field_concentration": (
        "How closely related the 20 most frequent longer words are: their average similarity "
        "in spaCy's word vectors (or, without vectors, the share sharing a 4-letter start).",
        None,
    ),
    "polysyndeton_ratio": (
        "Lists joined with repeated and/or/but (“X and Y and Z”) as a share of those plus bare "
        "comma lists (“X, Y, Z”). 0.5 when neither appears.",
        None,
    ),
    "chiasmus_rate": (
        "How often the last three word classes of a sentence appear reversed at the start of "
        "the next (spaCy tags), per 100 sentence pairs, ÷ 5 and capped at 1.",
        None,
    ),
    "latinate_ratio": (
        "Share of content words with Latin- or French-style endings (-tion, -ment, -ity, -ous, "
        "-ive, -ate, …).",
        None,
    ),
    "nominalization_density": (
        "Nouns made from verbs or adjectives (-tion, -ment, -ness, -ity, -ance, -ence) per 100 "
        "words, ÷ 15 and capped at 1.",
        None,
    ),
    # ── Tier 16: citation habits (from text before citations are stripped) ──
    "signal_verb_entropy": (
        "How varied the verbs are that introduce sources (“Calvin argues”, “Barth notes”): "
        "entropy of those verbs. 0 when there are none.",
        "bits",
    ),
    "signal_verb_assertiveness": (
        "Average strength of those source verbs on Original's scale (proves 1.0 … suggests "
        "0.25). 0.5 when there are none.",
        None,
    ),
    "source_loyalty_index": (
        "Share of author-year citations that cite an author already cited. 0.5 with fewer "
        "than three citations.",
        None,
    ),
    "block_quote_rate": (
        "Words in long quotations and indented block quotes per 1,000 measured words.",
        "per 1,000 words",
    ),
    "citation_density_cv": (
        "How unevenly citations are spread over paragraphs: standard deviation ÷ mean of "
        "citations per paragraph. 0 without citations.",
        "std ÷ mean",
    ),
    "ibid_usage_rate": (
        "Ibid., op. cit. and loc. cit. as a share of parenthetical citations plus footnote "
        "markers.",
        "share of citations",
    ),
    "citation_position_pref": (
        "Where citation markers sit in their sentence on average: 0 at the start, 1 at the "
        "end. 0.5 without citations.",
        None,
    ),
    "paraphrase_density": (
        "Phrases that attribute without quoting (according to, as Calvin noted, …) per 100 "
        "measured words.",
        "per 100 words",
    ),
}

_COMPARISON_TEXT: dict[str, str] = {
    "argument_sequence_likelihood": (
        "Compares this paper's sequence of sentence moves with the move patterns in the past "
        "papers."
    ),
    "semantic_centroid_proximity": (
        "Compares this paper's sentence embeddings with the past papers' embeddings."
    ),
    "error_kl_divergence": (
        "Compares this paper's error-pattern profile with the past papers' profile."
    ),
    "stumble_rate_consistency": "Compares this paper's error rate with the past papers' rates.",
    "punctuation_error_ratio": (
        "Compares this paper's punctuation-error share with the past papers'."
    ),
    "char_trigram_profile_divergence": (
        "Compares this paper's most frequent three-letter sequences with the past papers' "
        "(KL divergence)."
    ),
    "function_word_profile_divergence": (
        "Compares this paper's most frequent function words with the past papers' (KL divergence)."
    ),
}


@lru_cache(maxsize=1)
def feature_info() -> dict[str, dict[str, str | None]]:
    """``code -> {"description", "unit", "kind"}`` for every code in the vector.

    Cached: callers must not mutate the result."""
    out: dict[str, dict[str, str | None]] = {}
    for code, (description, unit) in _MEASURED.items():
        out[code] = {"description": description, "unit": unit, "kind": "measured"}
    for code in TIER17_CODES:
        out[code] = {"description": _OFF_KEYSTROKE, "unit": None, "kind": "off"}
    for code in TIER18_CODES:
        out[code] = {"description": _OFF_UNIFORMITY, "unit": None, "kind": "off"}
    for code in NOT_COMPUTED_FOR_BASELINES:
        out[code] = {
            "description": _COMPARISON_TEXT[code] + _NOT_COMPARED,
            "unit": None,
            "kind": "not_compared",
        }
    return out


# ── How a page shows each measurement's number (display only) ──────────────
#
# A teacher reads a habit's number in one of five ways, and one shared
# formatter (demo/original/js/evidence-view.js ``readable``) follows this
# table, so the pages cannot disagree. Nothing here changes a value.
#
# * ``percent``: the plain value is a true proportion (a share of sentences,
#   of linking words, ...). Shown as a whole-number percent, one decimal under
#   10%. ``of`` is what it is a share of.
# * ``unit``: a count rate or an everyday measure ("2.4 per 100 words",
#   "18.4 words per sentence"). ``unit`` is the label shown. ``scale`` and
#   ``cap`` undo an extractor's own fixed scaling (``comma_splice_rate`` is
#   splices per 100 sentences ÷ 30, capped at 1): the shown number is
#   ``value × scale``, and a value at ``cap`` reads "N or more".
# * ``category``: the value is a code for a kind, not an amount; ``labels``
#   names each code.
# * ``compare``: no everyday unit and no true share (entropies, spreads,
#   similarity scores, positions in a calibration range). Shown only as a
#   plain comparison with the past papers ("higher than all 3 past papers");
#   the exact position is kept for a details line, never as a percent.
# * ``hidden``: not shown to teachers at all (still used in scoring).
#
# ``engine_is_raw`` says the 0–1 value the score uses *is* the extractor's
# value (``NORM_BOUNDS`` is exactly (0, 1)), so a page may read the number
# from it when no plain value was sent. Elsewhere the 0–1 value is a position
# in a calibration range, not a share, and only ``compare`` may use it.
#
# ``whole_paper`` (plain words) marks a habit that no single sentence can show:
# a spread, a variety, a similarity between parts, or a score of the whole.
# ``neutral`` is the sentence for a habit whose extractor returns 0.5 when
# there is nothing to count, so a 50% is not read as a measured half.

_PERCENT: dict[str, str] = {
    "type_token_ratio": "distinct words",
    "hapax_legomena_rate": "words used only once",
    "function_word_ratio": "function words",
    "passive_voice_ratio": "of sentences",
    "modal_verb_ratio": "modal verbs",
    "stop_word_ratio": "stop words",
    "additive_ratio": "of linking words",
    "adversative_ratio": "of linking words",
    "causal_ratio": "of linking words",
    "temporal_ratio": "of linking words",
    "thematic_progression_score": "of sentence pairs",
    "lexical_chain_density": "average word overlap between neighbouring sentences",
    "paragraph_topic_position": "of paragraphs",
    "cohesion_device_ratio": "linking and repeated words",
    "epistemic_certainty_ratio": "of stance words are confident",
    "source_integration_style": "of citing sentences",
    "counter_argument_ratio": "of sentences",
    "question_ratio": "of sentences",
    "first_person_ratio": "of personal pronouns",
    "sentence_initial_conjunction_rate": "of sentences",
    "that_which_ratio": "“that” rather than “which”",
    "abbreviation_tendency": "of terms with a short form",
    "vowel_sonority_ratio": "of vowel sounds are long",
    "pronoun_ambiguity_rate": "of sentences with he, she, it or they",
    "polysyndeton_ratio": "of lists joined with repeated and/or",
    "latinate_ratio": "of content words",
    "source_loyalty_index": "of author-year citations",
    "ibid_usage_rate": "of citations",
}

#: code -> (shown unit, scale, cap). scale/cap None: the plain value as it is.
_UNIT: dict[str, tuple[str, float | None, float | None]] = {
    "mean_sentence_length": ("words per sentence", None, None),
    "sentence_length_variance": ("words² (spread of sentence length)", None, None),
    "avg_word_length": ("letters per word", None, None),
    "discourse_marker_density": ("different linking words per 100 words", None, None),
    "pronoun_reference_density": ("pointing words per sentence", None, None),
    "avg_paragraph_length": ("sentences per paragraph", None, None),
    "transition_density": ("transitions per 100 words", None, None),
    "hedging_density": ("softening words per 100 words", None, None),
    "assertion_density": ("confident words per 100 words", None, None),
    "claim_density": ("claim phrases per 100 words", None, None),
    "imperative_density": ("command sentences per 100 words", None, None),
    "appeal_to_authority_density": ("source phrases per 100 words", None, None),
    "theological_register_score": ("theology terms per 100 words", 15.0, 1.0),
    "comma_rate": ("commas per 100 words", None, None),
    "semicolon_colon_rate": ("semicolons and colons per 100 words", None, None),
    "parenthetical_rate": ("brackets per 100 words", None, None),
    "dash_rate": ("dashes per 100 words", None, None),
    "quote_rate": ("quotation marks per 100 words", None, None),
    "noun_verb_ratio": ("nouns per verb", None, None),
    "adjective_rate": ("adjectives per 100 tokens", None, None),
    "adverb_rate": ("adverbs per 100 tokens", None, None),
    "subordination_ratio": ("subordinating words per sentence", None, None),
    "clause_depth_mean": ("levels of grammatical nesting, sentence average", None, None),
    "contraction_rate": ("contractions per 100 words", None, None),
    "comma_splice_rate": ("likely comma splices per 100 sentences", 30.0, 1.0),
    "chiasmus_rate": ("mirrored patterns per 100 sentence pairs", 5.0, 1.0),
    "nominalization_density": ("-tion, -ment, -ness words per 100 words", 15.0, 1.0),
    "block_quote_rate": ("words in long quotations per 1,000 words", None, None),
    "paraphrase_density": ("attribution phrases per 100 words", None, None),
}

_CATEGORY: dict[str, dict[str, str]] = {
    # tier6.list_marker_preference's own codes.
    "list_marker_preference": {
        "0": "no lists",
        "0.2": "numbered lists",
        "0.4": "lettered lists",
        "0.6": "roman-numeral lists",
        "0.8": "bulleted lists",
        "1": "lists inside sentences (first, second, finally)",
    },
}

#: Degenerate on real writing (constants.NORM_BOUNDS note: P95 = 0, only
#: 0, 1/3, 2/3 or 1): kept in scoring, never shown to a teacher.
HIDDEN_CODES = frozenset({"conclusion_strategy_score"})

_SPREAD = (
    "This is a pattern across the whole paper: how evenly something is spread or how "
    "much it varies from part to part. No single sentence shows it."
)
_VARIETY = (
    "This is a pattern across the whole paper: how varied the writing is overall. "
    "No single sentence shows it."
)
_BETWEEN = (
    "This is a pattern across the whole paper: how its sentences or paragraphs compare "
    "with each other. No single sentence shows it."
)
_WHOLE_SCORE = (
    "This is one score for the whole paper, built from all of it at once. No single "
    "sentence shows it."
)
WHOLE_PAPER: dict[str, str] = {
    "type_token_ratio": _VARIETY,
    "hapax_legomena_rate": _VARIETY,
    "char_trigram_entropy": _VARIETY,
    "punctuation_diversity": _VARIETY,
    "pos_bigram_entropy": _VARIETY,
    "pos_trigram_entropy": _VARIETY,
    "sentence_opener_variety": _VARIETY,
    "repetition_gap_entropy": _VARIETY,
    "stress_entropy_unigram": _VARIETY,
    "stress_entropy_bigram": _VARIETY,
    "signal_verb_entropy": _VARIETY,
    "citation_style_consistency": _VARIETY,
    "burstiness": _SPREAD,
    "breath_group_variance": _SPREAD,
    "breath_group_regularity": _SPREAD,
    "citation_density_cv": _SPREAD,
    "metric_flatness_score": _SPREAD,
    "filler_hedge_cluster_rate": _SPREAD,
    "clausulae_consistency": _SPREAD,
    "clausula_type_consistency": _SPREAD,
    "error_topology_consistency": _SPREAD,
    "lexical_chain_density": _BETWEEN,
    "thematic_progression_score": _BETWEEN,
    "transition_predictability": _BETWEEN,
    "semantic_field_dispersion": _BETWEEN,
    "semantic_field_concentration": _BETWEEN,
    "structural_centrist_penalty": _BETWEEN,
    "catastrophe_index": _WHOLE_SCORE,
    "arc_resolution_score": _WHOLE_SCORE,
    "clausula_shape_preference": _WHOLE_SCORE,
    "perplexity_proxy": _WHOLE_SCORE,
    "vocabulary_introduction_rate": _WHOLE_SCORE,
    "cohesion_device_ratio": _WHOLE_SCORE,
}

_NEUTRAL_WORDS = "Original records 50% when there is nothing to count, so 50% can also mean none."
#: Extractors that return exactly 0.5 when nothing was found (prosodic.py, tier3, tier6, tier16).
_NEUTRAL = frozenset(
    {
        "epistemic_certainty_ratio",
        "that_which_ratio",
        "abbreviation_tendency",
        "pronoun_ambiguity_rate",
        "polysyndeton_ratio",
        "source_loyalty_index",
        "vowel_sonority_ratio",
        "latinate_ratio",
    }
)


@cache
def display_info(code: str) -> dict[str, Any]:
    """How the pages show ``code``'s number (see the table notes above).

    Cached: callers must not mutate the result."""
    from .constants import NORM_BOUNDS

    out: dict[str, Any] = {"engine_is_raw": tuple(NORM_BOUNDS.get(code, ())) == (0.0, 1.0)}
    if code in HIDDEN_CODES:
        out["style"] = "hidden"
    elif code in _PERCENT:
        out.update(style="percent", of=_PERCENT[code])
    elif code in _UNIT:
        unit, scale, cap = _UNIT[code]
        out.update(style="unit", unit=unit)
        if scale is not None:
            out.update(scale=scale, cap=cap)
    elif code in _CATEGORY:
        out.update(style="category", labels=dict(_CATEGORY[code]))
    else:
        out["style"] = "compare"
    if code in WHOLE_PAPER:
        out["whole_paper"] = WHOLE_PAPER[code]
    if code in _NEUTRAL:
        out["neutral"] = _NEUTRAL_WORDS
    return out
