# Plan 01 — Gate Repair: make the validation battery fully evaluable again

> **For agentic workers (Codex):** This is a goal-oriented brief, not a step-by-step
> script. Each goal is independently verifiable; work them roughly in order (G1 first —
> everything else reads cleaner once the battery runs). Read
> `2026-08-26-codex-campaign-00-overview.md` for campaign context and the shared
> constraints, which are restated below because they are load-bearing.

**Goal:** Restore `python -m validation.calibration_gate` to a state where every gate
G1–G8 returns a real three-valued verdict (`pass`/`fail`/`uninformative`) with zero
machinery ERRORs, land the two stranded one-commit fixes, and commit a fresh battery
report so the repo's newest committed evidence is no longer 2026-07-31.

**Why now:** G5 — the suite's **only label-destruction control** — cannot run at all on
`main` today. The 2026-08-08 seminary corpus growth made real corpora trip the Phase-8
drift gate (42/326 G1 real-anchor folds and 56/139 G6 folds are drift-holds), which
exceeds `_require_healthy_leg`'s 10% failed-call ceiling and renders G5 and G6 as
permanent machinery ERRORs. The fix exists, is tested, and has been sitting unmerged
since 2026-08-14. Separately, the repo currently asserts two contradictory verdicts for
the AI-likelihood enablement gate in its own docs.

**Architecture:** All work is in `validation/`, docs, and CI config. Nothing here
changes scoring behavior. The one scoring-adjacent item (pooled typicality calibration)
is documentation + gate-harness wiring of an already-shipped flag.

## Global constraints

- Python: `~/Desktop/Original/.venv/bin/python` (absolute — worktrees have no `.venv`). Never system python3.
- Full suite `.venv/bin/python -m pytest tests/ -q` takes **11–12 min**; budget for it, don't background it on a 600 s timeout. Clean = 0 failed.
- Postgres-marked tests: `make test-postgres` (~10 s once the Docker container is up via `bash scripts/local_postgres.sh up`). Run them if you touch anything under persistence.
- CI coverage gate is `--cov-branch --cov-fail-under=98` with ~1.6 pt of margin. New code ships with tests.
- Every new/changed gate needs a failure witness registered in `validation/gate_contracts.py` or `tests/test_gate_falsifiability.py` fails the suite.
- Never quote a gate result without running `--strict` (`python -m validation.calibration_gate --strict` folds `uninformative` into `fail`).
- Never commit `validation/genre_crossgenre_2026-08/{raw,clean,chunks.json,vectors.npy,vectors_meta.json}` (copyrighted editions).
- Deleting files: `git rm`, never bare `rm`. No pushes to `main`. Branch, then PR.
- Commit style: `Fix …` / `Add …` / `Refactor …`, one logical change per commit, co-author trailer per repo convention.

---

## G1. Land the G5/G6 drift-hold carve-out (highest priority)

**Source:** branch `claude/gates-all-evaluable` (2026-08-14), commits:
- `b90995fc` — "Fix G5/G6 machinery ERRORs: carve drift-gate holds out of leg health checks"
- `88de2d93` — "Ignore G7's cross-genre corpus artifacts" (`.gitignore` rules; also a hard prerequisite for Plan 02, which regenerates that corpus locally)

`claude/peaceful-mccarthy-4f4a3a` carries a subset (`afc000f7`) — use `gates-all-evaluable`,
it supersedes it. Delta vs main: `validation/calibration_gate.py` +187/−26,
`tests/test_calibration_gate.py` +184, `.gitignore` +10/−3.

**How to verify main is still broken before you start** (don't skip this — if someone
landed it since 2026-08-26, this goal is done):

```bash
git log main --oneline --grep="drift-gate holds"        # expect: empty
grep -n "_real_g1_drift_rejected,  # unused here" validation/calibration_gate.py
```

**Approach:** branch from `main`, merge or cherry-pick both commits, resolve conflicts
against the current `calibration_gate.py` (it has moved since 08-14 — the branch-coverage
effort touched tests heavily; expect conflicts in `tests/test_calibration_gate.py`).
The semantic content to preserve: drift-gate holds on real-corpus folds are counted as a
**separate category** from scoring failures, excluded from `_require_healthy_leg`'s >10%
failed-call rule, and reported in the leg summary so a drift-hold spike is still visible.

**Acceptance:**
- `.venv/bin/python -m validation.calibration_gate` completes with G5 and G6 each
  showing a real verdict (pass/fail/uninformative), **no** `ERROR (machinery)` lines.
- `.venv/bin/python -m pytest tests/test_calibration_gate.py tests/test_gate_falsifiability.py -q` → 0 failed.
- `.gitignore` contains the cross-genre artifact rules
  (`validation/genre_crossgenre_2026-08/raw/` etc.).

## G2. Land the AI-likelihood doc correction

The repo currently contradicts itself: `CLAUDE.md:118` and `MODEL_CARD.md:283` state the
AI-likelihood document-level gate **FAILS** (FPR 8%, n=25 — the stale verdict), while
`MODEL_CARD.md:200-206` records the current one: **PASSES** at n=139 (seminary AUC
0.9975, CI95 [0.9914, 1.0]; FPR 2.88% = 4/139). The correction is one commit,
`a61f01f6` on `claude/readme-capabilities-docs-1e63d4`.

Cherry-pick it (or re-apply by hand if it conflicts), then grep for stragglers:

```bash
grep -rn "n=25\|8% vs\|FPR 8" CLAUDE.md MODEL_CARD.md README.md docs/
```

**Do NOT change the flag default** — `AI_LIKELIHOOD_ENABLED=0` stays. Passing the
corpus gate does not clear the pilot go/no-go (real-world FPR on instructor-confirmed
authentic work, ≥30 labeled joins, band sanity, sign-off — `docs/PILOT_RUNBOOK.md` §3).
The known false-positive register (real 19th-c. oratorical prose, e.g. Brooks at 0.8081)
and the single-generator (Claude) training caveat stay in the card verbatim.

**Acceptance:** both files state the n=139 verdict with its caveats; no doc in the repo
still asserts the n=25 FAIL as current.

## G3. Stop G8 from silently degrading in a base environment

G8's author-shuffled control needs scikit-learn; base `requirements.txt` doesn't carry
it (dev/demo locks only), so on a bare install G8 quietly reports `uninformative`
(handled explicitly around `validation/calibration_gate.py:3946`).

Preferred fix: add `scikit-learn` (same pinned version as the dev lock) to
`requirements.txt`. Check first whether that is deliberate — search git history and
`docs/adr/` for a decision keeping sklearn out of production deps (the AI-detector
loads a joblib artifact and has a version-skew runbook: predictions on 8 reference
vectors drifting >0.02 disables the detector; **the remedy is retrain via
`scripts/train_ai_detector.py`, never pinning around it**). If keeping it out of prod
deps is deliberate, the fallback fix is to make the degrade loud: the gate should print
an explicit `G8 UNINFORMATIVE: scikit-learn not installed — install dev requirements`
line, and `--strict` should exit 1 (it already folds uninformative→fail; confirm).

**Acceptance:** a fresh venv built from the chosen requirements set runs G8 to a real
verdict, **or** the degrade prints an unmissable reason and strict-mode fails. Either
way, document which in `validation/README.md`.

## G4. Document `TYPICALITY_POOLED_CALIBRATION`, then evaluate G1 under it

The flag exists in code (`original/quantum/scoring.py:532,621`,
`original/quantum/pooled_calibration.py`) and appears in **no** CLAUDE.md flag row, no
MODEL_CARD entry, no `.env.example`. It is also the intended remedy for G1's structural
uninformativeness: the conformal p-value floor is 1/(N+1), so at per-entity N≤4 the
loosest flag boundary (0.03, needs N≥33) is unreachable and G1 downgrades itself.

Two sub-goals, in order:

1. **Document it.** Add the flag row to CLAUDE.md's env-flag table and a MODEL_CARD
   section: pools same-tenant peers' LOO distances into one conformal reference
   (`min_students=3`, `min_total=30`, scored student always excluded), falls back to
   self-calibration on thin tenants. State the known evidence gap honestly:
   exchangeability was validated **within-seminary and within-Plato separately — never
   their union, and never public_authors at all** (`calibration_gate.py:1615-1622`,
   `validation/audits/pooled_calibration_payoff.py`).
2. **Close the evidence gap before wiring it into G1.** Run
   `validation/audits/pooled_calibration_payoff.py` (and extend it if needed) to test
   exchangeability on the union + public_authors. If exchangeability holds, add a
   **pooled-calibration G1 leg** to the battery that reports alongside (not instead of)
   the per-entity leg, and register its failure witness in `gate_contracts.py`. If it
   does not hold, commit the negative result to `validation/audits/` and record in the
   flag row that pooling across these corpora is not licensed — that is a real,
   valuable verdict; do not force it.

**Acceptance:** flag documented; audit verdict committed; G1 either has an informative
pooled leg with a registered witness, or a committed negative exchangeability result.

## G5. Run the G2 floor-asymmetry audit to a committed verdict

`validation/audits/g2_floor_asymmetry.py` exists to decide whether G2's pass margin
(impostor median q 0.048 vs holdout 0.222) is `artifact` / `genuine` / `inconclusive`
— the concern is the margin may be driven by the p-floor rather than real separation.
No committed verdict exists. Run it, commit the output JSON + a short README note in
`validation/audits/`, and if the verdict is `artifact`, annotate G2's row in
`validation/README.md` accordingly (do not silently keep quoting the pass).

**Acceptance:** committed verdict file; `validation/README.md` reflects it.

## G6. Put the battery in CI as a scheduled, non-blocking job

The instrumentation spec (`docs/superpowers/specs/2026-07-31-instrumentation-validation-layer-design.md`
§7, open decisions #3 and #5) left this unresolved: the corpus-driven battery is
manual-only and nothing anywhere invokes `--strict`. Resolve it as: **a scheduled
weekly GitHub Actions job** (not per-PR — the battery is minutes-long and its corpora
are partly regenerable-only) that runs
`.venv-equivalent python -m validation.calibration_gate --strict`, uploads the JSON
report as a build artifact, and is `continue-on-error: true` with a visible badge/log —
non-blocking, because G7 will legitimately report `uninformative` on a fresh checkout
until Plan 02's corpus regeneration is scripted into the job (leave a TODO comment
pointing at Plan 02, and skip G7-corpus fetching in CI for now).

Update the spec's §7 to record the decision taken.

**Acceptance:** workflow file merged; one successful scheduled/dispatched run visible;
spec updated.

## G7. Commit a fresh full battery report

The newest committed report is `validation/calibration_report_2026-07-31.json` — G1–G6
only, from before three-valued verdicts existed (all `verdict` fields `None`), before
G7/G8 existed. After G1–G5 above land, run the full battery (with the cross-genre corpus
regenerated locally if Plan 02 has landed; without it G7 will honestly read
`uninformative` — commit that) and commit
`validation/calibration_report_2026-08-XX.json` plus a dated line in
`validation/README.md` summarizing per-gate verdicts.

**Acceptance:** committed report containing all eight gates with populated `verdict`
fields; README table updated; any `uninformative` entries carry their reason string.

---

## Out of scope for this plan

- Regenerating the cross-genre corpus and running G7/G-P3 to real verdicts → Plan 02.
- Anything touching live pilot data or Render → Plan 03 + human ops track.
- The G1/G6 *corpus-depth* fixes (more docs per entity) → Plan 02 (public_authors depth goal).
