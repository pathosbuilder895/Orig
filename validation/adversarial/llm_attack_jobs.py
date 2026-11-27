"""
validation/adversarial/llm_attack_jobs.py: build the LLM attack corpus
(`corpus/llm_attacks/`) without an API key, by handing each prompt to a
Claude Code subagent instead of the Anthropic API.

`gen_llm_attacks.py` is the API route: it sends each prompt with the
`anthropic` SDK. This module is the route actually used on 2026-11-19,
when no key was available and the owner approved generating the corpus
with Claude itself. The prompts are built by `gen_llm_attacks`'s own prompt
builders from the same victim profiles, so the prompt text, and therefore
every manifest `prompt_sha`, is what the API route would have sent; only
the delivery differs (see "Delivery" below). The output layout and
manifest are `generators.py`'s contract unchanged, so the cache readers
and gates G-A2/G-A3 read the result exactly as they would an API run.

Three steps, each a subcommand:

  jobs      one prompt file per job: an imitation per (victim, N), and per
            genuine-holdout document a paraphrase plus the FIRST hop of each
            round trip (English to German or Japanese). Also writes
            jobs.json. Same selection rules as gen_llm_attacks._run: holdout
            attacks once per victim, at the first N the victim appears.
  hop2      once first-hop outputs exist, the back-translation prompt for
            each round trip, built from the normalized first-hop text.
  assemble  checks every output and writes `corpus/llm_attacks/`: the docs,
            each round trip's intermediate translation under
            `_intermediate/`, and the manifest (merged into an existing one
            by gen_llm_attacks._merge_entries, so a partial run is additive).

Delivery. A subagent reads its prompt from a file. Some source documents
are one line of 14,000 characters, longer than a file viewer reliably
shows, so each prompt also gets a display copy (`view/`) in which some
spaces on over-long lines are replaced by line breaks (`display_wrap`):
same words, same punctuation, whitespace only. `prompt_sha` is always the
sha of the canonical, unwrapped prompt, which is what the API route sends.

Independence. A round trip's second hop is done by an agent that has never
seen the English source, so the back-translation cannot be recalled rather
than translated; that mirrors gen_llm_attacks's two separate API calls.
One agent per imitation, so no imitation is written by an agent that has
read a different N's baselines.

Dash markers. The workspace this was run in has a hook that rewrites
the long dashes (U+2014 em dash, U+2015 horizontal bar) in every file a
tool writes, subagents' included, to commas. Several victims use em dashes
heavily and the feature pipeline measures punctuation, so a stripped
attack would be easier to catch than a real one. Agents therefore write
`[[EMDASH]]` / `[[HBAR]]` where the character goes, and `_read_output`
puts the character back (owner decision, 2026-11-19). Every count of
restored markers is in `generation_log.json`; a marker left in a doc, or
a malformed one, rejects it.

Output normalization is marker restoration then `str.strip()`, applied
before a first hop's text is put into its second-hop prompt and before
any doc's sha is taken.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

from validation.adversarial import gen_llm_attacks as gen
from validation.adversarial.profiles import build_victim_profiles

ROUTE = "claude-code-subagent"
DASH_MARKERS = {"[[EMDASH]]": "\u2014", "[[HBAR]]": "\u2015"}
_MARKER_LIKE_RE = re.compile(r"\[\[\s*[A-Za-z_ ]+\s*\]\]")
HOP_SEP = "\n<<ROUNDTRIP>>\n"  # gen_llm_attacks._generate_roundtrip's separator
WRAP_WIDTH = 1000

# An assistant talking about its answer, not the answer. Kept narrow: an
# imitation of a first-person essayist may well open "I have lately been".
_PREAMBLE_RE = re.compile(
    r"^\s*(here is|here's|sure[,!.]|certainly[,!.]|below is|okay[,!.]|of course[,!.]|"
    r"translation:|rewritten text:|i(?:'ve| have) (?:rewritten|translated|written|paraphrased))",
    re.IGNORECASE,
)
_KANA_KANJI_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
_WORD_RE = re.compile(r"[A-Za-z']+")
# Bounds on an output's length relative to its source, in words. A
# paraphrase is asked to keep "approximately the same length"; a
# back-translation should land near its source too. Outside these the doc
# is truncated or padded and is rejected, not quietly kept.
_RATIO_BOUNDS = (0.6, 1.5)
_IMITATION_WORD_BOUNDS = (300, 1500)
_SHINGLE = 8


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def display_wrap(text: str, width: int = WRAP_WIDTH) -> str:
    """Break lines longer than `width` at a space, replacing that space with
    a newline; on a line with no space before `width` (Japanese), break
    after the last full stop (U+3002) instead, inserting the newline. The
    result has the same characters as `text` apart from those newlines."""
    out: list[str] = []
    for line in text.split("\n"):
        while len(line) > width:
            cut = line.rfind(" ", 0, width + 1)
            if cut > 0:
                out.append(line[:cut])
                line = line[cut + 1 :]
                continue
            stop = line.rfind("\u3002", 0, width)
            if stop <= 0:
                break
            out.append(line[: stop + 1])
            line = line[stop + 1 :]
        out.append(line)
    return "\n".join(out)


# --- planning ------------------------------------------------------------------


def plan_jobs(
    ns: list[int], attacks: list[str], victims: list[str] | None, seed: int
) -> list[dict]:
    """First-step jobs with their canonical prompt text, in gen_llm_attacks._run's
    selection order. Each job: id, attack, victim_id, n_baselines, step
    ("imitation" | "paraphrase" | "hop1"), language (round trips), prompt."""
    unknown = [a for a in attacks if a not in gen._ATTACK_CHOICES]
    if unknown:
        raise ValueError(f"unknown attack(s) {unknown}, expected one of {gen._ATTACK_CHOICES}")
    jobs: list[dict] = []
    holdout_done: set[str] = set()
    for n in ns:
        for profile in build_victim_profiles(n_baselines=n, seed=seed):
            vid = profile.victim_id
            if victims is not None and vid not in victims:
                continue
            if "imitation" in attacks:
                jobs.append(
                    {
                        "id": f"imitation__{vid}__n{n}",
                        "attack": "imitation",
                        "victim_id": vid,
                        "n_baselines": n,
                        "step": "imitation",
                        "prompt": gen._imitation_prompt(profile),
                    }
                )
            if vid in holdout_done:
                continue
            for i, source in enumerate(profile.genuine_holdout):
                if "paraphrase" in attacks:
                    jobs.append(
                        {
                            "id": f"paraphrase__{vid}__h{i}",
                            "attack": "paraphrase",
                            "victim_id": vid,
                            "n_baselines": n,
                            "holdout_index": i,
                            "step": "paraphrase",
                            "prompt": gen._paraphrase_prompt(source),
                        }
                    )
                for lang in ("de", "ja"):
                    if f"roundtrip_{lang}" not in attacks:
                        continue
                    jobs.append(
                        {
                            "id": f"roundtrip_{lang}__{vid}__h{i}__hop1",
                            "attack": f"roundtrip_{lang}",
                            "victim_id": vid,
                            "n_baselines": n,
                            "holdout_index": i,
                            "language": lang,
                            "step": "hop1",
                            "prompt": gen._translate_prompt(source, gen._LANGUAGE_NAMES[lang]),
                        }
                    )
            holdout_done.add(vid)
    return jobs


def _jobs_path(jobs_dir: Path) -> Path:
    return jobs_dir / "jobs.json"


def _load_jobs(jobs_dir: Path) -> dict[str, dict]:
    path = _jobs_path(jobs_dir)
    if not path.exists():
        return {}
    return {j["id"]: j for j in json.loads(path.read_text(encoding="utf-8"))["jobs"]}


def _save_jobs(jobs_dir: Path, jobs: dict[str, dict]) -> None:
    ordered = [jobs[k] for k in sorted(jobs)]
    _jobs_path(jobs_dir).write_text(
        json.dumps({"jobs": ordered}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_job(jobs_dir: Path, job: dict) -> dict:
    """Write the canonical and display prompt files; return the job record
    (prompt text replaced by its sha and file paths)."""
    prompt = job.pop("prompt")
    for sub, text in (("prompts", prompt), ("view", display_wrap(prompt))):
        path = jobs_dir / sub / f"{job['id']}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (jobs_dir / "out").mkdir(parents=True, exist_ok=True)
    job["prompt_sha"] = _sha(prompt)
    job["view_file"] = str(jobs_dir / "view" / f"{job['id']}.txt")
    job["output_file"] = str(jobs_dir / "out" / f"{job['id']}.txt")
    return job


def write_jobs(jobs_dir: Path, planned: list[dict]) -> list[dict]:
    jobs = _load_jobs(jobs_dir)
    written = []
    for job in planned:
        rec = _write_job(jobs_dir, dict(job))
        jobs[rec["id"]] = rec
        written.append(rec)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    _save_jobs(jobs_dir, jobs)
    return written


def restore_markers(raw: str) -> tuple[str, int]:
    """Replace the dash markers with their characters; returns the text and
    how many markers were replaced."""
    count = 0
    for marker, char in DASH_MARKERS.items():
        count += raw.count(marker)
        raw = raw.replace(marker, char)
    return raw, count


def _read_output(job: dict) -> str | None:
    path = Path(job["output_file"])
    if not path.exists():
        return None
    return restore_markers(path.read_text(encoding="utf-8"))[0].strip()


def _markers_in_output(job: dict) -> int:
    return restore_markers(Path(job["output_file"]).read_text(encoding="utf-8"))[1]


def write_hop2_jobs(jobs_dir: Path) -> list[dict]:
    """A second-hop job for every first hop whose output exists and has no
    second hop yet."""
    jobs = _load_jobs(jobs_dir)
    planned = []
    for job in jobs.values():
        if job["step"] != "hop1":
            continue
        hop2_id = job["id"].replace("__hop1", "__hop2")
        if hop2_id in jobs:
            continue
        translated = _read_output(job)
        if not translated:
            continue
        planned.append(
            {
                **{k: job[k] for k in ("attack", "victim_id", "n_baselines", "holdout_index")},
                "id": hop2_id,
                "language": job["language"],
                "step": "hop2",
                "hop1_id": job["id"],
                "prompt": gen._translate_prompt(translated, "English"),
            }
        )
    return write_jobs(jobs_dir, planned)


# --- checks -----------------------------------------------------------------------


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def shingle_overlap(text: str, sources: list[str], k: int = _SHINGLE) -> float:
    """Share of `text`'s word k-grams that also occur in any of `sources`:
    near 0 for new writing, near 1 for a copy."""

    def grams(t: str) -> set[tuple[str, ...]]:
        w = _words(t)
        return {tuple(w[i : i + k]) for i in range(len(w) - k + 1)}

    mine = grams(text)
    if not mine:
        return 0.0
    theirs: set[tuple[str, ...]] = set()
    for s in sources:
        theirs |= grams(s)
    return len(mine & theirs) / len(mine)


def check_output(
    job: dict, text: str, source: str | None, baselines: list[str]
) -> tuple[list[str], dict]:
    """(problems, stats) for one output. A problem rejects the doc."""
    problems: list[str] = []
    stats: dict = {"chars": len(text)}
    if not text:
        return ["empty output"], stats
    if _PREAMBLE_RE.match(text):
        problems.append(f"starts with a preamble: {text[:60]!r}")
    leftover = _MARKER_LIKE_RE.findall(text)
    if leftover:
        problems.append(f"unrestored marker(s): {sorted(set(leftover))}")
    step = job["step"]
    if step == "hop1":
        if job["language"] == "ja":
            share = len(_KANA_KANJI_RE.findall(text)) / max(1, len(text))
            stats["japanese_char_share"] = round(share, 3)
            if share < 0.3:
                problems.append(f"not Japanese (kana/kanji share {share:.2f})")
        else:
            german = sum(
                1 for w in _words(text) if w in {"der", "die", "und", "das", "nicht", "ist"}
            )
            stats["german_marker_words"] = german
            if german < 20:
                problems.append("not German (few German function words)")
        return problems, stats
    words = len(text.split())
    stats["words"] = words
    if step == "imitation":
        lo, hi = _IMITATION_WORD_BOUNDS
        if not lo <= words <= hi:
            problems.append(f"{words} words, outside {lo}-{hi}")
        stats["overlap_with_baselines"] = round(shingle_overlap(text, baselines), 4)
        if stats["overlap_with_baselines"] > 0.05:
            problems.append(
                f"copies its baselines ({stats['overlap_with_baselines']:.1%} of 8-grams)"
            )
        return problems, stats
    # paraphrase or back-translation: English, near the source's length
    letters = len(_LATIN_LETTER_RE.findall(text))
    foreign = len(_KANA_KANJI_RE.findall(text))
    if foreign > 0.01 * max(1, letters):
        problems.append("not English (kana/kanji present)")
    ratio = words / max(1, len(source.split()))
    stats["length_ratio"] = round(ratio, 3)
    lo, hi = _RATIO_BOUNDS
    if not lo <= ratio <= hi:
        problems.append(f"length ratio {ratio:.2f} to its source, outside {lo}-{hi}")
    stats["overlap_with_source"] = round(shingle_overlap(text, [source]), 4)
    return problems, stats


# --- assembly -------------------------------------------------------------------


def _profiles(ns: list[int], seed: int) -> dict[tuple[str, int], object]:
    return {
        (p.victim_id, n): p for n in ns for p in build_victim_profiles(n_baselines=n, seed=seed)
    }


def assemble(
    jobs_dir: Path,
    out_dir: Path,
    model_id: str,
    seed: int,
    generated_on: str,
    dry_run: bool = False,
) -> dict:
    """Check every finished final-step job and write it into `out_dir`.
    Returns {"written": [...], "rejected": [...], "pending": [...], "stats": {...}}.
    Nothing is written when any finished job is rejected."""
    jobs = _load_jobs(jobs_dir)
    ns = sorted({j["n_baselines"] for j in jobs.values()})
    profiles = _profiles(sorted(set(ns) | {3, 5, 10}), seed)
    entries: list[dict] = []
    docs: list[tuple[dict, str, str | None, str | None]] = []
    rejected: list[dict] = []
    pending: list[str] = []
    stats: dict[str, dict] = {}
    log_rows: list[dict] = []

    for job in sorted(jobs.values(), key=lambda j: j["id"]):
        text = _read_output(job)
        if text is None:
            pending.append(job["id"])
            continue
        profile = profiles[(job["victim_id"], job["n_baselines"])]
        source = None
        if job["step"] != "imitation":
            source = profile.genuine_holdout[job["holdout_index"]]
        problems, job_stats = check_output(job, text, source, list(profile.baselines))
        job_stats["dash_markers_restored"] = _markers_in_output(job)
        stats[job["id"]] = job_stats
        if problems:
            rejected.append({"id": job["id"], "problems": problems})
            continue
        if job["step"] == "hop1":
            continue  # recorded through its hop2

        canonical = (jobs_dir / "prompts" / f"{job['id']}.txt").read_text(encoding="utf-8")
        if _sha(canonical) != job["prompt_sha"]:
            raise ValueError(f"{job['id']}: prompt file does not match its recorded sha")
        intermediate = None
        if job["step"] == "imitation":
            expected = gen._imitation_prompt(profile)
            prompt_sha = _sha(expected)
        elif job["step"] == "paraphrase":
            expected = gen._paraphrase_prompt(source)
            prompt_sha = _sha(expected)
        else:  # hop2
            hop1 = jobs[job["hop1_id"]]
            intermediate = _read_output(hop1)
            there = gen._translate_prompt(source, gen._LANGUAGE_NAMES[job["language"]])
            expected = gen._translate_prompt(intermediate, "English")
            prompt_sha = _sha(there + HOP_SEP + expected)
        if canonical != expected:
            raise ValueError(f"{job['id']}: prompt file is not the generator's prompt")
        entry = {
            "model_id": model_id,
            "prompt_sha": prompt_sha,
            "doc_sha": _sha(text),
            "victim_id": job["victim_id"],
            "attack": job["attack"],
            "n_baselines": job["n_baselines"],
            "route": ROUTE,
            "generated_on": generated_on,
        }
        if intermediate is not None:
            entry["intermediate_sha"] = _sha(intermediate)
            job_stats = {
                **job_stats,
                "hop1": {**stats[job["hop1_id"]]},
            }
        entries.append(entry)
        log_rows.append({"doc_sha": entry["doc_sha"], "job": job["id"], **job_stats})
        docs.append((entry, text, intermediate, job.get("language")))

    result = {
        "written": [e["doc_sha"] for e in entries],
        "rejected": rejected,
        "pending": pending,
        "stats": stats,
    }
    if rejected or dry_run:
        result["written"] = []
        return result

    for entry, text, intermediate, lang in docs:
        gen._write_doc(out_dir, entry["attack"], entry["victim_id"], entry["doc_sha"], text)
        if intermediate is not None:
            path = (
                out_dir
                / "_intermediate"
                / entry["attack"]
                / entry["victim_id"]
                / f"{entry['doc_sha']}.{lang}.txt"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(intermediate, encoding="utf-8")
    manifest_path = out_dir / "manifest.json"
    merged = gen._merge_entries(gen._load_existing_manifest(manifest_path), entries)
    merged.sort(key=lambda e: (e["attack"], e["victim_id"], e["n_baselines"], e["doc_sha"]))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"entries": merged}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    log_path = out_dir / "generation_log.json"
    old = json.loads(log_path.read_text(encoding="utf-8"))["docs"] if log_path.exists() else []
    by_sha = {row["doc_sha"]: row for row in old}
    by_sha.update({row["doc_sha"]: row for row in log_rows})
    log_path.write_text(
        json.dumps(
            {"docs": sorted(by_sha.values(), key=lambda r: r["job"])}, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    return result


# --- CLI ------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m validation.adversarial.llm_attack_jobs")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_jobs = sub.add_parser("jobs", help="write first-step prompt files")
    p_jobs.add_argument("--jobs-dir", type=Path, required=True)
    p_jobs.add_argument("--n-baselines", default="3,5,10")
    p_jobs.add_argument("--attacks", default=",".join(gen._ATTACK_CHOICES))
    p_jobs.add_argument("--victims", default=None)
    p_jobs.add_argument("--seed", type=int, default=gen._DEFAULT_SEED)

    p_hop2 = sub.add_parser("hop2", help="write back-translation prompts for finished first hops")
    p_hop2.add_argument("--jobs-dir", type=Path, required=True)

    p_asm = sub.add_parser("assemble", help="check outputs and write corpus/llm_attacks/")
    p_asm.add_argument("--jobs-dir", type=Path, required=True)
    p_asm.add_argument("--out-dir", type=Path, default=gen._DEFAULT_CACHE_DIR)
    p_asm.add_argument("--model", required=True, help="exact model id the subagents ran on")
    p_asm.add_argument("--seed", type=int, default=gen._DEFAULT_SEED)
    p_asm.add_argument("--generated-on", default=date.today().isoformat())
    p_asm.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "jobs":
        planned = plan_jobs(
            gen._parse_int_list(args.n_baselines),
            gen._parse_str_list(args.attacks) or list(gen._ATTACK_CHOICES),
            gen._parse_str_list(args.victims),
            args.seed,
        )
        written = write_jobs(args.jobs_dir, planned)
        for job in written:
            print(job["id"])
        print(f"{len(written)} job(s) in {args.jobs_dir}")
        return 0
    if args.cmd == "hop2":
        written = write_hop2_jobs(args.jobs_dir)
        for job in written:
            print(job["id"])
        print(f"{len(written)} second-hop job(s)")
        return 0
    result = assemble(
        args.jobs_dir, args.out_dir, args.model, args.seed, args.generated_on, args.dry_run
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["rejected"] else 0


if __name__ == "__main__":
    sys.exit(main())
