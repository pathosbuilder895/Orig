"""
main.py — FastAPI application factory.

Creates and configures the Original API FastAPI application.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from prometheus_fastapi_instrumentator import Instrumentator

from original.api.docs_hub import API_DOCS_HUB_HTML
from original.api.scalar_reference import SCALAR_REFERENCE_HTML
from original.api.v1 import v1_router
from original.canvas.lti import router as lti_router
from original.canvas.webhook import router as canvas_webhook_router
from original.canvas.baseline_import import router as canvas_baseline_router
from original.core.config import get_settings
from original.core.exceptions import register_exception_handlers
from original.core.limiter import limiter
from original.core.logging import configure_logging, get_logger
from original.core.security import SecurityHeadersMiddleware
from original.db.session import get_db, init_db

log = get_logger(__name__)

# Rich OpenAPI description (Markdown) — shown at the top of Swagger UI and ReDoc.
_OPENAPI_DESCRIPTION = """
**Original** exposes a JWT-protected REST API for stylometric baselines and authorship scoring.

### Using this page (Swagger UI)

1. Expand **Authentication** → **POST** `/api/v1/auth/login` → **Try it out** → execute with your email and password.
2. Copy the **`access_token`** from the response.
3. Click **Authorize** (top), enter `Bearer ` followed by your token (include the word `Bearer` and a space).
4. Click **Authorize**, then **Close**. Your session stays signed in (persisted in the browser).
5. Use the **filter** bar at the top to search endpoints by name or path.

### Other UIs

- **Scalar** (modern reference — search, clean layout): [`/api/reference`](/api/reference)
- **ReDoc** (readable reference): [`/api/redoc`](/api/redoc)
- **OpenAPI JSON** (for tools): [`/api/openapi.json`](/api/openapi.json)
"""

# Tag metadata controls order and section blurbs in Swagger / ReDoc.
_OPENAPI_TAGS = [
    {
        "name": "Authentication",
        "description": "Obtain JWTs. **Authorize here first** after calling `POST /auth/login`.",
    },
    {"name": "Students", "description": "Roster and writing-state for each learner in your institution."},
    {"name": "Submissions", "description": "Add baseline samples and score new text against a student profile."},
    {"name": "Admin", "description": "Institution policy, Canvas LTI, audit log (admin role)."},
    {"name": "Canvas LTI", "description": "LTI 1.3 tool configuration and launch (Canvas integration)."},
    {"name": "Canvas Webhooks", "description": "Inbound webhook endpoints for Canvas plagiarism / document workflows."},
    {"name": "Canvas Baseline Import", "description": "Import Canvas submissions as verified baselines."},
    {"name": "Platform", "description": "Liveness and readiness probes for operations and load balancers."},
]


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI app instance
    """
    settings = get_settings()

    # Configure logging
    configure_logging(level=settings.LOG_LEVEL, use_json=settings.LOG_JSON)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ARG001
        """Startup / shutdown lifecycle manager (replaces deprecated on_event)."""
        log.info("Starting up Original API")
        init_db()
        _warn_if_no_admin()
        yield
        log.info("Shutting down Original API")

    # Create FastAPI app
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        summary="Stylometric authorship detection for academic integrity",
        description=_OPENAPI_DESCRIPTION,
        openapi_tags=_OPENAPI_TAGS,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        swagger_ui_parameters={
            # Discovery & usability
            "filter": True,
            "persistAuthorization": True,
            "displayRequestDuration": True,
            "deepLinking": True,
            "tryItOutEnabled": True,
            # Default: show tag groups; keep each operation collapsed until opened
            "docExpansion": "list",
            "defaultModelsExpandDepth": 2,
            "defaultModelRendering": "example",
            "syntaxHighlight": {"activated": True, "theme": "agate"},
        },
    )

    # Middleware stack (order matters — innermost added first, outermost last)
    # Security headers — outermost layer so every response gets the headers
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging middleware
    from original.core.logging import RequestLoggingMiddleware

    app.add_middleware(RequestLoggingMiddleware)

    # Rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Custom exception handlers
    register_exception_handlers(app)

    # Mount v1 router
    app.include_router(v1_router, prefix=settings.API_V1_PREFIX)

    # Canvas LTI 1.3 and webhook routes (no API prefix — Canvas needs stable URLs)
    app.include_router(lti_router)
    app.include_router(canvas_webhook_router)
    app.include_router(canvas_baseline_router)

    # ── Prometheus metrics ────────────────────────────────────────────────
    # Exposes GET /metrics in Prometheus text format.
    # Instruments request count, latency (histogram), and in-flight requests
    # per endpoint and HTTP method automatically.
    # In production, restrict /metrics to internal network at the ingress layer
    # (e.g. nginx `allow 10.0.0.0/8; deny all;`).
    if settings.ENABLE_METRICS:
        Instrumentator(
            should_group_status_codes=False,
            should_ignore_untemplated=True,          # skip 404s from random paths
            should_instrument_requests_inprogress=True,
            excluded_handlers=["/health", "/readiness", "/metrics"],
            inprogress_name="original_requests_inprogress",
            inprogress_labels=True,
        ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    @app.get("/api", include_in_schema=False)
    @app.get("/api/", include_in_schema=False)
    def api_docs_hub() -> HTMLResponse:
        """Avoid bare /api 404 — hub links to Swagger, Scalar, ReDoc, and OpenAPI JSON."""
        return HTMLResponse(content=API_DOCS_HUB_HTML)

    @app.get("/api/reference", include_in_schema=False)
    def scalar_reference() -> HTMLResponse:
        """Scalar API Reference — modern OpenAPI UI (loads /api/openapi.json)."""
        return HTMLResponse(content=SCALAR_REFERENCE_HTML)

    @app.get("/api/reference/", include_in_schema=False)
    def scalar_reference_slash() -> RedirectResponse:
        """Normalize trailing slash so bookmarks and proxies do not 404."""
        return RedirectResponse(url="/api/reference", status_code=307)

    # Root — many users open http://localhost:8000/; interactive docs are at /api/docs
    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/api/docs")

    # Health check endpoints (no auth required)
    @app.get("/health", status_code=status.HTTP_200_OK, tags=["Platform"])
    def health() -> dict:
        """Health check endpoint."""
        return {"status": "ok", "version": settings.APP_VERSION}

    @app.get("/readiness", status_code=status.HTTP_200_OK, tags=["Platform"])
    def readiness(db=Depends(get_db)) -> dict:
        """Readiness check endpoint (includes DB connectivity test)."""
        try:
            db.execute(text("SELECT 1"))
            return {"status": "ready"}
        except Exception as e:
            log.error("Readiness check failed", extra={"error": str(e)})
            return {"status": "not_ready", "error": str(e)}

    return app


def _warn_if_no_admin() -> None:
    """
    Log a warning if no admin users exist so operators know to run the CLI.
    Does NOT auto-create users — that is the job of `python -m original.cli create-admin`.
    """
    from original.db.session import SessionLocal
    from original.db.models import User, UserRole

    db = SessionLocal()
    try:
        admin_count = (
            db.query(User)
            .filter(User.role == UserRole.ADMIN, User.is_active == True)  # noqa: E712
            .count()
        )
        if admin_count == 0:
            log.warning(
                "No active admin users found. "
                "Run `python -m original.cli create-admin` to create one."
            )
    except Exception:
        pass  # non-fatal; DB may not be ready yet
    finally:
        db.close()


# Create the application instance
app = create_app()
