"""
Regression test: run_calibration() must honor ScoringConfig env flags.

WS-7 step 1 (2026-07-07, original/quantum/scoring.py) moved every env-var
read out of score() and into ScoringConfig, requiring callers to build one
explicitly via ScoringConfig.from_env() and pass it in — a bare score(...)
call silently reproduces byte-identical flags-off Phase 1 behaviour no
matter what's in os.environ. validation/calibration.py::run_calibration()
was never updated for this and calls score() with no scoring_config,
so every calibration run (measure_lift_seminary.py, the admin calibration
endpoint, validation/lab/*) has been silently flags-off since that refactor.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from validation.calibration import run_calibration

_ROOT = Path(__file__).resolve().parent.parent
_SRC_CORPUS = _ROOT / "validation" / "corpus"
_SRC_MANIFEST = _ROOT / "validation" / "manifest.json"


@pytest.fixture
def small_corpus(tmp_path, monkeypatch):
    """A 3-baseline-plus-1-scored slice of the real seminary corpus, so the
    test runs in well under a second instead of scoring all 717 essays."""
    manifest = json.loads(_SRC_MANIFEST.read_text())
    by_author: dict[str, list] = {}
    for e in manifest["entries"]:
        by_author.setdefault(e["author_id"], []).append(e)

    author_id = next(
        aid for aid, es in by_author.items()
        if sum(1 for e in es if e["is_baseline"]) >= 3
        and any(not e["is_baseline"] for e in es)
    )
    entries = by_author[author_id]
    baselines = [e for e in entries if e["is_baseline"]][:3]
    scored = [e for e in entries if not e["is_baseline"]][:1]
    kept = baselines + scored

    dst_corpus = tmp_path / "corpus"
    dst_corpus.mkdir()
    for e in kept:
        src = _SRC_CORPUS / e["filename"]
        dst = dst_corpus / e["filename"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)

    dst_manifest = tmp_path / "manifest.json"
    dst_manifest.write_text(json.dumps({**manifest, "entries": kept}))
    return dst_corpus, dst_manifest


def test_length_adaptive_weights_flag_changes_calibration_scores(
    small_corpus, monkeypatch
):
    corpus_dir, manifest_path = small_corpus

    monkeypatch.delenv("LENGTH_ADAPTIVE_WEIGHTS", raising=False)
    off_report = run_calibration(corpus_dir=str(corpus_dir), manifest_path=str(manifest_path))

    monkeypatch.setenv("LENGTH_ADAPTIVE_WEIGHTS", "1")
    on_report = run_calibration(corpus_dir=str(corpus_dir), manifest_path=str(manifest_path))

    off_scores = [r.deviation_score for r in off_report.results]
    on_scores = [r.deviation_score for r in on_report.results]
    assert off_scores, "fixture must produce at least one scored result"
    assert off_scores != on_scores, (
        "toggling LENGTH_ADAPTIVE_WEIGHTS must change run_calibration()'s "
        "deviation scores — if this fails, score() is not receiving a "
        "ScoringConfig built from the current environment"
    )
