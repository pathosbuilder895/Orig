"""
tests/adversarial/test_generators_llm_cache.py — LLM attack cache-reader
generators (Task 15).

Covers `validation.adversarial.generators.LLMImitation`,
`LLMParaphrase`, and `LLMRoundTrip` — none of which ever makes a network
call — plus `validation.adversarial.gen_llm_attacks`'s fail-fast
"no ANTHROPIC_API_KEY" path.

Everything here is hermetic:
  - The real, current state of this repo has no
    `validation/adversarial/corpus/llm_attacks/` directory (populating it
    requires a human to run `gen_llm_attacks.py` with a real API key,
    which is explicitly NOT done in this task) — the "cache absent"
    assertions exercise that real state directly.
  - The "cache present" assertions build a synthetic fixture cache under
    `tmp_path` and monkeypatch each generator class's `CACHE_DIR` class
    attribute to point at it, so the real corpus directory is never
    touched and no network is ever involved.
  - The `gen_llm_attacks` CLI test monkeypatches `ANTHROPIC_API_KEY` unset
    and asserts the script fails fast on the missing-key check, before
    ever importing `anthropic` (which, as it happens, is not even
    installed in this venv — see the Task 15 report).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from validation.adversarial import gen_llm_attacks
from validation.adversarial.generators import LLMImitation, LLMParaphrase, LLMRoundTrip

_REAL_CACHE_DIR = Path("validation/adversarial/corpus/llm_attacks")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_doc(cache_dir: Path, attack: str, victim_id: str, text: str) -> str:
    doc_sha = _sha(text)
    path = cache_dir / attack / victim_id / f"{doc_sha}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return doc_sha


def _write_manifest(cache_dir: Path, entries: list[dict]) -> None:
    (cache_dir / "manifest.json").write_text(
        json.dumps({"entries": entries}, indent=2), encoding="utf-8"
    )


# --- cache absent (the real, current repo state) --------------------------


def test_real_repo_has_no_llm_attacks_cache_yet():
    # Sanity check on the premise of every "cache absent" assertion below:
    # this directory genuinely does not exist in this checkout, since
    # populating it requires a human to run gen_llm_attacks.py with a real
    # API key (a future step, not this task's).
    assert not _REAL_CACHE_DIR.exists()


def test_configured_false_when_cache_absent():
    gen = LLMImitation(victim_id="thoreau")
    assert gen.configured is False


def test_skip_reason_mentions_missing_path_when_cache_absent():
    gen = LLMParaphrase(victim_id="thoreau")
    reason = gen.skip_reason()
    assert reason is not None
    assert "llm_attacks" in reason
    assert "manifest.json" in reason


def test_load_samples_raises_when_cache_absent():
    gen = LLMRoundTrip(victim_id="thoreau", language="de")
    with pytest.raises(LookupError):
        gen.load_samples(prompts=[])


# --- synthetic fixture cache: configured + load_samples happy path --------


@pytest.fixture
def fixture_cache(tmp_path, monkeypatch):
    """Builds a small, valid synthetic cache under tmp_path and points all
    three generator classes' CACHE_DIR at it. Real SHA-256 hashes are
    computed over the fake content so the integrity check is genuinely
    exercised, not just assumed to pass."""
    cache_dir = tmp_path / "llm_attacks"
    cache_dir.mkdir()

    imitation_text = "This is a fixture imitation essay about lighthouses and solitude."
    paraphrase_text = "This is a fixture paraphrase of a held-out passage."
    roundtrip_text = "This is a fixture round-tripped passage, translated there and back."

    imitation_sha = _write_doc(cache_dir, "imitation", "alpha", imitation_text)
    paraphrase_sha = _write_doc(cache_dir, "paraphrase", "alpha", paraphrase_text)
    roundtrip_sha = _write_doc(cache_dir, "roundtrip_de", "alpha", roundtrip_text)

    entries = [
        {
            "model_id": "claude-opus-5",
            "prompt_sha": _sha("fixture imitation prompt"),
            "doc_sha": imitation_sha,
            "victim_id": "alpha",
            "attack": "imitation",
            "n_baselines": 3,
        },
        {
            "model_id": "claude-opus-5",
            "prompt_sha": _sha("fixture paraphrase prompt"),
            "doc_sha": paraphrase_sha,
            "victim_id": "alpha",
            "attack": "paraphrase",
            "n_baselines": 3,
        },
        {
            "model_id": "claude-opus-5",
            "prompt_sha": _sha(
                "fixture roundtrip there-prompt\n<<ROUNDTRIP>>\nfixture roundtrip back-prompt"
            ),
            "doc_sha": roundtrip_sha,
            "victim_id": "alpha",
            "attack": "roundtrip_de",
            "n_baselines": 3,
        },
    ]
    _write_manifest(cache_dir, entries)

    monkeypatch.setattr(LLMImitation, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(LLMParaphrase, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(LLMRoundTrip, "CACHE_DIR", cache_dir)

    return {
        "cache_dir": cache_dir,
        "imitation_text": imitation_text,
        "paraphrase_text": paraphrase_text,
        "roundtrip_text": roundtrip_text,
        "imitation_sha": imitation_sha,
        "paraphrase_sha": paraphrase_sha,
        "roundtrip_sha": roundtrip_sha,
    }


def test_configured_true_when_cache_covers_victim_and_attack(fixture_cache):
    assert LLMImitation(victim_id="alpha").configured is True
    assert LLMParaphrase(victim_id="alpha").configured is True
    assert LLMRoundTrip(victim_id="alpha", language="de").configured is True


def test_configured_false_for_uncovered_victim(fixture_cache):
    # Cache exists and has entries, but not for this victim_id.
    gen = LLMImitation(victim_id="omega")
    assert gen.configured is False
    reason = gen.skip_reason()
    assert reason is not None
    assert "omega" in reason
    assert "imitation" in reason


def test_configured_false_for_uncovered_attack(fixture_cache):
    # "alpha" is covered for imitation/paraphrase/roundtrip_de, but never
    # for roundtrip_ja in this fixture.
    gen = LLMRoundTrip(victim_id="alpha", language="ja")
    assert gen.configured is False
    assert gen.load_samples.__doc__ is not None  # sanity: method exists
    with pytest.raises(LookupError):
        gen.load_samples(prompts=[])


def test_load_samples_returns_matching_docs(fixture_cache):
    gen = LLMImitation(victim_id="alpha")
    samples = gen.load_samples(prompts=["ignored — see docstring"])
    assert len(samples) == 1
    assert samples[0].text == fixture_cache["imitation_text"]
    # The manifest's own doc_sha must equal the sha256 of the actual file
    # content — this is the real integrity check, not an assumption.
    assert fixture_cache["imitation_sha"] == hashlib.sha256(
        samples[0].text.encode("utf-8")
    ).hexdigest()


def test_load_samples_paraphrase_and_roundtrip(fixture_cache):
    paraphrase_samples = LLMParaphrase(victim_id="alpha").load_samples(prompts=[])
    assert [s.text for s in paraphrase_samples] == [fixture_cache["paraphrase_text"]]

    roundtrip_samples = LLMRoundTrip(victim_id="alpha", language="de").load_samples(prompts=[])
    assert [s.text for s in roundtrip_samples] == [fixture_cache["roundtrip_text"]]


# --- cache-miss / tamper scenarios: load_samples must raise, never skip ---


def test_load_samples_raises_on_missing_file(fixture_cache, tmp_path):
    cache_dir = fixture_cache["cache_dir"]
    # Manifest references a victim/attack combo whose doc file was never
    # actually written to disk.
    ghost_sha = _sha("this text was never written to a file")
    entries = json.loads((cache_dir / "manifest.json").read_text())["entries"]
    entries.append(
        {
            "model_id": "claude-opus-5",
            "prompt_sha": _sha("ghost prompt"),
            "doc_sha": ghost_sha,
            "victim_id": "beta",
            "attack": "imitation",
            "n_baselines": 3,
        }
    )
    _write_manifest(cache_dir, entries)

    gen = LLMImitation(victim_id="beta")
    assert gen.configured is True  # the manifest entry exists...
    with pytest.raises(FileNotFoundError):
        gen.load_samples(prompts=[])  # ...but the file it points to does not


def test_load_samples_raises_on_tampered_content(fixture_cache):
    cache_dir = fixture_cache["cache_dir"]
    doc_path = cache_dir / "imitation" / "alpha" / f"{fixture_cache['imitation_sha']}.txt"
    # Corrupt the file after the manifest was written — its content no
    # longer matches the recorded doc_sha.
    doc_path.write_text("this is NOT the text the manifest's doc_sha describes", encoding="utf-8")

    gen = LLMImitation(victim_id="alpha")
    with pytest.raises(ValueError, match="SHA-256"):
        gen.load_samples(prompts=[])


def test_load_samples_raises_on_missing_manifest_key(fixture_cache):
    cache_dir = fixture_cache["cache_dir"]
    entries = json.loads((cache_dir / "manifest.json").read_text())["entries"]
    for e in entries:
        if e["attack"] == "paraphrase":
            del e["model_id"]
    _write_manifest(cache_dir, entries)

    gen = LLMParaphrase(victim_id="alpha")
    with pytest.raises(ValueError, match="model_id"):
        gen.load_samples(prompts=[])


def test_llm_roundtrip_rejects_unknown_language():
    with pytest.raises(ValueError):
        LLMRoundTrip(victim_id="alpha", language="fr")


# --- gen_llm_attacks.py: fail-fast on a missing API key --------------------


def test_anthropic_is_not_importable_in_this_venv():
    # Documents the environment this task actually ran in (see the Task 15
    # report): the venv genuinely lacks the `anthropic` package, which is
    # exactly why the lazy-import discipline in gen_llm_attacks.py matters.
    with pytest.raises(ImportError):
        import anthropic  # noqa: F401


def test_gen_llm_attacks_module_import_does_not_import_anthropic():
    # gen_llm_attacks was already imported at the top of this test file (a
    # module-level import succeeding at all is itself proof --help/argparse
    # work without `anthropic` installed). Importing it must not have
    # eagerly imported `anthropic` as a side effect — that only happens
    # lazily, inside _import_anthropic(), after the key check passes.
    assert "anthropic" not in sys.modules


def test_gen_llm_attacks_fails_fast_with_no_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # anthropic is not installed in this venv (see
    # test_anthropic_is_not_importable_in_this_venv above) and nothing here
    # mocks a network client — if the missing-key check did not run first,
    # this would fail with ModuleNotFoundError instead of the intended
    # SystemExit(2), which is exactly the distinction this test enforces.
    with pytest.raises(SystemExit) as exc_info:
        gen_llm_attacks.main(["--n-baselines", "3"])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "ANTHROPIC_API_KEY" in captured.err


def test_gen_llm_attacks_help_works_without_anthropic(capsys):
    # argparse's --help path exits 0 before main() ever reaches the key
    # check or the anthropic import.
    with pytest.raises(SystemExit) as exc_info:
        gen_llm_attacks.main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "ANTHROPIC_API_KEY" in captured.out or "anthropic" in captured.out.lower()


def test_check_api_key_raises_before_any_anthropic_import(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        gen_llm_attacks._check_api_key()
    assert exc_info.value.code == 2
    assert "anthropic" not in sys.modules
