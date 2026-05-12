"""
run.py — Entry point for the Original backend server.

Usage:
    python run.py [--port 8000]
    python run.py --demo [--port 8000] [--frontend-dir PATH]

Modes:
    default   Start the DB-backed API in original.main
    --demo    Start the legacy demo API expected by the static HTML pages
              and serve the frontend files from the project root
"""

import argparse
import importlib.util
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent   # /path/to/Original
PROJECT_ROOT = BACKEND_ROOT                       # run.py lives at the project root

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
    from original import store
    from synthetic.seed_data import seed

    store.clear()
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

    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    app.state._original_demo_frontend_mounted = True
    return app


def main():
    parser = argparse.ArgumentParser(description="Original authorship API server")
    parser.add_argument("--port", type=int, default=8000)
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
        help="Deprecated: only meaningful with --demo; the modern API reads from its database",
    )
    args = parser.parse_args()

    if args.demo:
        frontend_dir = Path(args.frontend_dir).expanduser().resolve()
        if not frontend_dir.is_dir():
            parser.error(f"--frontend-dir does not exist or is not a directory: {frontend_dir}")

        if not args.skip_seed:
            seed_demo_store()

        app = create_demo_app(frontend_dir)

        print(f"Starting Original demo on http://localhost:{args.port}")
        print(f"  Landing page: http://localhost:{args.port}/original.html")
        print(f"  Review page:  http://localhost:{args.port}/original-review.html")
        print(f"  Health:       http://localhost:{args.port}/health")
        print()

    else:
        if args.seed:
            print("Note: --seed now applies to the legacy demo mode only.")
            print("      Run `python run.py --demo` to start the seeded frontend demo.")
            print()

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
