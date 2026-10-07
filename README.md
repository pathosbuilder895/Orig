# Original + Bluebook

Platform for trusted writing submission and writing-consistency observation. Helps teachers make sure a student's writing is really their own, and helps students become stronger writers by building their own skill.

## The Two Products

- **Bluebook**: Locked, in-browser writing and exam app. Teachers create classes, invite students, run timed sessions, and read, grade, release, and export sealed submissions. Works entirely on its own — a Bluebook-only workspace never builds a writing profile.

- **Original**: Writing-consistency engine. Builds a profile from teacher-approved earlier writing and reports how a new piece compares. **Optional and off by default.** When turned on, it displays testing-phase warnings. Original supports a teacher's judgment and is a reason for a conversation, never an accusation or a verdict.

## Current Phase

**Invitation-only Bluebook pilot for independent teachers.** Start with 1–3 teachers, possibly growing to a few dozen. No public signup.

Engineering for this phase is merged (PRs #226, #227, 5 Oct 2026). **Nothing is deployed yet.**

See [`docs/NORTH_STAR.md`](docs/NORTH_STAR.md) for mission, phase goals, and non-negotiables.

## Quick Start (Local Development)

**Prerequisites:** Python 3.11+

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
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

**Stack:** Python 3.11, FastAPI + uvicorn, SQLite (dev/demo), Postgres 16 (pilot), spaCy, numpy, sentence-transformers (optional).

**Entry point:** `run.py` → `original/api.py` (FastAPI app assembly). Routes in `original/routers/`: admin, auth, bluebook, health, imports, lti_routes, students, students_baseline, students_scoring, tenants.

**Pipeline:** `original/features/` (109 dimensions, 18 tiers) → `original/quantum/state.py` (density matrix) → `original/quantum/scoring.py` (Born rule).

**Frontends:**
- `demo/bluebook/` — React 19 exam app (committed bundle)
- `demo/*.html` — Static professor/admin pages
- `demo/bluebook/teacher-demo.html` — Fictional walkthrough

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for what is live vs. deleted. V1 backend was deleted in PR #90.

## Feature Pipeline

Original extracts **109 stylometric features** across 18 tiers. **97 are active** in the pilot configuration:

- Tier 17 (6 features, behavioral biometrics) is in `DISABLED_FEATURE_GROUPS`, fixed at neutral 0.5 per ADR-010 (no keystroke data)
- Tier 18 (6 features, uniformity) disabled pending validation gates

Features: surface stylometrics, discourse markers, rhetorical register, punctuation patterns, syntactic depth, idiosyncratic markers, prosodic rhythm, error ecology, semantic gravity, tension arc, citation fingerprint, lexical architecture.

Per [`original/constants.py`](original/constants.py):
- `FEATURE_DIM = 109` (total)
- `BASE_FEATURE_DIM = 102` (stored baseline width)

## Baseline Trust Weights

From [`original/constants.py:AUTH_WEIGHTS`](original/constants.py):

| Provenance | Weight | Meaning |
|------------|--------|---------|
| `proctored` | 2.0 | Live Bluebook exam |
| `verified` | 1.0 | Teacher-confirmed paper |
| `canvas` | 0.8 | LMS-imported |
| `unverified` | 0.5 | Student self-upload |

## Testing

**245 test files** as of Oct 2026. Test count grows regularly. Full suite runs ~4,100+ test cases with 99%+ coverage in 11-12 minutes.

**Core tests** (no environment setup needed):

```bash
python -m pytest tests/test_features.py tests/test_quantum.py -v
```

**Full suite:**

```bash
.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -m "not blocker and not certification" -q
```

See [`AGENTS.md`](AGENTS.md) and [`CLAUDE.md`](CLAUDE.md) for test commands, Postgres setup, and coverage requirements.

## Documentation Map

**For AI tools and agents:** Start at [`AGENTS.md`](AGENTS.md).

**Read order:**
1. [`docs/NORTH_STAR.md`](docs/NORTH_STAR.md) — Mission, phase, non-negotiables (**wins on conflict**)
2. [`docs/STATUS.md`](docs/STATUS.md) — Current state, in-flight work, blockers
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Live vs. deleted components
4. [`docs/adr/`](docs/adr/) — Architecture decision records

**Other key docs:**
- [`CLAUDE.md`](CLAUDE.md) — Claude Code mechanics: venv, tests, flags
- [`docs/research/`](docs/research/) — Research briefs
- [`docs/release/VERIFICATION_AND_BLOCKERS.md`](docs/release/VERIFICATION_AND_BLOCKERS.md) — What remains before deployment
- [`MODEL_CARD.md`](MODEL_CARD.md) — Model contract and scientific limits (v1.4.27)

**Canvas/LTI:** Implementation exists (`original/lti.py`, `/lti/*` routes) but has no UI entry points. Deferred for initial product.

## Data Privacy (FERPA)

**Raw text IS stored.** Authorized teachers can retrieve baseline sample text via `GET /students/{id}/samples/{index}/text`.

**Manual deletion supported:**
- `DELETE /students/{id}` (HTTP)
- `python -m original.cli.delete_student --student-id <id> --confirm` (CLI)

**Feature vectors** (109-dimensional encoding) are non-reversible.

**No automatic retention/deletion** runs.

See [`docs/data_inventory.md`](docs/data_inventory.md), [`docs/encryption_policy.md`](docs/encryption_policy.md), [`docs/dpa_template.md`](docs/dpa_template.md).

## Deployment

**Target:** Render, defined in [`render.yaml`](render.yaml)

Services:
- **`original-pilot`** — Starter plan + Postgres 16, invitation-only, `ORIGINAL_ENV=pilot`, `REPO_BACKEND=postgres`
- **`bluebook-teacher-demo`** — Static fictional walkthrough
- **`original-pg-backup`** — Daily encrypted off-box backups

SQLite (WAL) is used for local dev/demo. Pilot uses managed Postgres 16.

See [`docs/OPS_RUNBOOK.md`](docs/OPS_RUNBOOK.md) for deployment, maintenance, secret management.

## Support

For pilot inquiries: independent teachers only in current phase (invitation-only). See [`docs/NORTH_STAR.md`](docs/NORTH_STAR.md) § "Who it's for" and [`docs/release/VERIFICATION_AND_BLOCKERS.md`](docs/release/VERIFICATION_AND_BLOCKERS.md) for what remains before first invites.

## License

See [`LICENSE`](LICENSE).
