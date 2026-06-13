# Original — Claude Code Instructions

## Project Overview
Stylometric authorship verification system for academic integrity. Per-student quantum density matrix profiles scored via Born-rule projection. Targets seminaries and colleges. Positioned as pastoral, explainable, FERPA-compliant.

**Working directory:** `~/Desktop/Original`  
**Python environment:** always use `.venv/bin/python` and `.venv/bin/pytest` — NOT system python3  
**Run server:** `python run.py --demo` (port 8001 by default)

---

## Server Management
- **NEVER kill or restart running dev servers** without explicit user permission. Find a code-level workaround (env override, redirect flag, config change) and confirm first.
- When starting servers, always check the correct `--frontend-dir` before launching. It should match the demo/ directory: `python run.py --demo --frontend-dir demo/`
- The `.venv` is at `~/Desktop/Original/.venv/` — the system python3 has a broken pydantic_settings install that will cause conftest import errors.

---

## Testing
```bash
.venv/bin/python -m pytest tests/ -q                  # full suite (~497 tests, ~42s)
.venv/bin/python -m pytest tests/quantum/ -v          # quantum module only
.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q   # exact CI command
```
The 5 `TestAuthEndpoints` tests that 429 under full-suite rate-limit exhaustion are
marked `xfail(strict=False)` — they show as XFAIL/XPASS, never as failures. A clean
run is **0 failed**; treat any failure as real. (Historical note: counts before
2026-06 were inflated ~2× by macOS Finder-duplicate test files, since removed.)

---

## Design Philosophy
- **Prefer simple over elaborate.** Start with the minimal working solution. Do not propose multi-state scroll systems, 3D models, or complex animations unless explicitly asked.
- **Non-destructive first.** When something breaks, look for a workaround (env var, flag, config) before rebuilding or restarting.
- **Verify visually after UI changes.** Build → test → preview. Don't declare done until all three pass.

---

## Environment Flags
All production features are opt-in via env flags. Default OFF preserves Phase 1 byte-identical behaviour.

| Flag | Default | What it enables |
|------|---------|-----------------|
| `CONTEXT_MANIFEST_ENABLED` | `0` | Phase 3 resolver + context manifest |
| `ADAPTIVE_WEIGHTS_ENABLED` | `0` | Phase 5 cluster-matched adaptive weights |
| `AMPLITUDE_SCORING_ENABLED` | `0` | Phase 6 complex amplitude encoding + quantum fidelity |
| `SECRET_KEY` | `""` | Keyed random unitary projection (adversarial robustness) |
| `BAYESIAN_PRIOR_ENABLED` | `0` | Hierarchical Bayesian cold-start prior |
| `PRIOR_WEIGHT` | `3.0` | Virtual sample count for the prior |

Demo mode turns on CONTEXT_MANIFEST_ENABLED and ADAPTIVE_WEIGHTS_ENABLED automatically (set in run.py).

---

## Key Architecture
```
Text → 103-feature pipeline (original/features/)
     → StudentState (density matrix ρ, baseline_mean, baseline_std)
     → quantum/scoring.py:score() → Layer7Output
     → API response (deviation_score, action, quantum_fidelity, professor_explanation)
```

**Feature pipeline:** `original/features/` — 103 features across 17 tiers  
**Quantum state:** `original/quantum/state.py` — density matrix builder  
**Scoring:** `original/quantum/scoring.py` — Born-rule + amplitude (Phase 6)  
**Professor narrative:** `original/quantum/professor_narrative.py` — plain-English explanation  
**Context pipeline:** `original/context/pipeline.py` — adaptive Stage 5+6 (parallelized)  
**Store:** `original/store.py` — SQLite persistence + in-memory cache  
**API:** `original/api.py` — FastAPI endpoints (THE pilot backend)

⚠️ **Two backends / three frontends exist** — see `docs/ARCHITECTURE.md` before
touching auth or LTI. The live stack is `original/api.py` + `demo/` +
`demo/bluebook/` with LTI at `/lti/*` (`original/lti.py`). The v1 package
(`original/api/`, `original/main.py`, `frontend/`, `/canvas/lti/*`) is dormant;
`web/` is abandoned. New pilot features go in the live stack only.

**Bluebook frontend:** after editing any `demo/bluebook/*.jsx`, rebuild and
commit the bundle: `cd demo/bluebook && npm run build` (Render has no Node —
the committed `bluebook.bundle.js` is what production serves).

---

## Feature Dimensions
- `FEATURE_DIM = 103` (current)
- Legacy profiles serialized with 74 or 89 features will be padded with 0.5 on load (you'll see warnings). Run `rebuild-baselines` to fix.
- `ALL_FEATURE_CODES` in `original/constants.py` is the canonical ordered list — don't reorder it.

---

## Known Sandbox / Preview Issues
- Preview server sandbox restricts file access. Use the `/tmp` keeper script pattern if the preview server can't serve static assets.
- The Claude Preview MCP tool requires a running preview server started via `mcp__Claude_Preview__preview_start`.
- `chrome-in-extension` tools can navigate and click but NOT type into IDE terminals — use Bash tool for shell commands.

---

## Commit Style
- One focused commit per logical change
- Conventional: `Fix ...`, `Add ...`, `Refactor ...` (not `update` for new features)
- Co-author line: `Co-Authored-By: Claude <current model name> <noreply@anthropic.com>` (e.g. Claude Fable 5)
- Branch: `commit-changes` → PR to `main` on `pathosbuilder895/Orig`

---

## What Requires Explicit Permission
- Killing or restarting the dev server
- Pushing to main/master directly
- Deleting files (use git rm, not rm)
- Any change to `original/constants.py` feature ordering or NORM_BOUNDS
