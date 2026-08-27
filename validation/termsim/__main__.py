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
from validation.termsim.scorecard import build, json_text, markdown
from validation.termsim.script import dumps, generate, script_hash

ROOT = Path(__file__).resolve().parents[2]
SCORE_FLAGS = {
    key for config in cells().values() for key in config
} | {"TOPIC_VARIANCE_INFLATION", "CHARACTERISTIC_WEIGHTS", "GENRE_RESOLVER_V2"}


def _run_cell(payload: tuple) -> dict:
    name, flags, seed, cohorts, weeks, scenarios, out_dir = payload
    # Determinism guard: main() exports this before spawning workers, so a
    # worker without it means the harness was entered some other way.
    assert os.environ.get("PYTHONHASHSEED") == "0", "PYTHONHASHSEED=0 not exported"
    for key in SCORE_FLAGS:
        os.environ[key] = "0"
    os.environ.update(flags)
    db_dir = Path(tempfile.mkdtemp(prefix=f"termsim-{name}-"))
    os.environ["ORIGINAL_DB"] = str(db_dir / "profiles.db")
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
    run_parser.add_argument("--out", default=str(ROOT / ".benchmark_cache" / "termsim"))
    describe = sub.add_parser("describe")
    describe.add_argument("--seed", type=int, default=20260826)
    describe.add_argument("--cohorts", default="3,8,25")
    describe.add_argument("--weeks", type=int, default=15)
    args = parser.parse_args(argv)
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
    payloads = [(name, flags, args.seed, cohorts, args.weeks, scenarios, str(run_dir))
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
