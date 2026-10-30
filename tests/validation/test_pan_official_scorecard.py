import json

import numpy as np
import pytest

from validation.verify.pan_luar_expert import (
    EmbeddingCache,
    fit_lda_metric,
    fit_plda,
    score_partition,
    signal_matrix,
)
from validation.verify.pan_official_scorecard import (
    LuarFusion,
    OfficialPair,
    anchored_deviation_score,
    embed_episodes,
    exclusions,
    load_official_pairs,
    markdown_tables,
    pair_episodes,
    pair_luar_signals,
    public_author_id,
    sample_order,
    split_known,
    summarize,
)
from validation.verify.pan_style_expert import (
    StyleAuthor,
    _fit_representations,
    _score_partition,
    style_margin_only_signals,
)

WORDS = (
    "the a of and to in that it was he she they we you not but with for on at as "
    "said went came looked thought quiet river house night morning door window light "
    "never always again still only just even then there here very much"
).split()


def _text(rng, n=120):
    return " ".join(rng.choice(WORDS, size=n)) + "."


def test_split_known_is_contiguous_and_near_equal():
    text = " ".join(f"w{i}" for i in range(10))
    parts = split_known(text)
    assert [len(part.split()) for part in parts] == [3, 3, 4]
    assert " ".join(parts) == text
    with pytest.raises(ValueError):
        split_known("only two")


def test_anchored_deviation_score_moves_only_the_decision_point():
    assert anchored_deviation_score(0.0) == 1.0
    assert anchored_deviation_score(0.40) == 0.5
    assert anchored_deviation_score(1.0) == 0.0
    grid = np.linspace(0, 1, 101)
    mapped = [anchored_deviation_score(value) for value in grid]
    assert all(a > b for a, b in zip(mapped, mapped[1:]))
    assert anchored_deviation_score(0.39) > 0.5 > anchored_deviation_score(0.41)


def _write_pan(tmp_path, rows):
    root = tmp_path / "pan" / "pan21-authorship-verification-test"
    root.mkdir(parents=True)
    with (root / "pan21-authorship-verification-test.jsonl").open("w") as pairs, (
        root / "pan21-authorship-verification-test-truth.jsonl"
    ).open("w") as truth:
        for pair_id, authors, texts in rows:
            pairs.write(json.dumps({"id": pair_id, "fandoms": ["x", "y"], "pair": texts}) + "\n")
            truth.write(
                json.dumps({"id": pair_id, "same": authors[0] == authors[1], "authors": authors}) + "\n"
            )
    return tmp_path / "pan"


def test_load_official_pairs_windows_texts_and_reads_labels(tmp_path):
    long_text = " ".join(f"w{i}" for i in range(3000))
    cache = _write_pan(
        tmp_path,
        [("p1", ["a", "a"], [long_text, "short unknown"]), ("p2", ["a", "b"], ["k", "u"])],
    )
    pairs = load_official_pairs(cache)
    assert [pair.label for pair in pairs] == [1, 0]
    assert len(pairs[0].known.split()) == 2500
    assert pairs[0].unknown == "short unknown"
    assert len(load_official_pairs(cache, limit=1)) == 1


def _partition(raw_ids, rng, *, probes=1):
    return [
        StyleAuthor(
            author_id=public_author_id(raw),
            baseline_fandom="b",
            probe_fandom="p",
            baselines=tuple(_text(rng) for _ in range(3)),
            probes=tuple(_text(rng) for _ in range(probes)),
        )
        for raw in raw_ids
    ]


def test_exclusions_drop_fitting_authors_and_report_the_rest():
    rng = np.random.default_rng(1)
    groups = {"development": ["d1"], "calibration": ["c1"], "lock_100": ["l1"]}
    partitions = {"development": _partition(["d1"], rng), "calibration": _partition(["c1"], rng)}
    pairs = [
        OfficialPair("keep", 1, ("x", "x"), "k1", "u1"),
        OfficialPair("dev", 0, ("d1", "x"), "k2", "u2"),
        OfficialPair("both", 0, ("d1", "c1"), "k3", "u3"),
        OfficialPair("viewed", 0, ("l1", "x"), "k4", "u4"),
    ]
    kept, report = exclusions("pan20", pairs, groups, partitions)
    assert [pair.pair_id for pair in kept] == ["keep", "viewed"]
    assert report["excluded_by_split"] == {"development": 1, "calibration+development": 1}
    assert report["kept_pairs_touching_evaluation_only_authors"] == {"lock_100": 1}
    leaking = [OfficialPair("leak", 1, ("x", "x"), partitions["calibration"][0].baselines[0], "u")]
    with pytest.raises(RuntimeError, match="reuse a fitting-split text"):
        exclusions("pan20", leaking, groups, partitions)
    with pytest.raises(RuntimeError, match="do not map"):
        exclusions("pan20", pairs, {**groups, "development": ["other"]}, partitions)


def test_embed_episodes_embeds_only_missing_and_groups_by_length(tmp_path):
    cache = EmbeddingCache(tmp_path / "cache.npz")
    calls = []

    def embedder(batch):
        calls.append([len(episode) for episode in batch])
        return np.ones((len(batch), 512), dtype=np.float32)

    pairs = [OfficialPair("p", 1, ("a", "a"), "one two three four five six", "seven")]
    episodes = pair_episodes(pairs)
    assert episodes[0] == ("one two", "three four", "five six")
    assert embed_episodes(episodes, cache=cache, embedder=embedder, documents_per_batch=3) == 5
    assert calls == [[1, 1, 1], [1], [3]]
    assert embed_episodes(episodes, cache=EmbeddingCache(tmp_path / "cache.npz"), embedder=embedder) == 0


def test_pair_signals_match_the_committed_partition_pipeline():
    rng = np.random.default_rng(7)
    authors = _partition([f"r{i}" for i in range(6)], rng)
    n = len(authors)
    embeddings = {
        "baseline": rng.normal(size=(n, 512)).astype(np.float32),
        "baseline_documents": rng.normal(size=(n, 3, 512)).astype(np.float32),
        "probes": rng.normal(size=(n, 1, 512)).astype(np.float32),
    }
    plda, lda = fit_plda(embeddings), fit_lda_metric(embeddings)
    vectorizer, scaler = _fit_representations(authors)
    exhaustive = score_partition(authors, embeddings, plda, lda)
    matrix = np.column_stack(
        (signal_matrix(exhaustive), style_margin_only_signals(_score_partition(authors, vectorizer, scaler)))
    )
    fusion = LuarFusion(plda, lda, vectorizer, scaler, calibrator=None)
    for target, source in ((0, 0), (2, 4), (5, 1)):
        index = next(
            i
            for i, trial in enumerate(exhaustive)
            if trial.target_author == authors[target].author_id
            and trial.source_author == authors[source].author_id
        )
        others = [i for i in range(n) if i != target]
        row = pair_luar_signals(
            fusion,
            claimed_episode=embeddings["baseline"][[target]],
            claimed_documents=embeddings["baseline_documents"][[target]],
            probes=embeddings["probes"][[source], 0],
            claimed_texts=[authors[target].baselines],
            probe_texts=[authors[source].probes[0]],
            reference_episode=embeddings["baseline"][others],
            reference_documents=embeddings["baseline_documents"][others],
            reference_texts=[authors[i].baselines for i in others],
        )
        np.testing.assert_allclose(row[0], matrix[index], rtol=1e-7, atol=1e-9)


def test_sample_order_is_deterministic_and_independent_of_file_order():
    pairs = [OfficialPair(f"id-{i}", i % 2, ("a", "b"), "k", "u") for i in range(20)]
    forward = [pair.pair_id for pair in sample_order(pairs)]
    assert forward == [pair.pair_id for pair in sample_order(list(reversed(pairs)))]
    assert sorted(forward) == sorted(pair.pair_id for pair in pairs)
    assert forward != [pair.pair_id for pair in pairs]


def test_markdown_tables_render_every_row_and_the_published_target():
    row = summarize([1, 0, 1, 0], [0.9, 0.2, 0.5, 0.4])
    result = {
        "published_targets": {
            "pan20": {"system": "winner", "auc": 0.969, "c@1": 0.928, "overall": 0.935, "overall_measures": 4}
        },
        "datasets": {
            "pan20": {"protocols": {"pair_split3": {"models": {"fused_score_v1": row}}}}
        },
    }
    table = markdown_tables(result)
    assert "**pan20 / pair_split3**" in table
    assert "| fused_score_v1 (committed artifact) | 4 | 1 | 1.000 |" in table
    assert table.rstrip().endswith("| 0.969 | 0.928 |  |  |  |  | 0.935 | |")


def test_summarize_reports_unanswered_and_skips_intervals_when_all_abstain():
    row = summarize([1, 0, 1, 0], [0.5] * 4)
    assert row["n_unanswered"] == 4
    assert row["ci95_trial_bootstrap"] is None
    assert row["metrics"]["overall"] == 0.25
    answered = summarize([1, 0, 1, 0, 1, 0], [0.9, 0.2, 0.8, 0.4, 0.6, 0.3])
    assert answered["metrics"]["auc"] == 1.0
    assert answered["ci95_trial_bootstrap"]["auc"] == [1.0, 1.0]
