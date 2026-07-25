"""FastAPI routers carved out of the single-module ``original/api.py``.

Each module here owns one route group and exposes a module-level ``router``
(``fastapi.APIRouter``) that ``original.api`` mounts with
``app.include_router``. The app object, its middleware, the lifespan and the
deploy-mode flags stay in ``original/api.py``; the handlers and the helpers
they share moved here unchanged (WS-7.3).
"""
