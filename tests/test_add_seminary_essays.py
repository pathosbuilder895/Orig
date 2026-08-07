"""
tests/test_add_seminary_essays.py — the authentic-essay ingestion CLI.

Mirrors tests/test_add_ai_essays.py. Runs against tmp copies of the
manifest + corpus so the real validation corpus is never touched.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "add_seminary_essays", _ROOT / "scripts" / "add_seminary_essays.py"
)
add_seminary_essays = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(add_seminary_essays)

_ESSAY_TEXT = (
    "The doctrine of sanctification concerns the believer's growth in holiness, "
    "a theme every tradition treats with pastoral care. " * 20
)  # well over the 300-word verification floor


@pytest.fixture()
def tmp_corpus(tmp_path):
    """Miniature manifest + corpus with one existing seminary_05 entry."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "seminary_05_sin.txt").write_text("existing essay")
    manifest = {
        "version": "1.0",
        "created_at": "2026-01-01T00:00:00",
        "description": "test manifest",
        "authors": {},
        "entries": [
            {
                "filename": "seminary_05_sin.txt",
                "author_id": "seminary_05",
                "label": "authentic",
                "prompt": "The doctrine of original sin",
                "word_count": 400,
                "is_baseline": False,
                "ai_provider": "none",
                "theological_tradition": "Baptist",
                "native_english": False,
                "notes": "existing synthetic essay",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    essays = tmp_path / "new_essays"
    essays.mkdir()
    (essays / "b_second.txt").write_text(_ESSAY_TEXT)
    (essays / "a_first.txt").write_text(_ESSAY_TEXT)
    return {"corpus": corpus, "manifest": manifest_path, "essays": essays}


def _run(tmp_corpus, *extra):
    return add_seminary_essays.main(
        [
            str(tmp_corpus["essays"]),
            "--author-name",
            "Charles Haddon Spurgeon",
            "--title",
            "Around the Wicket Gate",
            "--source-note",
            "Project Gutenberg #60669",
            "--manifest",
            str(tmp_corpus["manifest"]),
            "--corpus-dir",
            str(tmp_corpus["corpus"]),
            *extra,
        ]
    )


def test_ingest_auto_assigns_next_seminary_id_and_round_trips(tmp_corpus):
    assert _run(tmp_corpus) == 0

    manifest = json.loads(tmp_corpus["manifest"].read_text())
    names = [e["filename"] for e in manifest["entries"]]
    # existing seminary_05 is untouched; new identity is seminary_06
    assert names == ["seminary_05_sin.txt", "seminary_06_001.txt", "seminary_06_002.txt"]
    new = manifest["entries"][1]
    assert new["author_id"] == "seminary_06"
    assert new["label"] == "authentic"
    assert new["provenance"] == "real_historical"
    assert new["word_count"] > 300
    assert "Spurgeon" in new["notes"]
    assert (tmp_corpus["corpus"] / "seminary_06_001.txt").exists()
    assert (tmp_corpus["corpus"] / "seminary_06_002.txt").exists()

    # The whole manifest still validates through the schema.
    from validation.manifest_schema import CorpusEntry

    for e in manifest["entries"]:
        CorpusEntry(**e)


def test_explicit_author_id_pools_across_runs(tmp_corpus):
    assert _run(tmp_corpus, "--author-id", "seminary_10") == 0
    manifest = json.loads(tmp_corpus["manifest"].read_text())
    names = {e["filename"] for e in manifest["entries"]}
    assert {"seminary_10_001.txt", "seminary_10_002.txt"} <= names

    # A second call with a different work, same author-id, continues numbering
    # rather than colliding — this is how multiple works by one real author
    # get pooled under a single identity.
    more_dir = tmp_corpus["essays"].parent / "more_essays"
    more_dir.mkdir()
    (more_dir / "c_third.txt").write_text(_ESSAY_TEXT)
    rc = add_seminary_essays.main(
        [
            str(more_dir),
            "--author-name",
            "Charles Haddon Spurgeon",
            "--author-id",
            "seminary_10",
            "--title",
            "Talks to Farmers",
            "--source-note",
            "Project Gutenberg #42518",
            "--manifest",
            str(tmp_corpus["manifest"]),
            "--corpus-dir",
            str(tmp_corpus["corpus"]),
        ]
    )
    assert rc == 0
    manifest = json.loads(tmp_corpus["manifest"].read_text())
    names = [e["filename"] for e in manifest["entries"]]
    assert names.count("seminary_10_003.txt") == 1
    assert (tmp_corpus["corpus"] / "seminary_10_003.txt").exists()


def test_rejects_author_id_not_matching_seminary_pattern(tmp_corpus):
    assert _run(tmp_corpus, "--author-id", "spurgeon") == 1
    manifest = json.loads(tmp_corpus["manifest"].read_text())
    assert len(manifest["entries"]) == 1  # nothing written


def test_dry_run_writes_nothing(tmp_corpus):
    before = tmp_corpus["manifest"].read_text()
    assert _run(tmp_corpus, "--dry-run") == 0
    assert tmp_corpus["manifest"].read_text() == before
    assert not (tmp_corpus["corpus"] / "seminary_06_001.txt").exists()


def test_empty_file_fails(tmp_corpus):
    (tmp_corpus["essays"] / "c_empty.txt").write_text("   ")
    assert _run(tmp_corpus) == 1


def test_tradition_and_native_english_recorded(tmp_corpus):
    assert (
        _run(
            tmp_corpus,
            "--tradition",
            "Reformed Baptist",
            "--native-english",
        )
        == 0
    )
    manifest = json.loads(tmp_corpus["manifest"].read_text())
    new = manifest["entries"][1]
    assert new["theological_tradition"] == "Reformed Baptist"
    assert new["native_english"] is True
