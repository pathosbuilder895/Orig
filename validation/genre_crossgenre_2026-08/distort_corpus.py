"""POSNoise-distort the cleaned crossgenre corpus, between clean_corpus.py and
extract_vectors.py. Research script only -- not part of the Original codebase.

Pipeline position::

    clean_corpus.py  ->  chunks.json
    distort_corpus.py -> chunks_distorted.json      (this file)
    extract_vectors.py / sweep_harness.py           (UNMODIFIED)

Each chunk's ``text`` is replaced by its POSNoise mask (function words and
punctuation literal, content words replaced by their universal POS tag) via
``validation.verify.distortion_signals.mask_text``; every other field --
author, work, genre, chunk_id -- is carried through unchanged so the
downstream harness partitions identically. ``word_count`` is recomputed from
the masked text and the original is preserved as ``raw_word_count``.

Because ``extract_vectors.py`` hardcodes its input as ``chunks.json``, running
the *unmodified* downstream harness on distorted vectors is done by swapping
the file rather than by editing the harness::

    python validation/genre_crossgenre_2026-08/distort_corpus.py            # write chunks_distorted.json
    python validation/genre_crossgenre_2026-08/distort_corpus.py --activate # back up + swap it in
    python validation/genre_crossgenre_2026-08/extract_vectors.py           # unmodified
    python validation/genre_crossgenre_2026-08/sweep_harness.py             # unmodified
    python validation/genre_crossgenre_2026-08/distort_corpus.py --restore  # put the raw corpus back

``--activate`` copies the untouched corpus to ``chunks_raw.json`` first and
refuses to overwrite an existing backup, so the raw corpus cannot be lost by
running it twice. ``extract_vectors.py`` writes its own vector cache; delete
that cache between the raw and distorted runs or the second run will read the
first run's vectors.

!!! UNEXERCISED ON THE REAL CORPUS !!!
--------------------------------------
This script has NEVER been run against the Lewis/Chesterton corpus, because
that corpus is not committed (copyright) and
``validation/genre_crossgenre_2026-08/raw/`` is absent from this checkout.
Its masking call is covered by ``tests/test_distortion_signals.py`` and its
record-rewriting logic by ``--smoke-test`` below, which runs the whole
transform over synthetic in-memory records. That is unit evidence, not
end-to-end evidence: the chunk-count, genre-balance and downstream
vector-extraction behaviour on real distorted prose are unverified. Anyone
holding the corpus should re-read this docstring before trusting a number
that came out the far end.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_ROOT = HERE.parent.parent
sys.path.insert(0, str(_ROOT))

CHUNKS = HERE / "chunks.json"
DISTORTED = HERE / "chunks_distorted.json"
RAW_BACKUP = HERE / "chunks_raw.json"


def distort_records(records: list[dict]) -> list[dict]:
    """Return ``records`` with every ``text`` POSNoise-masked.

    Records whose mask comes back empty (no taggable tokens at all) are
    dropped rather than emitted with an empty body -- an empty chunk would
    otherwise reach feature extraction and be scored as if it were prose.
    """
    from validation.verify.distortion_signals import mask_text

    out: list[dict] = []
    dropped = 0
    for record in records:
        masked = mask_text(record["text"])
        if not masked.strip():
            dropped += 1
            continue
        new = dict(record)
        new["text"] = masked
        new["raw_word_count"] = record.get("word_count", len(record["text"].split()))
        new["word_count"] = len(masked.split())
        new["distorted"] = True
        out.append(new)
    if dropped:
        print(f"dropped {dropped} chunk(s) that masked to nothing", file=sys.stderr)
    return out


def _smoke_test() -> int:
    """Run the transform over synthetic records -- no corpus required."""
    records = [
        {
            "author": "synthetic",
            "work": "Synthetic Work",
            "genre": "test",
            "chunk_id": "synthetic_000",
            "word_count": 12,
            "text": "If they actually censor anything is another question for the reader.",
        },
        {
            "author": "synthetic",
            "work": "Synthetic Work",
            "genre": "test",
            "chunk_id": "synthetic_001",
            "word_count": 0,
            "text": "   ",
        },
    ]
    out = distort_records(records)
    assert len(out) == 1, f"expected the empty chunk to be dropped, got {len(out)}"
    masked = out[0]["text"]
    assert "censor" not in masked, masked
    assert "question" not in masked, masked
    assert "if" in masked.lower(), masked
    assert "VERB" in masked, masked
    assert out[0]["author"] == "synthetic" and out[0]["genre"] == "test"
    assert out[0]["raw_word_count"] == 12
    assert out[0]["word_count"] == len(masked.split())
    assert out[0]["distorted"] is True
    print("smoke test OK:", masked)
    print("NOTE: synthetic only -- this script is unexercised on the real corpus.")
    return 0


def _activate() -> int:
    if not DISTORTED.exists():
        print(f"{DISTORTED} missing -- run without --activate first", file=sys.stderr)
        return 1
    if RAW_BACKUP.exists():
        print(
            f"{RAW_BACKUP} already exists -- refusing to overwrite the raw corpus "
            f"backup. Run --restore first.",
            file=sys.stderr,
        )
        return 1
    shutil.copy2(CHUNKS, RAW_BACKUP)
    shutil.copy2(DISTORTED, CHUNKS)
    print(f"backed up raw corpus to {RAW_BACKUP}; {CHUNKS} is now distorted")
    print("remember to clear extract_vectors.py's cache before re-extracting")
    return 0


def _restore() -> int:
    if not RAW_BACKUP.exists():
        print(f"{RAW_BACKUP} missing -- nothing to restore", file=sys.stderr)
        return 1
    shutil.copy2(RAW_BACKUP, CHUNKS)
    RAW_BACKUP.unlink()
    print(f"restored raw corpus to {CHUNKS}")
    return 0


def main() -> int:
    if "--smoke-test" in sys.argv:
        return _smoke_test()
    if "--activate" in sys.argv:
        return _activate()
    if "--restore" in sys.argv:
        return _restore()

    if not CHUNKS.exists():
        print(
            f"{CHUNKS} missing -- run clean_corpus.py first. The Lewis/Chesterton "
            f"corpus is not committed (copyright); populate raw/ locally.",
            file=sys.stderr,
        )
        return 1

    records = json.loads(CHUNKS.read_text(encoding="utf-8"))
    print(f"masking {len(records)} chunks (POSNoise, spaCy en_core_web_sm)...")
    distorted = distort_records(records)
    DISTORTED.write_text(json.dumps(distorted, indent=1), encoding="utf-8")

    raw_words = sum(r.get("raw_word_count", 0) for r in distorted)
    masked_words = sum(r["word_count"] for r in distorted)
    print(f"wrote {len(distorted)} distorted chunks to {DISTORTED}")
    print(f"words: {raw_words} raw -> {masked_words} masked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
