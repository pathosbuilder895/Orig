"""
run.py — Entry point for the Original server (the original/api.py app).

Usage:
    python run.py --demo [--port 8001] [--frontend-dir PATH]

The dormant v1 stack (original.main + the original/api/ package) was deleted
in WS-6 P6, which also dissolved the api.py-vs-api/ module-name collision —
``original.api`` now resolves to the one real app module, imported plainly.
"""

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent  # /path/to/Original
PROJECT_ROOT = BACKEND_ROOT  # run.py lives at the project root

# Ensure the backend directory is on the path
sys.path.insert(0, str(BACKEND_ROOT))

import uvicorn


def load_legacy_demo_app():
    """Return the FastAPI app from original/api.py (plain import).

    Kept under its historical name — tests' ``live_app`` fixture and older
    tooling call this. The importlib.spec_from_file_location hack that used
    to live here existed only because the deleted v1 ``original/api/``
    package shadowed the module name (audit A9).
    """
    from original import api

    return api.app


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
        required=True,
        help="Run the Original app and serve the static frontend pages "
        "(the only mode since WS-6 P6 deleted the v1 stack; kept as an "
        "explicit flag so every existing start command keeps working)",
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

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
