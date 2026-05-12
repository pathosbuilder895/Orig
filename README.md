# Original — Authorship Verification for Academic Integrity

Original verifies that a student wrote their own work. It builds a per-student writing profile from authenticated baseline samples, then scores new submissions against that profile using a **97-feature stylometric pipeline** and a quantum density matrix scoring engine.

Designed for seminaries and colleges that want a pastoral, explainable, FERPA-compliant alternative to text-matching plagiarism tools — one that detects ghostwriting, AI-assisted writing, and any significant deviation from a student's established voice, without flagging natural growth or topic-driven variation.

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

## The 97-feature pipeline

Features are extracted across 16 tiers. Before any feature runs, the text passes through a **preprocessing stage** that strips bibliography, appendix, and notes sections, removes parenthetical citation markers and footnote superscripts from prose, and strips block quotes — while extracting citation fingerprint data for Tier 16.

| Tier | Name | Features | Suspicion weight | What it measures |
|------|------|----------|-----------------|-----------------|
| 1 | Surface stylometrics | 9 | 1.0× | Type-token ratio, hapax rate, sentence length, function words, passive voice |
| 2 | Discourse & cohesion | 13 | 1.0× | Discourse markers, transitions, lexical chains, paragraph structure |
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

**Why Tier 16 matters:** Citation habits are deeply unconscious. Students do not think about whether they always write "argues" or rotate verbs, whether they block-quote constantly or rarely, or whether they habitually use ibid. AI ghostwriters replicate vocabulary and argument structure but have no access to the student's citation personality — they use a small set of signal verbs (low entropy), cite no repeat sources (no loyalty), and default to end-of-sentence citation placement.

**Preprocessing detail:** A bibliography or appendix section in a 2,000-word paper can contain 300–400 words of citation noise. Without stripping, noun-verb ratio spikes, type-token ratio drops, sentence-length variance explodes, and first-person ratio collapses — all pulling the score in misleading directions. Signal phrases ("As Calvin argues, ...") are intentionally kept in the prose because they are the student's own word choice and feed into Tier 16.

---

## Action thresholds

| Score | Action | Meaning |
|-------|--------|---------|
| 0.00 – 0.40 | `no_action` | Consistent with established voice |
| 0.40 – 0.55 | `monitor` | Minor deviation — watch future submissions |
| 0.55 – 0.75 | `schedule_conversation` | Notable deviation — discuss with student |
| 0.75 – 1.00 | `escalate` | Significant deviation — formal review |
| RMS z > 3.0 | `escalate` (override) | Catastrophic drift — immediate review regardless of score |

Fewer than 5 verified baselines suppresses escalation to `schedule_conversation` automatically.

---

## Setting up a class

### Option 1 — Onboarding wizard

Open http://localhost:8001/onboard.html and follow the four-step wizard:
1. Institution name and short code
2. Course details
3. Add students — type names, paste a list, or **drop a CSV** (columns: `external_id, full_name, email`)
4. Copy the generated links

### Option 2 — Roster CSV API

```bash
curl -X POST https://your-server/api/v1/students/roster/import \
  -H "Authorization: Bearer <token>" \
  -F "file=@roster.csv" \
  -F "course_id=<course-uuid>"
```

Returns `{created, skipped_duplicates, enrolled, errors[]}`.

---

## Importing past papers

### Batch file upload (professor dashboard)

Click **📥 Import Papers** in the header. The drawer has three tabs:

**Upload Files** — drag multiple PDFs, DOCXs, or TXTs for the selected student. All files go to the server in one request. SHA-256 deduplication prevents re-importing the same paper.

**From Canvas** — enter a Canvas Course ID, User ID, and optional API token. Lists all eligible submissions (online_text_entry + file uploads) and imports selected ones with one click.

**Turnitin CSV** — drop a Turnitin admin export. The system maps students by External ID, creates stub records for unmatched students, and flags submissions as "needs text upload." Actual paper text must then be uploaded via the Upload Files tab (Turnitin CSV does not contain full text).

### API — batch file upload

```bash
curl -X POST https://your-server/api/v1/submissions/{student_id}/baseline/upload-batch \
  -H "Authorization: Bearer <token>" \
  -F "files=@essay1.pdf" \
  -F "files=@essay2.docx" \
  -F "provenance=verified" \
  -F "assignment=Systematic Theology Essay"
# Returns: {"imported": 2, "skipped_duplicates": 0, "errors": []}
```

### API — Turnitin CSV

```bash
curl -X POST https://your-server/api/v1/import/courses/{course_id}/turnitin-csv \
  -H "Authorization: Bearer <token>" \
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

### Canvas

1. Admin → Developer Keys → **+ LTI Key** → paste `https://your-server/lti/config`
2. Note the **client_id**.
3. Register in Original:
   ```
   POST /api/v1/admin/canvas/registrations
   { "platform_iss": "https://your.instructure.com", "client_id": "...",
     "auth_endpoint": "...", "jwks_url": "...", "api_token": "..." }
   ```
4. Verify: `GET /lti/registrations/{id}/verify` → `{"ok": true}`

### Blackboard

Register with `"platform_type": "blackboard"` in the same endpoint. Blackboard config JSON is served at `GET /lti/blackboard/config`. Submission events arrive via AGS at `POST /lti/ags/submissions`.

### LTI claim normalisation

Canvas and Blackboard structure their OIDC claims differently. Original normalises both into a single `LTIContext` dataclass in `canvas/lti.py`, so all downstream logic is platform-agnostic. Platform type is auto-detected from the `iss` claim if not explicitly set.

---

## Key API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/login` | JWT access + refresh tokens |
| POST | `/api/v1/auth/refresh` | Rotate access token |
| GET | `/api/v1/students/` | List students |
| POST | `/api/v1/students/` | Create student |
| POST | `/api/v1/students/roster/import` | Bulk CSV roster import |
| POST | `/api/v1/submissions/{id}/baseline` | Add baseline sample (text) |
| POST | `/api/v1/submissions/{id}/baseline/upload-batch` | Add baseline samples (files) |
| POST | `/api/v1/submissions/{id}/score` | Score submission |
| POST | `/api/v1/submissions/{id}/submissions/{sid}/decision` | Record instructor decision |
| POST | `/api/v1/import/courses/{id}/turnitin-csv` | Import Turnitin metadata CSV |
| GET | `/lti/config` | Canvas LTI tool configuration JSON |
| GET | `/lti/blackboard/config` | Blackboard LTI tool configuration JSON |
| POST | `/canvas/lti/login` | LTI 1.3 OIDC login initiation |
| GET | `/canvas/lti/jwks` | LTI 1.3 public key set |
| GET | `/lti/registrations/{id}/verify` | Verify Canvas API token |
| POST | `/lti/ags/submissions` | Blackboard AGS event receiver |
| GET | `/health` | Liveness probe |

Full interactive docs at `/docs`.

---

## Data privacy (FERPA)

Every institution is created with FERPA-safe defaults:

```json
{
  "retain_raw_text_days": 365,
  "retain_scores_days": 1825,
  "ferpa_mode": true
}
```

With `ferpa_mode: true`, raw submission text is deleted after feature extraction. Only the 97-dimensional feature vector and scoring results are retained. Student data is never sold or used to train external models.

Update an institution's policy:
```
PATCH /api/v1/admin/institutions/{id}/data-policy
{"retain_raw_text_days": 90, "ferpa_mode": true}
```

---

## Production deployment

**Full runbook (Docker Compose + nginx + Let’s Encrypt + backups + static frontend):** see [deploy/DEPLOY.md](deploy/DEPLOY.md).

```bash
cp .env.dev .env
# Set: DATABASE_URL, SECRET_KEY, FIRST_ADMIN_PASSWORD
./start-prod.sh
```

`start-prod.sh` runs `alembic upgrade head`, then launches uvicorn. Set `PORT` and `WORKERS` environment variables to override defaults. Put Original behind nginx or Caddy for HTTPS.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | *(required)* | PostgreSQL connection string |
| `SECRET_KEY` | *(required)* | JWT signing key |
| `ENVIRONMENT` | `development` | `development` / `production` |
| `MIN_BASELINE_SAMPLES` | `3` | Minimum baselines to allow scoring |
| `MIN_BASELINE_FOR_ESCALATE` | `5` | Minimum baselines to allow escalation |
| `RATE_LIMIT_SCORING` | `10/minute` | Per-IP scoring rate limit |
| `PORT` | `8000` | uvicorn port |
| `WORKERS` | `2` | uvicorn worker count |

---

## Architecture

| Layer | Technology |
|-------|-----------|
| API | FastAPI + uvicorn |
| Database | PostgreSQL (production) / SQLite (test) |
| ORM & migrations | SQLAlchemy + Alembic |
| Auth | JWT (python-jose) + bcrypt |
| NLP | spaCy `en_core_web_sm` |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` (optional — Tier 10 falls back to neutral if unavailable) |
| Feature extraction | Pure Python + numpy (Tiers 1–9, 12–16) |
| Scoring | Quantum density matrix, Born rule (numpy) |
| LTI | IMS LTI 1.3 / OIDC (Canvas + Blackboard) |
| PDF parsing | pypdf |
| DOCX parsing | python-docx |
| Rate limiting | slowapi |

```
original/
├── api/v1/
│   ├── auth.py               JWT login + refresh
│   ├── students.py           Student CRUD + roster CSV import
│   ├── submissions.py        Baseline add, batch upload, scoring, decisions
│   ├── paper_import.py       Turnitin CSV import
│   ├── admin.py              Institution + LTI registration management
│   └── upload_utils.py       Shared PDF/DOCX/TXT text extraction
├── canvas/
│   ├── lti.py                LTI 1.3 OIDC launch, Canvas + Blackboard config,
│   │                         LTIContext normalisation, AGS receiver
│   └── baseline_import.py    Canvas submission list + import (paginated, file-aware)
├── core/                     Config, logging, exceptions, rate limiting
├── db/
│   ├── models/               SQLAlchemy models (Student, BaselineSample,
│   │                         Submission, ScoringResult, LTIRegistration…)
│   └── alembic/              Migration versions (001–003)
├── features/
│   ├── preprocess.py         Back-matter stripping + citation data extraction
│   ├── tier1.py  … tier7.py  Original 34 features (surface → AI detection)
│   ├── tier8.py              Prosodic rhythm
│   ├── tier9.py              Cognitive sequencing
│   ├── tier10.py             Semantic gravity wells
│   ├── tier11.py             Error ecology
│   ├── prosodic.py           Tiers 13–15 (prosodic depth, error topology,
│   │                         lexical architecture)
│   ├── tier16.py             Citation fingerprint (8 features)
│   └── pipeline.py           Feature orchestrator + comparison features
├── quantum/
│   ├── state.py              StudentState density matrix builder + trajectory
│   └── scoring.py            Born-rule scoring, interference decomposition,
│                             catastrophic drift alert
├── tension_arc.py            Catastrophe index κ (Tier 12)
├── constants.py              All 97 feature codes, tier weights, norm bounds,
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

32 tests covering feature extraction, quantum invariants (Born probability bounds, density matrix trace normalisation, purity bounds, trajectory), and tension arc integration. No database or Docker required.

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
