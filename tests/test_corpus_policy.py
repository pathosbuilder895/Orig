"""
tests/test_corpus_policy.py — corpus floors are policy, enforced at load
time. Short texts are verification-only, never attribution candidates; an
attribution candidate needs >= 3 baseline docs (the TOC-chunk failure made
2 of 9 public-author profiles out of 6-17-word stubs — this makes that
class of corpus impossible to load silently).
"""
from __future__ import annotations

from validation.corpus_policy import (
    PolicyViolation,
    check_attribution_pool,
    check_genre_balance,
    check_verification_pool,
    conformal_informative_authors,
)
from validation.manifest_schema import (
    AuthorshipLabel,
    CorpusEntry,
    Provenance,
)


class TestVerificationPool:
    def test_clean_pool_passes(self):
        assert check_verification_pool({"d1": 400, "d2": 300}) == []

    def test_short_documents_flagged(self):
        violations = check_verification_pool({"d1": 400, "toc_stub": 17})
        assert len(violations) == 1
        v = violations[0]
        assert v.kind == "short_document" and v.subject == "toc_stub"


class TestAttributionPool:
    def test_floor_matches_the_corpus_chunker(self):
        # Floors are equal today by measured decision (2026-07-31): a stricter
        # attribution floor drops kempis, whose baseline chunks are 393-499
        # words. The constants stay separate so this can diverge later.
        assert check_attribution_pool({"d": 300}, {"a": 3}) == []
        kinds = [v.kind for v in check_attribution_pool({"d": 299}, {"a": 3})]
        assert kinds == ["short_document"]

    def test_floor_is_caller_controlled(self):
        # A caller can still demand a stricter floor than the default.
        violations = check_attribution_pool({"d": 400}, {"a": 3}, min_words=500)
        assert [v.kind for v in violations] == ["short_document"]

    def test_thin_baseline_flagged(self):
        violations = check_attribution_pool({"d": 900}, {"kempis": 2, "mill": 5})
        assert [(v.kind, v.subject) for v in violations] == [("thin_baseline", "kempis")]


class TestConformalInformative:
    def test_pilot_scale_counts_are_uninformative(self):
        result = conformal_informative_authors({"s1": 12, "s2": 40}, band_threshold=0.03)
        assert result == {"s1": False, "s2": True}


class TestGenreBalance:
    def test_the_actual_derivation_corpus_skew_is_flagged(self):
        # "21 parts Plato to 2 parts student-like prose" (Instrument Report)
        violations = check_genre_balance({"philosophy": 21000, "student_essay": 2000})
        assert len(violations) == 1
        v = violations[0]
        assert v.kind == "genre_dominance" and v.subject == "philosophy"
        assert "91" in v.detail  # 21000/23000 = 91.3%

    def test_balanced_corpus_passes(self):
        assert check_genre_balance(
            {"philosophy": 4000, "sermon": 3500, "student_essay": 3000}
        ) == []

    def test_threshold_is_caller_controlled(self):
        counts = {"philosophy": 7000, "student_essay": 3000}  # 70%
        assert check_genre_balance(counts, max_share=0.75) == []
        assert len(check_genre_balance(counts, max_share=0.6)) == 1

    def test_empty_corpus_is_not_a_violation(self):
        assert check_genre_balance({}) == []


class TestManifestV2:
    def _entry(self, **over):
        kwargs = dict(
            filename="x.txt", author_id="a", label=AuthorshipLabel.AUTHENTIC,
            prompt="p", word_count=500,
        )
        kwargs.update(over)
        return CorpusEntry(**kwargs)

    def test_v1_manifests_still_load(self):
        e = self._entry()
        assert e.genre is None and e.provenance is None

    def test_effective_provenance_defaults_by_label(self):
        assert self._entry().effective_provenance is Provenance.REAL_HISTORICAL
        assert (
            self._entry(label=AuthorshipLabel.AI_GENERATED).effective_provenance
            is Provenance.SYNTHETIC_AI
        )
        assert (
            self._entry(label=AuthorshipLabel.PARAPHRASED).effective_provenance
            is Provenance.SYNTHETIC_AI
        )
        assert (
            self._entry(label=AuthorshipLabel.GHOSTWRITTEN).effective_provenance
            is Provenance.REAL_HISTORICAL
        )

    def test_explicit_provenance_wins(self):
        e = self._entry(provenance=Provenance.STUDENT_PILOT)
        assert e.effective_provenance is Provenance.STUDENT_PILOT
