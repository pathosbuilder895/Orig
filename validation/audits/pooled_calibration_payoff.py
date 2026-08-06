"""Task 9 payoff check: does pooled typicality calibration actually make
G1/G6's thresholds reachable, and what does the real corpus say once it is?

Scope, deliberately narrower than the full G1-G6 gate: only G1 and G6 are
affected by TYPICALITY_POOLED_CALIBRATION (G2/G2b/G3/G4/G5 don't threshold a
raw typicality band the same way, and re-running them costs hours for no
information relevant to this question). This script runs each of G1 and G6
TWICE -- once with pooled calibration off (today's per-student self
calibration), once with it on -- and records, for each mode:

  * Step 1 (assert reachability before believing any result): the reference
    n actually achieved and whether _threshold_reachable() says it clears
    the gate's own threshold (G1: NO_ACTION_FAR_THRESHOLD=0.03; G6:
    NO_ACTION_CENTRAL_THRESHOLD=0.02) -- computed BOTH analytically (pure
    arithmetic from corpus text counts, before any HTTP call: see
    _hand_arithmetic) and empirically (from the real run's observed
    typicality_n values).

  * Step 1's non-negotiable corollary for G1: reachability and the flagged
    rate are reported PER CORPUS GROUP (seminary / plato / public_authors),
    never only pooled across all three -- because Task 7's exchangeability
    check (validation/audits/pooling_exchangeability.py) only ever validated
    within-seminary and within-Plato exchangeability SEPARATELY, never their
    union, and never public_authors at all. _group_entities_for_pooling and
    _pool_peers_for_entity (validation/calibration_gate.py) enforce that no
    fold's pooled reference spans more than one group; this script enforces
    that the REPORT never collapses that distinction back out.

  * Step 3 (interpret honestly): the pooled flagged rate for G1, with an
    explicit is_g1_failure flag if it exceeds 5% -- this must be recorded as
    a real finding about calibration, not tuned away. G6's ratio, whichever
    way it comes out, including "still unreachable even pooled" as an
    honest, complete answer for a group that's too small.

IMPORTANT -- read before trusting any number this script produces: neither
_score_corpus_for_g1_pooled nor _compute_g6_fairness_data_pooled goes
through the live HTTP /score endpoint the way the OFF-mode legs (and every
other gate in this project) do. original/routers/students_scoring.py's
score_submission() never threads pooled_states/student_id into
quantum_score() at all -- TYPICALITY_POOLED_CALIBRATION is consulted only
inside original/quantum/scoring.py's score() function itself, and nothing in
the live API surface wires a caller-supplied pooled reference into it. The
pooled-mode functions therefore call score() directly, bypassing the router.
This is currently the ONLY way to exercise pooled calibration at all; it is
not a stylistic shortcut, and it means today's ON-mode legs measure "what
pooled calibration would do if the live endpoint supported it", not
production behaviour as shipped. That gap is a real finding of this task,
not a defect in this script, and belongs in the report right next to the
numbers.

Run (following validation/audits/g2_floor_asymmetry.py's and
validation/audits/pooling_exchangeability.py's conventions):

    nohup ~/Desktop/Original/.venv/bin/python \
        -m validation.audits.pooled_calibration_payoff \
        > /path/to/log 2>&1 & disown

Writes two report files next to this module's invocation directory (repo
root): validation/calibration_report_pooled_off_<date>.json and
validation/calibration_report_pooled_on_<date>.json.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Pure result-shaping helpers (no HTTP, no scoring) ──────────────────────────


def _reconstruct_per_corpus_typicality_ns(per_corpus_actions, pooled_typicality_ns):
    """The self-mode (OFF) leg's _score_corpus_for_g1 returns pooled_actions/
    pooled_typicality_ns as two lists built by the SAME per-entity loop, in
    the SAME order, via .extend() (see that function's source) -- so slicing
    pooled_typicality_ns by cumulative per-entity action counts recovers an
    exact per-entity {entity_id: [typicality_n, ...]} breakdown without
    needing to change that function's return contract (out of scope for this
    task -- see the module docstring on additive-only changes)."""
    out: dict[str, list[int]] = {}
    idx = 0
    for entity_id, actions in per_corpus_actions.items():
        n = len(actions)
        out[entity_id] = list(pooled_typicality_ns[idx : idx + n])
        idx += n
    return out


def _group_reachability(per_corpus_typicality_ns, group_of, threshold):
    from validation.calibration_gate import _reachability_block

    by_group: dict[str, list[int]] = {}
    for entity_id, ns in per_corpus_typicality_ns.items():
        group = group_of.get(entity_id, "unknown")
        by_group.setdefault(group, []).extend(ns)
    return {group: _reachability_block(ns, threshold) for group, ns in by_group.items()}


def _group_flagged_rates(per_corpus_actions, group_of):
    by_group: dict[str, list[str]] = {}
    for entity_id, actions in per_corpus_actions.items():
        group = group_of.get(entity_id, "unknown")
        by_group.setdefault(group, []).extend(actions)
    out = {}
    for group, actions in by_group.items():
        n = len(actions)
        flagged = sum(1 for a in actions if a != "no_action")
        out[group] = {
            "n": n,
            "flagged": flagged,
            "flagged_rate": (flagged / n) if n else None,
        }
    return out


def _hand_arithmetic() -> dict:
    """Step 1: work out reachability from corpus text counts alone, BEFORE
    any HTTP call or real scoring -- see the module docstring on why this
    must be asserted, not assumed."""
    from original.quantum.typicality import (
        NO_ACTION_CENTRAL_THRESHOLD,
        NO_ACTION_FAR_THRESHOLD,
    )
    from validation.calibration_gate import (
        _group_entities_for_pooling,
        _load_g6_native_english_texts,
        _load_plato_texts_by_dialogue,
        _load_public_authors_baseline_texts,
        _load_seminary_texts,
        _min_n_for_threshold,
        _pooled_reference_arithmetic,
        _threshold_reachable,
    )

    seminary_texts = _load_seminary_texts()
    plato_texts = _load_plato_texts_by_dialogue()
    pa_texts = _load_public_authors_baseline_texts()
    g6_texts = _load_g6_native_english_texts()

    group_of = _group_entities_for_pooling(seminary_texts, plato_texts, pa_texts)
    sizes = {
        **{k: len(v) for k, v in seminary_texts.items()},
        **{k: len(v) for k, v in plato_texts.items()},
        **{k: len(v) for k, v in pa_texts.items()},
    }
    g1_arithmetic = _pooled_reference_arithmetic(group_of, sizes)

    by_group_pool_n: dict[str, set] = {}
    for info in g1_arithmetic.values():
        by_group_pool_n.setdefault(info["group"], set()).add(info["pool_n"])
    # Every group here is uniform in pool_n in practice (seminary: all
    # groups are exactly 5 texts; plato/public_authors vary per-entity, so
    # this stays a *set* rather than a single scalar) -- report min (the
    # BINDING case, same convention as _reachability_block) alongside the
    # full set for transparency.
    g1_group_min_pool_n = {g: min(ns) for g, ns in by_group_pool_n.items()}
    g1_group_reachable = {
        g: _threshold_reachable(n, NO_ACTION_FAR_THRESHOLD) for g, n in g1_group_min_pool_n.items()
    }

    g6_group_of = {author_id: "g6" for author_id in g6_texts}
    g6_sizes = {k: len(v) for k, v in g6_texts.items()}
    g6_arithmetic = _pooled_reference_arithmetic(g6_group_of, g6_sizes, min_size=3)
    g6_pool_ns = {info["pool_n"] for info in g6_arithmetic.values()}
    g6_min_pool_n = min(g6_pool_ns) if g6_pool_ns else None
    g6_reachable = (
        _threshold_reachable(g6_min_pool_n, NO_ACTION_CENTRAL_THRESHOLD)
        if g6_min_pool_n is not None
        else None
    )

    return {
        "g1_per_entity": g1_arithmetic,
        "g1_group_min_pool_n": g1_group_min_pool_n,
        "g1_group_pool_n_sets": {g: sorted(ns) for g, ns in by_group_pool_n.items()},
        "g1_group_reachable_at_no_action_far_threshold": g1_group_reachable,
        "g1_threshold": NO_ACTION_FAR_THRESHOLD,
        "g1_required_n": _min_n_for_threshold(NO_ACTION_FAR_THRESHOLD),
        "g6_per_entity": g6_arithmetic,
        "g6_min_pool_n": g6_min_pool_n,
        "g6_reachable_at_no_action_central_threshold": g6_reachable,
        "g6_threshold": NO_ACTION_CENTRAL_THRESHOLD,
        "g6_required_n": _min_n_for_threshold(NO_ACTION_CENTRAL_THRESHOLD),
        "note": (
            "pure arithmetic from corpus text counts (original/quantum/"
            "state.py's loo_distances: length == N per contributing peer "
            "entity) -- computed before any HTTP call or real scoring; the "
            "empirical per-mode results below either confirm or contradict "
            "this projection (build_pooled_reference's min_students=3/"
            "min_total=30 floor can make even an 'arithmetically reachable' "
            "pool_n fall back to self if too few PEER ENTITIES qualify, "
            "though not vice versa)."
        ),
    }


# ── Per-mode leg runners ────────────────────────────────────────────────────


def _run_g1_leg(client, group_of: dict[str, str], pooled: bool) -> dict:
    from original.quantum.typicality import NO_ACTION_FAR_THRESHOLD
    from validation.calibration_gate import (
        _load_plato_texts_by_dialogue,
        _load_public_authors_baseline_texts,
        _load_seminary_texts,
        _score_corpus_for_g1,
        _score_corpus_for_g1_pooled,
        evaluate_g1_fpr,
    )

    seminary_texts = _load_seminary_texts()
    public_authors_texts = _load_public_authors_baseline_texts()
    plato_texts = _load_plato_texts_by_dialogue()
    texts_by_id = {**seminary_texts, **public_authors_texts, **plato_texts}

    t0 = time.perf_counter()
    if pooled:
        out = _score_corpus_for_g1_pooled(client, "g1payoff", texts_by_id, group_of)
        pooled_actions = out["pooled_actions"]
        per_corpus_actions = out["per_corpus_actions"]
        pooled_typicality_ns = out["pooled_typicality_ns"]
        per_corpus_typicality_ns = out["per_corpus_typicality_ns"]
        extra = {
            "n_errors": out["n_errors"],
            "n_drift_rejected": out["n_drift_rejected"],
            "calibration_mode_counts": out["calibration_mode_counts"],
            "pool_reference_sizes": out["pool_reference_sizes"],
        }
    else:
        (
            pooled_actions,
            per_corpus_actions,
            _pooled_deviations,
            n_errors,
            pooled_typicality_ns,
            n_drift_rejected,
        ) = _score_corpus_for_g1(client, "g1payoff", texts_by_id)
        per_corpus_typicality_ns = _reconstruct_per_corpus_typicality_ns(
            per_corpus_actions, pooled_typicality_ns
        )
        extra = {"n_errors": n_errors, "n_drift_rejected": n_drift_rejected}
    elapsed = time.perf_counter() - t0

    gate_result = evaluate_g1_fpr(
        pooled_actions, per_corpus_actions, typicality_ns=pooled_typicality_ns
    )
    group_reachability = _group_reachability(
        per_corpus_typicality_ns, group_of, NO_ACTION_FAR_THRESHOLD
    )
    group_flagged_rates = _group_flagged_rates(per_corpus_actions, group_of)
    pooled_flagged_rate = gate_result.detail["pooled_flagged_rate"]

    return {
        "elapsed_seconds": elapsed,
        "gate_result": {
            "passed": gate_result.passed,
            "criterion": gate_result.criterion,
            "current_value": gate_result.current_value,
            "detail": gate_result.detail,
        },
        "pooled_flagged_rate": pooled_flagged_rate,
        # Step 3: an unambiguous, script-computed flag -- the interpretation
        # must not depend on eyeballing the percentage correctly.
        "is_g1_failure_over_5pct": pooled_flagged_rate > 0.05,
        "per_group_reachability": group_reachability,
        "per_group_flagged_rates": group_flagged_rates,
        **extra,
    }


def _run_g6_leg(client, pooled: bool) -> dict:
    from validation.calibration_gate import (
        _compute_g6_fairness_data,
        _compute_g6_fairness_data_pooled,
    )

    fn = _compute_g6_fairness_data_pooled if pooled else _compute_g6_fairness_data
    t0 = time.perf_counter()
    result = fn(client)
    elapsed = time.perf_counter() - t0
    return {
        "elapsed_seconds": elapsed,
        "passed": result.passed,
        "criterion": result.criterion,
        "current_value": result.current_value,
        "detail": result.detail,
    }


def _run_mode(client, group_of: dict[str, str], pooled: bool) -> dict:
    from original import store

    os.environ["TYPICALITY_POOLED_CALIBRATION"] = "1" if pooled else "0"
    store.reset_memory_conn()

    g1 = _run_g1_leg(client, group_of, pooled)
    g6 = _run_g6_leg(client, pooled)

    return {
        "mode": "pooled" if pooled else "self",
        "typicality_pooled_calibration_env": os.environ["TYPICALITY_POOLED_CALIBRATION"],
        "g1": g1,
        "g6": g6,
    }


def main() -> dict:
    from validation.benchmark.reproducibility import lock_environment

    lock_environment()
    os.environ["TYPICALITY_SCORING"] = "1"

    from original import store

    store.reset_memory_conn()

    import run as _run_module
    from fastapi.testclient import TestClient

    from validation.calibration_gate import (
        _group_entities_for_pooling,
        _load_plato_texts_by_dialogue,
        _load_public_authors_baseline_texts,
        _load_seminary_texts,
    )

    group_of = _group_entities_for_pooling(
        _load_seminary_texts(), _load_plato_texts_by_dialogue(), _load_public_authors_baseline_texts()
    )

    arithmetic = _hand_arithmetic()
    print("=== Step 1: reachability arithmetic (pure, pre-run) ===", flush=True)
    print(json.dumps(arithmetic, indent=2, default=str), flush=True)

    client = TestClient(_run_module.load_legacy_demo_app())

    print("=== Running OFF mode (TYPICALITY_POOLED_CALIBRATION=0) ===", flush=True)
    off_result = _run_mode(client, group_of, pooled=False)
    print(json.dumps(off_result, indent=2, default=str), flush=True)

    print("=== Running ON mode (TYPICALITY_POOLED_CALIBRATION=1) ===", flush=True)
    on_result = _run_mode(client, group_of, pooled=True)
    print(json.dumps(on_result, indent=2, default=str), flush=True)

    date_str = datetime.date.today().isoformat()
    off_path = _ROOT / "validation" / f"calibration_report_pooled_off_{date_str}.json"
    on_path = _ROOT / "validation" / f"calibration_report_pooled_on_{date_str}.json"

    common_meta = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "reachability_arithmetic": arithmetic,
        "caveat": (
            "ON-mode legs call original.quantum.scoring.score() directly, "
            "bypassing the live HTTP /score endpoint, because "
            "original/routers/students_scoring.py never threads "
            "pooled_states/student_id into quantum_score() -- see "
            "validation/audits/pooled_calibration_payoff.py's module "
            "docstring. ON-mode numbers show what pooled calibration would "
            "do if the live endpoint supported it, not production behaviour "
            "as currently shipped."
        ),
    }

    off_path.write_text(json.dumps({**common_meta, **off_result}, indent=2, default=str))
    on_path.write_text(json.dumps({**common_meta, **on_result}, indent=2, default=str))

    print(f"Wrote {off_path}", flush=True)
    print(f"Wrote {on_path}", flush=True)

    return {"off": off_result, "on": on_result, "arithmetic": arithmetic}


if __name__ == "__main__":
    main()
