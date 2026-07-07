# Changelog

All notable changes to Original are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); dates are the date of the
merge/commit that shipped the change, not necessarily the PR-open date.

> **Version source of truth.** The version numbers below track
> [`MODEL_CARD.md`](MODEL_CARD.md)'s "Version History" table, which versions
> the *scoring model and its contract* (feature pipeline, thresholds, gated
> scoring modes) — not the whole application. `pyproject.toml` (`0.0.0`) and
> the FastAPI app object (`0.1.0`, `original/api.py`) do not currently track
> this number; reconciling the three is out of scope here (see
> `docs/implementation/WS-3-trust-surface.md` "Risks & watch-outs", D7).

## [Unreleased]

Work merged after the 1.3.0 model-card entry, not yet reflected in a new
model-card version line (this reflects operational/docs/hygiene work, not a
new scoring-behavior change — no version bump is implied):

### Changed
- Configured ruff/black/mypy tooling in `pyproject.toml` (`a8ed29e`).
- Cleaned up Finder-duplicate and junk files; gitignored FUSE/benchmark
  artifacts (`68b4f57`).

## [1.3.0] — 2026-07-06

### Added
- Peer-pool null model wired into production scoring: `NULL_MODEL=impostor`
  builds a per-tenant impostor cohort on the live scoring path and attaches
  `authorship.llr_deviation_score` — attach-only, cold-start abstention,
  enabled by default in demo mode only (`4091ff0`, `06e7368`).

### Fixed
- Pilot go-live hardening: lockdown behavior, in-app backup scheduler,
  FERPA-accuracy corrections across docs (`f4e7589`).
- All 7 findings from the UX audit; CI pytest provisioning fixed
  (`1f31306`).

### Added (pilot readiness)
- Preflight checks, operations runbook, weekly reports, multi-generator
  evals (`4713328`).
- Shadow mode + baseline-readiness surface for the first pilot weeks
  (`6854a84`).

## [1.2.0] — 2026-07-01

### Added
- AI-likelihood detector: the corpus-level second scoring mode
  (`39db0af`, `b662bc1`). Committed calibrated classifier artifact
  (`original/data/ai_detector_v1.joblib`), `AI_LIKELIHOOD_ENABLED` /
  `AI_LIKELIHOOD_SHADOW` / `AI_LIKELIHOOD_MODEL_PATH` flags, report-only
  contract (never affects `deviation_score` or the recommended action),
  enablement gate (seminary AUC ≥ 0.85, FPR ≤ 5%), and a sklearn
  version-skew runbook. See
  [`docs/adr/007-ai-likelihood-gating.md`](docs/adr/007-ai-likelihood-gating.md)
  for the full gating rationale.
- Retrained the detector on an academic-register-diverse mix
  (AuTexTification + M4) after the AuTexT-only v1 model over-flagged
  formal/archaic prose; the in-domain enablement gate now passes
  (`cee1f00`).
- Diagnostic isolating the feature-vs-scoring-method gap that motivated the
  detector (`12f979c`, `b73da57`).
- AuTexTification adapter for a real head-to-head benchmark against the
  StyloAI paper (`803a820`, `be83acf`).
- Ledoit-Wolf shrinkage (`RANK_REMEDIATION=shrinkage`) and the impostor-null
  LLR groundwork later wired into 1.3.0 (`06e7368`).
- Binary authorship-verification evaluator; three measurement bugs fixed
  (`99170fe`).
- RAID fetcher fix (range-sampled `train.csv`) and first real RAID
  cross-dataset evidence (`4cd5ef7`, `4c9b5b4`).

## [1.1.0] — 2026-06-09

### Changed
- Model card updated for the 103-dimensional pipeline, Tier 17 behavioral
  biometrics, comparison dimensions, pilot runtime posture, and an explicit
  human-review policy (per `MODEL_CARD.md`'s own version history).

### Added
- Length-adaptive tier weighting, evidence-based (`3abb886`, `616087a`).
- Length-stability study measuring which features survive at 500 words
  (`fe06b3a`).
- Wide-dataset accuracy benchmark (RAID + PAN AV + M4 adapters)
  (`e553572`, `d4c8789`).
- ADR-005: redacting student read-model (`GET /me/voice`, `POST /me/work`,
  `POST /me/formation/advance`) — feature codes, raw deviation scores,
  purity, sample counts, action enums, and thresholds are projected away
  server-side before any response reaches the student client
  (`235eaf2`, `24126f6`, `525a09e`, `602d4b8`).
- Real roster (names, counts, status) rendered in professor and admin
  dashboards; student display names persisted (`f716e82`, `e91d373`).
- Bluebook production bundle + vendored React (no CDN/Babel at exam time);
  Playwright E2E suite for Bluebook (`221e4f8`, `09f71af`, `72d5395`).
- Render pilot service: hardened `original-pilot` config, login throttle,
  operations runbook (`dbf35f9`).
- Architecture map and dormant-stack quarantine banners; Owner's Manual
  (surfaces map, dean-demo script, operator tasks) (`ffe0ef0`, `140654e`).
- ADR-003 (multi-tenant auth without losing the demo) and ADR-004 (hardened
  SQLite for the pilot) (`3cd3f94`, later marked Accepted in `81554ba`).

## [1.0.0] — 2026-03-17

### Added
- Initial release: 34-feature pipeline, quantum density-matrix scorer (per
  `MODEL_CARD.md`'s version history). Superseded by the 103-feature,
  17-tier pipeline documented in later entries and in `CLAUDE.md`.

---

## Related documents

- [`MODEL_CARD.md`](MODEL_CARD.md) — the authoritative scoring-model version
  history this changelog mirrors and extends with git-level detail.
- [`docs/adr/`](docs/adr/) — architecture decision records for the
  larger design choices behind entries above (ADR-003 through ADR-007).
- [`docs/AUDIT_2026-07-06.md`](docs/AUDIT_2026-07-06.md) — the audit that
  produced the current documentation workstream (WS-3) this file is part of.
