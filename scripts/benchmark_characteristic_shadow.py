"""Benchmark the peer-state scan added by CHARACTERISTIC_WEIGHTS shadow mode."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
import uuid
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from original.quantum.state import StudentState


def _percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[round((len(values) - 1) * q)]


def benchmark(repo, sizes=(50, 500, 5000), repeats=7, prefix="termsim-latency") -> dict:
    created: list[str] = []
    rows = []
    try:
        for size in sizes:
            while len(created) < size:
                student_id = f"{prefix}:student-{len(created):05d}"
                repo.put(StudentState(student_id=student_id))
                created.append(student_id)
            samples = []
            for _ in range(repeats):
                started = time.perf_counter()
                states = repo.all_states()
                samples.append((time.perf_counter() - started) * 1000)
                if len(states) < size:
                    raise RuntimeError(f"state scan returned {len(states)} rows; expected >= {size}")
            rows.append({"profiles": size, "repeats": repeats,
                         "median_ms": statistics.median(samples),
                         "p95_ms": _percentile(samples, 0.95), "samples_ms": samples})
    finally:
        for student_id in created:
            repo.delete_student(student_id)
    worst = max(row["p95_ms"] for row in rows)
    return {"measure": "repository.all_states peer scan only", "rows": rows,
            "decision": ("retain full scan for bounded pilot; alert at 100 ms p95"
                         if worst <= 100 else
                         "mitigate before shadow: add a bounded tenant-scoped peer-stat query")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("sqlite", "postgres"), default="sqlite")
    parser.add_argument("--sizes", default="50,500,5000")
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    run_id = uuid.uuid4().hex[:10]
    if args.backend == "sqlite":
        from original import store
        from original.repository import SqliteRepository
        db_dir = Path(tempfile.mkdtemp(prefix="characteristic-latency-"))
        store._DB_PATH = db_dir / "profiles.db"
        repo = SqliteRepository()
    else:
        url = os.environ.get("TERMSIM_BENCHMARK_DATABASE_URL")
        if not url or not url.startswith("postgresql"):
            raise SystemExit("set TERMSIM_BENCHMARK_DATABASE_URL to an isolated local Postgres DB")
        os.environ["DATABASE_URL"] = url
        from original.postgres_repository import PostgresRepository
        repo = PostgresRepository()
    result = benchmark(repo, tuple(int(v) for v in args.sizes.split(",")), args.repeats,
                       f"termsim-latency-{run_id}")
    result.update({"backend": args.backend, "run_id": run_id})
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
