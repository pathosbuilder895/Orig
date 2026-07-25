"""FastAPI routers carved out of the single-module ``original/api.py``.

Each module here owns one route group and exposes a module-level ``router``
(``fastapi.APIRouter``) whose routes ``original.api`` splices onto the app (see
the "Routers" block at the bottom of api.py for why it is not
``app.include_router``). The app object, its middleware, the lifespan and the
deploy-mode flags stay in ``original/api.py``; the handlers and the helpers
they share moved here unchanged (WS-7.3).
"""
