"""
_env.py — minimal, dependency-free .env loader (ADR-003, Phase 1).

The legacy demo app reads configuration from os.environ directly and the demo
deployment intentionally omits python-dotenv (requirements-demo.txt). This tiny
loader lets a pilot/production operator drop a `.env` file next to the repo and
have SECRET_KEY, ALLOWED_ORIGINS, ORIGINAL_ENV, LTI_* etc. picked up — without
adding a dependency. Existing environment variables always win (setdefault).
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path: "str | Path | None" = None) -> bool:
    """Load KEY=VALUE lines from `.env` into os.environ (without overriding).

    Returns True if a file was found and read. Silent and safe to call multiple
    times; malformed lines are skipped.
    """
    p = Path(path) if path else (_REPO_ROOT / ".env")
    try:
        if not p.exists():
            return False
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if value[:1] in ("'", '"'):
                # Quoted value: take through the matching quote (keeps any '#').
                quote = value[0]
                end = value.find(quote, 1)
                value = value[1:end] if end != -1 else value[1:]
            else:
                # Strip an inline comment: a '#' preceded by whitespace.
                for i, ch in enumerate(value):
                    if ch == "#" and (i == 0 or value[i - 1] in " \t"):
                        value = value[:i]
                        break
                value = value.strip()
            if key:
                os.environ.setdefault(key, value)
        return True
    except Exception:
        return False
