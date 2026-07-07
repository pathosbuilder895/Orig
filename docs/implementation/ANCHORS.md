# Code anchors for the implementation plans

The workstream plans cite `path:line` locations. **Line numbers drift** — and as of 2026-07-07 the
working tree is under active concurrent edit (see the callout in [README](README.md)), so several are
already stale. This file is the drift-proof index: for each load-bearing site a plan depends on, a
**greppable symbol** and a `grep` that locates it no matter where the line moves.

**How to use:** when a plan cites `foo.py:123 (bar)`, don't trust `123` — run the anchor's grep to find
`bar`'s current line, then read there. All greps are written to run from the repo root.

> Scope: the ~35 sites the plans tell you to *modify* or that anchor a *claim*. Not every reference —
> just the load-bearing ones. If a site you need isn't here, `grep -rn "<symbol>" original/`.

> ⚠️ **Some anchors are already in flux (2026-07-07).** A concurrent session is implementing parts of
> WS-8 and WS-9 live: `demo/bluebook/index.prod.html` and `demo/bluebook/vendor/` have been **deleted**
> (React being bundled — WS-8 R1), and `RENDER_GIT_COMMIT` handling + `_resolve_app_version()` were
> **added** to `original/api.py`/`schemas.py` (WS-9 R.1/R.2 — matching those plans' recommendations).
> The affected rows below are marked ⚠. Treat this whole file as "true at read time" and re-run the greps.

---

## WS-1 — Security & data-integrity
| Site | Locate with |
|---|---|
| python-jose CVE pin (pilot) | `grep -n python-jose requirements-pilot.txt requirements.txt` |
| store write/load swallowers | `grep -n "def _persist\|def _load_all" original/store.py` |
| `put()` (calls `_persist`) | `grep -n "^def put\b\|def put(" original/store.py` |
| run.py port default | `grep -n '"--port"' run.py` |
| run.py seed-by-default | `grep -n "seed_demo_store\|skip_seed\|args.seed" run.py` |
| run.py stale banner | `grep -n "original.html\|original-review" run.py` |
| MAINTENANCE_TOKEN / guard | `grep -n "MAINTENANCE_TOKEN\|GUARD_DESTRUCTIVE\|_require_guard\|_audit_maintenance" original/api.py` |
| MAINTENANCE_TOKEN runbook row | `grep -n "MAINTENANCE_TOKEN\|GUARD_DESTRUCTIVE" docs/OPS_RUNBOOK.md` |

## WS-2 — Guardrails
| Site | Locate with |
|---|---|
| CI jobs (currently 2) | `grep -n "^  [a-z].*:\|runs-on:\|needs:" .github/workflows/test.yml` |
| ruff/tool config (absent) | `grep -n "\[tool" pyproject.toml` (expect none) |
| black pin to drop | `grep -n "black" requirements.txt` |
| requirements layering | `grep -n "^-r \|^fastapi" requirements.txt requirements-demo.txt` |
| `.venv` python version | `grep version .venv/pyvenv.cfg` |
| start.sh interpreter/deps | `grep -n "pip install\|python3\|requirements" start.sh` |
| build.mjs ORDER + sourcemap | `grep -n "ORDER\|sourcemap\|minify" demo/bluebook/build.mjs` |
| unregistered `slow` marker | `grep -rn "@pytest.mark.slow" tests/` and `grep -n markers pytest.ini` |
| Finder-dup still on disk | `git status --porcelain \| grep -E ' [0-9]+\.\|~\$'` |

## WS-3 — Trust surface
| Site | Locate with |
|---|---|
| action thresholds (truth) | `grep -n "ACTION_THRESHOLDS" original/constants.py` |
| feature dim / disabled tiers | `grep -n "FEATURE_DIM\|BASE_FEATURE_DIM\|DISABLED_FEATURE_GROUPS\|TIER17_CODES" original/constants.py` |
| README/model-card thresholds | `grep -n "0.55\|0.40\|monitor" README.md MODEL_CARD.md` |
| app-level crypto (only LTI RSA) | `grep -rniE "aes\|fernet\|gcm" original/ --include=*.py` (expect none) |
| LTI RSA key material | `grep -n "NoEncryption\|private_key" original/canvas/keys.py` |
| raw-text retrieval endpoint | `grep -n "samples/.*text\|def .*sample.*text" original/api.py` |
| README dormant `/api/v1` table | `grep -n "/api/v1/\|/canvas/lti" README.md SETUP.md` |
| CLAUDE.md flag table | `grep -n "CONTEXT_MANIFEST_ENABLED\|NULL_MODEL" CLAUDE.md` |
| every live env var (for the table) | `grep -rhoE "os\.(environ\.get\|getenv)\(['\"][A-Z_]+" original/ run.py \| sort -u` |

## WS-4 — Accessibility (exam-flow hotfix)
| Site | Locate with |
|---|---|
| exam answer textarea | `grep -n "textarea\|placeholder" demo/bluebook/Exam.jsx` |
| proctoring warning + auto-dismiss | `grep -n "recordWarning\|showWarn\|setTimeout" demo/bluebook/Exam.jsx` |
| keyboard pattern to copy | `grep -n 'role="button" tabindex="0"' demo/professor.html` |
| student.html click-only nav | `grep -n "nav-item\|signOut\|spine\|sub-row" demo/student.html` |
| Bluebook click-div rows | `grep -n "onClick=" demo/bluebook/Dashboard.jsx demo/bluebook/Results.jsx demo/bluebook/Students.jsx` |
| ToggleRow switch | `grep -n "ToggleRow" demo/bluebook/NewExam.jsx` |
| contrast tokens | `grep -n "parchment\|--ink\|--gold\|--text-muted\|hairline" demo/student.html demo/professor.html` |
| MetaLabel (needs htmlFor) | `grep -n "MetaLabel" demo/bluebook/components.jsx` |

## WS-5 — Test depth
| Site | Locate with |
|---|---|
| dormant v1 conftest | `grep -n "from original.main" tests/conftest.py` |
| live-app bootstrap pattern | `grep -rln "load_legacy_demo_app" tests/` |
| Bluebook API endpoints | `grep -n "bluebook/exams\|bluebook/submissions" original/api.py` |
| Bluebook store layer | `grep -n "def put_bluebook\|def list_bluebook\|def get_bluebook" original/store.py` |
| scoring flag branches | `grep -n "AMPLITUDE_SCORING_ENABLED\|BAYESIAN_PRIOR_ENABLED\|def _amplitude_score\|conformal" original/quantum/scoring.py` |
| test_quantum defects | `grep -n "from hypothesis\|@given\|test_empty_state\|np.random" tests/test_quantum.py` |
| dead modules | `grep -rn "rbac\|tasks/scoring\|tasks.scoring" original/ --include=*.py` |
| rbac→security_audit coupling | `grep -n "rbac\|check_rbac_middleware" original/cli/security_audit.py` |

## WS-6 — Postgres convergence
| Site | Locate with |
|---|---|
| Repository seam + PG skeleton | `grep -n "class .*Repository\|def get_repository\|NotImplementedError" original/repository.py` |
| all store public fns | `grep -n "^def " original/store.py` |
| all store tables | `grep -n "CREATE TABLE" original/store.py` |
| tenant string-prefix convention | `grep -n "tenant_id\}:\|like_prefix\|:{.*local" original/store.py` |
| `store._DB_PATH` private reaches | `grep -n "_DB_PATH" original/api.py` |
| v1 SQLAlchemy models | `ls original/db/models/` |
| v1 pydantic Settings | `grep -n "class Settings\|BaseSettings" original/core/config.py` |
| run.py importlib shadow hack | `grep -n "spec_from_file_location\|_legacy_demo_api" run.py` |
| the 62 v1 tests | `grep -rln "from original.main\|/api/v1" tests/ ; ls tests/test_api.py tests/test_auth.py tests/test_canvas.py` |
| alembic (v1) migrations | `ls alembic/versions/` |

## WS-7 — API-layer refactor
| Site | Locate with |
|---|---|
| `score()` + in-body env reads | `grep -n "def score\|os.environ" original/quantum/scoring.py` |
| scoring→store edge (A5) | `grep -n "from ..store\|import.*store" original/quantum/scoring.py` |
| amplitude `secret_key` param (model) | `grep -n "secret_key" original/quantum/amplitude.py` |
| dict-body endpoints (the 8) | `grep -n "body: dict" original/api.py` |
| `_to_response` mapper | `grep -n "_to_response" original/api.py` |
| blocking async handlers | `grep -n "async def upload_\|async def import_\|async def list_canvas\|async def import_canvas" original/api.py` |
| demo-only static gating | `grep -n "_DEMO_ONLY_STATICS\|_IS_REAL_DEPLOY" original/api.py` |
| Canvas baseline stubs | `grep -n "canvas/baseline\|list_canvas_submissions\|import_canvas_baseline" original/api.py` |
| ORIGINAL_ENV vs ENVIRONMENT | `grep -rn "ORIGINAL_ENV\|ENVIRONMENT" original/api.py` |
| tier list (ordering contract) | `grep -n "ALL_FEATURE_CODES\|TIER.*_CODES\|NORM_BOUNDS" original/constants.py` |
| pipeline tier wiring | `grep -n "tier\|extract_tier" original/features/pipeline.py` |

## WS-8 — React migration
| Site | Locate with |
|---|---|
| ⚠ React load path — `index.prod.html` + `vendor/` now **deleted** (R1 bundling React) | `ls demo/bluebook/index.prod.html demo/bluebook/vendor 2>/dev/null; grep -n "react\|external\|unpkg" demo/bluebook/build.mjs demo/bluebook/index.html` |
| build.mjs ORDER + stale CDN comment | `grep -n "ORDER\|CDN\|external" demo/bluebook/build.mjs` |
| JSX file inventory | `ls demo/bluebook/*.jsx` |
| committed bundle | `ls -la demo/bluebook/bluebook.bundle.js` |
| student-coach caller | `grep -n "openCoach\|student-coach" demo/student.html` |
| landing.html inbound links | `grep -rn "landing.html" demo/` (expect none = orphaned) |
| page sizes | `wc -l demo/*.html` |

## WS-9 — E2E + release hygiene
| Site | Locate with |
|---|---|
| `/health` handler | `grep -n "def health" original/api.py` |
| FastAPI app version | `grep -n "version=\|_resolve_app_version" original/api.py` |
| HealthResponse schema | `grep -n "class HealthResponse" original/schemas.py` |
| ⚠ RENDER_GIT_COMMIT — R.1 **landed**: now in `api.py`/`schemas.py` | `grep -rn "RENDER_GIT_COMMIT" original/` |
| version drift (3 surfaces) | `grep -n "version" pyproject.toml ; grep -n "^# Model Card" MODEL_CARD.md` |
| playwright workers/retries/parallel | `grep -n "workers\|retries\|fullyParallel" demo/bluebook/playwright.config.mjs` |
| existing e2e specs | `ls demo/bluebook/e2e/` |
| professor pages (no e2e) | `ls demo/bluebook/Dashboard.jsx demo/bluebook/Results.jsx demo/bluebook/Students.jsx demo/bluebook/NewExam.jsx demo/bluebook/Courses.jsx` |
| render deploy config | `grep -n "autoDeploy\|healthCheckPath\|startCommand" render.yaml` |

---

*Regenerate/extend this table whenever a plan adds a new load-bearing citation. If a symbol here stops
resolving, the code moved or was renamed — update the plan and this anchor together.*
