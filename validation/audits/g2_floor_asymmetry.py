"""Is G2's margin authorship signal, or the arithmetic of unequal N?

q = min(p_far, p_central) is quantised at 1/(n+1). The impostor leg runs
at n=20 (floor 0.0476); holdouts run at n=3-11 (floors 0.083-0.25). A
gap between the two medians is only evidence of discrimination if it
survives after both legs are put on a common footing.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _at_floor(rec: dict) -> bool:
    """True when the sample is already the most extreme its n allows."""
    return rec["rank"] == 1


def analyze_floor_asymmetry(holdout_records, impostor_records) -> dict:
    h_floor = sum(_at_floor(r) for r in holdout_records) / max(1, len(holdout_records))
    i_floor = sum(_at_floor(r) for r in impostor_records) / max(1, len(impostor_records))

    # Rank is scale-free where q is not: if both legs are saturated at
    # rank 1, the q difference is the floor difference and nothing else.
    if h_floor >= 0.5 and i_floor >= 0.5:
        verdict = "artifact"
    elif i_floor > h_floor:
        verdict = "genuine"
    else:
        verdict = "inconclusive"

    h_ns = sorted({r["n"] for r in holdout_records})
    return {
        "holdout_at_floor_rate": h_floor,
        "impostor_at_floor_rate": i_floor,
        "holdout_n_range": (h_ns[0], h_ns[-1]) if h_ns else (0, 0),
        "impostor_n": sorted({r["n"] for r in impostor_records}),
        "matched_n_verdict": verdict,
    }


# ── Real-corpus re-run (Step 5) ─────────────────────────────────────────────
#
# Everything below re-derives validation.calibration_gate._compute_g2_q_values
# faithfully (same sids, same baseline/score call sequence, same corpora),
# except it keeps typicality_n / typicality_p_far / typicality_p_central and
# a derived rank per sample instead of collapsing straight to a bare q list.
# _compute_g2_q_values itself is treated read-only — nothing here imports it
# for mutation, only its sibling helper _load_plato_texts_by_dialogue, and
# only inside main()/its helpers so importing this module for the unit tests
# above never touches the HTTP-heavy TestClient machinery.


def _rank_from_q(q: float, n: int) -> int:
    """Derive the sample's rank within its own reference set directly from
    the conformal fraction, instead of re-deriving state.loo_distances (the
    API response exposes typicality_p_far/p_central/n, not the raw LOO
    distances — see _compute_g2_q_values's docstring on the response shape).

    p_far and p_central are each exactly (1 + count) / (n + 1) for their
    respective tail (original/quantum/typicality.py), and q = min(p_far,
    p_central) is whichever tail is more extreme. So count + 1 — the
    sample's 1-indexed position from the extreme end of that tail,
    including itself — recovers exactly as round(q * (n + 1)).

    rank == 1 iff q == 1/(n+1) exactly: the floor-equality condition the
    task brief describes as "the single most extreme value in its own
    reference set". This formula is a generalization of that floor check
    that also recovers the exact rank off the floor, not just a
    floor/not-floor boolean — and it needs nothing beyond the fields the
    live API already returns at the top level of the response.
    """
    return round(q * (n + 1))


def _record_from_response(payload: dict) -> dict | None:
    p_far_val = payload.get("typicality_p_far")
    p_central_val = payload.get("typicality_p_central")
    # Same guard as _compute_g2_q_values: both fields are None unless
    # TYPICALITY_SCORING=1, adaptive weights are off, and the scored
    # student has >= 2 LOO baseline distances. Skip silently in that case,
    # same convention as the gate itself.
    if p_far_val is None or p_central_val is None:
        return None
    n = payload.get("typicality_n", 0)
    q = min(p_far_val, p_central_val)
    return {
        "q": q,
        "n": n,
        "p_far": p_far_val,
        "p_central": p_central_val,
        "rank": _rank_from_q(q, n),
    }


def _rerun_g2_legs(client) -> tuple[list[dict], list[dict]]:
    """Faithful re-derivation of the two legs scored by
    validation.calibration_gate._compute_g2_q_values, using distinct sids
    (prefixed demo:audit_g2_* rather than demo:gate_g2_*) so this read-only
    audit never shares baseline state with a concurrent gate run against the
    same in-memory/db-backed store.
    """
    from validation.calibration_gate import _load_plato_texts_by_dialogue

    holdout_records: list[dict] = []
    plato_dialogues = _load_plato_texts_by_dialogue()
    for dialogue, chunks in plato_dialogues.items():
        if "eryxias" in dialogue or len(chunks) < 5:
            continue
        sid = f"demo:audit_g2_{dialogue}"
        for chunk in chunks[:-1]:
            client.post(f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"})
        r = client.post(
            f"/students/{sid}/score",
            json={"text": chunks[-1], "submission_id": f"{dialogue}_holdout"},
        )
        if r.status_code == 200:
            rec = _record_from_response(r.json())
            if rec is not None:
                holdout_records.append(rec)

    impostor_records: list[dict] = []
    eryxias_chunks = plato_dialogues.get("plato_eryxias", [])
    ai_corpus_dir = _ROOT / "validation" / "corpus"
    ai_texts = [p.read_text(encoding="utf-8") for p in sorted(ai_corpus_dir.glob("ai_*.txt"))]
    reference_dialogues = [
        c for name, chunks in plato_dialogues.items() if "eryxias" not in name for c in chunks
    ][:20]
    sid = "demo:audit_g2_impostor_reference"
    for chunk in reference_dialogues:
        client.post(f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"})
    for text in eryxias_chunks + ai_texts:
        r = client.post(f"/students/{sid}/score", json={"text": text, "submission_id": "impostor"})
        if r.status_code == 200:
            rec = _record_from_response(r.json())
            if rec is not None:
                impostor_records.append(rec)

    return holdout_records, impostor_records


def main() -> dict:
    # Same convention as validation/calibration_gate.py's run_all(): lock
    # the environment BEFORE any original.* import, then force
    # TYPICALITY_SCORING=1 before the TestClient is constructed (typicality
    # fields don't populate otherwise).
    from validation.benchmark.reproducibility import lock_environment

    lock_environment()
    os.environ["TYPICALITY_SCORING"] = "1"

    from original import store

    store.reset_memory_conn()

    import run as _run_module  # repo-root run.py, same convention as calibration_gate.py
    from fastapi.testclient import TestClient

    client = TestClient(_run_module.load_legacy_demo_app())

    holdout_records, impostor_records = _rerun_g2_legs(client)
    analysis = analyze_floor_asymmetry(holdout_records, impostor_records)

    print(
        json.dumps(
            {
                "holdout_records": holdout_records,
                "impostor_records": impostor_records,
                "analysis": analysis,
            },
            indent=2,
        )
    )
    return analysis


if __name__ == "__main__":
    main()
