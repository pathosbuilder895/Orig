# Original — Setup Guide

Authorship verification engine for academic integrity. Measures whether a submission
matches a student's own authenticated writing voice across 74 stylometric features.

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

Copy and edit the environment file:

```bash
cp .env.dev .env
# Edit .env — set DATABASE_URL, SECRET_KEY, FIRST_ADMIN_PASSWORD
```

Then start the production server:

```bash
./start-prod.sh
```

This runs Alembic database migrations and launches uvicorn on port 8000.
Set `PORT=8080` (or any port) as an environment variable to override.

For HTTPS in production, put Original behind nginx or Caddy and set:
```
BEHIND_PROXY=true
ALLOWED_HOSTS=yourdomain.edu
```

---

### Step 4 — Connect Canvas LTI

1. In Canvas Admin → Developer Keys → **+ LTI Key** → select **"Paste JSON"**
2. Paste the URL: `https://your-server/lti/config`
   - Canvas will fetch the configuration JSON automatically.
3. Note the **client_id** Canvas assigns.
4. Register the deployment in Original:
   ```
   POST /api/v1/admin/canvas/registrations
   {
     "platform_iss": "https://your-institution.instructure.com",
     "client_id": "<from Canvas>",
     "auth_endpoint": "https://your-institution.instructure.com/api/lti/authorize_redirect",
     "jwks_url": "https://your-institution.instructure.com/api/lti/security/jwks",
     "label": "My Seminary Canvas",
     "api_token": "<Canvas system-level token for baseline import>"
   }
   ```
5. Verify the token works:
   ```
   GET /lti/registrations/{registration_id}/verify
   # Returns: {"ok": true, "canvas_user": {...}}
   ```
6. Instructors can now use **"Import from Canvas"** in the professor dashboard
   to pull past student submissions directly as verified baselines.

---

### Step 5 — Connect Blackboard

Blackboard Ultra uses the same LTI 1.3 standard as Canvas.

1. In Blackboard Admin → **LTI Tool Providers** → Register by URL:
   `https://your-server/lti/blackboard/config`
2. Register in Original with `"platform_type": "blackboard"`:
   ```
   POST /api/v1/admin/canvas/registrations
   {
     "platform_iss": "https://blackboard.com",
     "platform_type": "blackboard",
     "client_id": "<from Blackboard>",
     "auth_endpoint": "https://developer.blackboard.com/api/v1/gateway/oidcauth",
     "jwks_url": "https://developer.blackboard.com/api/v1/management/applications/<appId>/jwks.json",
     "label": "My Seminary Blackboard"
   }
   ```
3. Blackboard pushes submission events via AGS to `POST /lti/ags/submissions`.
   Wire this to your task queue for production scoring.

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
     -H "Authorization: Bearer <token>" \
     https://your-server/api/v1/students/{student_id}/upload

# Add extracted text as a baseline sample
curl -X POST https://your-server/api/v1/students/{student_id}/baseline \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <token>" \
     -d '{"text": "...", "provenance": "verified", "assignment": "Essay 1"}'
```

### Option B — Turnitin CSV export

Turnitin admin exports contain metadata but not full text. Use the CSV to identify
which students have papers, then upload the PDF files via Option A.

---

## Data privacy (FERPA)

By default, every institution is created with FERPA-safe defaults:

```json
{
  "retain_raw_text_days": 365,
  "retain_scores_days": 1825,
  "ferpa_mode": true
}
```

With `ferpa_mode: true`, raw submission text is deleted after feature extraction.
Only the 74-dimensional feature vector and scoring results are retained.

To update an institution's data policy:
```
PATCH /api/v1/admin/institutions/{id}/data-policy
{"retain_raw_text_days": 90, "ferpa_mode": true}
```

---

## Architecture overview

| Layer | Tech |
|-------|------|
| API | FastAPI + uvicorn |
| Database | PostgreSQL (production) / SQLite (testing) |
| Feature extraction | Python: spaCy, sentence-transformers, numpy |
| Scoring | Quantum density matrix (74-dim Born rule) |
| LTI | IMS LTI 1.3 / OIDC (Canvas + Blackboard) |
| Auth | JWT (python-jose) + bcrypt |

74 stylometric features across 12 tiers:

| Tier | Features |
|------|----------|
| 1 | Surface stylometrics (TTR, sentence length, hapax…) |
| 2 | Discourse & cohesion |
| 3 | Rhetorical register & theological vocabulary |
| 4 | Character & punctuation fingerprint |
| 5 | POS / syntax patterns |
| 6 | Idiosyncratic markers |
| 7 | Voice authenticity signals |
| 8 | Prosodic rhythm (stress entropy) |
| 9 | Cognitive sequencing (Markov argument alignment) |
| 10 | Semantic gravity wells |
| 11 | Error ecology (KL-divergence of error profile) |
| 12 | Tension arc integration (catastrophe index κ) |

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

**Stored baselines have wrong dimension after Tier 8-12 upgrade**
The store automatically pads old 62-dimension vectors to 74 dimensions with 0.5
(neutral mid-range). To restore full accuracy, re-add those baseline samples
via the professor dashboard or the API.
