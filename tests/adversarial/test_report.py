"""
tests/adversarial/test_report.py: the SP1 harness run (Tasks 18-20).

Covers how `validation.adversarial.report` builds cells (public authors,
the LLM cache, Riddell-Juola), how it scopes the live scoring flags, and the
reducers that turn rows into gate inputs. Scoring itself is the runner's
job and is covered in test_runner.py; nothing here scores a real corpus.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile

import pytest

from validation.adversarial import fetch_riddell_juola as rj
from validation.adversarial import report
from validation.adversarial.generators import _LLMCacheGenerator
from validation.adversarial.profiles import VictimProfile

# ── Cell construction ──────────────────────────────────────────────────────


def test_public_author_cells_mark_injected_positions():
    cells = report.build_cells(
        kinds=("clean", "sigma_inflation", "outsourced_baselines"), ns=(3,), seed=1
    )
    by_kind: dict[str, list] = {}
    for cell in cells:
        by_kind.setdefault(cell.kind, []).append(cell)
    assert len(by_kind["clean"]) == len(by_kind["sigma_inflation"]) == 13
    assert all(c.injected_indices == () for c in by_kind["clean"])
    # sigma_inflation replaces a strict minority: one of three at N=3.
    assert all(len(c.injected_indices) == 1 for c in by_kind["sigma_inflation"])
    assert all(c.injected_indices == (0, 1, 2) for c in by_kind["outsourced_baselines"])
    assert {c.attack for c in by_kind["clean"]} == {"none"}


def test_kinds_for_legs_dedupes_in_order():
    assert report.kinds_for_legs(["G-A1", "G-A5"]) == ("clean", "rj_clean", "sigma_inflation")


def test_no_llm_or_rj_cells_without_their_corpora(tmp_path, monkeypatch):
    monkeypatch.setattr(_LLMCacheGenerator, "CACHE_DIR", tmp_path / "absent")
    monkeypatch.setattr(rj, "CORPUS_DIR", tmp_path)
    cells = report.build_cells(kinds=report.LLM_KINDS + report.RJ_KINDS, ns=(3,))
    assert cells == []
    assert report.llm_cache_status()["present"] is False
    assert report.riddell_juola_status()["participant_baselines_present"] is False


def _write_llm_cache(root, victim_id):
    entries = []
    for attack, n, text in [
        ("imitation", 3, "an imitation written from three essays"),
        ("imitation", 5, "an imitation written from five essays"),
        ("paraphrase", 3, "a paraphrase of the holdout"),
    ]:
        sha = hashlib.sha256(text.encode()).hexdigest()
        path = root / attack / victim_id / f"{sha}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        entries.append(
            {"model_id": "m", "prompt_sha": "p", "doc_sha": sha, "victim_id": victim_id,
             "attack": attack, "n_baselines": n}
        )
    (root / "manifest.json").write_text(json.dumps({"entries": entries}))


def test_llm_cells_score_imitations_only_at_their_own_n(tmp_path, monkeypatch):
    _write_llm_cache(tmp_path, "emerson")
    monkeypatch.setattr(_LLMCacheGenerator, "CACHE_DIR", tmp_path)
    cells = report.build_cells(kinds=("llm_imitation", "llm_paraphrase"), ns=(3, 5))
    got = {(c.kind, c.n): c.profile.impostor_docs for c in cells}
    assert got[("llm_imitation", 3)] == ["an imitation written from three essays"]
    assert got[("llm_imitation", 5)] == ["an imitation written from five essays"]
    # Paraphrases rewrite the holdout, which does not depend on N.
    assert got[("llm_paraphrase", 3)] == got[("llm_paraphrase", 5)]
    assert all(c.profile.genuine_holdout == [] for c in cells)
    assert report.llm_cache_status()["present"] is True


def _write_rj_corpus(root, chunks_per_participant=6):
    essays = {"control": ["c1", "c2", "c3"], "obfuscation": ["o1"], "imitation": ["i1"]}
    for condition, pids in essays.items():
        (root / condition).mkdir(parents=True)
        for pid in pids:
            (root / condition / f"{pid}.txt").write_text(f"{condition} essay by {pid}")
            base = root / "baselines" / pid
            base.mkdir(parents=True)
            for k in range(chunks_per_participant):
                (base / f"{pid}_{k:02d}.txt").write_text(f"prior chunk {k} by {pid}")


def test_rj_cells_pair_each_essay_with_its_authors_prior_writing(tmp_path, monkeypatch):
    _write_rj_corpus(tmp_path)
    monkeypatch.setattr(rj, "CORPUS_DIR", tmp_path)
    cells = report.build_cells(kinds=report.RJ_KINDS, ns=(3,), seed=1)
    by_kind: dict[str, list] = {}
    for cell in cells:
        by_kind.setdefault(cell.kind, []).append(cell)

    clean = {c.profile.victim_id: c for c in by_kind["rj_clean"]}
    assert sorted(clean) == ["c1", "c2", "c3"]
    c1 = clean["c1"].profile
    assert c1.genuine_holdout == ["control essay by c1"]
    assert all(chunk.endswith("by c1") for chunk in c1.baselines) and len(c1.baselines) == 3
    assert sorted(c1.impostor_docs) == ["control essay by c2", "control essay by c3"]

    embedded = {c.profile.victim_id: c for c in by_kind["rj_embedded_obfuscation"]}
    o1 = embedded["o1"]
    assert o1.injected_indices == (2,)
    assert o1.profile.baselines[-1] == "obfuscation essay by o1"
    assert o1.profile.genuine_holdout[0] not in o1.profile.baselines
    assert [c.profile.victim_id for c in by_kind["rj_embedded_control"]] == ["c1", "c2", "c3"]
    assert by_kind["rj_self_imitation"][0].profile.impostor_docs == ["imitation essay by i1"]
    assert "rj_self_control" not in by_kind
    assert report.riddell_juola_status()["participants_with_baselines"] == 5


def test_rj_participants_need_one_chunk_beyond_n(tmp_path, monkeypatch):
    _write_rj_corpus(tmp_path, chunks_per_participant=3)
    monkeypatch.setattr(rj, "CORPUS_DIR", tmp_path)
    assert report.build_cells(kinds=("rj_clean",), ns=(3,)) == []


def test_extract_participant_baselines_takes_only_split_participants(tmp_path):
    (tmp_path / "control").mkdir()
    (tmp_path / "control" / "aa11bb.txt").write_text("essay")
    buf = io.BytesIO()
    prefix = rj._BUNDLE_CORPUS_PREFIX
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{prefix}aa11bb/aa11bb_02.txt", "chunk two")
        zf.writestr(f"{prefix}aa11bb/aa11bb_03.txt", "chunk three")
        zf.writestr(f"{prefix}ffffff/ffffff_02.txt", "not in any split")
        zf.writestr(f"{prefix}attacks_control/aa11bb.txt", "essay")
    counts = rj.extract_participant_baselines(buf.getvalue(), dest=tmp_path)
    assert counts == {"aa11bb": 2}
    assert rj.load_riddell_juola_baselines(tmp_path) == {"aa11bb": ["chunk two", "chunk three"]}
    assert rj.load_riddell_juola_split_by_id("control", tmp_path) == {"aa11bb": "essay"}


def test_split_by_id_rejects_unknown_and_missing(tmp_path):
    with pytest.raises(ValueError):
        rj.load_riddell_juola_split_by_id("nope", tmp_path)
    with pytest.raises(FileNotFoundError):
        rj.load_riddell_juola_split_by_id("control", tmp_path)


# ── Running ────────────────────────────────────────────────────────────────


def test_run_cells_scopes_the_live_flags_and_restores_the_callers(monkeypatch):
    from validation.adversarial import runner

    seen = []

    def fake_run_attack(profile, attack, path="score", **kw):
        seen.append(os.environ["TYPICALITY_SCORING"])
        return runner.AttackResult(
            victim_id=profile.victim_id, attack=attack, path=path, n_baselines=3,
            holdout_actions=("no_action",), impostor_actions=(), holdout_max_action="no_action",
            impostor_max_action=None, imitation_success=None, poisoning_success=None,
            sigma_proxy=None, holdout_scores=(0.1,),
        )

    monkeypatch.setattr(runner, "run_attack", fake_run_attack)
    monkeypatch.setenv("TYPICALITY_SCORING", "1")
    profile = VictimProfile("v", ["a", "b", "c"], ["d"], [])
    cells = [report.Cell("public_authors", "clean", 3, "none", profile)]
    rows = report.run_cells(cells, path="api", workers=1)
    assert seen == ["0"]
    assert os.environ["TYPICALITY_SCORING"] == "1"
    assert rows[0]["kind"] == "clean" and rows[0]["holdout_scores"] == [0.1]


def test_default_workers_honours_the_env(monkeypatch):
    monkeypatch.setenv("ADVERSARIAL_WORKERS", "3")
    assert report.default_workers() == 3
    monkeypatch.delenv("ADVERSARIAL_WORKERS")
    assert 1 <= report.default_workers() <= 8


# ── Reducers ───────────────────────────────────────────────────────────────


def _row(kind, n=3, victim="v", corpus="public_authors", **over):
    row = {
        "corpus": corpus, "kind": kind, "n": n, "victim_id": victim,
        "injected_indices": [], "impostor_in_baseline": [], "n_baseline_docs": n,
        "holdout_actions": ["no_action"], "holdout_scores": [0.2],
        "impostor_actions": ["monitor", "no_action"], "impostor_scores": [0.7, 0.3],
        "held_baseline_indices": [], "baseline_integrity": None,
        "mean_baseline_std": 0.09, "scoring_refused": False,
    }
    row.update(over)
    return row


def test_ga1_inputs_pool_corpora_per_n():
    rows = [
        _row("clean", n=3),
        _row("rj_clean", n=3, corpus="riddell_juola", holdout_actions=["monitor"]),
        _row("clean", n=5, scoring_refused=True, holdout_actions=[]),
        _row("sigma_inflation", n=3, holdout_actions=["escalate"]),
    ]
    got = report.ga1_inputs(rows)
    assert got["holdout_actions_by_n"] == {3: ["no_action", "monitor"], 5: []}
    assert got["by_corpus_n"]["riddell_juola"] == {3: ["monitor"]}
    assert got["refused_by_n"] == {5: 1}


def test_attack_populations_use_the_same_victims_clean_holdouts():
    rows = [
        _row("clean", victim="a", holdout_scores=[0.1]),
        _row("clean", victim="b", holdout_scores=[0.2]),
        _row("llm_imitation", victim="a", impostor_actions=["monitor"], impostor_scores=[0.9]),
    ]
    (pop,) = report.attack_populations(rows, ("llm_imitation",))
    assert pop["name"] == "llm_imitation N=3" and pop["family"] == "llm_imitation"
    assert pop["attack_scores"] == [0.9] and pop["genuine_scores"] == [0.1]
    assert pop["coverage"] == [1, 2]


def test_populations_are_split_by_n_never_pooled():
    rows = [_row("clean", n=3), _row("clean", n=5), _row("rj_clean", n=3, corpus="riddell_juola")]
    names = [p["name"] for p in report.peer_swap_populations(rows)]
    assert names == [
        "public_authors/peer_swap N=3",
        "public_authors/peer_swap N=5",
        "riddell_juola/peer_swap_same_prompt N=3",
    ]


def test_ga5_cells_pair_victims_and_drop_refused_pairs():
    rows = [
        _row("clean", victim="a", impostor_actions=["monitor", "monitor"], mean_baseline_std=0.08),
        _row("sigma_inflation", victim="a", impostor_actions=["monitor", "no_action"],
             mean_baseline_std=0.10, injected_indices=[1]),
        _row("clean", victim="b"),
        _row("sigma_inflation", victim="b", scoring_refused=True, impostor_actions=[]),
        _row("clean", victim="c"),
        _row("sigma_inflation", victim="c", injected_indices=[2], held_baseline_indices=[2]),
        _row("clean", victim="unpaired"),
    ]
    (cell,) = report.ga5_inputs(rows)["cells"]
    # a fired; b refused (dropped from both sides); c's injection was held.
    assert (cell["n_pairs"], cell["n_refused"], cell["n_held"]) == (1, 1, 1)
    assert (cell["clean_caught"], cell["clean_n"]) == (2, 2)
    assert (cell["inflated_caught"], cell["inflated_n"]) == (1, 2)
    assert cell["clean_mean_sigma"] == pytest.approx(0.08)


def test_ga6_detection_maps_outliers_through_held_documents():
    # Baseline [0, 1, 2]; the drift gate held 0, so the admitted samples are
    # [1, 2] and integrity index 1 means document 2, the injected one.
    hit = _row("rj_embedded_obfuscation", corpus="riddell_juola", injected_indices=[2],
               held_baseline_indices=[0],
               baseline_integrity={"loo_outlier_samples": [{"index": 1, "z": 4.0}]})
    wrong_doc = _row("rj_embedded_obfuscation", corpus="riddell_juola", injected_indices=[2],
                     baseline_integrity={"loo_outlier_samples": [{"index": 0, "z": 4.0}]})
    held = _row("outsourced_baselines", injected_indices=[0, 1, 2], held_baseline_indices=[1])
    clean_quiet = _row("clean")
    clean_noted = _row("clean", baseline_integrity={"loo_outlier_samples": [{"index": 2}]})
    got = report.ga6_inputs([hit, wrong_doc, held, clean_quiet, clean_noted])
    assert got["poisoned"]["riddell_juola/embedded_obfuscation N=3"] == (1, 2)
    assert got["poisoned"]["public_authors/outsourced_baselines N=3"] == (1, 1)
    assert got["clean"]["public_authors/clean N=3"] == (1, 2)
    assert got["informational"]["drift_holds_on_injected"] == {
        "public_authors/outsourced_baselines N=3": (1, 1),
        "riddell_juola/embedded_obfuscation N=3": (0, 2),
    }


def test_merge_reports_refuses_overlapping_cells():
    a = {"meta": {"riddell_juola": {"participant_baselines_present": False}},
         "rows": [_row("clean")]}
    b = {"meta": {"riddell_juola": {"participant_baselines_present": True}},
         "rows": [_row("rj_clean", corpus="riddell_juola")]}
    merged = report.merge_reports([a, b])
    assert len(merged["rows"]) == 2
    assert merged["meta"]["riddell_juola"]["participant_baselines_present"] is True
    with pytest.raises(ValueError):
        report.merge_reports([a, a])


def test_summarize_reports_rates_per_bar():
    summary = report.summarize([_row("clean")])
    entry = summary["public_authors/clean/N=3"]
    assert entry["impostor"]["rate_at_or_above"]["monitor"] == 0.5
    assert entry["holdout"]["n"] == 1


def test_main_reuse_recomputes_gates_without_scoring(tmp_path):
    earlier = tmp_path / "earlier.json"
    earlier.write_text(json.dumps({"meta": {"seed": 1, "llm_attacks": {"present": False}},
                                   "rows": [_row("clean")]}))
    out = tmp_path / "out.json"
    assert report.main(["--out", str(out), "--reuse", str(earlier)]) == 0
    written = json.loads(out.read_text())
    assert [g["name"] for g in written["gates"]] == list(report.LEG_KINDS)
    assert written["meta"]["reused_from"] == [str(earlier)]


# ── Runner: the live route's refusal path ──────────────────────────────────


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


class _RefusingClient:
    """Holds every baseline after the first and then refuses to score, the
    way the live route does when the drift gate leaves fewer than three."""

    def __init__(self):
        self.baselines = 0

    def post(self, url, json):
        if url.endswith("/baseline"):
            self.baselines += 1
            return _Resp(200 if self.baselines == 1 else 409, {})
        return _Resp(422, {"detail": {"code": "insufficient_baseline"}})


def test_api_path_records_a_refusal_instead_of_crashing():
    from validation.adversarial.runner import run_attack

    profile = VictimProfile("v", ["a", "b", "c"], ["d"], ["e"])
    result = run_attack(profile, "none", path="api", client=_RefusingClient())
    assert result.scoring_refused is True
    assert result.held_baseline_indices == (1, 2)
    assert result.holdout_actions == () and result.impostor_actions == ()
    assert result.baseline_integrity is None


def test_api_path_still_raises_on_an_unexpected_422():
    from validation.adversarial.runner import _post_score

    class _Client:
        def post(self, url, json):
            return _Resp(422, {"detail": "validation error"})

    with pytest.raises(RuntimeError):
        _post_score(_Client(), "s", "t", "x")


def test_summarize_reports_the_collections_mark_on_ready_baselines_only():
    ready = _row("clean", baseline_integrity={"readiness": "ready"},
                 holdout_probabilities=[0.694, 0.695])
    thin = _row("clean", victim="w", baseline_integrity={"readiness": "thin"},
                holdout_probabilities=[0.1])
    entry = report.summarize([ready, thin])["public_authors/clean/N=3"]
    assert entry["holdout"]["collections_mark_rate"] == 0.5


def test_dumps_report_is_json_with_one_line_per_row():
    rep = {"meta": {"seed": 1}, "gates": [], "rows": [_row("clean"), _row("clean", victim="w")]}
    text = report.dumps_report(rep)
    assert json.loads(text) == json.loads(json.dumps(rep))
    row_lines = [line for line in text.splitlines() if line.startswith('    {"baseline_integrity"')]
    assert len(row_lines) == 2


def test_sigma_inflation_cells_mark_the_donor_document_when_it_is_also_a_peer():
    cells = report.build_cells(
        kinds=("clean", "sigma_inflation"), ns=(3,), seed=report.HARNESS_SEED
    )
    leaks = {
        c.profile.victim_id: c.impostor_in_baseline for c in cells if c.kind == "sigma_inflation"
    }
    assert any(leaks.values())  # the donor pool and the peer pool overlap
    for cell in cells:
        if cell.kind == "clean":
            assert cell.impostor_in_baseline == ()


def test_ga5_drops_leaked_documents_on_both_sides_of_the_pair():
    rows = [
        _row("clean", impostor_actions=["monitor", "monitor"], impostor_scores=[0.7, 0.7]),
        _row("sigma_inflation", impostor_actions=["no_action", "monitor"],
             impostor_scores=[0.1, 0.7], injected_indices=[1], impostor_in_baseline=[0],
             mean_baseline_std=0.2),
    ]
    (cell,) = report.ga5_inputs(rows)["cells"]
    assert cell["n_leaked_docs"] == 1
    assert (cell["clean_caught"], cell["clean_n"]) == (1, 1)
    assert (cell["inflated_caught"], cell["inflated_n"]) == (1, 1)
    assert cell["inflated_impostor_scores"] == [0.7]


def test_attach_cell_metadata_rederives_and_checks_rows():
    cells = report.build_cells(kinds=("sigma_inflation",), ns=(3,), seed=report.HARNESS_SEED)
    cell = cells[0]
    row = _row("sigma_inflation", victim=cell.profile.victim_id,
               injected_indices=list(cell.injected_indices))
    del row["impostor_in_baseline"]
    assert report.attach_cell_metadata([row], report.HARNESS_SEED, (3,)) == 1
    assert row["impostor_in_baseline"] == list(cell.impostor_in_baseline)
    bad = _row("sigma_inflation", victim=cell.profile.victim_id, injected_indices=[99])
    del bad["impostor_in_baseline"]
    with pytest.raises(ValueError):
        report.attach_cell_metadata([bad], report.HARNESS_SEED, (3,))
