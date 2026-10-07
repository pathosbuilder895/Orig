# Original

**Stylometric authorship-consistency scoring for academic writing.** Original helps seminaries and writing-intensive colleges verify whether a submitted paper aligns with a student's established writing history.

This repository contains two products:

- **Bluebook**: A secure, in-browser writing and exam application
- **Original**: Per-student stylometric profiling and authorship-consistency analysis

## Current Status

**Invitation-only pilot.** Bluebook is available for independent teachers through a professor-accessible workflow. Original is **testing-phase only** — reports are generated but not shown to users by default and make no claims about AI detection, cheating, or calibrated probabilities.

Nothing is deployed yet. The pilot infrastructure is documented but not live.

## What Original Does

Original builds a per-student **stylometric profile** from authenticated baseline samples (verified papers, proctored exams). When a new submission arrives, it's scored against that profile using a 109-dimensional feature pipeline and a quantum density-matrix scorer.

The system returns a **deviation score** (0-1) and a **recommended action** (no_action / monitor / schedule_conversation / escalate). These are **decision-support recommendations only**, not verdicts. Institutional action remains with instructors and academic integrity officers.

### What Original Does NOT Claim

- **No AI detection claims.** The system reports authorship consistency, not whether text is AI-generated.
- **No cheating verdicts.** A high deviation score means the submission differs from the student's established baseline — it does not prove misconduct.
- **No keystroke biometrics.** Per ADR-010, Original does not collect or store per-key timing data.

## Mission

From the governing design documents: Original exists to **build students' own writing skill**, not to outsource correction to AI. The posture is "show how this writing compares with an adequately established baseline, including when comparison is inconclusive" — **consistency, not accusation**.

## Quick Start

**Prerequisites:** Python 3.11, ~2 GB disk space for dependencies

```bash
cd /workspace
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements-pilot.lock.txt
python -m spacy download en_core_web_sm
python run.py --demo
```

Opens on `http://localhost:8001` with five synthetic student profiles.

| Page | URL |
|------|-----|
| Professor dashboard | http://localhost:8001/professor.html |
| Student view | http://localhost:8001/student.html |
| API docs | http://localhost:8001/docs |

## Architecture

**Stack:** Python 3.11, FastAPI + uvicorn, SQLite (WAL) by default, Postgres 16 opt-in via repository seam, spaCy, numpy, sentence-transformers (optional).

**Entry point:** `run.py` → `original/api.py` (FastAPI app assembly, middleware, product gate). Routes are in `original/routers/`: admin, auth, bluebook, health, imports, lti_routes, students, students_baseline, students_scoring, tenants.

**Scoring pipeline:** `original/features/` (109 dimensions across 18 tiers) → `original/quantum/state.py` (density matrix) → `original/quantum/scoring.py` (Born rule scoring).

**Frontends:**
- `demo/bluebook/` — React 19 exam app (committed bundle)
- `demo/*.html` — Static professor/admin pages
- `demo/bluebook/teacher-demo.html` — Fictional walkthrough

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full map, including which components are live vs. deleted.

## Feature Pipeline

Original extracts **109 stylometric features** across 18 tiers. Of these, **97 are active** in the default configuration:

- Tier 17 (6 features, behavioral biometrics) is in `DISABLED_FEATURE_GROUPS` and fixed at neutral 0.5 placeholders
- Tier 18 (6 features, uniformity) is also disabled pending validation gates

Features include: surface stylometrics, discourse markers, rhetorical register, punctuation patterns, syntactic depth, idiosyncratic markers, prosodic rhythm, error ecology, semantic gravity, tension arc, citation fingerprint, and lexical architecture.

Per [`original/constants.py`](original/constants.py):
- `FEATURE_DIM = 109` (total dimensionality)
- `BASE_FEATURE_DIM = 102` (stored baseline width, before tier 18 landed)

See `CLAUDE.md` Environment Flags table for which research features are dark.

## Baseline Trust Weights

From [`original/constants.py:AUTH_WEIGHTS`](original/constants.py):

| Provenance | Weight | Meaning |
|------------|--------|---------|
| `proctored` | 2.0 | Live Bluebook exam — gold standard |
| `verified` | 1.0 | Instructor-confirmed paper |
| `canvas` | 0.8 | LMS-imported (Canvas/Blackboard) |
| `unverified` | 0.5 | Student self-upload — lowest trust |

## Testing

The repository contains **245 test files** as of Oct 2026. Test count grows regularly as coverage expands.

**Run core tests** (requires Python environment setup):

```bash
.venv/bin/python -m pytest tests/test_features.py tests/test_quantum.py -v
```

**Full suite** (requires ~11-12 minutes):

```bash
.venv/bin/python -m pytest tests/ -m "not blocker and not certification" -q
```

Add Postgres tests:

```bash
make test-postgres  # Starts local Postgres container and runs postgres-marked tests
```

See [`CLAUDE.md` Testing section](CLAUDE.md#testing) for budget, coverage requirements, and CI commands.

## Repository Map

**For AI tools and agents:** Start at [`AGENTS.md`](AGENTS.md), which points to [`CLAUDE.md`](CLAUDE.md) for environment/venv rules, test commands, validation layer, design philosophy, env flags, and commit style.

**Key documentation:**

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Live vs. deleted components (two backends existed; only one remains)
- [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md) — Development instructions
- [`docs/adr/`](docs/adr/) — Architecture decision records
- [`docs/research/`](docs/research/) — Research briefs
- [`MODEL_CARD.md`](MODEL_CARD.md) — Model contract and scientific limits (v1.4.27)

**Canvas/LTI:** Implementation exists at `original/lti.py` and `/lti/*` routes but has no UI entry points. Canvas and LTI are deferred for the initial product. See [`docs/CANVAS_RUNBOOK.md`](docs/CANVAS_RUNBOOK.md) when re-enabled.

**Bluebook as standalone product:** Tenants can have Original, Bluebook, or both. A tenant's `products_json` field gates Original routes — Bluebook-only workspaces never profile students. See [`docs/ARCHITECTURE.md` § Bluebook standalone](docs/ARCHITECTURE.md).

## Data Privacy (FERPA)

**Raw text IS stored.** Authorized instructors can retrieve baseline sample text via `GET /students/{id}/samples/{index}/text` (used to review a student's writing before approving it as baseline).

**Manual deletion is supported:**
- `DELETE /students/{id}` (HTTP endpoint)
- `python -m original.cli.delete_student --student-id <id> --confirm` (CLI)

**Feature vectors** (the 109-dimensional encoding) are non-reversible and cannot reconstruct original text.

**No automatic retention/deletion scheduler runs** in the live stack.

See [`docs/data_inventory.md`](docs/data_inventory.md), [`docs/encryption_policy.md`](docs/encryption_policy.md), and [`docs/dpa_template.md`](docs/dpa_template.md).

## Deployment

**Target:** Render, defined in [`render.yaml`](render.yaml)

Services declared:
- **`original-pilot`** — Starter plan + managed Postgres, invitation-only, hardened by `ORIGINAL_ENV=pilot`
- **`bluebook-teacher-demo`** — Static site, fictional professor walkthrough
- **`original-pg-backup`** — Daily cron job, encrypted off-box backups

See [`docs/OPS_RUNBOOK.md`](docs/OPS_RUNBOOK.md) for deployment procedure, maintenance windows, and secret management.

## License

See [`LICENSE`](LICENSE) for terms.

## Support

For institutional pilot inquiries, see [`docs/PROVISIONING_CHECKLIST.md`](docs/PROVISIONING_CHECKLIST.md).
