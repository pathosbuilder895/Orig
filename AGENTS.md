# Original — Agent Instructions

**Single source of truth: [`CLAUDE.md`](CLAUDE.md).** This file used to be a
copy and had already drifted (stale test counts, old route names); keeping two
instruction files current is a losing game.

Read `CLAUDE.md` for: environment/venv rules, server management, testing
commands, design philosophy, env flags, architecture map, feature-dimension
rules, commit style, and the actions that require explicit permission.

Two pointers worth repeating for any agent landing here cold:

- `docs/ARCHITECTURE.md` — this repo contains **two backends and three
  frontend generations**; only `original/api.py` + `demo/` + `demo/bluebook/`
  are live. Check which stack you're in before touching auth or LTI.
- Always use `.venv/bin/python` / `.venv/bin/pytest`, never system python3.
