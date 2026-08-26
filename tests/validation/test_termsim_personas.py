from validation.termsim.personas import build_manifest, chunk_text


def test_chunking_respects_submission_floors():
    text = "\n\n".join((f"Paragraph {i}. " + "word " * 180) for i in range(8))
    chunks = chunk_text(text)
    assert chunks
    assert all(300 <= len(chunk.split()) <= 1500 for chunk in chunks)


def test_manifest_is_deterministic_and_sufficiently_deep():
    first = build_manifest()
    second = build_manifest()
    assert first == second
    counts = sorted(persona["n_docs"] for persona in first["personas"])
    assert len(counts) >= 25
    assert counts[len(counts) // 2] >= 15
