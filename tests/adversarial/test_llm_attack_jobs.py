"""Tests for validation/adversarial/llm_attack_jobs.py, the no-API-key route
that builds corpus/llm_attacks/ from Claude subagent outputs.

What these pin: the prompts are gen_llm_attacks's own (so prompt_sha means
the same thing on both routes), the display copy differs from the prompt
in whitespace only, dash markers are restored, a bad output is rejected
before anything is written, and a finished run reads back through the
cache readers the gates use."""

from __future__ import annotations

import hashlib
import json

import pytest

from validation.adversarial import gen_llm_attacks as gen
from validation.adversarial import llm_attack_jobs as jobs_mod
from validation.adversarial.generators import LLMImitation, LLMParaphrase, LLMRoundTrip
from validation.adversarial.profiles import build_victim_profiles

EM = "\u2014"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -- display_wrap ----------------------------------------------------------------


def test_display_wrap_changes_only_spaces_into_newlines():
    text = " ".join(f"word{i}" for i in range(2000)) + "\n\nshort line\n"
    wrapped = jobs_mod.display_wrap(text, width=100)
    assert all(len(line) <= 100 for line in wrapped.split("\n"))
    assert wrapped.replace("\n", " ") == text.replace("\n", " ")
    assert len(wrapped) == len(text)


def test_display_wrap_breaks_japanese_after_a_full_stop():
    sentence = "\u3053\u308c\u306f\u6587\u3067\u3059\u3002"  # 7 characters, ends in U+3002
    text = sentence * 40
    wrapped = jobs_mod.display_wrap(text, width=50)
    assert wrapped.replace("\n", "") == text
    assert all(line.endswith("\u3002") for line in wrapped.split("\n"))
    assert all(len(line) <= 50 for line in wrapped.split("\n"))


def test_restore_markers_counts_and_replaces():
    text, n = jobs_mod.restore_markers("a [[EMDASH]] b [[EMDASH]][[EMDASH]] c [[HBAR]]")
    assert n == 4
    assert text == f"a {EM} b {EM}{EM} c \u2015"


# -- planning --------------------------------------------------------------------


def test_plan_jobs_uses_the_api_routes_prompts():
    planned = jobs_mod.plan_jobs([3, 5], list(gen._ATTACK_CHOICES), ["mill"], seed=1729)
    profiles = {n: {p.victim_id: p for p in build_victim_profiles(n, 1729)} for n in (3, 5)}
    by_id = {j["id"]: j for j in planned}
    assert by_id["imitation__mill__n3"]["prompt"] == gen._imitation_prompt(profiles[3]["mill"])
    assert by_id["imitation__mill__n5"]["prompt"] == gen._imitation_prompt(profiles[5]["mill"])
    source = profiles[3]["mill"].genuine_holdout[1]
    assert by_id["paraphrase__mill__h1"]["prompt"] == gen._paraphrase_prompt(source)
    assert by_id["roundtrip_ja__mill__h1__hop1"]["prompt"] == gen._translate_prompt(
        source, "Japanese"
    )
    # Holdout attacks once per victim, at the first N, as gen_llm_attacks._run does.
    holdout = [j for j in planned if j["step"] != "imitation"]
    assert {j["n_baselines"] for j in holdout} == {3}
    assert len(holdout) == 2 * 3  # 2 holdouts x (paraphrase + 2 first hops)


def test_plan_jobs_rejects_an_unknown_attack():
    with pytest.raises(ValueError, match="unknown attack"):
        jobs_mod.plan_jobs([3], ["imitation", "summarize"], None, seed=1729)


# -- end to end --------------------------------------------------------------------


def _german(n_words: int) -> str:
    base = "der Mann und die Frau sind nicht das Haus es ist gut".split()
    return " ".join(base[i % len(base)] for i in range(n_words))


def _run_jobs(tmp_path):
    jobs_dir = tmp_path / "jobs"
    planned = jobs_mod.plan_jobs(
        [3], ["imitation", "paraphrase", "roundtrip_de"], ["mill"], seed=1729
    )
    jobs_mod.write_jobs(jobs_dir, planned)
    profile = {p.victim_id: p for p in build_victim_profiles(3, 1729)}["mill"]
    recorded = jobs_mod._load_jobs(jobs_dir)
    for job in recorded.values():
        out = jobs_mod.Path(job["output_file"])
        if job["step"] == "imitation":
            out.write_text(" ".join(f"novel{i}" for i in range(600)) + " [[EMDASH]] end")
        elif job["step"] == "paraphrase":
            out.write_text(profile.genuine_holdout[job["holdout_index"]])
        else:
            out.write_text(_german(2400) + " [[EMDASH]] Ende")
    second = jobs_mod.write_hop2_jobs(jobs_dir)
    assert {j["id"] for j in second} == {
        "roundtrip_de__mill__h0__hop2",
        "roundtrip_de__mill__h1__hop2",
    }
    for job in second:
        source = profile.genuine_holdout[job["holdout_index"]]
        jobs_mod.Path(job["output_file"]).write_text(source.replace(", ", " [[EMDASH]] ", 1))
    return jobs_dir, profile


def test_assemble_writes_a_cache_the_gate_readers_load(tmp_path, monkeypatch):
    jobs_dir, profile = _run_jobs(tmp_path)
    out_dir = tmp_path / "llm_attacks"
    result = jobs_mod.assemble(jobs_dir, out_dir, "claude-test-model", 1729, "2026-11-19")
    assert result["rejected"] == [] and result["pending"] == []
    assert len(result["written"]) == 1 + 2 + 2

    for cls in (LLMImitation, LLMParaphrase, LLMRoundTrip):
        monkeypatch.setattr(cls, "CACHE_DIR", out_dir)
    imitation = LLMImitation("mill").load_entries()
    assert len(imitation) == 1 and EM in imitation[0][1]
    assert imitation[0][0]["prompt_sha"] == _sha(gen._imitation_prompt(profile))
    assert imitation[0][0]["route"] == jobs_mod.ROUTE
    assert imitation[0][0]["model_id"] == "claude-test-model"

    paraphrases = LLMParaphrase("mill").load_entries()
    assert {e["prompt_sha"] for e, _ in paraphrases} == {
        _sha(gen._paraphrase_prompt(s)) for s in profile.genuine_holdout
    }

    trips = LLMRoundTrip("mill", "de").load_entries()
    assert len(trips) == 2
    for entry, text in trips:
        assert EM in text
        hop1 = (
            out_dir / "_intermediate" / "roundtrip_de" / "mill" / f"{entry['doc_sha']}.de.txt"
        ).read_text(encoding="utf-8")
        assert entry["intermediate_sha"] == _sha(hop1) and hop1.endswith(f"{EM} Ende")
        sources = [
            s
            for s in profile.genuine_holdout
            if entry["prompt_sha"]
            == _sha(
                gen._translate_prompt(s, "German")
                + jobs_mod.HOP_SEP
                + gen._translate_prompt(hop1, "English")
            )
        ]
        assert len(sources) == 1

    log = json.loads((out_dir / "generation_log.json").read_text())["docs"]
    assert {row["doc_sha"] for row in log} == set(result["written"])
    expected_markers = {"imitation": 1, "paraphrase": 0, "roundtrip_de": 1}
    for row in log:
        assert row["dash_markers_restored"] == expected_markers[row["job"].split("__")[0]]
        if row["job"].startswith("roundtrip"):
            assert row["hop1"]["dash_markers_restored"] == 1

    # A second assembly of the same outputs is idempotent.
    again = jobs_mod.assemble(jobs_dir, out_dir, "claude-test-model", 1729, "2026-11-19")
    assert sorted(again["written"]) == sorted(result["written"])
    manifest = json.loads((out_dir / "manifest.json").read_text())["entries"]
    assert len(manifest) == 5


@pytest.mark.parametrize(
    ("bad_output", "problem"),
    [
        ("Here is the rewritten text:\n\n" + "word " * 2500, "preamble"),
        ("word " * 400, "length ratio"),
        ("word " * 2500 + "[[ EMDASH ]]", "unrestored marker"),
    ],
)
def test_a_bad_output_rejects_the_whole_assembly(tmp_path, bad_output, problem):
    jobs_dir, _ = _run_jobs(tmp_path)
    jobs = jobs_mod._load_jobs(jobs_dir)
    jobs_mod.Path(jobs["paraphrase__mill__h0"]["output_file"]).write_text(bad_output)
    out_dir = tmp_path / "llm_attacks"
    result = jobs_mod.assemble(jobs_dir, out_dir, "claude-test-model", 1729, "2026-11-19")
    assert [r["id"] for r in result["rejected"]] == ["paraphrase__mill__h0"]
    assert problem in " ".join(result["rejected"][0]["problems"])
    assert result["written"] == [] and not out_dir.exists()


def test_first_person_prose_is_not_a_preamble():
    job = {"step": "imitation"}
    text = "I have lately been employed by a neighbor to run the lines of his farm. " * 40
    problems, _ = jobs_mod.check_output(job, text, None, [])
    assert not any("preamble" in p for p in problems)
    problems, _ = jobs_mod.check_output(job, "I have rewritten it below. " + text, None, [])
    assert any("preamble" in p for p in problems)


def test_an_imitation_that_copies_its_baselines_is_rejected(tmp_path):
    jobs_dir, profile = _run_jobs(tmp_path)
    jobs = jobs_mod._load_jobs(jobs_dir)
    copied = " ".join(profile.baselines[0].split()[:700])
    jobs_mod.Path(jobs["imitation__mill__n3"]["output_file"]).write_text(copied)
    result = jobs_mod.assemble(jobs_dir, tmp_path / "out", "m", 1729, "2026-11-19")
    assert "copies its baselines" in " ".join(result["rejected"][0]["problems"])


def test_unfinished_jobs_are_reported_pending_not_written(tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_mod.write_jobs(jobs_dir, jobs_mod.plan_jobs([3], ["imitation"], ["mill"], seed=1729))
    result = jobs_mod.assemble(jobs_dir, tmp_path / "out", "m", 1729, "2026-11-19")
    assert result["pending"] == ["imitation__mill__n3"] and result["written"] == []
