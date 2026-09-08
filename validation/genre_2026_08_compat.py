"""Import bridge for the date-named genre validation directory."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).parent / "genre_2026-08" / "read_shadow_log.py"
_SPEC = importlib.util.spec_from_file_location("genre_shadow_reader", _PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
genre_summary = _MODULE.summarise
