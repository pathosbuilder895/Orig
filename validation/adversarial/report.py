"""
validation/adversarial/report.py: the SP1 red-team harness run (Tasks 18-20).

`runner.run_attack` scores ONE victim profile under ONE attack. This module
decides which (profile, attack) cells make up a measurement, runs them
(optionally across worker processes), and reduces the resulting rows into
the inputs the six G-A gates in `validation/calibration_gate.py` evaluate.

Run the whole thing (every gate cell plus the report-only cells) and write
the raw rows to JSON:

    .venv/bin/python -m validation.adversarial.report --out PATH

Scoring configuration
=====================
Every cell is scored through the real API path (`runner.run_attack(...,
path="api")`) under `LIVE_SCORING_ENV`: the env lock's pinned flags plus
every other score-affecting flag at the value the pilot blueprint
(`render.yaml`) deploys. That is the live `deviation_score` and the live
`recommendation.action`, NOT the typicality path `run_all()` turns on for
G1-G6. Worker processes apply it in their initializer; the in-process path
applies it for the duration of the run and restores the caller's values.

Cells
=====
public_authors (`profiles.build_victim_profiles`, N in {3, 5, 10}):
  clean                   attack "none". Genuine holdouts feed G-A1. The
                          impostor docs are OTHER victims' own baseline
                          documents, i.e. a classmate's writing handed in
                          under this student's name: the peer swap G-A4
                          measures. The integrity block is G-A6's
                          clean-profile side.
  obfuscated_baselines,   G-A6's detection side (attacks 1 and 2: the
  outsourced_baselines    whole baseline is obfuscated or someone else's).
  sigma_inflation         G-A5 (against `clean` at the same N); its
                          integrity detection is informational in G-A6.
  mechanical_obfuscation  report-only sanity cell (submissions obfuscated).
llm_attacks (`corpus/llm_attacks/`, absent until `gen_llm_attacks.py` runs
with an API key):
  llm_imitation           G-A2
  llm_paraphrase,         G-A3
  llm_roundtrip_de/_ja
riddell_juola (attack splits committed; needs each participant's prior
writing under `corpus/riddell_juola/baselines/`, see fetch_riddell_juola):
  rj_clean                control participants: their own control essay is a
                          genuine new-topic submission (G-A1); five other
                          control participants' essays on the SAME prompt
                          are a same-assignment peer swap (G-A4).
  rj_embedded_control,    N-1 prior chunks plus the participant's essay as
  rj_embedded_obfuscation the LAST baseline document; one held-out chunk is
  rj_embedded_imitation   scored to obtain the live integrity block. G-A6:
                          control is the clean side (a topic shift alone),
                          obfuscation/imitation the detection side.
  rj_self_obfuscation,    report-only: the participant's own attack essay
  rj_self_imitation       against their own prior writing (does deliberate
                          restyling move the live score?).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from validation.adversarial.profiles import VictimProfile, build_victim_profiles

_REPO_ROOT = Path(__file__).resolve().parents[2]

HARNESS_SEED = 20260920
NS: tuple[int, ...] = (3, 5, 10)

# The pilot's scoring configuration for every flag the score route reads
# that lock_environment() does not already pin. Values are the code
# defaults, which is what render.yaml's pilot service runs with.
LIVE_SCORING_ENV: dict[str, str] = {
    "TYPICALITY_SCORING": "0",
    "TYPICALITY_POOLED_CALIBRATION": "0",
    "TOPIC_VARIANCE_INFLATION": "0",
    "CHARACTERISTIC_WEIGHTS": "0",
    "LLR_ACTION_MODE": "gate",
    "GENRE_RESOLVER_V2": "off",
    "GENRE_INVARIANT_WEIGHTS_ENABLED": "0",
    "COHORT_PRIOR_FALLBACK": "0",
    "MIN_BASELINE_SAMPLES": "3",
    # Not scoring flags: keep the harness's throwaway students in its own
    # SQLite file even when the calling shell points the app at Postgres.
    "REPO_BACKEND": "sqlite",
    "REPO_SHADOW": "off",
}

_PEERS_PER_VICTIM = 5

PUBLIC_AUTHOR_KINDS: tuple[str, ...] = (
    "clean",
    "mechanical_obfuscation",
    "obfuscated_baselines",
    "outsourced_baselines",
    "sigma_inflation",
)
LLM_KINDS: tuple[str, ...] = (
    "llm_imitation",
    "llm_paraphrase",
    "llm_roundtrip_de",
    "llm_roundtrip_ja",
)
RJ_KINDS: tuple[str, ...] = (
    "rj_clean",
    "rj_embedded_control",
    "rj_embedded_obfuscation",
    "rj_embedded_imitation",
    "rj_self_obfuscation",
    "rj_self_imitation",
)

# Which cells each gate leg needs. Cells not listed under any leg are
# report-only and run only from this module's CLI.
LEG_KINDS: dict[str, tuple[str, ...]] = {
    "G-A1": ("clean", "rj_clean"),
    "G-A2": ("clean", "llm_imitation"),
    "G-A3": ("clean", "llm_paraphrase", "llm_roundtrip_de", "llm_roundtrip_ja"),
    "G-A4": ("clean", "rj_clean"),
    "G-A5": ("clean", "sigma_inflation"),
    "G-A6": (
        "clean",
        "obfuscated_baselines",
        "outsourced_baselines",
        "sigma_inflation",
        "rj_embedded_control",
        "rj_embedded_obfuscation",
        "rj_embedded_imitation",
    ),
}
ALL_KINDS: tuple[str, ...] = PUBLIC_AUTHOR_KINDS + LLM_KINDS + RJ_KINDS

_ATTACK_FOR_KIND = {
    "mechanical_obfuscation": "mechanical_obfuscation",
    "obfuscated_baselines": "obfuscated_baselines",
    "outsourced_baselines": "outsourced_baselines",
    "sigma_inflation": "sigma_inflation",
}


@dataclass(frozen=True)
class Cell:
    """One unit of work: score `profile` under `attack` via the runner.

    `injected_indices` are the positions in the baseline list actually
    scored against that are NOT the victim's own writing (empty for a
    clean baseline); G-A6 counts a detection only when the drift gate or
    the integrity block points at one of them.
    """

    corpus: str
    kind: str
    n: int
    attack: str
    profile: VictimProfile
    injected_indices: tuple[int, ...] = ()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ── Cell construction ──────────────────────────────────────────────────────


def _injected(original: list[str], poisoned: list[str]) -> tuple[int, ...]:
    return tuple(i for i, (a, b) in enumerate(zip(original, poisoned, strict=True)) if a != b)


def _public_author_cells(ns, seed, kinds) -> tuple[list[Cell], dict[int, list[VictimProfile]]]:
    from validation.adversarial.poisoning import poison_profile

    cells: list[Cell] = []
    profiles_by_n: dict[int, list[VictimProfile]] = {}
    for n in ns:
        profiles = build_victim_profiles(n, seed=seed)
        profiles_by_n[n] = profiles
        for profile in profiles:
            for kind in kinds:
                if kind not in PUBLIC_AUTHOR_KINDS:
                    continue
                injected: tuple[int, ...] = ()
                if kind in ("obfuscated_baselines", "outsourced_baselines", "sigma_inflation"):
                    injected = _injected(
                        profile.baselines, poison_profile(profile, kind).baselines
                    )
                cells.append(
                    Cell(
                        corpus="public_authors",
                        kind=kind,
                        n=n,
                        attack=_ATTACK_FOR_KIND.get(kind, "none"),
                        profile=profile,
                        injected_indices=injected,
                    )
                )
    return cells, profiles_by_n


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def llm_cache_status() -> dict:
    from validation.adversarial.generators import LLMImitation

    manifest = LLMImitation.CACHE_DIR / "manifest.json"
    return {"present": manifest.exists(), "manifest": _display_path(manifest)}


def _llm_cells(profiles_by_n, kinds) -> list[Cell]:
    """LLM attack docs scored against the same victim's clean baseline.

    Imitations are scored only at the N they were written from (their
    manifest `n_baselines`): an imitation of three essays scored against a
    ten-essay baseline answers a different question. Paraphrase and
    round-trip docs rewrite the victim's genuine holdout, which does not
    depend on N, so they are scored at every N the victim has. The genuine
    comparator is the `clean` cell of the same (victim, N), so these cells
    score only the attack docs."""
    from validation.adversarial.generators import LLMImitation, LLMParaphrase, LLMRoundTrip

    readers = {
        "llm_imitation": lambda vid: LLMImitation(vid),
        "llm_paraphrase": lambda vid: LLMParaphrase(vid),
        "llm_roundtrip_de": lambda vid: LLMRoundTrip(vid, "de"),
        "llm_roundtrip_ja": lambda vid: LLMRoundTrip(vid, "ja"),
    }
    cells: list[Cell] = []
    for n, profiles in profiles_by_n.items():
        for profile in profiles:
            for kind in kinds:
                if kind not in readers:
                    continue
                reader = readers[kind](profile.victim_id)
                if not reader.configured:
                    continue
                docs = [
                    text
                    for entry, text in reader.load_entries()
                    if kind != "llm_imitation" or entry.get("n_baselines") == n
                ]
                if not docs:
                    continue
                cells.append(
                    Cell(
                        corpus="llm_attacks",
                        kind=kind,
                        n=n,
                        attack="none",
                        profile=VictimProfile(
                            victim_id=profile.victim_id,
                            baselines=list(profile.baselines),
                            genuine_holdout=[],
                            impostor_docs=docs,
                        ),
                    )
                )
    return cells


def riddell_juola_status() -> dict:
    from validation.adversarial import fetch_riddell_juola as rj

    baselines = rj.load_riddell_juola_baselines(rj.CORPUS_DIR)
    return {
        "attack_splits_present": True,
        "participant_baselines_present": bool(baselines),
        "participants_with_baselines": len(baselines),
    }


def _rj_order(chunks: list[str]) -> list[str]:
    """Content-addressed order (profiles.py's convention), so which chunks
    form the baseline does not depend on file numbering."""
    return sorted(chunks, key=_digest)


def _rj_cells(ns, seed, kinds) -> list[Cell]:
    from validation.adversarial import fetch_riddell_juola as rj

    if not any(kind in RJ_KINDS for kind in kinds):
        return []
    chunks_by_pid = {
        pid: _rj_order(chunks)
        for pid, chunks in rj.load_riddell_juola_baselines(rj.CORPUS_DIR).items()
    }
    if not chunks_by_pid:
        return []
    essays = {
        condition: rj.load_riddell_juola_split_by_id(condition, rj.CORPUS_DIR)
        for condition in ("control", "obfuscation", "imitation")
    }
    cells: list[Cell] = []
    for n in ns:
        # A participant needs N chunks for the baseline and one more to hold
        # out (the embedded cells score a held-out chunk), so every RJ cell
        # at a given N draws from the same participants.
        eligible = {pid for pid, chunks in chunks_by_pid.items() if len(chunks) >= n + 1}
        control_ids = sorted(pid for pid in essays["control"] if pid in eligible)
        for pid in control_ids:
            chunks = chunks_by_pid[pid]
            peers = sorted(
                (p for p in control_ids if p != pid),
                key=lambda p: _digest(f"{seed}:rj-peers:{pid}:{p}"),
            )[:_PEERS_PER_VICTIM]
            if "rj_clean" in kinds:
                cells.append(
                    Cell(
                        corpus="riddell_juola",
                        kind="rj_clean",
                        n=n,
                        attack="none",
                        profile=VictimProfile(
                            victim_id=pid,
                            baselines=chunks[:n],
                            genuine_holdout=[essays["control"][pid]],
                            impostor_docs=[essays["control"][p] for p in peers],
                        ),
                    )
                )
        for condition in ("control", "obfuscation", "imitation"):
            for pid in sorted(p for p in essays[condition] if p in eligible):
                chunks = chunks_by_pid[pid]
                essay = essays[condition][pid]
                if f"rj_embedded_{condition}" in kinds:
                    cells.append(
                        Cell(
                            corpus="riddell_juola",
                            kind=f"rj_embedded_{condition}",
                            n=n,
                            attack="none",
                            profile=VictimProfile(
                                victim_id=pid,
                                baselines=chunks[: n - 1] + [essay],
                                genuine_holdout=[chunks[n]],
                                impostor_docs=[],
                            ),
                            injected_indices=(n - 1,),
                        )
                    )
                if condition != "control" and f"rj_self_{condition}" in kinds:
                    cells.append(
                        Cell(
                            corpus="riddell_juola",
                            kind=f"rj_self_{condition}",
                            n=n,
                            attack="none",
                            profile=VictimProfile(
                                victim_id=pid,
                                baselines=chunks[:n],
                                genuine_holdout=[],
                                impostor_docs=[essay],
                            ),
                        )
                    )
    return cells


def build_cells(kinds=ALL_KINDS, ns=NS, seed=HARNESS_SEED) -> list[Cell]:
    kinds = tuple(kinds)
    cells, profiles_by_n = _public_author_cells(ns, seed, kinds)
    cells += _llm_cells(profiles_by_n, kinds)
    cells += _rj_cells(ns, seed, kinds)
    return cells


def kinds_for_legs(legs) -> tuple[str, ...]:
    wanted: list[str] = []
    for leg in legs:
        for kind in LEG_KINDS[leg]:
            if kind not in wanted:
                wanted.append(kind)
    return tuple(wanted)


# ── Running ────────────────────────────────────────────────────────────────


@contextlib.contextmanager
def live_scoring_env():
    """Apply LIVE_SCORING_ENV for the duration, restoring the caller's
    values afterwards (run_all() sets TYPICALITY_SCORING=1 for its own
    legs and must get it back)."""
    saved = {key: os.environ.get(key) for key in LIVE_SCORING_ENV}
    os.environ.update(LIVE_SCORING_ENV)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _row(cell: Cell, path: str) -> dict:
    from validation.adversarial.runner import run_attack

    result = run_attack(cell.profile, cell.attack, path=path)
    row = {
        "corpus": cell.corpus,
        "kind": cell.kind,
        "n": cell.n,
        "injected_indices": list(cell.injected_indices),
        "n_baseline_docs": len(cell.profile.baselines),
    }
    row.update(json.loads(json.dumps(asdict(result))))
    return row


def _worker_init() -> None:
    import logging
    import warnings

    from validation.benchmark.reproducibility import lock_environment

    lock_environment()  # fresh per-process ORIGINAL_DB, pinned flags
    os.environ.update(LIVE_SCORING_ENV)
    logging.disable(logging.WARNING)
    warnings.filterwarnings("ignore")
    from validation.vector_cache import maybe_install_from_env

    maybe_install_from_env()


def _cell_cost(cell: Cell) -> int:
    p = cell.profile
    return sum(len(t.split()) for t in p.baselines + p.genuine_holdout + p.impostor_docs)


def default_workers() -> int:
    configured = int(os.environ.get("ADVERSARIAL_WORKERS", "0") or 0)
    if configured > 0:
        return configured
    return max(1, min(8, (os.cpu_count() or 2) - 2))


def run_cells(cells: list[Cell], path: str = "api", workers: int = 1) -> list[dict]:
    """Score every cell, longest first so the pool stays busy. Rows come
    back in the order of `cells` regardless of completion order."""
    order = sorted(range(len(cells)), key=lambda i: -_cell_cost(cells[i]))
    rows: list[dict | None] = [None] * len(cells)
    started = time.monotonic()

    def _progress(done: int) -> None:
        if done == len(cells) or done % max(1, len(cells) // 10) == 0:
            elapsed = int(time.monotonic() - started)
            print(f"[adversarial] {done}/{len(cells)} cells, +{elapsed}s", flush=True)

    if workers <= 1:
        with live_scoring_env():
            for done, i in enumerate(order, 1):
                rows[i] = _row(cells[i], path)
                _progress(done)
        return rows  # type: ignore[return-value]

    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor, as_completed

    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers, mp_context=ctx, initializer=_worker_init
    ) as pool:
        futures = {pool.submit(_row, cells[i], path): i for i in order}
        for done, future in enumerate(as_completed(futures), 1):
            rows[futures[future]] = future.result()
            _progress(done)
    return rows  # type: ignore[return-value]


def run_harness(
    legs=None,
    *,
    kinds=None,
    ns=NS,
    seed=HARNESS_SEED,
    path: str = "api",
    workers: int | None = None,
) -> dict:
    """Build and score the cells the given gate legs need (or `kinds`, or
    every cell), returning `{"meta": ..., "rows": [...]}`."""
    if kinds is None:
        kinds = kinds_for_legs(legs) if legs else ALL_KINDS
    workers = default_workers() if workers is None else workers
    started = time.monotonic()
    # Snapshot corpus status before building cells, so the metadata describes
    # what the cells were built from even if a corpus lands mid-run.
    llm_status, rj_status = llm_cache_status(), riddell_juola_status()
    cells = build_cells(kinds, ns, seed)
    rows = run_cells(cells, path=path, workers=workers)
    texts = sorted(
        {_digest(t) for c in cells for t in c.profile.baselines + c.profile.genuine_holdout
         + c.profile.impostor_docs}
    )
    from validation.vector_cache import semantic_backend

    return {
        "meta": {
            # Tier 10's encoder: "tfidf" matches the pilot, whose
            # requirements leave sentence-transformers out; "st" would not.
            "semantic_backend": semantic_backend(),
            "corpus_fingerprint": _digest("\n".join(texts)),
            "n_distinct_documents": len(texts),
            "seed": seed,
            "ns": list(ns),
            "path": path,
            "kinds": list(kinds),
            "workers": workers,
            "n_cells": len(cells),
            "runtime_seconds": round(time.monotonic() - started, 1),
            "live_scoring_env": dict(LIVE_SCORING_ENV),
            "llm_attacks": llm_status,
            "riddell_juola": rj_status,
        },
        "rows": rows,
    }


# ── Reducers: rows -> gate inputs ──────────────────────────────────────────
#
# Every population is split by baseline size N. The same documents recur at
# N=3, 5 and 10 (a cross-work victim's holdouts, and the peer documents taken
# from other victims' first baseline, do not depend on N), so pooling across
# N would count one document up to three times and overstate how often a
# result is demonstrated. Within one N a peer document still recurs across
# victims; each use is a test against a different student's baseline, and the
# gate docstrings say so.

CLEAN_KINDS = ("clean", "rj_clean")


def _rows(rows, *kinds):
    return [r for r in rows if r["kind"] in kinds]


def _by_n(rows) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["n"], []).append(r)
    return dict(sorted(grouped.items()))


def ga1_inputs(rows: list[dict]) -> dict:
    """Genuine-holdout actions per N, pooled over corpora, plus the
    per-corpus split and how many profiles the route refused to score."""
    by_n: dict[int, list[str]] = {}
    by_corpus: dict[str, dict[int, list[str]]] = {}
    refused: dict[int, int] = {}
    for r in _rows(rows, *CLEAN_KINDS):
        by_n.setdefault(r["n"], []).extend(r["holdout_actions"])
        by_corpus.setdefault(r["corpus"], {}).setdefault(r["n"], []).extend(r["holdout_actions"])
        if r["scoring_refused"]:
            refused[r["n"]] = refused.get(r["n"], 0) + 1
    return {"holdout_actions_by_n": by_n, "by_corpus_n": by_corpus, "refused_by_n": refused}


def _population(name, family, n, attack_rows, genuine_scores, coverage=None) -> dict:
    return {
        "name": f"{name} N={n}",
        "family": family,
        "n": n,
        "attack_actions": [a for r in attack_rows for a in r["impostor_actions"]],
        "attack_scores": [s for r in attack_rows for s in r["impostor_scores"]],
        "genuine_scores": genuine_scores,
        "n_refused": sum(1 for r in attack_rows if r["scoring_refused"]),
        "coverage": coverage,
    }


def attack_populations(rows: list[dict], kinds) -> list[dict]:
    """One population per (attack kind, N): the attack docs' actions and
    scores, the genuine-holdout scores of the SAME victims' public-author
    clean cells at that N (the LLM attacks are written against those
    victims) as the separation comparator, and `coverage` = [victims with
    attack docs, victims with a clean cell] so a partly generated cache
    cannot pass."""
    clean = {(r["victim_id"], r["n"]): r for r in _rows(rows, "clean")}
    expected = {n: len(group) for n, group in _by_n(_rows(rows, "clean")).items()}
    populations = []
    for kind in kinds:
        for n, kind_rows in _by_n(_rows(rows, kind)).items():
            victims = sorted({r["victim_id"] for r in kind_rows})
            genuine = [
                s for v in victims for s in (clean.get((v, n)) or {}).get("holdout_scores", [])
            ]
            populations.append(
                _population(kind, kind, n, kind_rows, genuine, [len(victims), expected.get(n, 0)])
            )
    return populations


PEER_SWAP_FAMILIES = {
    "clean": "public_authors/peer_swap",
    "rj_clean": "riddell_juola/peer_swap_same_prompt",
}


def peer_swap_populations(rows: list[dict]) -> list[dict]:
    """G-A4: in a clean cell the impostor docs ARE peers' own writing, and
    the holdouts of the same cells are the genuine comparator."""
    populations = []
    for kind, family in PEER_SWAP_FAMILIES.items():
        for n, kind_rows in _by_n(_rows(rows, kind)).items():
            genuine = [s for r in kind_rows for s in r["holdout_scores"]]
            populations.append(_population(family, family, n, kind_rows, genuine))
    return populations


def _caught(actions) -> int:
    return sum(1 for a in actions if a != "no_action")


def _mean(values):
    return sum(values) / len(values) if values else None


def ga5_inputs(rows: list[dict]) -> dict:
    """Per N, clean vs. sigma-inflated baselines for the SAME public-author
    victims: impostor catch at monitor+, the unfloored real-feature baseline
    spread (`mean_baseline_std`), and the inflated cells' impostor and
    genuine scores for the separation leg.

    Only pairs whose injected document actually reached the scored baseline
    are compared. A pair where the drift gate held every injected document
    is the ingestion defence working, not a test of "catch as sigma grows",
    and keeping it would dilute the comparison toward no change; those are
    counted as `n_held`. A pair either side of which was refused scoring is
    dropped from both sides and counted as `n_refused`."""
    clean = {(r["victim_id"], r["n"]): r for r in _rows(rows, "clean")}
    inflated = {(r["victim_id"], r["n"]): r for r in _rows(rows, "sigma_inflation")}
    paired = set(clean) & set(inflated)
    cells = []
    for n in sorted({key[1] for key in paired}):
        keys = sorted(k for k in paired if k[1] == n)
        refused = [k for k in keys if inflated[k]["scoring_refused"] or clean[k]["scoring_refused"]]
        live = [k for k in keys if k not in refused]
        fired = [
            k
            for k in live
            if set(inflated[k]["injected_indices"]) - set(inflated[k]["held_baseline_indices"])
        ]
        c_rows = [clean[k] for k in fired]
        s_rows = [inflated[k] for k in fired]
        cells.append(
            {
                "n": n,
                "n_pairs": len(fired),
                "n_held": len(live) - len(fired),
                "n_refused": len(refused),
                "clean_caught": sum(_caught(r["impostor_actions"]) for r in c_rows),
                "clean_n": sum(len(r["impostor_actions"]) for r in c_rows),
                "inflated_caught": sum(_caught(r["impostor_actions"]) for r in s_rows),
                "inflated_n": sum(len(r["impostor_actions"]) for r in s_rows),
                "clean_mean_sigma": _mean(
                    [r["mean_baseline_std"] for r in c_rows if r["mean_baseline_std"] is not None]
                ),
                "inflated_mean_sigma": _mean(
                    [r["mean_baseline_std"] for r in s_rows if r["mean_baseline_std"] is not None]
                ),
                "inflated_impostor_scores": [x for r in s_rows for x in r["impostor_scores"]],
                "inflated_genuine_scores": [x for r in s_rows for x in r["holdout_scores"]],
            }
        )
    return {"cells": cells}


def _flagged_indices(row: dict) -> tuple[set[int], set[int]]:
    """(indices the integrity block calls LOO outliers, indices the drift
    gate held), both as positions in the SUBMITTED baseline list. The
    integrity block indexes the admitted samples only, so outlier positions
    are mapped back through the held ones."""
    held = set(row["held_baseline_indices"])
    admitted = [i for i in range(row["n_baseline_docs"]) if i not in held]
    outliers: set[int] = set()
    integrity = row.get("baseline_integrity") or {}
    for item in integrity.get("loo_outlier_samples") or []:
        k = item.get("index")
        if isinstance(k, int) and 0 <= k < len(admitted):
            outliers.add(admitted[k])
    return outliers, held


def _detected(row: dict) -> bool:
    outliers, held = _flagged_indices(row)
    return bool((outliers | held) & set(row["injected_indices"]))


def _any_flag(row: dict) -> bool:
    outliers, held = _flagged_indices(row)
    return bool(outliers or held)


GA6_POISONED = {
    "obfuscated_baselines": "public_authors/obfuscated_baselines",
    "outsourced_baselines": "public_authors/outsourced_baselines",
    "rj_embedded_obfuscation": "riddell_juola/embedded_obfuscation",
    "rj_embedded_imitation": "riddell_juola/embedded_imitation",
}
GA6_CLEAN = {
    "clean": "public_authors/clean",
    "rj_embedded_control": "riddell_juola/embedded_control",
}


def ga6_inputs(rows: list[dict]) -> dict:
    """Per (poisoned family, N) the count of profiles where the drift gate
    or the integrity block pointed at an INJECTED document, and per (clean
    family, N) the count with any hold or outlier note (a false alarm), as
    {"<family> N=<n>": (hits, profiles)}. sigma_inflation's detection is
    informational: that attack is G-A5's."""

    def _counts(families: dict, hit) -> dict:
        out = {}
        for kind, family in families.items():
            for n, kind_rows in _by_n(_rows(rows, kind)).items():
                out[f"{family} N={n}"] = (sum(hit(r) for r in kind_rows), len(kind_rows))
        return out

    return {
        "poisoned": _counts(GA6_POISONED, _detected),
        "clean": _counts(GA6_CLEAN, _any_flag),
        "informational": {
            "sigma_inflation_detected": _counts(
                {"sigma_inflation": "public_authors/sigma_inflation"}, _detected
            ),
            "drift_holds_on_injected": _counts(
                GA6_POISONED,
                lambda r: bool(set(r["held_baseline_indices"]) & set(r["injected_indices"])),
            ),
        },
    }


# ── Report-only summaries ──────────────────────────────────────────────────

ACTION_BARS = ("monitor", "schedule_conversation", "escalate")

# Collections (Bluebook) marks a sealed exam "worth a look" when
# authorship_probability * 100 rounds below 70 on a ready baseline
# (bbSealStatus / bbScoreWithOriginal in demo/bluebook/Exam.jsx). That is a
# second live decision rule next to recommendation.action, so the summary
# reports it too.
COLLECTIONS_MARK_BELOW = 70


def _collections_mark_rate(group: list[dict], side: str) -> float | None:
    marks = [
        math.floor(p * 100 + 0.5) < COLLECTIONS_MARK_BELOW  # JS Math.round, as Exam.jsx
        for r in group
        if ((r.get("baseline_integrity") or {}).get("readiness") == "ready")
        for p in r.get(f"{side}_probabilities") or []
    ]
    return sum(marks) / len(marks) if marks else None


def _rate_at_or_above(actions, bar: str) -> float | None:
    from validation.adversarial.runner import ACTION_ORDER

    if not actions:
        return None
    floor = ACTION_ORDER.index(bar)
    return sum(1 for a in actions if ACTION_ORDER.index(a) >= floor) / len(actions)


def summarize(rows: list[dict]) -> dict:
    """Per (corpus, kind, N): how many docs, the share at or above each
    action bar, the mean deviation_score and the Collections "worth a look"
    rate, for the genuine (holdout) and attack (impostor-slot) sides
    separately."""
    out: dict[str, dict] = {}
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["corpus"], r["kind"], r["n"]), []).append(r)
    for (corpus, kind, n), group in sorted(groups.items()):
        entry = {"profiles": len(group), "refused": sum(r["scoring_refused"] for r in group)}
        for side in ("holdout", "impostor"):
            actions = [a for r in group for a in r[f"{side}_actions"]]
            scores = [s for r in group for s in r[f"{side}_scores"]]
            if not actions:
                continue
            entry[side] = {
                "n": len(actions),
                "rate_at_or_above": {bar: _rate_at_or_above(actions, bar) for bar in ACTION_BARS},
                "mean_deviation": sum(scores) / len(scores),
                "collections_mark_rate": _collections_mark_rate(group, side),
            }
        out[f"{corpus}/{kind}/N={n}"] = entry
    return out


def merge_reports(reports: list[dict]) -> dict:
    """Concatenate the rows of several harness reports (e.g. a public-author
    run and a later Riddell-Juola run). Refuses overlapping cells: the same
    (corpus, kind, N, victim) twice would double its documents and could
    turn an underpowered result into a demonstrated one. Corpus status is
    taken from whichever input saw the corpus, and every input's meta is
    kept under `merged_meta`."""
    seen: set[tuple] = set()
    rows: list[dict] = []
    for report in reports:
        for row in report["rows"]:
            key = (row["corpus"], row["kind"], row["n"], row["victim_id"])
            if key in seen:
                raise ValueError(f"cell {key} appears in more than one report")
            seen.add(key)
            rows.append(row)
    metas = [r["meta"] for r in reports]
    meta = dict(metas[0])
    status_flags = (("llm_attacks", "present"), ("riddell_juola", "participant_baselines_present"))
    for key, flag in status_flags:
        for m in metas:
            if (m.get(key) or {}).get(flag):
                meta[key] = m[key]
    if len(metas) > 1:
        meta["merged_meta"] = metas
    return {"meta": meta, "rows": rows}


def _write(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="where to write the JSON report")
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument(
        "--kinds", default=None, help=f"comma-separated subset of {', '.join(ALL_KINDS)}"
    )
    parser.add_argument(
        "--reuse",
        type=Path,
        nargs="+",
        default=None,
        help="recompute the summary and gates from the rows of earlier reports "
        "(concatenated) instead of scoring anything",
    )
    args = parser.parse_args(argv)

    if args.reuse:
        report = merge_reports([json.loads(p.read_text()) for p in args.reuse])
        report["meta"]["reused_from"] = [str(p) for p in args.reuse]
    else:
        kinds = tuple(k.strip() for k in args.kinds.split(",")) if args.kinds else ALL_KINDS
        report = run_harness(kinds=kinds, workers=args.workers)
        # The scoring is the expensive part: keep it even if a later step
        # fails.
        _write(args.out, report)

    from validation.calibration_gate import adversarial_results_from_rows, render

    report["summary"] = summarize(report["rows"])
    gates = adversarial_results_from_rows(report["rows"], report["meta"])
    report["gates"] = [asdict(g) for g in gates]
    _write(args.out, report)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(render(gates))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    from validation.benchmark.reproducibility import lock_environment

    lock_environment()
    sys.exit(main())
