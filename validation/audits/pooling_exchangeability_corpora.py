"""Measure the pooled-typicality exchangeability assumption on the committed
corpora -- every group, every union, and the G1-eligible subsets.

Why this exists: ``pooling_exchangeability.assess_exchangeability`` (Task 7 of
docs/superpowers/plans/2026-07-31-pilot-scale-reachability.md) shipped on
2026-08-01 with synthetic unit tests only. No committed artifact records it
ever being run on real data, yet ``validation/calibration_gate.py``'s
corpus-group pooling helpers and the ``TYPICALITY_POOLED_CALIBRATION`` flag
rows in CLAUDE.md / MODEL_CARD.md describe "within-seminary and within-Plato
exchangeability, validated separately" as the only evidence that exists.
This script is the first real-corpus measurement, so it reports the
within-group verdicts alongside the union and public_authors verdicts the
campaign plan (docs/superpowers/plans/2026-08-26-codex-campaign-01-gate-repair.md,
G4) asked for -- not just the gap.

What is assessed: each entity's ``StudentState.loo_distances`` (leave-one-out
rms_z, one per contributing baseline sample) after uploading ALL of that
entity's texts through the live ``/students/{sid}/baseline`` route -- the
same quantity ``original/quantum/pooled_source.collect_tenant_distances``
pools and the same construction ``_build_pool_reference_states`` uses for a
pool-reference peer. Entities are then grouped and passed to
``assess_exchangeability`` as one population per row.

Rows reported (each is an independent verdict; a heterogeneous union does
not contaminate a within-group row, and vice versa):

  * seminary / plato / public_authors -- every entity with >= 2 contributing
    samples (the assessor's own floor);
  * the same three restricted to G1's >= 5-text LOO eligibility bar, because
    that is the population ``_score_corpus_for_g1_pooled`` actually pools
    (public_authors has no such entity: 3-4 texts each);
  * seminary+plato union and the all-three union, both unrestricted and
    G1-eligible -- the cross-group pooling that ``_pool_peers_for_entity``
    currently forbids for want of evidence;
  * g6 -- the native_english-annotated authentic corpus
    ``_compute_g6_fairness_data_pooled`` pools as one homogeneous group.

Phase-8 drift-gate holds (202/409 on upload) are recorded per entity, never
silently absorbed: a held sample does not contribute to ``loo_distances``,
so the reported ``n_distances`` is what the pooled reference would really
see, and the hold counts say how far that is from the raw text count.

Run (mirrors validation/audits/pooled_calibration_payoff.py):

    nohup ~/Desktop/Original/.venv/bin/python \
        -m validation.audits.pooling_exchangeability_corpora \
        > /path/to/log 2>&1 & disown

Writes validation/audits/pooling_exchangeability_<date>.json.
"""

from __future__ import annotations

import datetime
import json
import os
import statistics
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

G1_MIN_TEXTS = 5  # _score_corpus_for_g1's LOO participation bar
G6_MIN_TEXTS = 3  # _compute_g6_fairness_data_pooled's participation bar


# ── Pure helpers (unit-tested in tests/test_pooling_exchangeability.py) ───────


def summarize_distances(per_entity: dict[str, list[float]]) -> dict:
    """Per-entity mean/std/n plus the population's spread of entity means --
    context that makes a 'heterogeneous' verdict readable (which entities
    sit far from the rest), never a second verdict."""
    rows = {}
    for entity_id, d in per_entity.items():
        rows[entity_id] = {
            "n": len(d),
            "mean": statistics.fmean(d) if d else None,
            "std": statistics.pstdev(d) if len(d) > 1 else None,
        }
    means = [r["mean"] for r in rows.values() if r["mean"] is not None]
    return {
        "per_entity": rows,
        "n_entities": len(rows),
        "n_distances": sum(r["n"] for r in rows.values()),
        "entity_mean_min": min(means) if means else None,
        "entity_mean_max": max(means) if means else None,
        "entity_mean_median": statistics.median(means) if means else None,
    }


def assess_population(
    label: str, per_entity: dict[str, list[float]], description: str
) -> dict:
    from validation.audits.pooling_exchangeability import assess_exchangeability

    verdict = assess_exchangeability(list(per_entity.values()))
    return {
        "label": label,
        "description": description,
        "entities": sorted(per_entity),
        **verdict,
        "summary": summarize_distances(per_entity),
    }


def build_populations(
    distances: dict[str, list[float]],
    group_of: dict[str, str],
    text_counts: dict[str, int],
    g6_distances: dict[str, list[float]],
) -> list[dict]:
    """Every row the audit reports, from already-collected distances."""

    def subset(groups: set[str], min_texts: int) -> dict[str, list[float]]:
        return {
            e: d
            for e, d in distances.items()
            if group_of.get(e) in groups and text_counts.get(e, 0) >= min_texts
        }

    rows = []
    for g in ("seminary", "plato", "public_authors"):
        rows.append(
            assess_population(
                f"{g}", subset({g}, 2), f"every {g} entity with >= 2 contributing samples"
            )
        )
        rows.append(
            assess_population(
                f"{g}_g1_eligible",
                subset({g}, G1_MIN_TEXTS),
                f"{g} entities with >= {G1_MIN_TEXTS} texts -- the population "
                "_score_corpus_for_g1_pooled actually pools",
            )
        )
    rows.append(
        assess_population(
            "seminary+plato",
            subset({"seminary", "plato"}, 2),
            "cross-group union the pooled G1 leg currently forbids",
        )
    )
    rows.append(
        assess_population(
            "seminary+plato_g1_eligible",
            subset({"seminary", "plato"}, G1_MIN_TEXTS),
            "same union restricted to G1-eligible entities",
        )
    )
    rows.append(
        assess_population(
            "all_three",
            subset({"seminary", "plato", "public_authors"}, 2),
            "all three corpora as one flat 'demo' tenant -- what tenant-string "
            "pooling would silently do",
        )
    )
    rows.append(
        assess_population(
            "all_three_g1_eligible",
            subset({"seminary", "plato", "public_authors"}, G1_MIN_TEXTS),
            "all three corpora, G1-eligible entities only",
        )
    )
    rows.append(
        assess_population(
            "g6_native_english",
            {e: d for e, d in g6_distances.items() if len(d) >= 2},
            "the native_english-annotated authentic corpus "
            "_compute_g6_fairness_data_pooled pools as one group",
        )
    )
    return rows


# ── Real-corpus collection (HTTP, one upload per text) ────────────────────────


def collect_entity_distances(client, sid_prefix: str, texts_by_id: dict[str, list[str]]) -> tuple[dict, dict]:
    """Upload every text of every entity with >= 2 texts under one sid and
    read back loo_distances. Returns (distances, upload_health)."""
    from original import store

    distances: dict[str, list[float]] = {}
    health: dict[str, dict] = {}
    for entity_id, texts in texts_by_id.items():
        if len(texts) < 2:
            continue
        sid = f"demo:{sid_prefix}_{entity_id}"
        counts = {"n_texts": len(texts), "ok": 0, "drift_hold": 0, "other_failure": 0}
        for text in texts:
            r = client.post(
                f"/students/{sid}/baseline",
                json={"text": text, "provenance": "verified", "submitted_at": "2026-01-01"},
            )
            if r.status_code == 200:
                counts["ok"] += 1
            elif r.status_code in (202, 409):
                counts["drift_hold"] += 1
            else:
                counts["other_failure"] += 1
        state = store.get(sid)
        d = [float(x) for x in (state.loo_distances if state is not None else [])]
        counts["n_distances"] = len(d)
        distances[entity_id] = d
        health[entity_id] = counts
        print(f"  {entity_id}: {counts}", flush=True)
    return distances, health


def main() -> dict:
    from validation.benchmark.reproducibility import lock_environment

    lock_environment()
    os.environ["TYPICALITY_SCORING"] = "1"

    from original import store

    store.reset_memory_conn()

    import run as _run_module
    from fastapi.testclient import TestClient

    from validation.calibration_gate import (
        _corpus_fingerprint,
        _group_entities_for_pooling,
        _load_g6_native_english_texts,
        _load_plato_texts_by_dialogue,
        _load_public_authors_baseline_texts,
        _load_seminary_texts,
    )

    seminary = _load_seminary_texts()
    plato = _load_plato_texts_by_dialogue()
    pa = _load_public_authors_baseline_texts()
    g6 = _load_g6_native_english_texts()
    group_of = _group_entities_for_pooling(seminary, plato, pa)
    texts_by_id = {**seminary, **plato, **pa}
    text_counts = {e: len(t) for e, t in texts_by_id.items()}

    client = TestClient(_run_module.load_legacy_demo_app())

    t0 = time.perf_counter()
    print("=== collecting G1-corpora distances ===", flush=True)
    distances, health = collect_entity_distances(client, "audit_exch", texts_by_id)
    print("=== collecting G6 corpus distances ===", flush=True)
    g6_distances, g6_health = collect_entity_distances(client, "audit_exch_g6", g6)
    elapsed = time.perf_counter() - t0

    rows = build_populations(distances, group_of, text_counts, g6_distances)
    for r in rows:
        print(
            f"{r['label']:32s} verdict={r['verdict']:14s} n_students={r['n_students']:3d} "
            f"ratio={r['between_within_variance_ratio']} ks_max={r['ks_max_pairwise']}",
            flush=True,
        )

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "elapsed_seconds": elapsed,
        "assessor": "validation.audits.pooling_exchangeability.assess_exchangeability",
        "assessor_limits": {"ratio_limit": 1.0, "ks_limit": 0.5, "min_students": 3, "min_per_student": 2},
        "quantity": "StudentState.loo_distances (leave-one-out rms_z per contributing sample) "
        "after uploading every text of the entity via /students/{sid}/baseline",
        "corpus_fingerprints": {
            "seminary": _corpus_fingerprint(seminary),
            "plato": _corpus_fingerprint(plato),
            "public_authors": _corpus_fingerprint(pa),
            "g6_native_english": _corpus_fingerprint(g6),
        },
        "upload_health": {"g1_corpora": health, "g6": g6_health},
        "populations": rows,
    }
    out = _HERE / f"pooling_exchangeability_{datetime.date.today().isoformat()}.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"Wrote {out}", flush=True)
    return report


if __name__ == "__main__":
    main()
