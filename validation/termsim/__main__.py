"""Command-line entry point for deterministic deployment-shaped validation."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from validation.termsim.matrix import cells
from validation.termsim.metrics import compute
from validation.termsim.personas import CorpusTextResolver, build_manifest
from validation.termsim.scorecard import build, json_text, markdown, verify_diff_directions
from validation.termsim.script import dumps, generate, script_hash

ROOT = Path(__file__).resolve().parents[2]
SCORE_FLAGS = {
    key for config in cells().values() for key in config
} | {"TOPIC_VARIANCE_INFLATION", "CHARACTERISTIC_WEIGHTS", "GENRE_RESOLVER_V2"}


def _run_cell(payload: tuple) -> dict:
    name, flags, seed, cohorts, weeks, scenarios, out_dir, backend = payload
    # Determinism guard: main() exports this before spawning workers, so a
    # worker without it means the harness was entered some other way.
    assert os.environ.get("PYTHONHASHSEED") == "0", "PYTHONHASHSEED=0 not exported"
    for key in SCORE_FLAGS:
        os.environ[key] = "0"
    os.environ.update(flags)
    db_dir = Path(tempfile.mkdtemp(prefix=f"termsim-{name}-"))
    os.environ["ORIGINAL_DB"] = str(db_dir / "profiles.db")
    if backend == "postgres":
        from validation.termsim.runner import create_postgres_schema, isolated_postgres_url

        base_url = os.environ.get("DATABASE_URL", "")
        if not base_url.startswith("postgresql"):
            raise RuntimeError(
                "--backend postgres needs DATABASE_URL set to a postgresql:// "
                "instance — run `bash scripts/local_postgres.sh up` and export "
                "DATABASE_URL=$(bash scripts/local_postgres.sh url)")
        os.environ["DATABASE_URL"] = isolated_postgres_url(base_url, name)
        os.environ["REPO_BACKEND"] = "postgres"
        create_postgres_schema()
    else:
        os.environ["DATABASE_URL"] = f"sqlite:///{db_dir / 'live.db'}"
        os.environ["REPO_BACKEND"] = "sqlite"
    os.environ.setdefault("SECRET_KEY", "termsim-isolated-secret-" * 3)

    from fastapi.testclient import TestClient
    import run

    manifest = build_manifest()
    events = generate(seed, cohort_sizes=cohorts, weeks=weeks,
                      personas=manifest["personas"], scenarios=scenarios)
    started = time.perf_counter()
    from validation.termsim.runner import install_vector_cache
    install_vector_cache(ROOT / ".benchmark_cache" / "termsim" / "vectors")
    with TestClient(run.load_legacy_demo_app()) as client:
        from validation.termsim.runner import run_events
        rows = run_events(client, events, CorpusTextResolver(manifest), accrete=True)
    elapsed = time.perf_counter() - started
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    log_path = output / f"{name}.jsonl"
    log_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    return {"cell": name, "flags": flags, "seed": seed, "elapsed_seconds": elapsed,
            "script_sha256": script_hash(events), "manifest_sha256": manifest["manifest_sha256"],
            "event_log": str(log_path), "metrics": compute(rows)}


def pooled_gate_evidence(seed_dirs: list[Path], cell: str = "baseline") -> dict:
    """Pool a cell's event logs across seeds into one gate-evidence payload.

    Students are namespaced by seed before pooling so per-student term
    aggregation never merges two seeds' terms; the pooled metrics are what
    reports/latest.json feeds the T-gates (T-4's minimum-N floor is only
    reachable pooled — one seed carries 6 COLDSTART students against a
    floor of 8).
    """
    rows = []
    provenance = []
    for seed_dir in seed_dirs:
        log_path = seed_dir / f"{cell}.jsonl"
        seed_name = seed_dir.name
        for line in log_path.read_text().splitlines():
            row = json.loads(line)
            row["student"] = f"{seed_name}:{row['student']}"
            rows.append(row)
        provenance.append({"seed_dir": seed_name, "event_log": str(log_path)})
    return {"cell": cell, "metrics": compute(rows), "pooled_from": provenance}


def _describe(seed: int, cohorts: tuple[int, ...], weeks: int) -> None:
    events = generate(seed, cohort_sizes=cohorts, weeks=weeks)
    print(f"TermSim seed {seed}: {weeks} weeks; cohorts {', '.join(map(str, cohorts))}")
    for scenario in ("HONEST", "GHOST", "AI", "HYBRID", "COLDSTART", "TRANSFER"):
        scores = [e for e in events if e["scenario"] == scenario and e["kind"] == "score"]
        onsets = sorted({e["onset_week"] for e in scores if e.get("onset_week") is not None})
        print(f"  {scenario}: {len(scores)} submissions" + (f"; onset weeks {onsets}" if onsets else ""))
    print(f"script_sha256={script_hash(events)}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m validation.termsim")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--matrix", default="standard")
    run_parser.add_argument("--cell")
    run_parser.add_argument("--seed", type=int, default=20260826)
    run_parser.add_argument("--cohorts", default="3,8,25")
    run_parser.add_argument("--weeks", type=int, default=15)
    run_parser.add_argument("--scenarios", default=",".join(("HONEST", "GHOST", "AI", "HYBRID", "COLDSTART", "TRANSFER")))
    run_parser.add_argument("--workers", type=int, default=3)
    run_parser.add_argument("--backend", choices=("sqlite", "postgres"), default="sqlite")
    run_parser.add_argument("--out", default=str(ROOT / ".benchmark_cache" / "termsim"))
    describe = sub.add_parser("describe")
    describe.add_argument("--seed", type=int, default=20260826)
    describe.add_argument("--cohorts", default="3,8,25")
    describe.add_argument("--weeks", type=int, default=15)
    evidence = sub.add_parser("gate-evidence")
    evidence.add_argument("--seeds", required=True,
                          help="comma-separated seeds whose runs to pool")
    evidence.add_argument("--cell", default="baseline")
    evidence.add_argument("--runs", default=str(ROOT / ".benchmark_cache" / "termsim"))
    evidence.add_argument("--out", default=str(ROOT / "validation" / "termsim"
                                               / "reports" / "latest.json"))
    args = parser.parse_args(argv)
    if args.command == "gate-evidence":
        seed_dirs = [Path(args.runs) / f"seed-{s.strip()}" for s in args.seeds.split(",")]
        payload = pooled_gate_evidence(seed_dirs, args.cell)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        honest = payload["metrics"]["honest_term_flag_probability"]
        print(f"wrote {out} (honest schedule_conversation rate="
              f"{honest['schedule_conversation']['rate']})")
        return 0
    cohorts = tuple(int(value) for value in args.cohorts.split(","))
    if args.command == "describe":
        _describe(args.seed, cohorts, args.weeks)
        return 0

    # Exported (not just checked) so spawned workers inherit it; the parent
    # process's own hashing never feeds the metrics (all JSON is sort_keys).
    os.environ["PYTHONHASHSEED"] = "0"
    matrix = cells(args.matrix)
    if args.cell:
        matrix = {args.cell: matrix[args.cell]}
    run_dir = Path(args.out) / f"seed-{args.seed}"
    scenarios = tuple(value.strip().upper() for value in args.scenarios.split(","))
    payloads = [(name, flags, args.seed, cohorts, args.weeks, scenarios, str(run_dir),
                 args.backend)
                for name, flags in matrix.items()]
    results = []
    # Import through the canonical module name: macOS uses spawn and cannot
    # pickle functions whose module identity is the runpy ``__main__`` alias.
    from validation.termsim.__main__ import _run_cell as worker
    with ProcessPoolExecutor(max_workers=min(args.workers, len(payloads))) as executor:
        futures = [executor.submit(worker, payload) for payload in payloads]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"{result['cell']}: {result['elapsed_seconds']:.1f}s", flush=True)
    baseline = next((r["metrics"] for r in results if r["cell"] == "baseline"), None)
    for result in results:
        card = build(result["cell"], args.seed, result["metrics"], result["flags"], baseline)
        card.update({key: result[key] for key in
                     ("elapsed_seconds", "script_sha256", "manifest_sha256", "event_log")})
        (run_dir / f"{result['cell']}.json").write_text(json_text(card))
        (run_dir / f"{result['cell']}.md").write_text(markdown(card))
    checks = verify_diff_directions({r["cell"]: r["metrics"] for r in results})
    if checks:
        (run_dir / "diff_checks.json").write_text(
            json.dumps(checks, indent=2, sort_keys=True) + "\n")
        for check in checks:
            status = {True: "ok", False: "VIOLATED", None: "not comparable"}[check["ok"]]
            print(f"{check['check']}: {status}")
    return 0 if all(c["ok"] is not False for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
