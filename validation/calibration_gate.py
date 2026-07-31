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
G5 (permutation-null control) shuffles author labels with a fixed seed and
re-runs the G1/G3/G4 machinery — see run_g5(). G2b (paraphrase-resistant)
and G6 (native_english fairness) are added once
original/features/uniformity.py exists (Phase 4).
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


def evaluate_g3_attribution(
    top1_accuracy: float, top1_accuracy_raw_argmin: float | None = None
) -> GateResult:
    """
    G3 — Attribution non-regression. Existing bar: >= 0.7 (unchanged).
    top1_accuracy is the impostor-calibrated accuracy from
    validation/public_authors/run.py (summary.top1_accuracy); the raw
    argmin accuracy (summary.top1_accuracy_raw_argmin) is carried in
    detail for comparison when present, but never gated on.
    """
    passed = top1_accuracy >= 0.7
    detail = {"top1_accuracy": top1_accuracy}
    if top1_accuracy_raw_argmin is not None:
        detail["top1_accuracy_raw_argmin"] = top1_accuracy_raw_argmin
    return GateResult(
        name="G3",
        passed=passed,
        criterion="public_authors top-1 accuracy >= 0.7 (impostor-calibrated attribution)",
        current_value=f"{top1_accuracy:.3f}",
        detail=detail,
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


def evaluate_g5_permutation_null(
    real_g1_mean_deviation: float,
    shuffled_g1_mean_deviation: float,
    shuffled_g3_accuracy: float,
    g4_nonmonotone_draws: int,
    g4_total_draws: int,
    informational: dict | None = None,
) -> GateResult:
    """
    G5 — Selection-bias null control. Author labels are shuffled with a fixed
    seed and the SAME three scoring legs the real G1/G3/G4 gates use are
    re-run through the production pipeline. (The plan's original Task-13 text
    described re-deriving weights via scripts.derive_measured_weights; the
    gates as built score the production pipeline directly, so the faithful
    null is a label-shuffled rerun of the same scoring legs — reviewed
    deviation, 2026-07-30 fix round.) All three shuffled legs must collapse:

      - G1 leg: the shuffled corpus gives every pseudo-student a cross-author
        blended baseline, so its mean deviation_score must come out STRICTLY
        ABOVE the real same-author leg's mean. Insensitivity to blending
        (shuffled mean <= real mean) means the measurement is not measuring
        authorship. The flagged RATE is deliberately NOT the criterion:
        conformal typicality p-values floor at 1/(N+1) and every G1 corpus
        entity has at most ~a dozen LOO folds, which pins the action band to
        no_action for real AND shuffled labels alike — a low shuffled rate is
        guaranteed by construction and carries no circularity information
        (rates travel in detail as context only).
      - G3 leg: attribution accuracy must be near chance (roughly
        1/n_authors; generous < 0.30 threshold since n_authors varies by
        corpus).
      - G4 leg: a MAJORITY of the K seeded shuffle draws must be
        non-monotone. A single draw's monotonicity over 3 group means is a
        near-coin-flip on blended groups, so one monotone draw among K is
        noise, not signal.

    Fails (correctly) if ANY of the three still looks like real signal.
    `informational` is attach-only context merged into detail — it never
    affects the verdict.
    """
    g1_is_suspicious = shuffled_g1_mean_deviation <= real_g1_mean_deviation
    g3_is_suspicious = shuffled_g3_accuracy >= 0.30
    g4_majority = g4_total_draws // 2 + 1
    g4_is_suspicious = g4_nonmonotone_draws < g4_majority

    passed = not (g1_is_suspicious or g3_is_suspicious or g4_is_suspicious)
    detail = {
        "real_g1_mean_deviation": real_g1_mean_deviation,
        "shuffled_g1_mean_deviation": shuffled_g1_mean_deviation,
        "shuffled_g3_accuracy": shuffled_g3_accuracy,
        "g4_nonmonotone_draws": g4_nonmonotone_draws,
        "g4_total_draws": g4_total_draws,
    }
    if informational:
        detail.update(informational)
    return GateResult(
        name="G5",
        passed=passed,
        criterion="G1/G3/G4 collapse to chance under permuted author labels",
        current_value=(
            f"g1_dev real={real_g1_mean_deviation:.3f} "
            f"shuffled={shuffled_g1_mean_deviation:.3f}, "
            f"g3_acc={shuffled_g3_accuracy:.3f}, "
            f"g4_nonmonotone={g4_nonmonotone_draws}/{g4_total_draws}"
        ),
        detail=detail,
    )


def _g5_machinery_error_result(exc: Exception) -> GateResult:
    """
    run_all()'s G5 wrapper: a crash inside run_g5 is a scoring-MACHINERY
    failure, not a null-hypothesis verdict. It must neither discard the four
    completed real gates nor masquerade as a genuine G5 result — so it
    renders as a FAILED G5 whose current_value is unmistakably an error.
    """
    return GateResult(
        name="G5",
        passed=False,
        criterion="G1/G3/G4 collapse to chance under permuted author labels",
        current_value=f"ERROR (machinery): {exc}",
        detail={"machinery_error": str(exc)},
    )


# ── Corpus-driving orchestration (exercised by `main()`, not unit-tested) ──────


def _score_corpus_for_g1(
    client, sid_prefix: str, texts_by_id: dict[str, list[str]]
) -> tuple[list[str], dict[str, list[str]], list[float], int]:
    """
    For each id in texts_by_id with >= 5 texts: build a baseline from all
    but one text (leave-one-out over WHOLE documents, not chunks), score
    the held-out text, record its recommendation.action. Repeat holding out
    each text in turn. Requires TYPICALITY_SCORING=1 already set in os.environ
    before `client` was constructed (env is read at score() call time, so
    this also works if set right before this call — see
    validation/verify/run_null_model.py's docstring on this point).

    Returns (pooled_actions, per_corpus_actions, pooled_deviations, n_errors):
    pooled_deviations is each successful fold's deviation_score, index-aligned
    with pooled_actions — the real G1 evaluator (evaluate_g1_fpr) ignores it;
    G5's deviation-shift criterion consumes it. n_errors counts non-200 score
    responses so callers can distinguish "clean run" from "the numbers came
    from a broken leg" (see _require_healthy_leg).
    """
    pooled: list[str] = []
    per_corpus: dict[str, list[str]] = {}
    pooled_deviations: list[float] = []
    n_errors = 0
    for entity_id, texts in texts_by_id.items():
        if len(texts) < 5:
            continue
        actions: list[str] = []
        deviations: list[float] = []
        for held_out_idx in range(len(texts)):
            sid = f"demo:gate_{sid_prefix}_{entity_id}_{held_out_idx}"
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
                payload = r.json()
                actions.append(payload["recommendation"]["action"])
                deviations.append(float(payload["authorship"]["deviation_score"]))
            else:
                n_errors += 1
        if actions:
            per_corpus[entity_id] = actions
            pooled.extend(actions)
            pooled_deviations.extend(deviations)
    return pooled, per_corpus, pooled_deviations, n_errors


def run_all() -> list[GateResult]:
    # Defensive reset, before anything else: ENV_LOCK (module import time,
    # above) already put us on ORIGINAL_DB=":memory:", so this is a no-op
    # today (the first _get_conn() call in a fresh process already gets an
    # empty database). It's insurance against a second, currently-untaken
    # call path: nothing prevents run_all() from being invoked twice in one
    # process (e.g. a future test harness, or a REPL/notebook session), and
    # without this, a second call would silently reuse the first call's
    # leftover ":memory:" data — get_or_create() would double every gate
    # student's baseline sample count instead of starting fresh, corrupting
    # every gate's numbers without raising anything. This is exactly what
    # original/store.py's reset_memory_conn() exists to prevent; it's a
    # no-op on the file-backed path (see its docstring), so this line is
    # always safe regardless of ORIGINAL_DB.
    from original import store

    store.reset_memory_conn()

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
    pooled_actions, per_corpus_actions, real_g1_deviations, _real_g1_errors = _score_corpus_for_g1(
        client, "g1", texts_by_id
    )
    g1_result = evaluate_g1_fpr(pooled_actions, per_corpus_actions)
    results.append(g1_result)

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
    pa_summary = pa_report.get("summary", {})
    top1_accuracy = pa_summary.get("top1_accuracy", 0.0)
    results.append(
        evaluate_g3_attribution(
            top1_accuracy,
            top1_accuracy_raw_argmin=pa_summary.get("top1_accuracy_raw_argmin"),
        )
    )

    # G4: Plato early/middle/late monotonicity.
    group_means, _g4_stats = _compute_g4_group_means()
    results.append(evaluate_g4_career_drift_monotone(group_means))

    # G5: permutation-null selection-bias control — seeded label shuffles,
    # then shuffled-label reruns of the G1/G3/G4 machinery above (see run_g5).
    # A crash inside the shuffled legs is a machinery failure: it must neither
    # discard the four completed real gates above nor read as a genuine null
    # verdict, so it renders as a failed ERROR-(machinery) result instead.
    try:
        results.append(
            run_g5(
                real_g1_deviations=real_g1_deviations,
                real_g1_flagged_rate=g1_result.detail["pooled_flagged_rate"],
            )
        )
    except Exception as exc:  # noqa: BLE001 — see _g5_machinery_error_result
        results.append(_g5_machinery_error_result(exc))

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
        sid = f"demo:gate_g2_{dialogue}"
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
    sid = "demo:gate_g2_impostor_reference"
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


def _compute_g4_group_means(
    plato_texts: dict[str, list[str]] | None = None,
    sid: str = "demo:gate_g4_early_baseline",
) -> tuple[dict[str, float], dict[str, int]]:
    """
    Defaults reproduce the real G4 leg exactly. run_g5() passes a
    label-shuffled `plato_texts` dict plus a DIFFERENT `sid` per draw: the
    store is a process-wide :memory: database, so reusing the real G4 sid on
    a later call would silently stack the shuffled early-group baselines on
    top of the real ones instead of starting a fresh student.

    Returns (group_means, {"n_scored": int, "n_errors": int}); the stats let
    G5 distinguish "genuinely non-monotone" from "NaN means because every
    score call 4xx'd" (see _require_healthy_leg). The real G4 evaluator
    ignores them.
    """
    from validation.plato.chronology import GROUP_NAMES, ranked

    dialogues = ranked()
    if plato_texts is None:
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
    for chunk in groups["early"]:
        client.post(f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"})

    means = {}
    n_scored = 0
    n_errors = 0
    for group_key in ("early", "middle", "late"):
        devs = []
        for chunk in groups[group_key]:
            r = client.post(f"/students/{sid}/score", json={"text": chunk, "submission_id": group_key})
            if r.status_code == 200:
                devs.append(r.json()["authorship"]["deviation_score"])
            else:
                n_errors += 1
        n_scored += len(devs)
        means[group_key] = sum(devs) / len(devs) if devs else float("nan")
    return means, {"n_scored": n_scored, "n_errors": n_errors}


# ── G5 — permutation-null orchestration ────────────────────────────────────────
#
# One seeded label shuffle (seed 1730 by default — BENCHMARK_SEED + 1, so the
# shuffle is decorrelated from the scoring-stack seed lock_environment() sets),
# three shuffled-label reruns of the SAME machinery the real gates use, then
# the pure evaluate_g5_permutation_null() on the three collapsed metrics.
#
# Per the plan (Task 13) the shuffle is a PLAIN permutation, not a derangement:
# fixed points (a label mapped back to its own texts) are acceptable noise at
# this corpus size — they can only push the shuffled metrics TOWARD "real
# signal", i.e. toward a G5 failure, so they never mask circularity.


def _shuffle_value_lists_across_keys(
    texts_by_id: dict[str, list[str]], rng
) -> dict[str, list[str]]:
    """
    Label shuffle at the whole-list level: key N gets key M's entire text
    list for a seeded random permutation over sorted keys ("student N's
    baseline is built from student M's texts"). Used for the G4 and G3
    shuffled legs, where the KEY carries meaning beyond a student id
    (chronology group membership / attribution identity).
    """
    keys = sorted(texts_by_id)
    perm = rng.permutation(len(keys))
    return {keys[i]: texts_by_id[keys[int(perm[i])]] for i in range(len(keys))}


def _shuffle_documents_across_keys(
    texts_by_id: dict[str, list[str]], rng
) -> dict[str, list[str]]:
    """
    Label shuffle at the document level: flatten every (key, text) pair over
    sorted keys, permute the texts with the seeded rng, and re-bucket them
    into the original keys' list LENGTHS.

    Why not _shuffle_value_lists_across_keys for the G1 leg: G1's LOO scorer
    (_score_corpus_for_g1) pairs baseline and held-out text from the SAME
    value list and uses the key only to name the student id, so permuting
    whole lists across keys re-measures the real G1 leg exactly — it is not
    a shuffled-label rerun at all. Destroying the label→document assignment
    itself is what makes the null genuine: each pseudo-student's baseline
    becomes a cross-author grab-bag and its held-out document is (almost
    surely) by a different author, so a pipeline with real authorship signal
    must flag far more than the calibrated ~5%.
    """
    keys = sorted(texts_by_id)
    all_docs = [t for k in keys for t in texts_by_id[k]]
    perm = rng.permutation(len(all_docs))
    shuffled_docs = [all_docs[int(i)] for i in perm]
    out: dict[str, list[str]] = {}
    pos = 0
    for k in keys:
        n = len(texts_by_id[k])
        out[k] = shuffled_docs[pos : pos + n]
        pos += n
    return out


def _require_healthy_leg(leg: str, *, n_success: int, n_errors: int) -> None:
    """
    Trivial-pass guard for the shuffled legs: an all-errors leg produces
    numbers that READ as "collapsed to chance" (n=0 -> G1 rate 1.0; G3 error
    dict -> accuracy 0.0; all-4xx G4 -> NaN means -> non-monotone), silently
    converting a machinery failure into a G5 pass. Zero successful folds or a
    >10% scoring-error rate raises RuntimeError, which run_all() renders as a
    failed ERROR-(machinery) G5 result (_g5_machinery_error_result).
    """
    if n_success == 0:
        raise RuntimeError(f"G5 {leg}: zero successful scoring folds")
    total = n_success + n_errors
    if n_errors / total > 0.10:
        raise RuntimeError(f"G5 {leg}: {n_errors}/{total} scoring calls failed (>10%)")


def _shuffled_public_authors_top1(rng) -> tuple[float, dict]:
    """
    G3 shuffled leg: rerun the FULL public_authors attribution machinery
    (validation/public_authors/run.py — baselines, impostor reference
    distributions, calibrated argmin) with author labels shuffled at the
    corpus-manifest level: each author keeps their own held-out (scored)
    essays but receives another author's ENTIRE baseline-document list,
    via a seeded permutation over sorted author ids.

    Mechanically: write a temp manifest whose baseline entries are
    re-assigned across authors, prefix every author_id with "g5perm_" so the
    rerun's student ids (demo:pa_g5perm_*) can never collide with the real
    G3 run's demo:pa_* students in the process-wide :memory: store, and call
    run() with report artifacts routed to a temp dir (removed in a finally).
    Eligibility rules (>= 3 baseline docs etc.) are applied by run() itself
    to the SHUFFLED assignment, same as the real run applies them to the
    real one.

    Returns (top1_accuracy, informational dict). Unlike the real G3 wiring's
    .get chain, an error report or a >10% per-essay scoring failure rate
    raises RuntimeError here: on this leg a silent 0.0 would read as
    "collapsed to chance" and fake a G5 pass (see _require_healthy_leg).
    """
    import json as _json
    import shutil
    import tempfile
    from collections import defaultdict

    from validation.public_authors.run import run as run_public_authors

    manifest_path = _ROOT / "validation" / "public_authors" / "manifest.json"
    corpus_dir = _ROOT / "validation" / "public_authors" / "corpus"
    manifest = _json.loads(manifest_path.read_text())

    baseline_entries: dict[str, list[dict]] = defaultdict(list)
    scored_entries: dict[str, list[dict]] = defaultdict(list)
    for entry in manifest["entries"]:
        (baseline_entries if entry.get("is_baseline") else scored_entries)[
            entry["author_id"]
        ].append(entry)

    author_ids = sorted(set(baseline_entries) | set(scored_entries))
    perm = rng.permutation(len(author_ids))

    shuffled_entries: list[dict] = []
    for i, aid in enumerate(author_ids):
        donor = author_ids[int(perm[i])]
        for entry in baseline_entries.get(donor, []):
            shuffled_entries.append({**entry, "author_id": f"g5perm_{aid}"})
        for entry in scored_entries.get(aid, []):
            shuffled_entries.append({**entry, "author_id": f"g5perm_{aid}"})

    tmp_dir = Path(tempfile.mkdtemp(prefix="gate_g5_public_authors_"))
    try:
        shuffled_manifest_path = tmp_dir / "manifest.json"
        shuffled_manifest_path.write_text(
            _json.dumps({**manifest, "entries": shuffled_entries}, indent=2)
        )
        report = run_public_authors(
            manifest_path=shuffled_manifest_path,
            corpus_dir=corpus_dir,
            report_dir=tmp_dir / "report",
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if "summary" not in report:
        raise RuntimeError(
            f"G5 shuffled G3 leg: public_authors rerun errored: "
            f"{report.get('error', 'no summary in report')}"
        )
    essays = report.get("results", [])
    n_essay_errors = sum(1 for e in essays if e.get("error"))
    _require_healthy_leg(
        "shuffled G3 leg",
        n_success=len(essays) - n_essay_errors,
        n_errors=n_essay_errors,
    )
    info = {
        "shuffled_g3_n_essays": len(essays),
        "shuffled_g3_n_scoring_errors": n_essay_errors,
        "shuffled_g3_n_eligible_authors": report["summary"].get("n_eligible_authors"),
        "shuffled_g3_attribution_method": report["summary"].get("attribution_method"),
    }
    return report["summary"]["top1_accuracy"], info


def run_g5(
    real_g1_deviations: list[float],
    real_g1_flagged_rate: float | None = None,
    seed: int = 1730,
) -> GateResult:
    """
    G5 orchestration — seeded label shuffles, then shuffled-label reruns of
    the G1/G3/G4 machinery, then the pure evaluate_g5_permutation_null().
    All the expensive shuffled scoring happens here, exactly once per gate
    run; the verdict stays a pure function of the collapsed metrics.

    Args:
        real_g1_deviations: pooled per-fold deviation_scores from the REAL G1
            leg (run_all() forwards _score_corpus_for_g1's third return) —
            the comparison point for the G1-leg deviation-shift criterion.
        real_g1_flagged_rate: the real leg's flagged rate, attached to detail
            as context only (see the evaluator's docstring on why flagged
            rates are never gated here).
        seed: one np.random.default_rng(seed) instance drives every shuffle,
            consumed in a fixed order — G1 document shuffle, then the G3
            author permutation, then the three G4 dialogue-list permutations
            (draws 0, 1, 2) — so the whole gate reproduces from this single
            seed. 1730 = BENCHMARK_SEED + 1, decorrelated from the
            scoring-stack seed lock_environment() sets.

    Raises:
        RuntimeError: when any shuffled leg fails the machinery-health guard
            (_require_healthy_leg), or real_g1_deviations is empty. run_all()
            converts this into a failed "ERROR (machinery)" G5 result rather
            than letting it read as a genuine null verdict.

    NOTE vs. the original Task-13 plan text: weights are NOT re-derived via
    scripts.derive_measured_weights here — the gates as they exist today
    score through the production pipeline directly, so the faithful null is
    a label-shuffled rerun of the same three scoring legs (the plan's Step-3
    wiring note), not a weight re-derivation.
    """
    import statistics

    if not real_g1_deviations:
        raise RuntimeError(
            "G5: the real G1 leg produced zero deviation samples — nothing to "
            "compare the shuffled leg against"
        )

    import numpy as np

    rng = np.random.default_rng(seed)

    os.environ["TYPICALITY_SCORING"] = "1"  # same contract as run_all()

    import run as _run_module  # repo-root run.py — see run_all()'s identical import
    from fastapi.testclient import TestClient

    client = TestClient(_run_module.load_legacy_demo_app())

    # Shuffled G1: same merged corpus, same LOO scorer, document-level label
    # shuffle (see _shuffle_documents_across_keys docstring for why not the
    # list-level shuffle here). The "g5" sid prefix keeps these pseudo-students
    # distinct from the real G1 leg's in the process-wide :memory: store.
    # The criterion input is the MEAN DEVIATION, not the flagged rate — see
    # evaluate_g5_permutation_null's docstring for why the conformal floor
    # makes the rate uninformative at this corpus size; both rates still
    # travel in detail as context.
    texts_by_id: dict[str, list[str]] = {
        **_load_seminary_texts(),
        **_load_public_authors_baseline_texts(),
        **_load_plato_texts_by_dialogue(),
    }
    shuffled_g1_corpus = _shuffle_documents_across_keys(texts_by_id, rng)
    s_actions, s_per_corpus, s_deviations, s_errors = _score_corpus_for_g1(
        client, "g5", shuffled_g1_corpus
    )
    _require_healthy_leg("shuffled G1 leg", n_success=len(s_actions), n_errors=s_errors)
    shuffled_g1_flagged_rate = evaluate_g1_fpr(s_actions, s_per_corpus).detail[
        "pooled_flagged_rate"
    ]

    # Shuffled G3: full public_authors rerun with baseline lists permuted
    # across author labels.
    shuffled_g3_accuracy, g3_info = _shuffled_public_authors_top1(rng)

    # Shuffled G4: K=3 seeded draws. Dialogue keys keep their chronology-group
    # membership, but each key receives another dialogue's ENTIRE chunk list,
    # so the early/middle/late groups become random blends. A single draw's
    # monotonicity over 3 group means is a near-coin-flip, so the evaluator
    # requires a MAJORITY of draws non-monotone; each draw gets a fresh
    # student sid and its own permutation from the shared rng stream.
    plato_texts = _load_plato_texts_by_dialogue()
    g4_draws: list[dict] = []
    for draw_idx in range(3):
        shuffled_plato = _shuffle_value_lists_across_keys(plato_texts, rng)
        draw_means, draw_stats = _compute_g4_group_means(
            plato_texts=shuffled_plato,
            sid=f"demo:gate_g5_g4_early_baseline_{draw_idx}",
        )
        _require_healthy_leg(
            f"shuffled G4 draw {draw_idx}",
            n_success=draw_stats["n_scored"],
            n_errors=draw_stats["n_errors"],
        )
        g4_draws.append(
            {
                "group_means": draw_means,
                # Monotonicity judged by the SAME rule as the real gate.
                "monotone": evaluate_g4_career_drift_monotone(draw_means).passed,
                **draw_stats,
            }
        )
    g4_nonmonotone_draws = sum(1 for d in g4_draws if not d["monotone"])

    return evaluate_g5_permutation_null(
        real_g1_mean_deviation=statistics.fmean(real_g1_deviations),
        shuffled_g1_mean_deviation=statistics.fmean(s_deviations),
        shuffled_g3_accuracy=shuffled_g3_accuracy,
        g4_nonmonotone_draws=g4_nonmonotone_draws,
        g4_total_draws=len(g4_draws),
        informational={
            "seed": seed,
            "real_g1_flagged_rate": real_g1_flagged_rate,
            "shuffled_g1_flagged_rate": shuffled_g1_flagged_rate,
            "flagged_rate_note": (
                "context only, never gated: conformal typicality p-values "
                "floor at 1/(N+1) and every G1 entity has at most ~a dozen "
                "LOO folds, pinning the action band to no_action for real "
                "and shuffled labels alike"
            ),
            "shuffled_g1_n_folds": len(s_actions),
            "shuffled_g1_n_scoring_errors": s_errors,
            **g3_info,
            "g4_draws": g4_draws,
        },
    )


def render(results: list[GateResult]) -> str:
    lines = ["╭─ Calibration gates (G1-G5) ─────────────────────────────────╮"]
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
