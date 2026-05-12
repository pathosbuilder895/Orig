"""Small HTML hub at GET /api so /api does not 404 in the browser."""

API_DOCS_HUB_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Original — API documentation</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 36rem; margin: 3rem auto; padding: 0 1.25rem; line-height: 1.5; color: #141c2c; }
    h1 { font-size: 1.35rem; font-weight: 600; }
    ul { padding-left: 1.2rem; }
    a { color: #1e4d7b; }
    p.muted { color: #5a6578; font-size: 0.9rem; margin-top: 2rem; }
  </style>
</head>
<body>
  <h1>Original API — documentation</h1>
  <p>Choose a reference UI (same OpenAPI spec):</p>
  <ul>
    <li><a href="/api/docs">Swagger UI</a> — try requests and Authorize (JWT)</li>
    <li><a href="/api/reference">Scalar</a> — modern layout and search</li>
    <li><a href="/api/redoc">ReDoc</a> — readable reference</li>
    <li><a href="/api/openapi.json">OpenAPI JSON</a> — for tools and codegen</li>
  </ul>
  <p class="muted">If links return 404, restart the API with a current image:
    <code>docker compose up -d --build api</code></p>
</body>
</html>
"""
