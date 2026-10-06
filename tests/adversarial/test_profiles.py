"""
tests/adversarial/test_profiles.py — victim-profile construction (Task 13).

Covers `validation.adversarial.profiles.build_victim_profiles`, the first
piece of SP1's offline red-team harness
(docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md).

The corpus split it draws on:
  - validation/public_authors/manifest.json — 11 authors, is_baseline
    True/False is the primary holdout signal.
  - validation/public_authors/cross_work_manifest.json — a stricter
    holdout for 6 authors (dickens, chesterton, christie, emerson, mill,
    thoreau), where baseline/probe partitions never share a literary work.
    Only dickens and christie lack any entry in the plain manifest; the
    other 4 appear in both, and this module prefers the cross-work split
    for them (a real different-work holdout beats a same-work fallback).
"""

from __future__ import annotations

from pathlib import Path

from validation.adversarial.profiles import VictimProfile, build_victim_profiles

_PUBLIC_AUTHORS_DIR = Path("validation/public_authors")
_CORPUS_DIR = _PUBLIC_AUTHORS_DIR / "corpus"
_CROSS_WORK_CORPUS_DIR = _PUBLIC_AUTHORS_DIR / "cross_work_corpus"

_SEED = 20260921


def test_returns_at_least_eight_victims_at_n3():
    profiles = build_victim_profiles(n_baselines=3, seed=_SEED)
    assert len(profiles) >= 8
    for p in profiles:
        assert len(p.baselines) == 3
        assert len(p.genuine_holdout) >= 1
        assert len(p.impostor_docs) >= 1


def test_deterministic_across_calls():
    a = build_victim_profiles(n_baselines=3, seed=_SEED)
    b = build_victim_profiles(n_baselines=3, seed=_SEED)
    assert [p.victim_id for p in a] == [p.victim_id for p in b]
    assert [p.baselines for p in a] == [p.baselines for p in b]
    assert [p.genuine_holdout for p in a] == [p.genuine_holdout for p in b]
    assert [p.impostor_docs for p in a] == [p.impostor_docs for p in b]


def test_victim_ids_are_unique():
    profiles = build_victim_profiles(n_baselines=3, seed=_SEED)
    ids = [p.victim_id for p in profiles]
    assert len(ids) == len(set(ids))


def test_victim_profile_is_frozen_dataclass_with_four_fields():
    profiles = build_victim_profiles(n_baselines=3, seed=_SEED)
    p = profiles[0]
    assert isinstance(p, VictimProfile)
    assert {f for f in p.__dataclass_fields__} == {
        "victim_id",
        "baselines",
        "genuine_holdout",
        "impostor_docs",
    }
    # frozen: mutation raises
    try:
        p.victim_id = "someone_else"
    except Exception:
        pass
    else:
        raise AssertionError("VictimProfile must be frozen (immutable)")


def test_all_text_fields_are_real_prose_not_filenames():
    profiles = build_victim_profiles(n_baselines=3, seed=_SEED)
    for p in profiles:
        for text in p.baselines + p.genuine_holdout + p.impostor_docs:
            assert isinstance(text, str)
            # A filename would never contain whitespace-separated prose this long.
            assert len(text) > 200
            assert " " in text.strip()
            assert not text.strip().endswith(".txt")


def test_cross_work_author_holdout_is_genuinely_different_work():
    """thoreau is in both manifests; this module must prefer the
    cross-work split (a probe-role, different-work document) over the
    plain manifest's same-work-family is_baseline=false fallback."""
    profiles = {p.victim_id: p for p in build_victim_profiles(n_baselines=3, seed=_SEED)}
    assert "thoreau" in profiles
    thoreau = profiles["thoreau"]

    cross_work_probe_texts = {
        f.read_text(encoding="utf-8") for f in (_CROSS_WORK_CORPUS_DIR / "thoreau").glob("*.txt")
    }
    plain_manifest_scored_texts = {
        f.read_text(encoding="utf-8") for f in (_CORPUS_DIR / "thoreau").glob("*.txt")
    }

    # Every holdout doc must be drawn from the cross-work probe pool...
    for holdout_text in thoreau.genuine_holdout:
        assert holdout_text in cross_work_probe_texts
    # ...and none should be the plain-manifest fallback text (which would
    # mean the stricter, genuinely-different-work split was skipped).
    for holdout_text in thoreau.genuine_holdout:
        assert holdout_text not in plain_manifest_scored_texts


def test_fallback_only_author_uses_plain_manifest_holdout():
    """augustine has no cross_work_manifest entry at all, so this module
    must fall back to the plain manifest's is_baseline=false documents."""
    profiles = {p.victim_id: p for p in build_victim_profiles(n_baselines=3, seed=_SEED)}
    assert "augustine" in profiles
    augustine = profiles["augustine"]

    plain_manifest_scored_texts = {
        f.read_text(encoding="utf-8") for f in (_CORPUS_DIR / "augustine").glob("*.txt")
    }
    assert not (_CROSS_WORK_CORPUS_DIR / "augustine").exists()

    for holdout_text in augustine.genuine_holdout:
        assert holdout_text in plain_manifest_scored_texts


def test_impostor_docs_are_not_the_victims_own_text():
    profiles = build_victim_profiles(n_baselines=3, seed=_SEED)
    for p in profiles:
        own_texts = set(p.baselines) | set(p.genuine_holdout)
        for impostor_text in p.impostor_docs:
            assert impostor_text not in own_texts


def test_dickens_and_christie_are_cross_work_only_victims():
    """dickens/christie have no plain-manifest entry — confirm the loader
    still admits them as victims purely from the cross-work corpus."""
    profiles = {p.victim_id: p for p in build_victim_profiles(n_baselines=3, seed=_SEED)}
    assert "dickens" in profiles
    assert "christie" in profiles
    for victim_id in ("dickens", "christie"):
        assert not (_CORPUS_DIR / victim_id).exists()
        assert len(profiles[victim_id].baselines) == 3
        assert len(profiles[victim_id].genuine_holdout) >= 1


def test_insufficient_baseline_authors_are_skipped_not_crashed_at_high_n():
    # Plain-manifest-only authors (e.g. augustine, boethius) have only 3-4
    # is_baseline=true documents, so at n_baselines=10 they cannot produce
    # a full profile and must be excluded rather than raise or under-fill.
    profiles = build_victim_profiles(n_baselines=10, seed=_SEED)
    for p in profiles:
        assert len(p.baselines) == 10
    ids = {p.victim_id for p in profiles}
    assert "augustine" not in ids
