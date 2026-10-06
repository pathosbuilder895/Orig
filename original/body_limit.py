"""body_limit.py — cap request body size before a handler buffers it.

Nothing else in the app bounds upload size, and the pilot runs on a ~512 MB
Render Starter instance, so one oversized POST could exhaust memory for every
exam in progress. Two checks:

* A declared ``Content-Length`` over the cap is refused with 413 before the
  app runs at all.
* A body without one (chunked transfer) is counted as it streams. Crossing the
  cap raises ``HTTPException(413)`` from ``receive()``; FastAPI surfaces that
  as a 413 because body reads happen inside its request handling.

The cap is ``MAX_REQUEST_BYTES`` (default 10 MB), read once at import.
"""

from __future__ import annotations

import json
import os

from fastapi import HTTPException

MAX_REQUEST_BYTES = int(os.environ.get("MAX_REQUEST_BYTES", str(10 * 1024 * 1024)))

_DETAIL = "Request body too large."


class BodySizeLimitMiddleware:
    def __init__(self, app, max_bytes: int | None = None):
        self.app = app
        self.max_bytes = MAX_REQUEST_BYTES if max_bytes is None else max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = None
        for name, value in scope.get("headers") or ():
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                break
        if declared is not None and declared > self.max_bytes:
            body = json.dumps({"detail": _DETAIL}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        seen = 0
        limit = self.max_bytes

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise HTTPException(status_code=413, detail=_DETAIL)
            return message

        await self.app(scope, limited_receive, send)
