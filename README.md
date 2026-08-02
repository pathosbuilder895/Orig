# Original — Authorship Verification for Academic Integrity

Original verifies whether a submitted paper is consistent with the student's own authenticated writing history. It builds a per-student writing profile from verified baseline samples, then scores new submissions against that profile using a **103-dimensional stylometric pipeline** and a quantum density matrix scoring engine.

Designed for seminaries and colleges that want a pastoral, explainable, FERPA-conscious alternative to text-matching plagiarism tools — one that detects ghostwriting, AI-assisted writing, and significant deviation from a student's established voice while preserving human review, student conversation, and documented institutional process.

Original is a **decision-support system, not a disciplinary decision-maker**. A score can recommend monitoring, a conversation, or formal review, but institutional action remains with instructors and academic integrity officers.

> **Which stack is live?** This repo contains two backends; exactly one is
> live. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before touching auth,
> LTI, or deployment — it is the single source of truth for the
> live-vs-dormant split. Short version: the live stack is `original/api.py` +
> `demo/` + `demo/bluebook/`, with LTI at `/lti/*`. The `original/api/` v1
> package is dormant. The dead `frontend/` and `web/` trees were removed
> 2026-07-07 (ADR-006); see git history.

---

## How it works

Every student's writing identity is modelled as a **density matrix** ρ built from weighted outer products of their authenticated baseline feature vectors:

```
ρ = Σᵢ wᵢ vᵢvᵢᵀ / Σᵢwᵢ
```

Where `wᵢ = auth_weight × recency_decay^age`. Proctored samples weight 1.0, instructor-verified samples weight 0.7, unverified submissions are excluded from baseline construction entirely.

When a new submission arrives, its feature vector is scored via variance-weighted Mahalanobis deviation — features where the student is highly *consistent* penalise deviation more severely than noisy features:

```
z_i = (submission_i − baseline_mean_i) / baseline_std_i
D_raw = tanh(RMS(z) / 2.5)
```

The score is then trajectory-adjusted (±15–25% based on whether the deviation aligns with observed writing development) and mapped to a recommended action.

**What the system returns per submission:**

- **Deviation score** (0–1) — distance from the student's established baseline
- **Authorship probability** — Born-rule projection onto the density matrix
- **Interference decomposition** — which specific features are driving the deviation and why
- **Trajectory conformance** — whether deviation is consistent with natural growth
- **Baseline purity** — how consistent the student's baseline samples are (pure state = 1.0)
- **Tension arc** — structural catastrophe index κ, an orthogonal AI-writing signal
- **Recommended action** — no_action / monitor / schedule_conversation / escalate
- **Catastrophic drift alert** — fires when RMS z > 3.0 SDs, overrides scoring threshold

---

## Quickstart

```bash
cd ~/Desktop/Original
./start.sh
```

Installs dependencies, downloads the spaCy language model, seeds five synthetic student profiles, and starts the demo on port 8001.

| Page | URL |
|------|-----|
| Professor dashboard | http://localhost:8001/professor.html |
| Student coaching view | http://localhost:8001/student.html |
| Class setup wizard | http://localhost:8001/onboard.html |
| API docs (Swagger) | http://localhost:8001/docs |

**Demo students:**

| Student | Baselines | What to expect |
|---------|-----------|----------------|
| James Whitfield | 5 | AI-written submission — deviation ~0.7+ |
| Sarah Okonkwo | 5 | Second AI pattern (covenant theology) |
| Daniel Osei | 5 | Mixed submission — moderate deviation |
| Lydia Mercer | 5 | Authentic submission — low deviation |
| Michael Chen | 1 | Live baseline building during demo — purity starts at 1.0 |

---

## The 103-dimensional pipeline

Original currently uses 103 ordered feature dimensions from `original/constants.py`: 96 base dimensions extracted from prose, citations, and optional proctored keystroke data, plus 7 comparison/profile dimensions computed during scoring. Before prose features run, the text passes through a **preprocessing stage** that strips bibliography, appendix, and notes sections, removes parenthetical citation markers and footnote superscripts from prose, and strips block quotes — while extracting citation fingerprint data for Tier 16.

| Tier | Name | Features | Suspicion weight | What it measures |
|------|------|----------|-----------------|-----------------|
| 1 | Surface stylometrics | 9 | 1.0× | Type-token ratio, hapax rate, sentence length, function words, passive voice |
| 2 | Discourse & cohesion | 13 | 0.6× | Discourse markers, transitions, lexical chains, paragraph structure |
| 3 | Rhetorical register | 12 | 0.8× | Hedging, assertion, epistemic certainty, theological vocabulary — *lower weight: topic-sensitive* |
| 4 | Char/punct fingerprint | 7 | 1.3× | Character trigram entropy, comma/semicolon/dash/quote rates |
| 5 | POS & syntax | 7 | 1.2× | Noun-verb ratio, clause depth, subordination, POS bigram entropy |
| 6 | Idiosyncratic markers | 6 | **1.4×** | Contractions, that/which ratio, sentence-initial conjunctions, citation style |
| 7 | AI detection | 6 | 1.1× | Burstiness, perplexity proxy, transition predictability, hedge clustering |
| 8 | Prosodic rhythm | 4 | 1.1× | Syllabic stress entropy, clausulae consistency, breath-group variance |
| 9 | Cognitive sequencing | 2 | 0.9× | Argument topology vs. AI question-claim-evidence pattern |
| 10 | Semantic gravity wells | 2 | 1.0× | Embedding centroid proximity, semantic field dispersion |
| 11 | Error ecology | 3 | **1.4×** | KL-divergence of error fingerprint, stumble-rate consistency |
| 12 | Tension arc | 1 | 1.2× | Catastrophe index κ = σ(ρ)·(1−μ(ρ)) from sentence-length arc |
| 13 | Prosodic depth | 6 | 1.3× | Clausula type/shape, breath-group regularity, arc resolution, metric flatness |
| 14 | Error topology | 4 | 1.3× | Positional entropy of errors, article omissions, pronoun ambiguity |
| 15 | Lexical architecture | 5 | 1.2× | Latinate ratio, nominalization density, chiasmus, polysyndeton |
| 16 | **Citation fingerprint** | 8 | **1.4×** | Signal verb entropy, source loyalty, block-quote habit, ibid. rate, citation position |
| 17 | Behavioral biometrics | 6 | 1.2× | Keystroke rhythm, bursts, deletion rate, pauses, paste events, revision depth |
| 0 | Comparison/profile features | 7 | 1.2× | Baseline-relative profile divergence features computed at scoring time |

**Why Tier 16 matters:** Citation habits are deeply unconscious. Students do not think about whether they always write "argues" or rotate verbs, whether they block-quote constantly or rarely, or whether they habitually use ibid. AI ghostwriters replicate vocabulary and argument structure but have no access to the student's citation personality — they use a small set of signal verbs (low entropy), cite no repeat sources (no loyalty), and default to end-of-sentence citation placement.

**Preprocessing detail:** A bibliography or appendix section in a 2,000-word paper can contain 300–400 words of citation noise. Without stripping, noun-verb ratio spikes, type-token ratio drops, sentence-length variance explodes, and first-person ratio collapses — all pulling the score in misleading directions. Signal phrases ("As Calvin argues, ...") are intentionally kept in the prose because they are the student's own word choice and feed into Tier 16.

---

## Action thresholds

| Score | Action | Meaning |
|-------|--------|---------|
| 0.00 – 0.40 | `no_action` | Consistent with established voice |
| 0.40 – 0.60 | `monitor` | Minor deviation — watch future submissions |
| 0.60 – 0.75 | `schedule_conversation` | Notable deviation — discuss with student |
| 0.75 – 1.00 | `escalate` | Significant deviation — formal review |
| RMS z > 3.0 | `escalate` (override) | Catastrophic drift — immediate review regardless of score |

Fewer than 5 verified baselines suppresses escalation to `schedule_conversation` automatically.

These thresholds generate recommendations only. `schedule_conversation` should be treated as an invitation to ask the student about process, sources, drafting conditions, accommodations, and possible legitimate changes in writing context. `escalate` means the case is ready for institutional review, not that misconduct has been proven.

---

## Setting up a class

### Option 1 — Onboarding wizard

Open http://localhost:8001/onboard.html and follow the four-step wizard:
1. Institution name and short code
2. Course details
3. Add students — type names, paste a list, or **drop a CSV** (columns: `external_id, full_name, email`)
4. Copy the generated links

### Option 2 — CSV drop in the wizard

The onboarding wizard's "Add students" step (above) accepts a dropped CSV
directly — there is no separate bulk-roster API endpoint in the live stack.
For programmatic provisioning of many students/tenants at once, see
`docs/PROVISIONING_CHECKLIST.md`.

---

## Importing past papers

### Batch file upload (professor dashboard)

Click **📥 Import Papers** in the header. The drawer has three tabs:

**Upload Files** — drag multiple PDFs, DOCXs, or TXTs for the selected student. All files go to the server in one request. SHA-256 deduplication prevents re-importing the same paper.

**From Canvas** — enter a Canvas Course ID, User ID, and optional API token. Lists all eligible submissions (online_text_entry + file uploads) and imports selected ones with one click.

**Turnitin CSV** — drop a Turnitin admin export. The system maps students by External ID, creates stub records for unmatched students, and flags submissions as "needs text upload." Actual paper text must then be uploaded via the Upload Files tab (Turnitin CSV does not contain full text).

### API — batch file upload

```bash
curl -X POST https://your-server/students/{student_id}/baseline/upload-batch \
  -F "files=@essay1.pdf" \
  -F "files=@essay2.docx" \
  -F "provenance=verified" \
  -F "assignment=Systematic Theology Essay"
# Returns: {"imported": 2, "skipped_duplicates": 0, "errors": []}
```

### API — Turnitin CSV

```bash
curl -X POST https://your-server/import/courses/{course_id}/turnitin-csv \
  -F "file=@turnitin_export.csv"
```

Expected columns (case-insensitive, order-independent): `Student Name`, `Student ID`, `Assignment`, `Submission Date`, `Similarity`, `File`.

---

## Supported file formats

| Format | Parser |
|--------|--------|
| `.txt` | Plain UTF-8 decode |
| `.pdf` | pypdf (handles scanned text layers) |
| `.docx` | python-docx |

---

## LTI integrations

The live LTI 1.3 implementation is `original/lti.py` (routes `/lti/login`,
`/lti/launch`, `/lti/jwks`), configured entirely through the `LTI_PLATFORMS`
environment variable — there is no registration API/database table in the
live stack.

Full walkthrough for connecting a Canvas institution end-to-end (developer
key, `LTI_PLATFORMS` JSON, verification steps):

- **Operator runbook:** [docs/CANVAS_RUNBOOK.md](docs/CANVAS_RUNBOOK.md)
- **One-pager to send the Canvas admin:** [docs/canvas_developer_key.md](docs/canvas_developer_key.md)

---

## Runtime surfaces

Original currently has two backend surfaces — only one is live:

| Surface | Entry point | Status | Purpose |
|---------|-------------|--------|---------|
| Dashboard/pilot app | `python run.py --demo --frontend-dir demo/` | **Live** | `original/api.py` — static professor, student, admin, operator, and Bluebook dashboards. Hardened with tenant isolation, staff login, guarded destructive operations, audit logging, and SQLite WAL backups. This is what `render.yaml` deploys. |
| v1 API | `python run.py` | Dormant | `original/main.py` + `original/api/` — JWT auth, SQLAlchemy models, rate limiting, and a Postgres path. Not deployed anywhere; see `docs/ARCHITECTURE.md`. |

The zero-login seeded demo remains the sales showcase. Real pilot tenants must run with `ORIGINAL_ENV=pilot`, a stable `SECRET_KEY`, locked CORS, `GUARD_DESTRUCTIVE=1`, and a configured `ORIGINAL_DB` backup path.

## Key API endpoints

`original/api.py` registers 59 routes. The minimum set most integrators need, grouped by audience:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness probe |
| POST | `/auth/login` | Instructor/admin login |
| GET | `/auth/me` | Current principal |
| POST | `/student-auth/login` | Student login |
| GET | `/students/{id}` | Student state summary |
| GET | `/students/{id}/samples/{index}/text` | Raw text of a single baseline sample |
| POST | `/students/{id}/baseline` | Add a baseline sample (text) |
| POST | `/students/{id}/baseline/upload-batch` | Add baseline samples (files) |
| POST | `/students/{id}/score` | Score a submission |
| DELETE | `/students/{id}` | Delete a student and associated data |
| GET | `/lti/jwks` | LTI 1.3 public key set |
| POST | `/lti/launch` | LTI 1.3 launch (id_token) |
| GET/POST | `/lti/login` | LTI 1.3 OIDC login initiation |

This is a curated subset, not the full list — endpoint tables in prose drift
fast against a 59-route file. For everything else:

- **Full interactive docs (always current):** `/docs` (Swagger UI, served by the running app)
- **Prose API reference grouped by audience:** [docs/API_REFERENCE.md](docs/API_REFERENCE.md)

---

## Data privacy (FERPA)

**Raw submission and baseline text IS stored** in the live stack — there is no
automatic `ferpa_mode` deletion pipeline. Authorized instructors can retrieve
the raw prose of any baseline sample via `GET /students/{id}/samples/{index}/text`,
which exists specifically so an instructor can re-read a student's writing
before authenticating a sample as a trusted baseline.

What retention actually looks like today:

- **No automatic/scheduled deletion runs** in the live app. (A retention
  scheduler exists only in the dormant v1 stack and is not deployed.)
- **Manual deletion is real and supported**: `store.delete_student()` and the
  CLI `python -m original.cli.delete_student --student-id <id> --confirm`
  both remove a student and all associated data (submissions, scoring
  results, baselines). The live `DELETE /students/{id}` endpoint does the
  same over HTTP.
- Feature vectors (the 103-dimensional stylometric encoding) are
  non-reversible — they cannot be used to reconstruct the original text.
- Student data is never sold or used to train external models.

See `docs/data_inventory.md` and `docs/encryption_policy.md` for the full
compliance detail, and `docs/dpa_template.md` for the DPA text.

---

## Production deployment

The live deploy target is **Render**, defined in `render.yaml`. Two services
are declared:

- **`original-demo`** — free-tier, always-live, zero-login sales demo.
  Ephemeral (writes reset on each deploy); seeded from the committed
  `demo/seed.db`. `startCommand: python run.py --demo --port $PORT --skip-seed`.
- **`original-pilot`** — Starter plan with a persistent disk, for a real
  institutional pilot. Same dashboard app, hardened by `ORIGINAL_ENV=pilot`
  (fails fast without a stable `SECRET_KEY`; CORS locked to
  `ALLOWED_ORIGINS`; HSTS on; destructive endpoints guarded by
  `MAINTENANCE_TOKEN`). Manual deploys only — see `docs/OPS_RUNBOOK.md` for
  the maintenance-window process.

For the full set of env vars each service sets (backup scheduler, LTI keys,
adaptive-scoring flags, AI-likelihood gate), read `render.yaml` directly —
it's heavily commented and is the source of truth.

A Docker Compose / nginx / Let's Encrypt / Alembic self-hosting path exists
at [deploy/DEPLOY.md](deploy/DEPLOY.md), but **it is not the current
deployment path** — that document targets the dormant v1 stack. Treat it as
a documented future option for self-hosting outside Render, not as the
pilot's actual deploy process.

---

## Architecture decision records

Load-bearing decisions and their rationale live in `docs/adr/`, each dated and
numbered — read the newest-relevant one before revisiting a decision that's
already been made:

| ADR | Decision |
|---|---|
| [001](docs/adr/001-quantum-scoring.md) | Quantum-inspired density-matrix scoring |
| [002](docs/adr/002-data-layer-convergence.md) | Converge demo/v1 data layers behind a `Repository` seam |
| [003](docs/adr/003-multi-tenant-auth-without-losing-demo.md) | Multi-institution readiness without losing the demo |
| [004](docs/adr/004-postgres-migration.md) | Hardened SQLite for the pilot; Postgres path documented |
| [005](docs/adr/005-student-read-model.md) | Redacting read-model for the student dashboard |
| [006](docs/adr/006-postgres-convergence.md) | Converge on Postgres via the `Repository` seam (Route A) |
| [007](docs/adr/007-ai-likelihood-gating.md) | AI-likelihood detector: report-only contract + gating |

See [docs/adr/README.md](docs/adr/README.md) for the fuller index (status
column + reading order for the Postgres decision thread).

---

## Architecture

| Layer | Technology |
|-------|-----------|
| API | FastAPI + uvicorn |
| Database | Hardened SQLite/WAL for the dashboard pilot; PostgreSQL path in the v1 API |
| ORM & migrations | SQLAlchemy + Alembic in v1; repository/store layer in the dashboard app |
| Auth | Principal tokens + PBKDF2 staff auth in dashboard app; JWT (python-jose) + bcrypt in v1 |
| NLP | spaCy `en_core_web_sm` |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` (optional — Tier 10 falls back to a genuine TF-IDF encoding, not a neutral placeholder, if unavailable) |
| Feature extraction | Pure Python + numpy (Tiers 1–17, with optional Tier 17 keystroke inputs) |
| Scoring | Quantum density matrix, Born rule (numpy) |
| LTI | IMS LTI 1.3 / OIDC (Canvas + Blackboard) |
| PDF parsing | pypdf |
| DOCX parsing | python-docx |
| Rate limiting | slowapi |

Directory map — **live files first**, dormant v1 package called out explicitly
(see `docs/ARCHITECTURE.md` for the full split):

```
original/
├── api.py                    ★ LIVE — the pilot FastAPI app (59 routes:
│                               students, scoring, auth, Bluebook, admin, LTI)
├── lti.py                    ★ LIVE — LTI 1.3 OIDC (/lti/login, /lti/launch, /lti/jwks)
├── store.py                  ★ LIVE — SQLite (WAL) persistence + in-memory cache
├── api/v1/                   dormant — v1 REST package, not deployed
│   ├── auth.py               JWT login + refresh
│   ├── students.py           Student CRUD + roster CSV import
│   ├── submissions.py        Baseline add, batch upload, scoring, decisions
│   ├── paper_import.py       Turnitin CSV import
│   ├── admin.py              Institution + LTI registration management
│   └── upload_utils.py       Shared PDF/DOCX/TXT text extraction
├── canvas/                   dormant — v1's own LTI stack (/canvas/lti/*)
│   ├── lti.py                LTI 1.3 OIDC launch, Canvas + Blackboard config,
│   │                         LTIContext normalisation, AGS receiver
│   └── baseline_import.py    Canvas submission list + import (paginated, file-aware)
├── core/                     dormant — config, logging, exceptions, rate limiting (v1)
├── db/                       dormant — v1 SQLAlchemy/Alembic
│   ├── models/               SQLAlchemy models (Student, BaselineSample,
│   │                         Submission, ScoringResult, LTIRegistration…)
│   └── alembic/              Migration versions (001–003)
├── features/
│   ├── preprocess.py         Back-matter stripping + citation data extraction
│   ├── tier1.py  … tier7.py  Surface, discourse, register, punctuation,
│   │                         syntax, idiosyncratic, and AI-pattern signals
│   ├── tier8.py              Prosodic rhythm
│   ├── tier9.py              Cognitive sequencing
│   ├── tier10.py             Semantic gravity wells
│   ├── tier11.py             Error ecology
│   ├── prosodic.py           Tiers 13–15 (prosodic depth, error topology,
│   │                         lexical architecture)
│   ├── tier16.py             Citation fingerprint (8 features)
│   ├── tier17.py             Behavioral biometrics for proctored sessions
│   └── pipeline.py           Feature orchestrator + comparison features
├── quantum/
│   ├── state.py              StudentState density matrix builder + trajectory
│   └── scoring.py            Born-rule scoring, interference decomposition,
│                             catastrophic drift alert
├── tension_arc.py            Catastrophe index κ (Tier 12)
├── constants.py              All 103 feature dimensions, tier weights, norm bounds,
│                             lexicons, thresholds
└── schemas_v1/               Pydantic request/response models

demo/
├── professor.html            Full professor dashboard — baseline builder,
│                             scoring, radar compare, Import Papers drawer
├── student.html              Student-facing coaching view (tier-by-tier feedback)
└── onboard.html              4-step class setup wizard

synthetic/
└── seed_data.py              5 synthetic student profiles for demo
                              (theological essays, authentic + AI submissions)

tests/
├── test_features.py          Feature extraction unit tests
├── test_quantum.py           Quantum invariant property tests (Hypothesis)
└── test_tension_arc_integration.py
```

---

## Testing

```bash
python3 -m pytest tests/test_features.py tests/test_quantum.py \
  tests/test_tension_arc_integration.py --noconftest -v
```

A narrow slice covering feature extraction, quantum invariants (Born probability bounds, density matrix trace normalisation, purity bounds, trajectory), and tension arc integration. No database or Docker required. The full suite (`.venv/bin/pytest tests/ -q`, see `CLAUDE.md`) is ~1050 tests as of 2026-08-01 (test count grows regularly — treat this as approximate, not a pinned number).

---

## Troubleshooting

**spaCy model not found**
```bash
python3 -m spacy download en_core_web_sm
```

**Port 8001 already in use**
```bash
python3 run.py --demo --frontend-dir demo --port 8002
```

**`pydantic-settings` import error**
```bash
pip install pydantic-settings==2.3.4
```

**Stored baselines have wrong dimension after feature tier upgrade**
Old baseline vectors are automatically padded to the current dimension with 0.5 (neutral) on load. To restore full accuracy, re-add those baselines via the professor dashboard or the API. The dimension guard is in `store.py._deserialize()`.

**`/health` returns 200 but `/professor.html` returns 404**
The server was started with `--frontend-dir frontend` instead of `--frontend-dir demo`. Use `./start.sh` or pass `--frontend-dir demo` explicitly.
