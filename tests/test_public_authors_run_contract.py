"""
tests/test_public_authors_run_contract.py — pins the producer half of the
n_scored_essays producer/consumer contract between
validation/public_authors/run.py's run() and G3's informativeness check
in validation/calibration_gate.py (evaluate_g3_attribution /
_g3_inputs_from_pa_report — see tests/test_calibration_gate.py's
TestG3InputsFromPaReport for the consumer half).

FIX 1: nothing in tests/ exercised run()'s summary shape end-to-end before
this file (`grep -rn n_scored_essays tests/` was zero hits). If
"n_scored_essays" is ever renamed or dropped from run.py (it is set in
exactly one place: `n_scored_essays = len(results)`), G3 silently reverts
to legacy two-valued pass/fail on real, already-measured numbers instead
of reporting "uninformative" — see test_calibration_gate.py for why that
matters on the real 0.7273/n=22 measurement.

This builds a small synthetic manifest + corpus in tmp_path and runs
validation.public_authors.run.run() end-to-end (real FastAPI TestClient,
real original.quantum.scoring.score() calls — nothing mocked) — NOT the
multi-minute real public_authors benchmark. Runtime is a handful of
scoring calls against a 2-author, tiny-document corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

from validation.public_authors.run import run as run_public_authors

# Above validation/corpus_policy.py's ATTRIBUTION_MIN_WORDS (300) so no
# document here is dropped as a short_document policy violation.
_WORDS_PER_DOC = 320
_VOCAB = (
    "the quick brown fox jumps over lazy dog while pondering philosophical "
    "questions about language and style in a manner reminiscent of classical "
    "prose authorship verification systems analyze such patterns carefully"
).split()


def _filler_text(seed: int, n_words: int = _WORDS_PER_DOC) -> str:
    words = []
    i = seed
    while len(words) < n_words:
        words.append(f"{_VOCAB[i % len(_VOCAB)]}{i % 7}")
        i += 1
    return " ".join(words)


def _write_synthetic_fixture(
    root: Path, *, n_authors: int, n_baseline_per_author: int, n_scored_per_author: int
) -> tuple[Path, Path]:
    """
    A minimal public_authors-shaped manifest + corpus: every author gets
    >= validation/corpus_policy.ATTRIBUTION_MIN_BASELINE_DOCS (3) baseline
    documents so nobody is excluded as thin_baseline, and every document
    clears ATTRIBUTION_MIN_WORDS (300) so nobody is excluded as
    short_document — the point of this fixture is to pin the
    n_scored_essays *count*, which only means what it says if every
    author stays eligible and every document stays in the pool.
    """
    corpus_dir = root / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    authors = [f"fix1_synthetic_author_{i}" for i in range(n_authors)]
    entries = []
    for ai, author in enumerate(authors):
        for i in range(n_baseline_per_author):
            fn = f"{author}_baseline_{i}.txt"
            text = _filler_text(ai * 1000 + i)
            (corpus_dir / fn).write_text(text)
            entries.append(
                {
                    "filename": fn,
                    "author_id": author,
                    "label": "authentic",
                    "prompt": "baseline",
                    "word_count": len(text.split()),
                    "is_baseline": True,
                }
            )
        for i in range(n_scored_per_author):
            fn = f"{author}_scored_{i}.txt"
            text = _filler_text(ai * 1000 + 500 + i)
            (corpus_dir / fn).write_text(text)
            entries.append(
                {
                    "filename": fn,
                    "author_id": author,
                    "label": "authentic",
                    "prompt": "scored",
                    "word_count": len(text.split()),
                    "is_baseline": False,
                }
            )
    manifest = {
        "version": "1.0",
        "created_at": "2026-07-31T00:00:00Z",
        "description": "synthetic fixture — tests/test_public_authors_run_contract.py",
        "authors": {a: {} for a in authors},
        "entries": entries,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path, corpus_dir


class TestNScoredEssaysProducerContract:
    def test_summary_n_scored_essays_matches_the_actual_scored_count(
        self, tmp_path, store_reset
    ):
        n_authors, n_baseline, n_scored = 2, 3, 2
        manifest_path, corpus_dir = _write_synthetic_fixture(
            tmp_path,
            n_authors=n_authors,
            n_baseline_per_author=n_baseline,
            n_scored_per_author=n_scored,
        )

        report = run_public_authors(
            manifest_path=manifest_path,
            corpus_dir=corpus_dir,
            report_dir=tmp_path / "out",
        )

        summary = report["summary"]
        # Guard the fixture itself: if any author got excluded, the
        # n_authors * n_scored expectation below would be checking the
        # wrong number for the wrong reason (thin_baseline/short_document
        # instead of the producer contract).
        assert summary["skipped_authors"] == []
        assert summary["n_eligible_authors"] == n_authors

        assert "n_scored_essays" in summary
        assert summary["n_scored_essays"] == n_authors * n_scored
