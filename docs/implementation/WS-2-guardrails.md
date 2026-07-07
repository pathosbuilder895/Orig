# WS-2 — Guardrails: CI, pre-commit, lint, hygiene

> Part of the [Master Implementation Plan](../AUDIT_2026-07-06.md) (Audit §9). Refs are a 2026-07-07 snapshot — resolve each cited `path:line` by its **named symbol** via [ANCHORS.md](ANCHORS.md); the tree is under active edit and line numbers drift.
> **Findings:** H1–H4, D9, B1–B9, B11–B14, B17, B18, T8, T9, S6, S10–S12 · **Effort:** 3–5 days · **Depends on:** — (runs in parallel with WS-1/WS-3 immediately) · **Unblocks:** WS-5 (fixtures + green coverage gate), WS-6/WS-7 (`extend-exclude` of the dormant tree is the lint contract they delete against), WS-9 (bundle-diff + e2e-on-pilot is the release-hygiene base).

## Objective
Put enforcement under the "better-than-its-guardrails" core (audit §8 theme 3): a four-job CI that goes red on a lint violation, a stale Bluebook bundle, a coverage drop, or a CVE'd dependency; a pre-commit gate that blocks the recurring `file 2.py` / committed-`.db` failure modes at staging time; and a one-command task runner that hard-codes `.venv/bin/python` so the system-python and 3.9-vs-3.11 traps stop mattering. The single highest-value addition is the bundle-freshness byte-diff (B2) — today the committed `bluebook.bundle.js` is fresh by discipline, not enforcement. Nothing in this workstream touches scoring; the flags-OFF byte-identical invariant is unaffected.

## Prerequisites & dependencies
- **Tools already present:** `.venv/bin/ruff` is 0.6.9 (matches §13 pin); `pytest-cov==5.0.0`, `black`, `mypy` are pinned in `requirements.txt:48–53`. No config consumes any of them yet.
- **`.venv` is Python 3.9.6** (audit B7) — must be rebuilt on 3.11 (task 6) before `target-version = "py311"` lint rules and mypy run cleanly locally. This is the one internal ordering trap: land the ruff *config* (task 3) and rebuild `.venv` (task 6) before wiring `ruff-format --check` into a blocking CI job, or local pre-commit output will disagree with CI on 3.11-only idioms.
- **Shared findings / ownership boundaries:**
  - **B10** (python-jose CVE pin) is *owned by WS-1*, not here — WS-2 only adds the pip-audit job (B4) that would police it going forward.
  - **B16** (run.py port default + destructive seed) is *owned by WS-1*. WS-2 depends on the outcome only as documentation (CI already passes `--port 8001 --skip-seed` explicitly, so WS-2 CI is correct regardless).
  - **B15 / B19** (stale docker/fly/alembic deploy targets; SQLite migration ladder) are *owned by WS-6*; not in scope here. Noted in Risks.
  - **D9** (docs/scripts duplicates) overlaps H1/H4 — the file deletions live in task 1 here; the "prevent recurrence" pre-commit hook is task 3.
  - **T1–T3** (raising real coverage) belong to WS-5. WS-2 only installs the *gate* at a floor the current suite already clears; WS-5 ratchets it.

## Tasks

### 2.1 Delete Finder-duplicate + junk files — H1, H4, D9
- **Current state:** all deletion targets are **untracked** (verified `git ls-files --error-unmatch` fails for every one), so the audit's "`git rm` where tracked" clause applies to *none* of them — plain `rm` throughout. Present on disk: `tests/test_roster_links 2.py` (pytest still collects it locally → silent double-run, the exact §0/H1 regression), `scripts/roster_links 2.py`, `docs/DAY_ONE_CLASS 2.md` (md5 `8ca78c1d…`, byte-identical to the tracked `docs/DAY_ONE_CLASS.md` — confirmed), `docs/~$NERS_MANUAL.md` (Word lock file), `~$iginal_Business_Plan.docx` (Word lock file, repo root), `err.log`, two `pytest-cache-files-*` dirs from March. `.benchmark_cache/` (233 sibling `.fuse_hidden*` files also present — those are handled by the .gitignore add in 2.2, not deleted here).
- **Change:** delete the seven items. Note `docs/DAY_ONE_CLASS.md` (the real one) and `demo/seed.db` stay.
  ```bash
  rm "tests/test_roster_links 2.py" "scripts/roster_links 2.py" \
     "docs/DAY_ONE_CLASS 2.md" "docs/~\$NERS_MANUAL.md" \
     "~\$iginal_Business_Plan.docx" err.log
  rm -rf pytest-cache-files-*
  ```
- **Files touched:** deletions only (no tracked file changes → no commit needed for the removals themselves; they land in the same commit as 2.2/2.3).
- **Verify:** `git status --porcelain | grep -E ' [0-9]+\.|~\$|pytest-cache-files' ` returns nothing; `.venv/bin/python -m pytest tests/ --collect-only -q 2>&1 | grep -c "roster_links 2"` → `0`.
- **Note (scope):** `explainer-screenshot.png` (267 KB, root) is untracked — audit H4 asked "tracked?"; answer is **no**. It is *not* in the §9 task-1 delete list, so it is left as-is here (a deliberate scope boundary; flag to owner if a cleanup pass is wanted).

### 2.2 `.gitignore` additions — H2, B18
- **Current state:** `.gitignore` is already thorough — it ignores `err.log` (`:55`), `*.log` (`:56`), `~$*` Word lock files (`:59`), `pytest-cache-files-*/` (`:52`), and `* 2.*`/`* 3.*`/`* 4.*` (`:88–90`). So the junk in 2.1 was never *tracked*; the problem is local accumulation. Missing: `.fuse_hidden*` (233 present at root) and `.benchmark_cache/` (present; no matching rule — `validation/benchmarks/*` at `:96` is a different path).
- **Change:** append two lines under a clear header.
  ```gitignore
  # FUSE-mount deletion artifacts (accumulate on synced/FUSE filesystems)
  .fuse_hidden*
  # pytest-benchmark cache
  .benchmark_cache/
  ```
- **Files touched:** `.gitignore`.
- **Verify:** `git status --porcelain | grep -E '\.fuse_hidden|\.benchmark_cache'` returns nothing.

### 2.3 Land pre-commit + ruff config; one autofix commit — B18, B1, D9, S6, S10, S11, S12
- **Current state:** no `.pre-commit-config.yaml`; `pyproject.toml` has **only** `[project]` (6 lines, verified — no `[tool.*]`). `ruff check original/` reports **86 F401** repo-wide (matches audit S6); on the live-only subset (dormant tree excluded) it is **46 F401 + 38 I001** (both auto-fixable) plus 356 E501 (addressed by `line-length = 100` + the `constants.py` E501 exemption). S6's other examples verified: `api.py:1844–1846` imports `Layer7Output, FeatureContribution, EntanglementAnomaly` inside `_to_response` then the block continues — the imported-then-partially-unused pattern; `api.py:65–68` is a schemas import block.
- **Change:** add the two concrete configs **exactly as specified in [audit §13](../AUDIT_2026-07-06.md#13-pre-commit-hooks--linting-improvements-concrete-configs)** — do not re-invent them here:
  1. Copy the complete `.pre-commit-config.yaml` from §13 (verbatim): `pre-commit-hooks` v4.6.0 (`check-added-large-files --maxkb=500`, `check-merge-conflict`, `detect-private-key`, EOF/whitespace fixers excluding bundle+vendor), `ruff-pre-commit` v0.6.9 (`ruff --fix`, `ruff-format`), and the three `local` hooks (`finder-duplicates` name-regex blocker, `no-db-files` allowing only `demo/seed.db`, pre-push `bundle-freshness` heuristic).
  2. Add the `[tool.ruff]` / `[tool.ruff.lint]` / `.pydocstyle` (`convention = "numpy"`, covers S10) / `.per-file-ignores` blocks from §13 to `pyproject.toml`. The `extend-exclude` list is the dormant-tree contract WS-6/WS-7 will delete against; keep it verbatim so ownership stays aligned.
  3. Add `pre-commit` to `requirements-dev.txt`; **drop the `black` pin** from `requirements.txt:51` (ruff-format subsumes it — §13 "What NOT to add").
- **Adoption order (from §13, "avoids a big-bang diff"):**
  1. **Commit A** — autofix only: `ruff check --fix original/ && ruff format original/` on live modules, `--exclude original/constants.py` from `ruff format` (preserve its column-aligned tables; S11). This is the ~46 F401 + 38 I001 + f-string/format sweep in one reviewable diff, no behavior change.
  2. **Commit B** — config + the CI lint job (task 2.4 job 1) together, so the gate lands already-green.
  3. **Later (NOT this workstream):** per-module opt-in of `D` (docstrings) starting with `quantum/`, and `ANN` on new files only. Never retrofit `D`/`ANN` repo-wide.
  - S12 (in-function imports in `api.py`) is handled by enabling `I`; genuine lazy imports (LTI crypto, optional `ai_likelihood`) keep a `# noqa: E402`/reason comment rather than being hoisted.
- **Files touched:** `.pre-commit-config.yaml` (new), `pyproject.toml`, `requirements-dev.txt`, `requirements.txt` (drop black), plus the autofix diff across `original/*.py`.
- **Verify:** `pre-commit install --hook-type pre-commit --hook-type pre-push`; `pre-commit run --all-files` exits 0 after Commit A; staging a scratch `foo 2.py` and a scratch `x.db` each makes `git commit` fail with the named hook.

### 2.4 CI rework to the four-job shape — B1, B2, B3, B4, B5, B6, B11, T9
- **Current state:** `.github/workflows/test.yml` has exactly **two** jobs — `pytest` (installs full `requirements.txt` incl. PyTorch via sentence-transformers, runs `pytest -q`, no coverage) and `bluebook-e2e` (`needs: pytest`; installs `requirements-demo.txt`; **never runs `npm run build`**; boots the server on `--port 8001 --skip-seed` with `ORIGINAL_ENV=pilot`). No lint job, no coverage flag, no bundle diff, no security job, no `concurrency:`, no `timeout-minutes:`, actions pinned to mutable major tags (`@v4`/`@v5`), no top-level `permissions:`. The e2e job already uses port 8001 (audit B11 note holds — the *wrong requirements* is the bug, not the port).
- **Change:** restructure to the four jobs the audit specifies at §7 (lines 470–476) and §8:

  | Job | `needs` | Runs |
  |---|---|---|
  | **1. lint** | — | `ruff check .` + `ruff format --check .` (fast gate, ~5 min). Blocking. |
  | **2. pytest+coverage** | `lint` | install (see B6 below) + `python -m spacy download en_core_web_sm` → `python -m pytest tests/ validation/test_tier10_optional.py --cov=original --cov-report=xml --cov-fail-under=70` → upload `coverage.xml` artifact. (T9/B3; floor 70 is cleared by today's suite — WS-5 ratchets it.) |
  | **3. bundle+e2e** | — (parallel to job 2) | `npm ci` → **`npm run build` → `git diff --exit-code -- demo/bluebook/bluebook.bundle.js`** (B2) → install **`requirements-pilot.txt`** (B11, superset — pulls the LTI jose/cryptography stack so `/lti/*` is exercised) → spaCy model → boot server `--port 8001 --skip-seed` `ORIGINAL_ENV=pilot` → Playwright. |
  | **4. security** | — (parallel; `continue-on-error: true` initially) | `pip-audit` on the pilot lockset + `gitleaks detect` (B4). Would have caught B10 automatically. |

  Workflow-level (all jobs): `concurrency: {group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true}` (B5); `timeout-minutes: 20` on jobs 1/2/4, `15` on job 3 (B5); pin every `uses:` to a **full commit SHA** with a `# vX.Y.Z` trailing comment (B5); top-level `permissions: {contents: read}` (§7 line 475).
  - **B6 (install cost):** job 2 should install from the compiled lock without PyTorch if the suite passes on `requirements-demo.txt` + dev extras — **verify this before switching** (`.venv/bin/python -m pytest tests/ -q` under a demo-only env). If any test needs the sentence-transformers backend, keep `requirements.txt` for job 2 but pin the spaCy model by wheel URL (as the Dockerfile already does) to stop the per-run re-download. Do not silently drop PyTorch without the pass check.
- **Files touched:** `.github/workflows/test.yml`, new `.github/dependabot.yml` (pip + npm + github-actions — B4).
- **Verify:** open a scratch PR that (a) adds an unused import → job 1 red; (b) edits a `demo/bluebook/*.jsx` without rebuilding → job 3 `git diff` red; (c) drops a covered test file → job 2 `--cov-fail-under` red; (d) confirm job 4 pip-audit flags the pre-B10-fix jose range if run against it. Green baseline: all four pass on `main` after tasks 2.1–2.3 land.

### 2.5 Requirements layering + lock strategy — B6, B8, B9
- **Current state (verified):** `requirements.txt` does **not** start with `-r requirements-demo.txt`; it re-lists fastapi/uvicorn/pydantic/starlette/numpy/scikit-learn/spacy/langdetect/python-docx/pypdf (~11 pins) that also live in `requirements-demo.txt`, with copy-pasted CVE comments that match today but nothing keeps matched (B8/B9). Dev tools (`pytest`, `pytest-asyncio`, `pytest-cov`, `hypothesis`, `black`, `ruff`, `mypy`) sit in `requirements.txt:44–53`, **not** in `requirements-dev.txt` — which currently holds only `matplotlib` + `scikit-learn` and a header *claiming* dev-only scope. `requirements-pilot.txt` correctly layers (`-r requirements-demo.txt` + jose).
- **Change:**
  1. Make `requirements.txt` begin with `-r requirements-demo.txt`, then keep only the *production-superset* deps not in demo (sqlalchemy, alembic, psycopg2-binary, python-jose, passlib, bcrypt, slowapi, prometheus-*, httpx). Delete the ~11 duplicated demo pins and their duplicated comments.
  2. Move `pytest*`, `hypothesis`, `mypy`, `ruff`, `pre-commit` (from 2.3) into `requirements-dev.txt`; drop `black` entirely (2.3). Fix the requirements-dev.txt header if scope wording drifts.
  3. Compile per-target locks with `pip-compile` (or `uv pip compile`): `requirements-demo.lock.txt`, `requirements-pilot.lock.txt`, `requirements-dev.lock.txt`. CI jobs install from the `.lock.txt`; the human-edited `.txt` files stay the source. This also fixes the B6 cache-key drift (floating ranges under a constant hash).
- **Files touched:** `requirements.txt`, `requirements-dev.txt`, three new `*.lock.txt`, CI install steps (job 2/3 reference locks).
- **Verify:** `pip install --dry-run -r requirements-demo.txt` and `-r requirements-pilot.txt` resolve identically before/after; `grep -c fastapi requirements.txt` → the pin appears once (via the `-r` include); the pilot lock still resolves python-jose ≥3.4 (post-WS-1).

### 2.6 Rebuild `.venv` on 3.11; preflight version assert; fix `start.sh` — B7, B17
- **Current state:** `.venv/pyvenv.cfg` → `version = 3.9.6` (Xcode system python; audit B7), two minors behind CI/Render/Docker (all 3.11) and below pyproject's `requires-python = ">=3.10"`. `start.sh:14` runs `pip install -r requirements.txt -q` (full set → PyTorch) with bare `pip`/`python3` (the broken system interpreter) for a demo that needs only `requirements-demo.txt` (B17).
- **Change:**
  1. Rebuild: `python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt` (or the compiled locks from 2.5). Update the CLAUDE.md `.venv` note's Python version.
  2. Add a preflight assert (in `run.py` startup or a `scripts/preflight.py` reused by the Makefile `preflight` target): `assert sys.version_info >= (3, 10), f"Python 3.10+ required, got {sys.version}"`.
  3. Rewrite `start.sh` to use `.venv/bin/python` + `.venv/bin/pip` and install `requirements-demo.txt` (not the full set). Keep `--port 8001` (already correct at `start.sh:28`).
- **Files touched:** `.venv/` (rebuilt), `start.sh`, `run.py` (or `scripts/preflight.py`), `CLAUDE.md` (version note).
- **Verify:** `.venv/bin/python -c 'import sys; print(sys.version_info[:2])'` → `(3, 11)`; `.venv/bin/python -m pytest tests/ -q` → 0 failed; `bash -n start.sh` clean and `grep -c requirements.txt start.sh` → 0 (only requirements-demo.txt referenced).

### 2.7 Makefile task runner — B17
- **Current state:** no `Makefile`/`justfile` exists (verified). The safety-critical `cd demo/bluebook && npm run build` bundle rebuild lives only in CLAUDE.md prose — omitting it ships stale code.
- **Change:** add a ~20-line `Makefile` with targets hard-coding `.venv/bin/python` (mechanically neutralizes the system-python/3.9 traps): `test`, `test-quantum`, `run`, `bundle`, `e2e`, `backup`, `preflight`, `lint`, plus a `setup` target that runs `pre-commit install …` (per §13). Concrete bodies:
  - `test:` → `.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`
  - `test-quantum:` → `.venv/bin/python -m pytest tests/quantum/ -v`
  - `run:` → `.venv/bin/python run.py --demo --frontend-dir demo/ --port 8001`
  - `bundle:` → `cd demo/bluebook && npm run build`
  - `e2e:` → `cd demo/bluebook && npx playwright test`
  - `lint:` → `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
  - `preflight:` → the 2.6 version assert + a bundle-freshness check
  - `backup:` → the existing `scripts/backup_db.sh` invocation
- **Files touched:** `Makefile` (new).
- **Verify:** `make lint`, `make test`, `make bundle` each run; `grep -c 'python3 ' Makefile` → 0 (no bare system python).

### 2.8 Bluebook build chain hardening + register `slow` marker — B12, B13, T8
- **Current state:** `demo/bluebook/build.mjs:20–24` has `const ORDER = [...]` with the comment "Load order MUST match index.html" — a comment, not a check; `minify: true` (`:41`) with **no `sourcemap`** key → pilot errors point into one minified line. Vendored React 18.3.1 in `demo/bluebook/vendor/` is identifiable only by grepping minified source (no VERSION/checksum file). `demo/bluebook/package.json:8` build script = `node build.mjs`. `pytest.ini` (verified, 3 lines) has **no `markers` section** → `@pytest.mark.slow` at `tests/context/test_blend.py:251` raises `PytestUnknownMarkWarning` and is never deselected (T8).
- **Change:**
  1. `build.mjs`: add `sourcemap: 'linked'` to the esbuild call (free; B13). Assert the `ORDER` array matches the `<script>` tags in `index.html` — read `index.html`, extract the ordered `*.jsx` script `src`es, and throw if they differ from `ORDER` (B12). The CI byte-diff (job 3) remains the real freshness gate; this catches the drift at build time.
  2. Add `demo/bluebook/vendor/README.md` listing each vendored file with version + source URL + `sha256` (B13).
  3. Register the marker — add to `pytest.ini`:
     ```ini
     markers =
         slow: marks tests as slow (deselect with '-m "not slow"')
     ```
     (T8; alternatively migrate to `[tool.pytest.ini_options]` in pyproject — keep it in `pytest.ini` to avoid a config move in this PR.)
  4. **Rebuild + commit the bundle** after the `build.mjs` change (CLAUDE.md rule; the sourcemap change alters `bluebook.bundle.js`).
- **Files touched:** `demo/bluebook/build.mjs`, `demo/bluebook/bluebook.bundle.js` (+ `.js.map`), `demo/bluebook/vendor/README.md` (new), `pytest.ini`.
- **Verify:** `cd demo/bluebook && npm run build` emits a `.js.map` and prints the ORDER-match assertion passing; `.venv/bin/python -m pytest tests/context/test_blend.py -q -W error::pytest.PytestUnknownMarkWarning` no longer warns; `.venv/bin/python -m pytest -m "not slow" tests/context/test_blend.py --collect-only -q` deselects `:251`.

## Acceptance criteria
Expands the §9 WS-2 `Accept:` line ("CI red on: lint violation, stale bundle, coverage drop below floor, CVE'd dep; pre-commit blocks a staged `file 2.py` and a `.db` file").
- [ ] CI job **lint** fails on any `ruff check`/`ruff format --check` violation (proven via scratch unused-import PR).
- [ ] CI job **bundle+e2e** fails when a `demo/bluebook/*.jsx` changes without a rebuilt `bluebook.bundle.js` (`git diff --exit-code` red).
- [ ] CI job **pytest+coverage** fails when coverage drops below `--cov-fail-under=70`; `coverage.xml` uploaded as an artifact.
- [ ] CI job **security** runs pip-audit + gitleaks (non-blocking initially) and flags the pre-fix python-jose range.
- [ ] `pre-commit run --all-files` is green on `main`; staging `foo 2.py` blocks the commit (`finder-duplicates`); staging a `*.db` other than `demo/seed.db` blocks the commit (`no-db-files`).
- [ ] Workflow has `concurrency: cancel-in-progress`, `timeout-minutes` on every job, SHA-pinned actions, `permissions: contents: read`, and a `dependabot.yml` (pip/npm/actions).
- [ ] `requirements.txt` starts with `-r requirements-demo.txt`; no demo pin appears twice; dev tools live only in `requirements-dev.txt`; `black` pin removed; `*.lock.txt` compiled per target.
- [ ] `.venv` reports Python 3.11; preflight assert rejects <3.10; `start.sh` uses `.venv` + `requirements-demo.txt`.
- [ ] `make lint`/`make test`/`make bundle`/`make e2e` all run; no bare `python3` in the Makefile.
- [ ] `build.mjs` emits a linked sourcemap and asserts ORDER↔index.html; `vendor/README.md` lists versions + sha256; `slow` marker registered (no `PytestUnknownMarkWarning`).
- [ ] The seven junk/duplicate files are gone; `.gitignore` ignores `.fuse_hidden*` and `.benchmark_cache/`; pytest no longer collects `test_roster_links 2.py`.

## Risks & watch-outs
- **Ordering trap:** wiring a *blocking* `ruff format --check` CI job before rebuilding `.venv` on 3.11 (task 6) can produce local-vs-CI disagreement on `UP`/py311 idioms. Land config (2.3) + venv rebuild (2.6) before making the format check blocking.
- **`extend-exclude` is a cross-workstream contract.** The dormant-tree exclusion list in `[tool.ruff]` (§13) is what WS-6/WS-7 delete against — do not prune it here to "clean up lint," or you re-enable ~40 F821 forward-ref warnings in `db/models/*` and hundreds of E501s in code scheduled for deletion.
- **`constants.py` must stay format-exempt.** `ruff format` would collapse the deliberate column alignment in `ALL_FEATURE_CODES`/`NORM_BOUNDS`; the `per-file-ignores` E501 + `--exclude` from `ruff format` are load-bearing (and CLAUDE.md gates feature-ordering changes on explicit permission).
- **B6 PyTorch drop is conditional.** Do not remove sentence-transformers from the CI pytest install without first confirming the suite passes demo-only — `features/tier10.py` and tension-arc have a TF-IDF fallback, but a test may assert the ST backend path.
- **Bundle commit discipline:** the `sourcemap: 'linked'` change (2.8) alters `bluebook.bundle.js`; forgetting to rebuild+commit it would immediately trip the new job-3 diff — which is the gate working, but sequence the commit so `main` stays green.
- **Not in scope (owned elsewhere):** B10 (WS-1), B16 (WS-1), B15/B19 (WS-6 — stale docker/fly/alembic + SQLite migration ladder), B20 (release-hygiene/CHANGELOG → WS-9). Flag if any get pulled forward.

## Sequencing within the workstream
1. **2.1 + 2.2** (delete junk, `.gitignore`) — one commit; independently shippable, unblocks a clean pytest collection immediately.
2. **2.3 Commit A** (ruff/format autofix on live modules) — independently shippable; large mechanical diff, review in isolation.
3. **2.6** (rebuild `.venv` on 3.11 + preflight + `start.sh`) — local/tooling; do before making lint blocking.
4. **2.3 Commit B** (pre-commit + `[tool.ruff]` config) **together with 2.4 job 1** (CI lint) — the gate lands already-green.
5. **2.5** (requirements layering + locks) — must precede/accompany the 2.4 install-step rewrite so CI installs from locks.
6. **2.4 jobs 2–4** (coverage, bundle+e2e-on-pilot, security) + workflow-level hardening + `dependabot.yml` — the CI cutover; lands as one workflow rewrite.
7. **2.7 Makefile** — any time after 2.6; convenience wrapper, low risk.
8. **2.8** (build.mjs sourcemap + ORDER assert, vendor README, `slow` marker) — independent; ends with a bundle rebuild+commit.

Shippable-alone: 2.1/2.2, 2.3-A, 2.6, 2.7, 2.8. Must-land-together: 2.3-B + 2.4-lint; 2.5 + 2.4-install.
