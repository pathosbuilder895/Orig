"""
validation/adversarial/gen_llm_attacks.py — offline LLM attack-corpus
generator (Task 15).

This is the ONE script in SP1's red-team harness that is allowed to make a
live network call. It reads victim profiles (Task 13's
`validation.adversarial.profiles.build_victim_profiles`), prompts the
Anthropic API to produce three kinds of adversarial samples per victim
(imitation, paraphrase, MT round-trip), and commits the results to
`validation/adversarial/corpus/llm_attacks/` — text files plus a
`manifest.json` recording `{model_id, prompt_sha, doc_sha, victim_id,
attack}` per doc (see `validation/adversarial/generators.py`'s
"LLMImitation / LLMParaphrase / LLMRoundTrip" section for the full,
authoritative contract — this script and the three cache-reading
`Generator` subclasses there must never drift apart on it).

This script has NOT been run in this task. No `ANTHROPIC_API_KEY` is
available in this environment, so `corpus/llm_attacks/` does not exist
after this commit — that is expected and correct. A human runs this once,
later, with their own key:

    ANTHROPIC_API_KEY=sk-ant-... /Users/andrew/Desktop/Original/.venv/bin/python \\
        -m validation.adversarial.gen_llm_attacks --n-baselines 3,5,10

Fail-fast discipline: `main()` checks `ANTHROPIC_API_KEY` and prints a clear
error (`_NO_KEY_ERROR`) BEFORE ever importing the `anthropic` package —
`import anthropic` is lazy, inside `_import_anthropic()`, specifically so
(a) `--help` and argument parsing work even when `anthropic` is not
installed at all (true of this repo's `.venv` as of 2026-09-21 — see the
Task 15 report), and (b) the missing-key path is provably network-free: it
never reaches the import, let alone a socket.

Env locking: `validation.benchmark.reproducibility.lock_environment()` is
called before generation runs, per the Task 15 brief's instruction to lock
the env before importing `original.*`. This script does not currently
import any `original.*` module — `profiles.py` has no dependency on the
scoring stack at all — so the call is precautionary rather than load-bearing
today. It costs nothing and protects any future addition here (e.g. scoring
the freshly generated attacks inline) from picking up a leaked
`ADAPTIVE_WEIGHTS_ENABLED=1` or similar from the calling shell.

Round-trip design decision (EN -> {German, Japanese} -> EN as TWO API calls
per leg, not one "translate there and back" prompt) and the manifest/file
layout contract are both documented in detail in
`validation/adversarial/generators.py`, right above the `LLMImitation` /
`LLMParaphrase` / `LLMRoundTrip` classes — read that before changing
anything here, since the reader classes and this writer must stay in sync.

Idempotent by design: re-running for a subset of victims/attacks/N merges
new entries into the existing manifest by `(victim_id, attack, doc_sha)`
key rather than overwriting it, so a partial re-run (e.g. topping up one
new victim) never drops previously generated attacks for the others.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from validation.adversarial.profiles import VictimProfile, build_victim_profiles

_HERE = Path(__file__).resolve().parent
_DEFAULT_CACHE_DIR = _HERE / "corpus" / "llm_attacks"

# "The latest Claude model" per the Task 15 brief. Anthropic's own current
# model table (2026-09) puts Claude Opus 5 as the general-purpose default
# unless a task calls for a different tier — this is a one-shot offline
# generation job, not a latency- or cost-sensitive production path, so the
# default is the highest-quality model rather than a cheaper one. Override
# with --model if a human running this later wants something else.
_DEFAULT_MODEL_ID = "claude-opus-5"

# Matches validation/benchmark/reproducibility.BENCHMARK_SEED — reusing the
# same constant keeps this script's default victim-profile selection
# reproducible with the rest of the validation suite's conventions.
_DEFAULT_SEED = 1729

# Matches the "~600-word ... essay" convention already used by
# validation/diagnostics/generators.py's OpenAIGenerator/GeminiGenerator/
# CohereGenerator, for consistency across validation/'s various generated-
# text corpora.
_IMITATION_TARGET_WORDS = 600

_LANGUAGE_NAMES = {"de": "German", "ja": "Japanese"}
_ATTACK_CHOICES = ("imitation", "paraphrase", "roundtrip_de", "roundtrip_ja")

_NO_KEY_ERROR = (
    "error: ANTHROPIC_API_KEY is not set.\n\n"
    "gen_llm_attacks.py calls the live Anthropic API to populate\n"
    f"{_DEFAULT_CACHE_DIR}\n"
    "and must not run without a real key. Set it and re-run, e.g.:\n\n"
    "    ANTHROPIC_API_KEY=sk-ant-... /Users/andrew/Desktop/Original/.venv/bin/python \\\n"
    "        -m validation.adversarial.gen_llm_attacks --n-baselines 3,5,10\n"
)


# --- CLI ---------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m validation.adversarial.gen_llm_attacks",
        description=(
            "Offline populator for validation/adversarial/corpus/llm_attacks/. "
            "Calls the live Anthropic API (needs ANTHROPIC_API_KEY) to generate "
            "imitation, paraphrase, and MT-round-trip adversarial samples for the "
            "SP1 red-team harness, then commits them to a content-addressed cache "
            "so later test/gate runs never need the network again."
        ),
    )
    parser.add_argument(
        "--n-baselines",
        default="3,5,10",
        help="Comma-separated baseline counts to build victim profiles at (default: 3,5,10).",
    )
    parser.add_argument(
        "--victims",
        default=None,
        help="Comma-separated victim_ids to restrict generation to (default: every victim "
        "build_victim_profiles(n, seed) returns at each requested N).",
    )
    parser.add_argument(
        "--attacks",
        default=",".join(_ATTACK_CHOICES),
        help=f"Comma-separated attack ids to generate, from {_ATTACK_CHOICES} (default: all).",
    )
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL_ID,
        help=f"Anthropic model id to generate with (default: {_DEFAULT_MODEL_ID}).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=_DEFAULT_SEED,
        help=f"Seed for build_victim_profiles and lock_environment (default: {_DEFAULT_SEED}).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_CACHE_DIR,
        help=f"Cache directory to write into (default: {_DEFAULT_CACHE_DIR}).",
    )
    return parser


def _parse_int_list(raw: str) -> list[int]:
    return [int(v.strip()) for v in raw.split(",") if v.strip()]


def _parse_str_list(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    return [v.strip() for v in raw.split(",") if v.strip()]


def _check_api_key() -> str:
    """Returns the key, or prints a clear error to stderr and raises
    SystemExit(2). Deliberately the FIRST thing `main()` does after parsing
    args — before `_import_anthropic()` — so an unset key fails fast
    without ever touching the network or requiring the `anthropic` package
    to be installed. `tests/adversarial/test_generators_llm_cache.py`
    exercises exactly this path with `ANTHROPIC_API_KEY` unset in a venv
    where `anthropic` is not installed, and asserts it never gets far
    enough to need it."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print(_NO_KEY_ERROR, file=sys.stderr)
        raise SystemExit(2)
    return api_key


def _import_anthropic():
    """Lazy import so `--help` and argument parsing work in an environment
    that doesn't have the `anthropic` package installed at all (true of
    this repo's own `.venv` as of 2026-09-21 — see the Task 15 report)."""
    try:
        import anthropic
    except ImportError as exc:
        print(
            "error: the 'anthropic' package is not installed in this environment "
            f"({exc}).\nInstall it (`pip install anthropic`) in the validation venv "
            "before running gen_llm_attacks.py.",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    return anthropic


# --- prompt construction -------------------------------------------------
# Each of these builds the EXACT prompt text a human running this later
# would send to the API — reviewable, runnable as-is with no further
# changes once a key is available.


def _imitation_prompt(profile: VictimProfile, target_words: int = _IMITATION_TARGET_WORDS) -> str:
    baselines_block = "\n\n---\n\n".join(profile.baselines)
    return (
        f"Write approximately {target_words} words of original prose, matching the "
        "subject matter and register of the following writing samples as closely as "
        "possible, in the same authorial voice and style. Do not summarize, quote, or "
        "refer to the samples themselves — write new, freestanding material a reader "
        "would mistake for more work by the same author.\n\n"
        f"{baselines_block}\n\n---\n\n"
        "Write only the new passage. No preamble, no commentary, no headers."
    )


def _paraphrase_prompt(source_text: str) -> str:
    return (
        "Rewrite the following text, preserving its full meaning and factual content "
        "but paraphrasing the wording, sentence structure, and phrasing throughout so "
        "it reads as freshly composed rather than copied. Keep approximately the same "
        "length.\n\n"
        f"{source_text}\n\n---\n\n"
        "Write only the rewritten text. No preamble, no commentary."
    )


def _translate_prompt(text: str, target_language_name: str) -> str:
    return (
        f"Translate the following text into {target_language_name}. Output only the "
        "translation, with no preamble or commentary.\n\n"
        f"{text}"
    )


# --- API call --------------------------------------------------------------


def _complete(client, model_id: str, prompt: str) -> str:
    response = client.messages.create(
        model=model_id,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "text":
            return block.text
    raise RuntimeError(f"no text block in Claude response for model {model_id!r}")


# --- generation ------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry(
    model_id: str, prompt_sha: str, text: str, victim_id: str, attack: str, n_baselines: int
) -> dict:
    return {
        "model_id": model_id,
        "prompt_sha": prompt_sha,
        "doc_sha": _sha(text),
        "victim_id": victim_id,
        "attack": attack,
        "n_baselines": n_baselines,
        "_text": text,  # popped before writing the manifest; used to write the doc file
    }


def _generate_imitation(
    client, model_id: str, profile: VictimProfile, n_baselines: int
) -> list[dict]:
    prompt = _imitation_prompt(profile)
    text = _complete(client, model_id, prompt)
    return [_entry(model_id, _sha(prompt), text, profile.victim_id, "imitation", n_baselines)]


def _generate_paraphrase(
    client, model_id: str, profile: VictimProfile, n_baselines: int
) -> list[dict]:
    entries = []
    for source_text in profile.genuine_holdout:
        prompt = _paraphrase_prompt(source_text)
        text = _complete(client, model_id, prompt)
        entries.append(
            _entry(model_id, _sha(prompt), text, profile.victim_id, "paraphrase", n_baselines)
        )
    return entries


def _generate_roundtrip(
    client, model_id: str, profile: VictimProfile, language: str, n_baselines: int
) -> list[dict]:
    target_name = _LANGUAGE_NAMES[language]
    entries = []
    for source_text in profile.genuine_holdout:
        there_prompt = _translate_prompt(source_text, target_name)
        translated = _complete(client, model_id, there_prompt)
        back_prompt = _translate_prompt(translated, "English")
        text = _complete(client, model_id, back_prompt)
        # prompt_sha covers BOTH hops (this doc is the product of two API
        # calls, not one) — see generators.py's "Round-trip design
        # decision" comment for why round-trip is two calls at all.
        combined_prompt_sha = _sha(there_prompt + "\n<<ROUNDTRIP>>\n" + back_prompt)
        entries.append(
            _entry(
                model_id,
                combined_prompt_sha,
                text,
                profile.victim_id,
                f"roundtrip_{language}",
                n_baselines,
            )
        )
    return entries


# --- manifest I/O ------------------------------------------------------------


def _load_existing_manifest(manifest_path: Path) -> list[dict]:
    if not manifest_path.exists():
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return data.get("entries", [])


def _merge_entries(existing: list[dict], new: list[dict]) -> list[dict]:
    """Replace any existing entry sharing a (victim_id, attack, doc_sha)
    key with the new one; keep every other existing entry untouched. This
    is what makes a partial re-run (one new victim, one new attack)
    additive rather than destructive to the rest of the committed cache."""

    def key(entry: dict) -> tuple[str, str, str]:
        return (entry["victim_id"], entry["attack"], entry["doc_sha"])

    merged = {key(e): e for e in existing}
    for e in new:
        merged[key(e)] = e
    return list(merged.values())


def _write_doc(out_dir: Path, attack: str, victim_id: str, doc_sha: str, text: str) -> None:
    path = out_dir / attack / victim_id / f"{doc_sha}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- orchestration ------------------------------------------------------------


def _run(args: argparse.Namespace, anthropic_module) -> None:
    client = anthropic_module.Anthropic()
    out_dir: Path = args.out_dir
    manifest_path = out_dir / "manifest.json"

    n_baselines_list = _parse_int_list(args.n_baselines)
    requested_victims = _parse_str_list(args.victims)
    requested_attacks = _parse_str_list(args.attacks) or list(_ATTACK_CHOICES)
    unknown = [a for a in requested_attacks if a not in _ATTACK_CHOICES]
    if unknown:
        raise SystemExit(f"error: unknown attack(s) {unknown}, expected one of {_ATTACK_CHOICES}")

    new_entries: list[dict] = []
    # paraphrase/roundtrip operate on genuine_holdout text, which does not
    # vary with n_baselines (see profiles.py — only the *baseline* selection
    # is N-dependent) — generate those once per victim, the first time that
    # victim is seen, rather than once per requested N.
    holdout_attacks_done: set[str] = set()

    for n in n_baselines_list:
        profiles = build_victim_profiles(n_baselines=n, seed=args.seed)
        for profile in profiles:
            if requested_victims is not None and profile.victim_id not in requested_victims:
                continue
            if "imitation" in requested_attacks:
                new_entries.extend(_generate_imitation(client, args.model, profile, n))
            if profile.victim_id not in holdout_attacks_done:
                if "paraphrase" in requested_attacks:
                    new_entries.extend(_generate_paraphrase(client, args.model, profile, n))
                if "roundtrip_de" in requested_attacks:
                    new_entries.extend(_generate_roundtrip(client, args.model, profile, "de", n))
                if "roundtrip_ja" in requested_attacks:
                    new_entries.extend(_generate_roundtrip(client, args.model, profile, "ja", n))
                holdout_attacks_done.add(profile.victim_id)

    for e in new_entries:
        text = e.pop("_text")
        _write_doc(out_dir, e["attack"], e["victim_id"], e["doc_sha"], text)

    merged = _merge_entries(_load_existing_manifest(manifest_path), new_entries)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"entries": merged}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(new_entries)} new/updated entries, {len(merged)} total, to {manifest_path}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    _check_api_key()
    anthropic_module = _import_anthropic()

    from validation.benchmark.reproducibility import lock_environment

    lock_environment(seed=args.seed)

    _run(args, anthropic_module)
    return 0


if __name__ == "__main__":
    sys.exit(main())
