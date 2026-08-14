"""Phase-8 drift-gate calibration: false-hold rate vs. impostor catch rate.

Measures both sides of ``StudentState.check_drift`` (original/quantum/state.py)
against real single-author corpora:

  Genuine side  — per-upload false-hold rate when a real single author's docs
                  are uploaded sequentially as baseline samples (the exact
                  production flow: a held sample is NOT admitted, the
                  consecutive counter persists).
  Impostor side — per-upload catch rate when another author's docs are
                  presented against a genuine gated baseline.

The simulator replicates check_drift bit-for-bit for the production config
(anchor tiers {4,6}, recency-weighted baseline_mean, per-tier round(...,4))
and is verified against the real class in ``verify_against_production`` before
any sweep runs.

Usage:
  ~/Desktop/Original/.venv/bin/python validation/drift_calibration_2026-08/calibrate.py VECTORS.npz OUT.json
"""

from __future__ import annotations

import json
import os
import random
import sys
from collections import defaultdict

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from original.constants import (  # noqa: E402
    ALL_FEATURE_CODES,
    RECENCY_DECAY,
    TIER4_CODES,
    TIER6_CODES,
    TIER8_CODES,
    TIER13_CODES,
)

CODE_TO_INDEX = {c: i for i, c in enumerate(ALL_FEATURE_CODES)}
TIER_INDICES = {
    4: np.array([CODE_TO_INDEX[c] for c in TIER4_CODES if c in CODE_TO_INDEX]),
    6: np.array([CODE_TO_INDEX[c] for c in TIER6_CODES if c in CODE_TO_INDEX]),
    8: np.array([CODE_TO_INDEX[c] for c in TIER8_CODES if c in CODE_TO_INDEX]),
    13: np.array([CODE_TO_INDEX[c] for c in TIER13_CODES if c in CODE_TO_INDEX]),
}

ANCHOR_SETS = {
    "t4": (4,),
    "t6": (6,),
    "t4+6": (4, 6),  # production default
    "t4+6+8+13": (4, 6, 8, 13),
}
THRESHOLDS = [round(float(t), 2) for t in np.arange(0.16, 0.451, 0.01)]

# Uploads per genuine sequence (real students upload ~3-20 baselines/term).
SEQ_CAP = 24
N_SHUFFLES = 5  # extra random upload orders per author, seeded
IMPOSTOR_DOCS_PER_PAIR = 10


def weighted_mean(vectors: np.ndarray) -> np.ndarray:
    """baseline_mean for auth_weight=1.0 samples: w_i = RECENCY_DECAY^(N-1-i)."""
    n = len(vectors)
    w = RECENCY_DECAY ** np.arange(n - 1, -1, -1, dtype=np.float64)
    return (w[:, None] * vectors).sum(axis=0) / w.sum()


def tier_deltas(mu: np.ndarray, v: np.ndarray) -> dict[int, float]:
    """Per-tier mean |delta|, rounded to 4 decimals exactly as check_drift does."""
    return {t: round(float(np.abs(v[idx] - mu[idx]).mean()), 4) for t, idx in TIER_INDICES.items()}


def magnitude(deltas: dict[int, float], anchors: tuple[int, ...]) -> float:
    return float(np.mean([deltas[t] for t in anchors]))


def simulate_sequence(
    vectors: np.ndarray, order: list[int], threshold: float, anchors: tuple[int, ...]
) -> tuple[list[dict], list[int]]:
    """Sequential baseline-upload simulation with production gate dynamics.

    Returns (per-check records, final accepted order-indices). The first
    sample bootstrap-accepts without a check, as in check_drift.
    """
    accepted: list[int] = [order[0]]
    checks: list[dict] = []
    for oi in order[1:]:
        mu = weighted_mean(vectors[accepted])
        deltas = tier_deltas(mu, vectors[oi])
        mag = magnitude(deltas, anchors)
        held = mag > threshold
        checks.append(
            {"doc": int(oi), "magnitude": mag, "held": held, "baseline_size": len(accepted)}
        )
        if not held:
            accepted.append(oi)
    return checks, accepted


def consecutive_outcomes(held_flags: list[bool], consecutive_required: int) -> tuple[int, int]:
    """(n_202_flag_for_review, n_409_rebaseline) for a hold/accept sequence."""
    count = 0
    n202 = n409 = 0
    for h in held_flags:
        if h:
            count += 1
            if count >= consecutive_required:
                n409 += 1
            else:
                n202 += 1
        else:
            count = 0
    return n202, n409


def verify_against_production(vectors: np.ndarray, authors: dict[str, list[int]]) -> None:
    """Assert the simulator matches StudentState.check_drift exactly."""
    from original.quantum.state import BaselineSample, StudentState

    for author in ["seminary_09", "seminary_06", "burke"]:
        idxs = authors.get(author)
        if not idxs:
            continue
        order = idxs[:12]
        state = StudentState(student_id=f"verify_{author}")
        sim_checks, _ = simulate_sequence(vectors, order, 0.25, (4, 6))
        sim_iter = iter(sim_checks)
        for j, oi in enumerate(order):
            sample = BaselineSample(
                text="", vector=vectors[oi], provenance="proctored", auth_weight=1.0
            )
            result = state.check_drift(sample)
            if j == 0:
                assert result.recommendation == "accept"
            else:
                sim = next(sim_iter)
                assert abs(result.drift_magnitude - round(sim["magnitude"], 4)) < 1e-9, (
                    f"{author} doc {j}: prod {result.drift_magnitude} != sim {sim['magnitude']}"
                )
                assert result.drift_detected == sim["held"], f"{author} doc {j} decision mismatch"
            if result.recommendation == "accept":
                state.add_sample(sample)
    print("verify_against_production: simulator matches check_drift", flush=True)


def auc(genuine: np.ndarray, impostor: np.ndarray) -> float:
    """Rank AUC: P(impostor magnitude > genuine magnitude), ties=0.5."""
    from scipy.stats import rankdata

    if len(genuine) == 0 or len(impostor) == 0:
        return float("nan")
    r = rankdata(np.concatenate([genuine, impostor]))
    r_imp = r[len(genuine) :].sum()
    n1, n2 = len(impostor), len(genuine)
    return float((r_imp - n1 * (n1 + 1) / 2.0) / (n1 * n2))


def main(npz_path: str, out_path: str) -> None:
    data = np.load(npz_path, allow_pickle=False)
    vectors = data["vectors"]
    meta = json.loads(str(data["meta"]))
    assert len(meta) == len(vectors)

    # author -> doc indices in sorted-path order
    authors: dict[str, list[int]] = defaultdict(list)
    family: dict[str, str] = {}
    role: dict[str, str] = {}
    order_pairs = sorted(range(len(meta)), key=lambda i: meta[i]["path"])
    for i in order_pairs:
        a = meta[i]["author"]
        authors[a].append(i)
        family[a] = meta[i]["family"]
        role[a] = meta[i]["role"]

    genuine_authors = [a for a in authors if role[a] == "genuine" and len(authors[a]) >= 4]
    impostor_only = [a for a in authors if role[a] == "impostor_only"]

    verify_against_production(vectors, authors)

    rng = random.Random(20260813)
    orders: dict[str, list[list[int]]] = {}
    for a in genuine_authors:
        docs = authors[a][:SEQ_CAP]
        os_ = [list(docs)]
        for _ in range(N_SHUFFLES):
            sh = list(authors[a])
            rng.shuffle(sh)
            os_.append(sh[:SEQ_CAP])
        orders[a] = os_

    results: dict = {
        "config": {
            "thresholds": THRESHOLDS,
            "anchor_sets": {k: list(v) for k, v in ANCHOR_SETS.items()},
            "seq_cap": SEQ_CAP,
            "n_shuffles": N_SHUFFLES,
            "recency_decay": RECENCY_DECAY,
            "genuine_authors": {a: len(authors[a]) for a in genuine_authors},
            "impostor_only": {a: len(authors[a]) for a in impostor_only},
        }
    }

    # ── Threshold-free discrimination (AUC per anchor set / family) ──────────
    # Genuine magnitudes from no-gate trajectories (every doc admitted);
    # impostor magnitudes vs the same full baselines at k=3/5/full.
    print("threshold-free AUC pass...", flush=True)
    auc_out: dict = {}
    genuine_mags: dict[str, dict[str, list[float]]] = {k: defaultdict(list) for k in ANCHOR_SETS}
    imp_mags: dict[str, dict[str, dict[str, list[float]]]] = {
        k: {"k3": defaultdict(list), "k5": defaultdict(list), "full": defaultdict(list)}
        for k in ANCHOR_SETS
    }
    for a in genuine_authors:
        docs = authors[a][:SEQ_CAP]
        fam = family[a]
        # no-gate genuine checks (sorted order)
        for j in range(1, len(docs)):
            mu = weighted_mean(vectors[docs[:j]])
            deltas = tier_deltas(mu, vectors[docs[j]])
            for aname, anchors in ANCHOR_SETS.items():
                genuine_mags[aname][fam].append(magnitude(deltas, anchors))
        # impostor probes vs this author's baselines
        mus = {"k3": weighted_mean(vectors[docs[:3]]), "k5": weighted_mean(vectors[docs[:5]]),
               "full": weighted_mean(vectors[docs])}
        # Same-family probes only (register-matched — the hard case). ai/ghost
        # carry family "seminary" so they probe seminary baselines.
        probes = [b for b in genuine_authors + impostor_only if b != a and family[b] == fam]
        for b in probes:
            for oi in authors[b][:IMPOSTOR_DOCS_PER_PAIR]:
                for kname, mu in mus.items():
                    deltas = tier_deltas(mu, vectors[oi])
                    for aname, anchors in ANCHOR_SETS.items():
                        imp_mags[aname][kname][fam].append(magnitude(deltas, anchors))
    for aname in ANCHOR_SETS:
        auc_out[aname] = {}
        fams = set(genuine_mags[aname])
        for fam in fams:
            g = np.array(genuine_mags[aname][fam])
            auc_out[aname][fam] = {
                k: auc(g, np.array(imp_mags[aname][k][fam])) for k in ("k3", "k5", "full")
            }
        g_all = np.array([m for fam in fams for m in genuine_mags[aname][fam]])
        auc_out[aname]["pooled"] = {
            k: auc(
                g_all, np.array([m for fam in fams for m in imp_mags[aname][k][fam]])
            )
            for k in ("k3", "k5", "full")
        }
    results["auc"] = auc_out

    # ── Operational sweep: gate dynamics per (threshold, anchor set) ─────────
    print("operational sweep...", flush=True)
    sweep: list[dict] = []
    for aname, anchors in ANCHOR_SETS.items():
        for t in THRESHOLDS:
            # genuine side
            n_checks = n_holds = 0
            fam_checks: dict[str, int] = defaultdict(int)
            fam_holds: dict[str, int] = defaultdict(int)
            authors_hit = set()
            n202 = {1: 0, 2: 0, 3: 0}
            n409 = {1: 0, 2: 0, 3: 0}
            holds_by_bsize: dict[str, int] = defaultdict(int)
            checks_by_bsize: dict[str, int] = defaultdict(int)
            gated_baseline: dict[str, list[int]] = {}
            held_files_prod: list[dict] = []
            for a in genuine_authors:
                for k, order in enumerate(orders[a]):
                    checks, accepted = simulate_sequence(vectors, order, t, anchors)
                    if k == 0:
                        gated_baseline[a] = accepted
                    flags = [c["held"] for c in checks]
                    n_checks += len(checks)
                    n_holds += sum(flags)
                    fam_checks[family[a]] += len(checks)
                    fam_holds[family[a]] += sum(flags)
                    if any(flags):
                        authors_hit.add(a)
                    for cr in (1, 2, 3):
                        a202, a409 = consecutive_outcomes(flags, cr)
                        n202[cr] += a202
                        n409[cr] += a409
                    for c in checks:
                        b = "1-2" if c["baseline_size"] <= 2 else ("3-5" if c["baseline_size"] <= 5 else "6+")
                        checks_by_bsize[b] += 1
                        if c["held"]:
                            holds_by_bsize[b] += 1
                    if (
                        aname == "t4+6"
                        and t == 0.25
                        and k == 0
                    ):
                        for c in checks:
                            if c["held"]:
                                held_files_prod.append(
                                    {
                                        "author": a,
                                        "path": meta[c["doc"]]["path"],
                                        "magnitude": c["magnitude"],
                                    }
                                )
            # impostor side vs gated (sorted-order) baselines
            imp_checks = imp_caught = 0
            fam_ichecks: dict[str, int] = defaultdict(int)
            fam_icaught: dict[str, int] = defaultdict(int)
            caught_k = {"k3": [0, 0], "k5": [0, 0]}
            for a in genuine_authors:
                fam = family[a]
                accepted = gated_baseline[a]
                if len(accepted) < 3:
                    continue
                mus = {
                    "k3": weighted_mean(vectors[accepted[:3]]),
                    "k5": weighted_mean(vectors[accepted[:5]]) if len(accepted) >= 5 else None,
                    "full": weighted_mean(vectors[accepted]),
                }
                probes = [
                    b for b in genuine_authors + impostor_only if b != a and family[b] == fam
                ]
                for b in probes:
                    for oi in authors[b][:IMPOSTOR_DOCS_PER_PAIR]:
                        deltas = tier_deltas(mus["full"], vectors[oi])
                        caught = magnitude(deltas, anchors) > t
                        imp_checks += 1
                        imp_caught += int(caught)
                        fam_ichecks[fam] += 1
                        fam_icaught[fam] += int(caught)
                        d3 = tier_deltas(mus["k3"], vectors[oi])
                        caught_k["k3"][0] += 1
                        caught_k["k3"][1] += int(magnitude(d3, anchors) > t)
                        if mus["k5"] is not None:
                            d5 = tier_deltas(mus["k5"], vectors[oi])
                            caught_k["k5"][0] += 1
                            caught_k["k5"][1] += int(magnitude(d5, anchors) > t)
            row = {
                "anchor_set": aname,
                "threshold": t,
                "genuine_checks": n_checks,
                "genuine_holds": n_holds,
                "false_hold_rate": n_holds / n_checks if n_checks else None,
                "false_hold_rate_by_family": {
                    f: fam_holds[f] / fam_checks[f] for f in fam_checks
                },
                "authors_with_any_hold": len(authors_hit),
                "n_genuine_authors": len(genuine_authors),
                "outcome_202_409_by_consecutive": {
                    str(cr): [n202[cr], n409[cr]] for cr in (1, 2, 3)
                },
                "hold_rate_by_baseline_size": {
                    b: (holds_by_bsize[b] / checks_by_bsize[b] if checks_by_bsize[b] else None)
                    for b in ("1-2", "3-5", "6+")
                },
                "impostor_checks": imp_checks,
                "impostor_caught": imp_caught,
                "catch_rate": imp_caught / imp_checks if imp_checks else None,
                "catch_rate_by_family": {
                    f: fam_icaught[f] / fam_ichecks[f] for f in fam_ichecks
                },
                "catch_rate_k3": caught_k["k3"][1] / caught_k["k3"][0] if caught_k["k3"][0] else None,
                "catch_rate_k5": caught_k["k5"][1] / caught_k["k5"][0] if caught_k["k5"][0] else None,
            }
            if aname == "t4+6" and t == 0.25:
                row["held_files_at_production_default"] = held_files_prod
            sweep.append(row)
            if t in (0.25, 0.30, 0.35):
                print(
                    f"  {aname} t={t}: FPR={row['false_hold_rate']:.4f} "
                    f"catch={row['catch_rate']:.3f}",
                    flush=True,
                )
    results["sweep"] = sweep

    with open(out_path, "w") as f:
        json.dump(results, f, indent=1)
    print(f"wrote {out_path}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
