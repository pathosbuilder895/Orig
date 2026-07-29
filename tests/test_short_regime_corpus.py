# tests/test_short_regime_corpus.py
from pathlib import Path

import pytest

from validation.short_regime.corpus import attack_probes, build_pools, build_trials

CORPUS = Path(__file__).resolve().parent.parent / "validation" / "corpus"
pytestmark = pytest.mark.skipif(not CORPUS.exists(), reason="validation corpus absent")


def test_pools_have_expected_authors_and_chunk_sizes():
    pools = build_pools(CORPUS, words=500)
    for author in ["seminary_01", "seminary_05", "burke", "douglass", "lincoln", "paine"]:
        assert author in pools, author
        assert all(len(c.split()) == 500 for c in pools[author])
    assert len(pools["burke"]) > 50          # 173 docs -> plenty of chunks
    assert len(pools["seminary_01"]) >= 4    # 5 essays -> at least 3 baseline + 1 honest


def test_trials_disjoint_and_deterministic():
    pools = build_pools(CORPUS, words=500)
    t1 = build_trials(pools, n_baseline=3, max_honest=30, seed=7)
    t2 = build_trials(pools, n_baseline=3, max_honest=30, seed=7)
    assert [t.student_id for t in t1] == [t.student_id for t in t2]
    for tr in t1:
        assert len(tr.baseline) == 3
        assert 1 <= len(tr.honest) <= 30
        assert set(tr.baseline).isdisjoint(set(tr.honest))
        assert t2[[x.student_id for x in t2].index(tr.student_id)].baseline == tr.baseline


def test_attack_probes_labeled():
    atk = attack_probes(CORPUS, words=500)
    assert set(atk) == {"ai", "ghost"}
    assert len(atk["ai"]) >= 10
    assert all(len(c.split()) == 500 for v in atk.values() for c in v)
