"""
Scalar API Reference — modern OpenAPI UI (https://scalar.com).

Served at GET /api/reference as static HTML that loads the bundled spec from
/api/openapi.json (same origin, no CORS proxy needed).
"""

# jsDelivr resolves semver; pin when you want reproducible builds.
_SCALAR_CDN = "https://cdn.jsdelivr.net/npm/@scalar/api-reference"

SCALAR_REFERENCE_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Original — API Reference</title>
  <style>
    html, body {{ margin: 0; height: 100%; }}
    #scalar-app {{ height: 100vh; }}
  </style>
</head>
<body>
  <div id="scalar-app"></div>
  <script src="{_SCALAR_CDN}"></script>
  <script>
    Scalar.createApiReference("#scalar-app", {{
      url: "/api/openapi.json",
    }});
  </script>
</body>
</html>
"""
