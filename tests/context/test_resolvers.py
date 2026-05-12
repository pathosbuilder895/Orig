"""
tests/context/test_resolvers.py — Phase 2 resolver unit tests.

Each test exercises one resolver in isolation against synthetic text fixtures.
The orchestrator tests at the bottom verify parallel execution + per-resolver
exception isolation (graceful degradation contract).
"""

from __future__ import annotations

import re
from typing import Dict, List
from unittest import mock

import pytest

from original.context import resolvers as r


# ── Fixture text generators ──────────────────────────────────────────────────

def _english_paragraph(words_per_sentence: int = 18, sentences: int = 60) -> str:
    """Build a long-ish English paragraph (~1k words) that langdetect tags as 'en'."""
    base = (
        "The committee considered the proposed amendment with great care over many days. "
        "Several members expressed reservations about the long-term implications for trade. "
        "After a long debate the chair called the question and the motion was carried by acclamation. "
    )
    out = (base * (sentences // 3 + 1)).strip()
    return out


def _greek_paragraph() -> str:
    """About 100 words of Greek prose (modern Greek; langdetect handles it as 'el')."""
    return (
        "Η συνεδρίαση της επιτροπής ξεκίνησε με μεγάλη επισημότητα και διάρκεσε αρκετές ώρες. "
        "Τα μέλη συζήτησαν διεξοδικά τις προτεινόμενες τροπολογίες και κατέληξαν σε συμβιβασμό. "
        "Ο πρόεδρος ευχαρίστησε όλους τους συμμετέχοντες για τη γόνιμη συμβολή τους. "
        "Στη συνέχεια παρουσιάστηκαν οι προτάσεις για τον προϋπολογισμό του επόμενου έτους. "
        "Η διαδικασία ολοκληρώθηκε χωρίς προβλήματα και η ψηφοφορία ήταν ομόφωνη. "
        "Κανείς δεν έφερε αντίρρηση για το τελικό κείμενο που είχε προετοιμαστεί. "
        "Η επόμενη συνεδρίαση θα πραγματοποιηθεί την ερχόμενη εβδομάδα στην ίδια αίθουσα. "
        "Ευχαριστούμε όλους τους παρευρισκόμενους για την παρουσία και τη συνεργασία τους."
    )


def _academic_exegesis_text() -> str:
    """Heavy citation density + signal verbs + long sentences."""
    return (
        "In his commentary on Romans, Calvin (1559, p. 145) argues that the apostle's "
        "language presupposes a covenantal framework that runs throughout the epistle, and "
        "modern scholars such as Moo (1996, pp. 12-15) have largely confirmed this exegetical "
        "instinct against the older liberal readings of Käsemann (1980, p. 88). Wright "
        "(2002) demonstrates that the participial construction in 1:17 cannot be divorced "
        "from the eschatological vista the apostle sets forth in chapters 9 through 11. "
        "Schreiner (1998, p. 211) maintains that the imputation of righteousness is "
        "forensic in character, and contends against the New Perspective that this reading "
        "preserves the integrity of Pauline soteriology. As Calvin (1559) writes, the "
        "apostle's argument moves from condemnation to justification with relentless force. "
        "Ibid., p. 146. Subsequent commentators have noted that the passage establishes a "
        "framework which Owen (1657, pp. 33-39) developed in his treatise on communion. "
        "The text reveals a coherent theological vision that emphasizes both divine sovereignty "
        "and human responsibility, a tension that Bavinck (1906) explored at length."
    )


def _sermon_text() -> str:
    """High imperative density + first-person plural + low citation density."""
    return (
        "My friends, let us consider what the Scriptures teach about prayer and devotion. "
        "Open your hearts and listen carefully. Pray without ceasing. Give thanks in all "
        "circumstances. Trust in the Lord with all your heart and lean not on your own "
        "understanding. We must remember the kindness of our Heavenly Father. "
        "Examine yourselves and ask whether you have been faithful in the small things. "
        "Consider how often we forget to pray for our neighbors. We are called to love. "
        "Hear the Word of God this morning and let it transform your life. "
        "I urge you, beloved, to walk worthy of your calling. Remember Christ's example. "
        "Hold fast to what is good. Examine your hearts. Pray for your families. "
        "Walk in the light. Forgive as you have been forgiven. Bear one another's burdens. "
        "I have seen what God can do in a humble heart, and I know He is faithful."
    )


def _blog_post_text() -> str:
    """Short sentences, low citation, low first person, conversational."""
    return (
        "Coffee shops are great. They have wifi. They serve drinks. The vibe is usually nice. "
        "I went to a new one yesterday. The barista was friendly. The seating was comfortable. "
        "Three people were there working on laptops. The music was at a reasonable volume. "
        "I had a flat white. It was excellent. The atmosphere felt productive without being silent. "
        "I will definitely go back. The hours are convenient. The space is bright. Everything works."
    )


def _build_baseline_corpus() -> List[str]:
    """A small academic-style baseline corpus for topic-resolver tests."""
    return [
        "The doctrine of justification has been central to Reformation theology since Luther.",
        "Calvin developed a covenantal framework that distinguished forensic from transformative grace.",
        "Modern Pauline scholarship has revisited the theological vocabulary of the apostle.",
        "Theological method requires careful attention to both biblical text and historical context.",
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Language resolver
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveLanguage:
    def test_pure_english(self):
        out = r.resolve_language(_english_paragraph())
        assert out["primary"] == "en", out
        assert out["code_switched"] is False
        assert out["segments"].get("en", 0) > 0.9

    def test_greek_segment_triggers_code_switch(self):
        # Mostly English with an embedded Greek paragraph (~100 words).
        text = _english_paragraph() + " " + _greek_paragraph()
        out = r.resolve_language(text)
        # langdetect sometimes labels Greek as 'el'; allow either 'en' or 'el' as primary
        # but require the OTHER language to exceed the code-switch threshold.
        assert out["code_switched"] is True, out
        non_primary = sum(p for lang, p in out["segments"].items() if lang != out["primary"])
        assert non_primary > 0.05

    def test_empty_string(self):
        out = r.resolve_language("")
        assert out == {"primary": "unknown", "segments": {}, "code_switched": False}


# ══════════════════════════════════════════════════════════════════════════════
# Genre resolver
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveGenre:
    def test_rule_based_exegesis(self):
        out = r.resolve_genre(_academic_exegesis_text())
        # Heavy citations + signal verbs + long sentences → academic_exegesis or scholarly_essay.
        assert out["primary"] in ("academic_exegesis", "scholarly_essay")
        assert out["confidence"] == 0.5

    def test_rule_based_sermon(self):
        out = r.resolve_genre(_sermon_text())
        # High imperative + high first-person + low citation → sermon (or personal_essay fallback)
        assert out["primary"] in ("sermon", "personal_essay")

    def test_blog_post_falls_through(self):
        out = r.resolve_genre(_blog_post_text())
        assert out["primary"] in ("blog_post", "correspondence", "personal_essay")

    def test_empty_text(self):
        out = r.resolve_genre("")
        assert out["primary"] in r.GENRE_LABELS
        assert out["confidence"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Topic resolver
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveTopic:
    def test_low_novelty_when_submission_matches_baseline(self):
        baseline = _build_baseline_corpus()
        # Submission constructed from baseline vocabulary → low distance.
        submission = (
            "The doctrine of justification developed by Calvin established a Pauline framework. "
            "His attention to theological method and biblical text shaped Reformation method."
        )
        out = r.resolve_topic(submission, baseline)
        assert out["novelty"] in ("low", "medium"), out
        assert out["baseline_distance"] < 0.5

    def test_high_novelty_when_submission_orthogonal(self):
        baseline = _build_baseline_corpus()
        # Submission about coffee — completely different vocabulary.
        submission = (
            "Coffee shops with reliable wifi continue to multiply in suburban neighborhoods. "
            "The barista pulled a delicate flat white as soft jazz played overhead."
        )
        out = r.resolve_topic(submission, baseline)
        assert out["novelty"] in ("medium", "high")
        assert out["baseline_distance"] > 0.2

    def test_empty_baseline_returns_medium(self):
        out = r.resolve_topic("Any text.", [])
        assert out == {"domain": "unknown", "baseline_distance": 0.5, "novelty": "medium"}


# ══════════════════════════════════════════════════════════════════════════════
# Length resolver
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveLength:
    def test_micro(self):
        out = r.resolve_length("Just a tiny note.")
        assert out["regime"] == "micro"
        assert 4 in out["reliable_tiers"]
        assert 7 in out["suppress_tiers"]

    def test_short(self):
        text = " ".join(["word"] * 300)
        out = r.resolve_length(text)
        assert out["regime"] == "short"
        assert out["tokens"] == 300

    def test_standard(self):
        text = " ".join(["word"] * 1500)
        out = r.resolve_length(text)
        assert out["regime"] == "standard"
        assert out["suppress_tiers"] == []

    def test_long(self):
        text = " ".join(["word"] * 5000)
        out = r.resolve_length(text)
        assert out["regime"] == "long"


# ══════════════════════════════════════════════════════════════════════════════
# Citation resolver
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveCitations:
    def test_chicago_format_detected(self):
        out = r.resolve_citations(_academic_exegesis_text())
        assert out["citations_present"] is True
        assert out["density"] > 0
        assert out["format"] in ("chicago", "turabian", "apa")

    def test_no_citations(self):
        out = r.resolve_citations(_blog_post_text())
        assert out["citations_present"] is False
        assert out["format"] == "none"
        assert out["density"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Composition-mode resolver
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveCompositionMode:
    def test_natural_drafted_normal_text(self):
        # ~250 words with ~10 punctuation anomalies (doubled periods, orphan-space
        # commas, doubled exclamation) — keeps punct_error_ratio above the
        # tool_cleaned floor so this is correctly classified as natural-drafted.
        text = (
            "The committee considered the proposed amendment with great care .. "
            "Several members expressed reservations about the long-term implications,, "
            "After a long debate the chair called the question and the motion was carried by acclamation. "
            "Several questions arose about the budget for the upcoming fiscal year .. "
            "Opinions were varied;; some supported the increase while others did not. "
            "The chair noted that the matter would require further discussion next week. "
            "Members thanked the secretary for her clear minutes and accurate notes . "
            "A motion was made to adjourn,, and the meeting ended at five o'clock!! "
            "Tea was served in the foyer , and the conversation continued for some time. "
            "The committee considered several alternatives before settling on the proposal. "
            "A small subcommittee was formed to draft the final language of the resolution.. "
            "The vice-chair offered to circulate a revised version before the next meeting!! "
        ) * 2
        out = r.resolve_composition_mode(text)
        assert out["mode"] in ("natural_drafted", "structured"), \
            f"Expected natural_drafted/structured, got {out}"

    def test_paste_event_marks_software_mediated(self):
        # Synthetic keystroke data with one paste revision.
        keystroke = {
            "keystrokes": [{"key": "a", "timestamp": 0, "elapsed": 0}] * 50,
            "pauses": [],
            "revisions": [{"type": "paste", "charsAffected": 200}],
            "deletionRate": 0.05,
            "wordCount": 100,
        }
        out = r.resolve_composition_mode(_blog_post_text(), keystroke_data=keystroke)
        assert out["software_mediated"] is True
        assert out["mode"] == "tool_cleaned"

    def test_structured_uniform_sentence_length(self):
        # Five sentences of identical length → low variance.
        text = "One two three four five. Six seven eight nine ten. " \
               "Eleven twelve thirteen fourteen fifteen. " \
               "Sixteen seventeen eighteen nineteen twenty. " \
               "Alpha beta gamma delta epsilon."
        out = r.resolve_composition_mode(text)
        assert out["mode"] in ("structured", "natural_drafted")


# ══════════════════════════════════════════════════════════════════════════════
# Orchestrator — parallel + graceful degradation
# ══════════════════════════════════════════════════════════════════════════════

class TestRunResolvers:
    def test_parallel_no_exceptions(self):
        out = r.run_resolvers(
            text=_academic_exegesis_text(),
            baseline_texts=_build_baseline_corpus(),
        )
        # All six resolvers ran successfully — no _errors key.
        for key in ("language", "genre", "topic", "length", "citations", "composition_mode"):
            assert key in out, f"missing {key} in run_resolvers output: {out}"
        assert "_errors" not in out

    def test_resolver_failure_isolated(self, monkeypatch):
        # Force `resolve_genre` to raise — the orchestrator must keep the
        # other 5 resolvers and surface the failure under `_errors`.
        def boom(*a, **kw):
            raise ValueError("genre exploded")

        monkeypatch.setattr(r, "resolve_genre", boom)

        out = r.run_resolvers(
            text=_blog_post_text(),
            baseline_texts=_build_baseline_corpus(),
        )

        assert "genre" not in out
        assert "_errors" in out
        assert any(e["resolver"] == "genre" for e in out["_errors"])
        # Other 5 resolvers ran successfully.
        for key in ("language", "topic", "length", "citations", "composition_mode"):
            assert key in out
