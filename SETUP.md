# Original — Setup Guide

Authorship verification engine for academic integrity. Measures whether a submission
matches a student's own authenticated writing voice across 103 stylometric features
(`original/constants.py`, `FEATURE_DIM = 103`).

> This guide covers the **live stack** (`original/api.py` + `demo/`) — the app
> `render.yaml` deploys and `./start.sh` runs. See
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full live-vs-dormant
> split before assuming any other doc, script, or `original/api/` route
> applies here.

### Prerequisites

- **Python 3.10+** (3.11 recommended — matches [Dockerfile](Dockerfile) and [CI](.github/workflows/test.yml)).
- **Tier 10** (`semantic_field_dispersion`, `semantic_centroid_proximity`) uses `sentence-transformers` when installed; if it is missing or fails to load, Tier 10 returns neutral values so the rest of the pipeline still runs.

---

## Quick Start (5 steps)

### Step 1 — Run the demo

```bash
./start.sh
```

This installs all Python dependencies, downloads the spaCy language model, seeds
five synthetic student profiles, and starts the demo server on port 8001.

Open your browser:

| Page | URL |
|------|-----|
| Professor dashboard | http://localhost:8001/professor.html |
| Student dashboard   | http://localhost:8001/student.html |
| Class setup wizard  | http://localhost:8001/onboard.html |

The demo includes:
- **James Whitfield** — 5 baselines, clearly AI-generated submission (deviation ~0.7+)
- **Sarah Okonkwo** — 5 baselines, second AI pattern
- **Daniel Osei** — 5 baselines, mixed submission (moderate deviation)
- **Lydia Mercer** — 5 baselines, authentic submission (low deviation expected)
- **Michael Chen** — 1 baseline only (watch confidence build live during demo)

---

### Step 2 — Set up a real class

1. Open http://localhost:8001/onboard.html
2. Enter your school name and short code
3. Enter course details
4. Add students — type names, or **drop a CSV file** with columns `external_id, full_name, email`
5. Copy the generated links and send them to students

---

### Step 3 — Deploy for a real institution

The live deploy target is **Render**, defined in `render.yaml`. The
`original-pilot` service runs the same dashboard app as the demo, hardened by
setting `ORIGINAL_ENV=pilot`, which:

- fails fast at boot if `SECRET_KEY` isn't set
- locks CORS to `ALLOWED_ORIGINS`
- turns on HSTS
- guards destructive endpoints behind `MAINTENANCE_TOKEN`

Read `render.yaml` directly for the full, commented list of env vars
(backups, LTI keys, adaptive-scoring flags). Deploys are manual (not
auto-on-merge) — see `docs/OPS_RUNBOOK.md` for the maintenance-window
process and `docs/PROVISIONING_CHECKLIST.md` for bringing up a new tenant.

A Docker Compose / nginx / Alembic self-hosting path exists at
[deploy/DEPLOY.md](deploy/DEPLOY.md), but it is **not** the current
deployment path — it targets the dormant v1 API, not this app.

---

### Step 4 — Connect Canvas LTI

The live LTI 1.3 implementation is `original/lti.py` (routes `/lti/login`,
`/lti/launch`, `/lti/jwks`), configured via the `LTI_PLATFORMS` environment
variable — there is no registration API or database table to POST to.

Follow these two docs in order:

1. **[docs/canvas_developer_key.md](docs/canvas_developer_key.md)** — the
   one-pager to send your Canvas administrator. They return a **Client ID**
   and **Deployment ID**.
2. **[docs/CANVAS_RUNBOOK.md](docs/CANVAS_RUNBOOK.md)** — the full operator
   runbook: generating the LTI signing key, setting `LTI_PLATFORMS` on the
   Render service, and verifying `/lti/jwks` and a real launch end-to-end.

---

## Importing past Turnitin papers

Schools migrating from Turnitin can import existing student papers as verified baselines.

### Option A — File upload (recommended)

Use the **drag-and-drop zone** in the professor dashboard (Baselines tab):
- Drop multiple PDF, DOCX, or TXT files per student
- Original extracts text, extracts features, and builds the baseline profile
- Supports `.pdf` (via pypdf), `.docx` (via python-docx), `.txt`

Or use the API directly:
```bash
# Upload a single file and get extracted text
curl -F "file=@essay.pdf" \
     https://your-server/students/{student_id}/upload

# Add extracted text as a baseline sample
curl -X POST https://your-server/students/{student_id}/baseline \
     -H "Content-Type: application/json" \
     -d '{"text": "...", "provenance": "verified", "assignment": "Essay 1"}'

# Or send multiple files in one request
curl -X POST https://your-server/students/{student_id}/baseline/upload-batch \
     -F "files=@essay1.pdf" -F "files=@essay2.docx" \
     -F "provenance=verified" -F "assignment=Essay 1"
```

### Option B — Turnitin CSV export

Turnitin admin exports contain metadata but not full text. Use the CSV to identify
which students have papers, then upload the PDF files via Option A.

---

## Data privacy (FERPA)

Raw submission and baseline text **is stored** in the live stack — there is
no automatic deletion pipeline. An authorized instructor can retrieve the raw
prose of any baseline sample via `GET /students/{id}/samples/{index}/text`.

Deletion is manual: `store.delete_student()`, the CLI
`python -m original.cli.delete_student --student-id <id> --confirm`, or the
live `DELETE /students/{id}` endpoint all remove a student and every
associated record. No scheduled/automatic retention job runs.

See `docs/data_inventory.md` and `docs/encryption_policy.md` for the full
compliance detail.

---

## Architecture overview

| Layer | Tech |
|-------|------|
| API | FastAPI + uvicorn |
| Database | Hardened SQLite/WAL for the pilot (`original/store.py`, `ORIGINAL_DB`) — see `docs/adr/004-postgres-migration.md`. A Postgres path exists only in the dormant v1 API. |
| Feature extraction | Python: spaCy, sentence-transformers (optional), numpy |
| Scoring | Quantum density matrix (103-dim Born rule) |
| LTI | IMS LTI 1.3 / OIDC, platform-agnostic via `LTI_PLATFORMS` (Canvas, Blackboard, Moodle, …) |
| Auth | Principal tokens + PBKDF2 staff/student auth (`original/api.py`) |

103 stylometric features across 17 tiers (`original/constants.py`,
`FEATURE_DIM = 103`) — see the [README's feature table](README.md#the-103-dimensional-pipeline)
for the full tier-by-tier breakdown. Briefly:

| Tiers | Coverage |
|-------|----------|
| 1–7 | Surface stylometrics, discourse/cohesion, rhetorical register, char/punct fingerprint, POS/syntax, idiosyncratic markers, AI-detection signals |
| 8–11 | Prosodic rhythm, cognitive sequencing, semantic gravity wells, error ecology |
| 12–17 | Tension arc, prosodic depth, error topology, lexical architecture, citation fingerprint, behavioral biometrics |
| 0 | Comparison/profile features computed at scoring time |

**Legacy baselines:** profiles serialized with an older 74- or 89-feature
vector are padded to 103 dimensions with 0.5 (neutral) on load — you'll see a
warning. Run `rebuild-baselines` to re-extract at full accuracy. (See
CLAUDE.md "Feature Dimensions" for the exact behavior.)

---

## Troubleshooting

**`./start.sh` fails with "spacy model not found"**
```bash
python3 -m spacy download en_core_web_sm
```

**Port 8001 already in use**
```bash
PORT=8002 python3 run.py --demo --frontend-dir demo --port 8002
```

**"pydantic-settings" import error in tests**
```bash
pip install pydantic-settings==2.3.4
```

**Stored baselines have wrong dimension after a feature tier upgrade**
Legacy baselines serialized at 74 or 89 dimensions are automatically padded
to the current 103-dimensional vector with 0.5 (neutral mid-range) on load —
you'll see a warning. To restore full accuracy, re-add those baseline
samples via the professor dashboard, the API, or run `rebuild-baselines`.
