import json
from pathlib import Path

import pytest

from validation.verify.pan_corpus import _load_histories, build_corpus


def _fixture(tmp_path: Path, *, mismatch: bool = False) -> Path:
    cache = tmp_path / "cache"
    root = cache / "pan20-authorship-verification-test"
    root.mkdir(parents=True)
    pairs, truths = [], []
    for author_idx in range(3):
        author = f"author-{author_idx}"
        for fandom in ("alpha", "beta"):
            for doc_idx in range(3):
                pair_id = f"{author}-{fandom}-{doc_idx}"
                other = author if not mismatch or pair_id != "author-0-alpha-0" else "wrong"
                pairs.append(
                    {
                        "id": pair_id,
                        "fandoms": [fandom, fandom],
                        "pair": [f"{pair_id} left " * 100, f"{pair_id} right " * 100],
                    }
                )
                truths.append({"id": pair_id, "same": True, "authors": [author, other]})
    (root / "pan20-authorship-verification-test.jsonl").write_text(
        "\n".join(json.dumps(row) for row in pairs), encoding="utf-8"
    )
    (root / "pan20-authorship-verification-test-truth.jsonl").write_text(
        "\n".join(json.dumps(row) for row in truths), encoding="utf-8"
    )
    return cache


def test_builds_real_author_topic_disjoint_corpus(tmp_path):
    cache = _fixture(tmp_path)
    corpus = tmp_path / "corpus"
    manifest = tmp_path / "manifest.json"
    stats = build_corpus(
        cache_dir=cache,
        corpus_dir=corpus,
        manifest_path=manifest,
        author_count=2,
        min_text_chars=20,
    )
    data = json.loads(manifest.read_text())

    assert stats["authors_kept"] == 2
    assert stats["topic_disjoint_authors"] == 2
    assert stats["unique_text_sha256"] == 12
    assert stats["max_words_per_document"] == 2500
    assert len(data["entries"]) == 12
    assert all(row["word_count"] <= 2500 for row in data["entries"])
    for author, metadata in data["authors"].items():
        rows = [row for row in data["entries"] if row["author_id"] == author]
        assert {row["prompt"] for row in rows if row["is_baseline"]} == {metadata["baseline_fandom"]}
        assert {row["prompt"] for row in rows if not row["is_baseline"]} == {metadata["probe_fandom"]}
        assert metadata["baseline_fandom"] != metadata["probe_fandom"]


def test_rejects_truth_author_disagreement(tmp_path):
    cache = _fixture(tmp_path, mismatch=True)
    pairs = next(cache.glob("**/*test.jsonl"))
    truth = next(cache.glob("**/*truth.jsonl"))
    with pytest.raises(ValueError, match="label and author IDs disagree"):
        _load_histories(pairs, truth, min_text_chars=20)
