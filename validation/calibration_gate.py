"""
validation/calibration_gate.py — Phase 0 calibration gates (G1-G6) for the
two-axis authorship verification redesign.

Run:
    python -m validation.calibration_gate
    python -m validation.calibration_gate --out /tmp/gate_report.json

Follows validation/plato/gate.py's shape: one dataclass per gate result
with a `passed: bool`, a pure `run()`, a `render()`, and a `main()` whose
exit code is 0 iff every gate passed — so CI fails automatically.

G1-G4 are implemented here against seminary + public_authors + Plato,
scored via the in-process TestClient with TYPICALITY_SCORING=1 (the same
"production-realistic in-process" pattern every other validation runner in
this repo uses — see validation/public_authors/run.py's docstring).
G5 (permutation-null control) is added once scripts/derive_measured_weights.py
exists (Phase 3). G2b (paraphrase-resistant) and G6 (native_english fairness)
are added once original/features/uniformity.py exists (Phase 4).
"""

from __future__ import annotations

# Lock the env BEFORE any original.* import.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402

ENV_LOCK = lock_environment()

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    criterion: str
    current_value: str
    detail: dict = field(default_factory=dict)


# ── Pure gate-evaluation logic (unit-tested in tests/test_calibration_gate.py) ─


def evaluate_g1_fpr(pooled_actions: list[str], per_corpus: dict[str, list[str]]) -> GateResult:
    """
    G1 — Same-author FPR. Pooled flagged rate (action != "no_action") must
    be <= 5%. Also reports per-corpus flagged rate so a pooled pass cannot
    hide an individual corpus running well above budget (Bates et al.'s
    marginal-not-conditional-validity finding — see design spec §10).
    """
    n = len(pooled_actions)
    flagged = sum(1 for a in pooled_actions if a != "no_action")
    pooled_rate = flagged / n if n else 1.0

    per_corpus_rate = {}
    for corpus, actions in per_corpus.items():
        cn = len(actions)
        cflagged = sum(1 for a in actions if a != "no_action")
        per_corpus_rate[corpus] = cflagged / cn if cn else 1.0

    passed = pooled_rate <= 0.05
    return GateResult(
        name="G1",
        passed=passed,
        criterion="pooled flagged rate <= 5%",
        current_value=f"{pooled_rate:.1%}",
        detail={
            "n": n,
            "flagged": flagged,
            "pooled_flagged_rate": pooled_rate,
            "per_corpus_flagged_rate": per_corpus_rate,
        },
    )


def evaluate_g2_bland_impostor(holdout_q: list[float], impostor_q: list[float]) -> GateResult:
    """
    G2 — Bland impostor. q = min(p_far, p_central) (the two-sided
    typicality). Median impostor q must be <= median holdout q — an
    impostor must not look MORE typical than genuine work.
    """
    import statistics

    med_holdout = statistics.median(holdout_q) if holdout_q else float("nan")
    med_impostor = statistics.median(impostor_q) if impostor_q else float("nan")
    passed = med_impostor <= med_holdout
    return GateResult(
        name="G2",
        passed=passed,
        criterion="median(impostor q) <= median(holdout q)",
        current_value=f"impostor={med_impostor:.3f}, holdout={med_holdout:.3f}",
        detail={"holdout_q": holdout_q, "impostor_q": impostor_q},
    )


def evaluate_g3_attribution(top1_accuracy: float) -> GateResult:
    """G3 — Attribution non-regression. Existing bar: >= 0.7."""
    passed = top1_accuracy >= 0.7
    return GateResult(
        name="G3",
        passed=passed,
        criterion="public_authors top-1 accuracy >= 0.7",
        current_value=f"{top1_accuracy:.3f}",
        detail={"top1_accuracy": top1_accuracy},
    )


def evaluate_g4_career_drift_monotone(group_means: dict[str, float]) -> GateResult:
    """
    G4 — Career-drift sanity. group_means keyed by "early"/"middle"/"late",
    values are mean typicality distance from an early-group baseline.
    Must be non-decreasing early -> middle -> late.
    """
    order = ["early", "middle", "late"]
    values = [group_means[k] for k in order if k in group_means]
    passed = all(values[i] <= values[i + 1] for i in range(len(values) - 1)) and len(values) == 3
    return GateResult(
        name="G4",
        passed=passed,
        criterion="early <= middle <= late (typicality distance from early baseline)",
        current_value=str(group_means),
        detail={"group_means": group_means},
    )


# ── Corpus-driving orchestration (exercised by `main()`, not unit-tested) ──────


def _score_corpus_for_g1(client, sid_prefix: str, texts_by_id: dict[str, list[str]]) -> tuple[list[str], dict[str, list[str]]]:
    """
    For each id in texts_by_id with >= 5 texts: build a baseline from all
    but one text (leave-one-out over WHOLE documents, not chunks), score
    the held-out text, record its recommendation.action. Repeat holding out
    each text in turn. Requires TYPICALITY_SCORING=1 already set in os.environ
    before `client` was constructed (env is read at score() call time, so
    this also works if set right before this call — see
    validation/verify/run_null_model.py's docstring on this point).
    """
    pooled: list[str] = []
    per_corpus: dict[str, list[str]] = {}
    for entity_id, texts in texts_by_id.items():
        if len(texts) < 5:
            continue
        actions: list[str] = []
        for held_out_idx in range(len(texts)):
            sid = f"gate:{sid_prefix}_{entity_id}_{held_out_idx}"
            for i, text in enumerate(texts):
                if i == held_out_idx:
                    continue
                client.post(
                    f"/students/{sid}/baseline",
                    json={"text": text, "provenance": "verified", "submitted_at": "2026-01-01"},
                )
            r = client.post(
                f"/students/{sid}/score",
                json={"text": texts[held_out_idx], "submission_id": f"{entity_id}_{held_out_idx}"},
            )
            if r.status_code == 200:
                actions.append(r.json()["recommendation"]["action"])
        if actions:
            per_corpus[entity_id] = actions
            pooled.extend(actions)
    return pooled, per_corpus


def run_all() -> list[GateResult]:
    os.environ["TYPICALITY_SCORING"] = "1"

    import run as _run_module  # the project's run.py at repo root — same
                                # convention as validation/public_authors/run.py:89,
                                # validation/verify/run.py:140, etc. Requires
                                # sys.path.insert(0, str(_ROOT)) above, already present.
    from fastapi.testclient import TestClient

    client = TestClient(_run_module.load_legacy_demo_app())

    results: list[GateResult] = []

    # G1: seminary + public_authors + Plato, LOO over whole documents.
    seminary_texts = _load_seminary_texts()
    public_authors_texts = _load_public_authors_baseline_texts()
    plato_texts = _load_plato_texts_by_dialogue()

    texts_by_id: dict[str, list[str]] = {**seminary_texts, **public_authors_texts, **plato_texts}
    pooled_actions, per_corpus_actions = _score_corpus_for_g1(client, "g1", texts_by_id)
    results.append(evaluate_g1_fpr(pooled_actions, per_corpus_actions))

    # G2: bland impostor via q = min(p_far, p_central).
    holdout_q, impostor_q = _compute_g2_q_values(client)
    results.append(evaluate_g2_bland_impostor(holdout_q, impostor_q))

    # G3: reuse the existing public_authors attribution accuracy computation.
    # validation/public_authors/run.py's run() returns a report dict shaped
    # {"summary": {"top1_accuracy": ..., ...}, "per_author": {...}, ...} —
    # NOT a flat "top1_accuracy" key (verified by reading run.py directly;
    # the original plan draft had not seen the real return shape). When the
    # corpus doesn't have >= 2 eligible authors, run() instead returns
    # {"error": ..., "skipped_authors": ...} with no "summary" key at all —
    # .get()-chain through that case rather than raising.
    from validation.public_authors.run import run as run_public_authors

    pa_report = run_public_authors()
    top1_accuracy = pa_report.get("summary", {}).get("top1_accuracy", 0.0)
    results.append(evaluate_g3_attribution(top1_accuracy))

    # G4: Plato early/middle/late monotonicity.
    group_means = _compute_g4_group_means()
    results.append(evaluate_g4_career_drift_monotone(group_means))

    return results


def _load_seminary_texts() -> dict[str, list[str]]:
    corpus_dir = _ROOT / "validation" / "corpus"
    seminary_files = sorted(corpus_dir.glob("seminary_*.txt"))
    # Group by the pre-underscore-number topic prefix isn't right here;
    # seminary essays are single-author-simulated per file with no natural
    # per-author grouping — bucket every 4-5 sequential files as one
    # "student" to get the N>=5 LOO regime the spec's Problem section used
    # (310-460 word essays, 4-of-25 grouping). Concretely: chunk the sorted
    # file list into groups of 5.
    texts = [f.read_text(encoding="utf-8") for f in seminary_files]
    groups: dict[str, list[str]] = {}
    for i in range(0, len(texts) - 4, 5):
        groups[f"seminary_group_{i // 5}"] = texts[i : i + 5]
    return groups


def _load_public_authors_baseline_texts() -> dict[str, list[str]]:
    import json as _json

    manifest_path = _ROOT / "validation" / "public_authors" / "manifest.json"
    corpus_dir = _ROOT / "validation" / "public_authors" / "corpus"
    manifest = _json.loads(manifest_path.read_text())
    by_author: dict[str, list[str]] = {}
    for entry in manifest["entries"]:
        if not entry.get("is_baseline"):
            continue
        text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
        by_author.setdefault(entry["author_id"], []).append(text)
    return by_author


def _load_plato_texts_by_dialogue() -> dict[str, list[str]]:
    corpus_dir = _ROOT / "validation" / "plato" / "corpus" / "jowett"
    by_dialogue: dict[str, list[str]] = {}
    for dialogue_dir in sorted(corpus_dir.iterdir()):
        if not dialogue_dir.is_dir():
            continue
        chunks = sorted(dialogue_dir.glob("*.txt"))
        by_dialogue[f"plato_{dialogue_dir.name}"] = [
            c.read_text(encoding="utf-8") for c in chunks
        ]
    return by_dialogue


def _compute_g2_q_values(client) -> tuple[list[float], list[float]]:
    """
    q = min(p_far, p_central) for genuine Plato holdouts vs. the Eryxias +
    synthetic-AI impostor pool.

    NOTE on the API response shape: original/schemas.py's Layer7OutputResponse
    puts typicality_p_far / typicality_p_central / typicality_band /
    typicality_n at the TOP LEVEL of the JSON body (siblings of "authorship",
    "recommendation", etc — see original/routers/_shared.py's _to_response()),
    not nested under a "typicality" sub-object. Both fields are None unless
    TYPICALITY_SCORING=1, adaptive weights are off, AND the scored student has
    >= 2 leave-one-out baseline distances (original/quantum/scoring.py's
    typicality block) — treat that as "no signal for this sample", not an
    error, and skip it.
    """
    holdout_q: list[float] = []
    plato_dialogues = _load_plato_texts_by_dialogue()
    for dialogue, chunks in plato_dialogues.items():
        if "eryxias" in dialogue or len(chunks) < 5:
            continue
        sid = f"gate:g2_{dialogue}"
        for chunk in chunks[:-1]:
            client.post(f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"})
        r = client.post(
            f"/students/{sid}/score",
            json={"text": chunks[-1], "submission_id": f"{dialogue}_holdout"},
        )
        if r.status_code == 200:
            payload = r.json()
            p_far_val = payload.get("typicality_p_far")
            p_central_val = payload.get("typicality_p_central")
            if p_far_val is not None and p_central_val is not None:
                holdout_q.append(min(p_far_val, p_central_val))

    impostor_q: list[float] = []
    eryxias_chunks = plato_dialogues.get("plato_eryxias", [])
    ai_corpus_dir = _ROOT / "validation" / "corpus"
    ai_texts = [p.read_text(encoding="utf-8") for p in sorted(ai_corpus_dir.glob("ai_*.txt"))]
    reference_dialogues = [
        c for name, chunks in plato_dialogues.items() if "eryxias" not in name for c in chunks
    ][:20]
    sid = "gate:g2_impostor_reference"
    for chunk in reference_dialogues:
        client.post(f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"})
    for text in eryxias_chunks + ai_texts:
        r = client.post(f"/students/{sid}/score", json={"text": text, "submission_id": "impostor"})
        if r.status_code == 200:
            payload = r.json()
            p_far_val = payload.get("typicality_p_far")
            p_central_val = payload.get("typicality_p_central")
            if p_far_val is not None and p_central_val is not None:
                impostor_q.append(min(p_far_val, p_central_val))

    return holdout_q, impostor_q


def _compute_g4_group_means() -> dict[str, float]:
    from validation.plato.chronology import GROUP_NAMES, ranked

    dialogues = ranked()
    plato_texts = _load_plato_texts_by_dialogue()
    groups = {"early": [], "middle": [], "late": []}
    for d in dialogues:
        if d.group is None:
            continue  # excluded from chronology (e.g. Eryxias, spurious=True)
        group_key = GROUP_NAMES[d.group]
        groups[group_key].extend(plato_texts.get(f"plato_{d.slug}", []))
    # Baseline built from the "early" group; score middle and late against it.
    from fastapi.testclient import TestClient

    import run as _run_module  # repo-root run.py — see run_all()'s identical import

    client = TestClient(_run_module.load_legacy_demo_app())
    sid = "gate:g4_early_baseline"
    for chunk in groups["early"]:
        client.post(f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"})

    means = {}
    for group_key in ("early", "middle", "late"):
        devs = []
        for chunk in groups[group_key]:
            r = client.post(f"/students/{sid}/score", json={"text": chunk, "submission_id": group_key})
            if r.status_code == 200:
                devs.append(r.json()["authorship"]["deviation_score"])
        means[group_key] = sum(devs) / len(devs) if devs else float("nan")
    return means


def render(results: list[GateResult]) -> str:
    lines = ["╭─ Calibration gates (G1-G4) ─────────────────────────────────╮"]
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"│ {r.name} [{status}] {r.criterion}")
        lines.append(f"│      current: {r.current_value}")
    lines.append("╰────────────────────────────────────────────────────────────╯")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="write JSON report to this path")
    args = parser.parse_args(argv)

    results = run_all()
    print(render(results))
    if args.out:
        Path(args.out).write_text(json.dumps([asdict(r) for r in results], indent=2))
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
