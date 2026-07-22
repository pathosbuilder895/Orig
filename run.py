"""
run.py — Entry point for the Original backend server.

Usage:
    python run.py [--port 8001]
    python run.py --demo [--port 8001] [--frontend-dir PATH]

Modes:
    default   Start the DB-backed API in original.main
    --demo    Start the legacy demo API expected by the static HTML pages
              and serve the frontend files from the project root
"""

import argparse
import importlib.util
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent  # /path/to/Original
PROJECT_ROOT = BACKEND_ROOT  # run.py lives at the project root

# Ensure the backend directory is on the path
sys.path.insert(0, str(BACKEND_ROOT))

import uvicorn


def load_legacy_demo_app():
    """Load the legacy FastAPI demo app from original/api.py.

    That module name collides with the original.api package, so we load it from
    its file path and give it a private module name.
    """
    module_name = "original._legacy_demo_api"
    module = sys.modules.get(module_name)
    if module is not None:
        return module.app

    module_path = BACKEND_ROOT / "original" / "api.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load legacy demo app from {module_path}")

    module = importlib.util.module_from_spec(spec)
    module.__package__ = "original"
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.app


def seed_demo_store():
    """Reset and seed the in-memory demo student store."""
    import os

    # Hard refusal, independent of CLI flags: seeding clears the store and
    # writes synthetic students. On a real deployment that would destroy and
    # pollute FERPA-protected data — no flag combination may allow it.
    env = os.environ.get("ORIGINAL_ENV", "demo")
    if env in ("pilot", "staging", "production"):
        raise SystemExit(
            f"Refusing to seed synthetic demo data: ORIGINAL_ENV={env}. "
            "Seeding clears the store and is demo-only. Unset ORIGINAL_ENV "
            "or run against a scratch database."
        )

    from synthetic.seed_data import seed

    # (store.clear() was called here historically; it only ever cleared the
    # in-memory cache, which WS-6 P6 removed. seed() itself upserts the
    # synthetic profiles by id, so reseeding remains idempotent without it.)
    print("Seeding synthetic demo student profiles...")
    seed(verbose=True)
    print()


def create_demo_app(frontend_dir: Path):
    """Return the legacy demo app with the static frontend mounted."""
    from fastapi.responses import RedirectResponse
    from fastapi.staticfiles import StaticFiles

    app = load_legacy_demo_app()
    if getattr(app.state, "_original_demo_frontend_mounted", False):
        return app

    @app.get("/", include_in_schema=False)
    def demo_root():
        return RedirectResponse(url="/professor.html")

    # Bluebook's index.html is the same file in dev and production — React is
    # bundled into bluebook.bundle.js (build.mjs), not loaded from a CDN or
    # vendored globals, so there's no separate prod entrypoint to swap in.
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    app.state._original_demo_frontend_mounted = True
    return app


def main():
    parser = argparse.ArgumentParser(description="Original authorship API server")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the legacy demo API and serve the static Original frontend pages",
    )
    parser.add_argument(
        "--frontend-dir",
        default=str(PROJECT_ROOT / "demo"),
        help="Frontend directory to serve in --demo mode (default: <project>/demo)",
    )
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="Skip loading synthetic student profiles in --demo mode",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Force-seed synthetic demo data in --demo mode, clearing any existing rows first",
    )
    args = parser.parse_args()

    # Load .env into the process environment before any app/config is imported.
    # Done here (the entrypoint) rather than at module import so that importing
    # the app in tests never pollutes os.environ for the v1 Settings.
    from original._env import load_env_file

    load_env_file()

    if args.demo:
        frontend_dir = Path(args.frontend_dir).expanduser().resolve()
        if not frontend_dir.is_dir():
            parser.error(f"--frontend-dir does not exist or is not a directory: {frontend_dir}")

        # Enable adaptive scoring pipeline (Phases 2–8) in demo mode.
        # setdefault preserves any explicit env override (e.g., for testing with flags off).
        os.environ.setdefault("CONTEXT_MANIFEST_ENABLED", "1")
        os.environ.setdefault("ADAPTIVE_WEIGHTS_ENABLED", "1")
        # Peer-pool null model: attaches llr_deviation_score (relative
        # "fits this student vs a typical classmate") when the tenant has
        # ≥3 peers with authenticated baselines. Attach-only — deviation
        # score and recommended action are unchanged.
        os.environ.setdefault("NULL_MODEL", "impostor")

        if args.seed:
            seed_demo_store()
        elif not args.skip_seed:
            from original import store

            if store.count() == 0:
                print(
                    "WARNING: empty store, auto-seeding synthetic demo data. "
                    "Pass --seed to silence, --skip-seed to disable."
                )
                seed_demo_store()
            else:
                print(
                    f"Store has {store.count()} profiles; not reseeding "
                    "(pass --seed to force, which CLEARS synthetic data first)."
                )

        app = create_demo_app(frontend_dir)

        print(f"Starting Original demo on http://localhost:{args.port}")
        print(f"  Landing page: http://localhost:{args.port}/professor.html")
        print(f"  Bluebook:     http://localhost:{args.port}/bluebook/")
        print(f"  Health:       http://localhost:{args.port}/health")
        print()

    else:
        from original.main import app

        print(f"Starting Original API on http://localhost:{args.port}")
        print(f"  Docs: http://localhost:{args.port}/api/docs")
        print(f"  Health: http://localhost:{args.port}/health")
        print()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
