"""
tests/test_add_ai_essays.py — the multi-generator essay ingestion CLI.

Runs against tmp copies of the manifest + corpus so the real validation
corpus is never touched.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "add_ai_essays", _ROOT / "scripts" / "add_ai_essays.py")
add_ai_essays = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(add_ai_essays)

_ESSAY_TEXT = ("Grace is the unmerited favor of God toward humanity, "
               "a theme every tradition treats with care. " * 20)   # ~320 words


@pytest.fixture()
def tmp_corpus(tmp_path):
    """Miniature manifest + corpus with one existing ai_007.txt entry."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "ai_007.txt").write_text("existing essay")
    manifest = {
        "version": "1.0",
        "created_at": "2026-01-01T00:00:00",
        "description": "test manifest",
        "authors": [],
        "entries": [{
            "filename": "ai_007.txt", "author_id": "ai_author",
            "label": "ai_generated", "prompt": "Grace", "word_count": 400,
            "is_baseline": False, "ai_provider": "claude",
            "theological_tradition": None, "native_english": None,
            "notes": "existing",
        }],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    essays = tmp_path / "new_essays"
    essays.mkdir()
    (essays / "b_second.txt").write_text(_ESSAY_TEXT)
    (essays / "a_first.txt").write_text(_ESSAY_TEXT)
    return {"corpus": corpus, "manifest": manifest_path, "essays": essays}


def _run(tmp_corpus, *extra):
    return add_ai_essays.main([
        str(tmp_corpus["essays"]),
        "--provider", "chatgpt",
        "--manifest", str(tmp_corpus["manifest"]),
        "--corpus-dir", str(tmp_corpus["corpus"]),
        *extra,
    ])


def test_ingest_continues_numbering_and_round_trips(tmp_corpus):
    assert _run(tmp_corpus) == 0

    manifest = json.loads(tmp_corpus["manifest"].read_text())
    names = [e["filename"] for e in manifest["entries"]]
    # numbering continues after the existing ai_007; sorted source order
    assert names == ["ai_007.txt", "ai_008.txt", "ai_009.txt"]
    new = manifest["entries"][1]
    assert new["ai_provider"] == "chatgpt"
    assert new["label"] == "ai_generated"
    assert new["word_count"] > 150
    assert (tmp_corpus["corpus"] / "ai_008.txt").exists()
    assert (tmp_corpus["corpus"] / "ai_009.txt").exists()

    # The whole manifest still validates through the schema.
    from validation.manifest_schema import CorpusEntry
    for e in manifest["entries"]:
        CorpusEntry(**e)


def test_dry_run_writes_nothing(tmp_corpus):
    before = tmp_corpus["manifest"].read_text()
    assert _run(tmp_corpus, "--dry-run") == 0
    assert tmp_corpus["manifest"].read_text() == before
    assert not (tmp_corpus["corpus"] / "ai_008.txt").exists()


def test_empty_file_fails(tmp_corpus):
    (tmp_corpus["essays"] / "c_empty.txt").write_text("   ")
    assert _run(tmp_corpus) == 1


def test_prompt_map_applied(tmp_corpus):
    pm = tmp_corpus["essays"].parent / "prompts.json"
    pm.write_text(json.dumps({"a_first.txt": "The Doctrine of Justification"}))
    assert _run(tmp_corpus, "--prompt-map", str(pm)) == 0
    manifest = json.loads(tmp_corpus["manifest"].read_text())
    prompts = {e["filename"]: e["prompt"] for e in manifest["entries"]}
    assert prompts["ai_008.txt"] == "The Doctrine of Justification"
    assert prompts["ai_009.txt"] == "AI-generated theology essay"
